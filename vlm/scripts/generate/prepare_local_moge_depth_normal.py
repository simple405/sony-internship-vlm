#!/usr/bin/env python3
"""Extract MoGe v2 metric depth + surface normals for a single character image.

Loads MoGe v2 from the fully-cached HF hub snapshot, runs single-image inference
on the char_001 source (or any --source), masks the outputs with a foreground mask,
and writes:

  * <stem>_moge_depth.png   – inverse depth normalized to [0,255] (same convention as DA3)
  * <stem>_moge_normal.png  – OpenGL-style RGB normal map (R right, G up, B out)
  * <stem>_moge_depth_raw.npy – raw metric depth float32 array (for mesh construction)

A three-panel comparison PNG is also saved when a DA3 baseline depth exists.

Uses the ComfyUI ``air310`` conda environment:
    /home/intern/anaconda3/envs/air310/bin/python
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path("/home/intern/Supervised 2D to 3D")
COMFYUI_ROOT = Path("/home/intern/wmy/ComfyUI")

MOGE_SNAPSHOT = Path(
    "/home/intern/.cache/huggingface/hub/"
    "models--Ruicheng--moge-2-vitl-normal/snapshots/"
    "b135031bae30b5ac2ae141a0e68717795ce38340"
)
MOGE_CHECKPOINT = MOGE_SNAPSHOT / "model.pt"

DEFAULT_SOURCE = Path(
    "/home/intern/Supervised 2D to 3D/vlm/data/SN_6期动漫数据标注/char_001/char_001.png"
)
DEFAULT_MASK = Path(
    "/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/foreground_mask.png"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "vlm/experiments/comfyui_output/front_view_local/char_001/candidates"
)
DEFAULT_DA3_DEPTH = DEFAULT_OUTPUT_DIR / "char_001_da3_depth.png"


# ---------------------------------------------------------------------------
# Argument parsing (follows prepare_local_da3_depth.py pattern)
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--foreground-mask", type=Path, default=DEFAULT_MASK)
    parser.add_argument("--model-path", type=Path, default=MOGE_CHECKPOINT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--output-stem",
        type=str,
        default="char_001",
        help="Prefix for output filenames (default: char_001)",
    )
    parser.add_argument(
        "--resolution-level",
        type=int,
        default=9,
        help="MoGe resolution level 0-9, higher = more detail (default: 9)",
    )
    parser.add_argument(
        "--gpu",
        type=int,
        default=2,
        help="CUDA device index (default: 2 — RTX 3090)",
    )
    parser.add_argument(
        "--da3-depth",
        type=Path,
        default=DEFAULT_DA3_DEPTH,
        help="Path to existing DA3 depth PNG for comparison panel",
    )
    parser.add_argument(
        "--no-comparison",
        action="store_true",
        help="Skip 3-panel comparison generation",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# I/O helpers (mirrors prepare_local_da3_depth.py)
# ---------------------------------------------------------------------------

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)


def atomic_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    image.save(temp, format="PNG", optimize=True)
    os.replace(temp, path)


def atomic_npy(array: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # np.save appends .npy if the filename doesn't end with it — ensure the
    # temp name ends with .npy so the atomic rename target matches.
    temp = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp.npy")
    np.save(temp, array)
    os.replace(temp, path)


# ---------------------------------------------------------------------------
# MoGe inference via ComfyUI
# ---------------------------------------------------------------------------

def load_moge_model(checkpoint_path: Path, gpu: int = 2):
    """Load the MoGe v2 model via ComfyUI's MoGeModel wrapper."""
    if str(COMFYUI_ROOT) not in sys.path:
        sys.path.insert(0, str(COMFYUI_ROOT))

    import torch
    import comfy.model_management
    from comfy.ldm.moge.model import MoGeModel

    # Load the raw checkpoint
    state_dict = torch.load(str(checkpoint_path), map_location="cpu")

    # Build the model (MoGeModel handles v1/v2 dispatch internally)
    model = MoGeModel(state_dict)
    print(f"MoGe version: {model.version}")
    print(f"num_tokens_range: {model.num_tokens_range}")
    print(f"mask_threshold: {model.mask_threshold}")

    return model


def run_moge_inference(
    model,
    source: Image.Image,
    foreground_mask: np.ndarray,
    resolution_level: int = 9,
    gpu: int = 2,
):
    """Run MoGe inference on a single PIL image and return processed outputs."""
    import torch

    # Prepare image tensor (B, 3, H, W) in [0, 1]
    source_np = np.asarray(source.convert("RGB"), dtype=np.float32) / 255.0
    image_tensor = torch.from_numpy(source_np).permute(2, 0, 1).unsqueeze(0)  # 1,3,H,W

    # Run inference
    with torch.no_grad():
        result = model.infer(
            image_tensor,
            resolution_level=resolution_level,
            fov_x=None,               # auto-recover focal length
            force_projection=False,    # keep metric depth from points, don't reproject
            apply_mask=False,          # we apply our own foreground mask
            apply_metric_scale=True,   # use predicted metric scale
        )

    depth = result["depth"].squeeze(0).cpu().numpy()        # (H, W) metric depth
    mask_pred = result["mask"].squeeze(0).cpu().numpy()     # (H, W) model mask
    normal = result.get("normal")                           # (B, H, W, 3) or None

    if normal is not None:
        normal = normal.squeeze(0).cpu().numpy()            # (H, W, 3) OpenCV convention

    return depth, mask_pred, normal


# ---------------------------------------------------------------------------
# Depth processing (matches prepare_local_da3_depth.py)
# ---------------------------------------------------------------------------

def process_depth(
    depth: np.ndarray,
    foreground: np.ndarray,
    depth_threshold: float = 1e-6,
) -> tuple[np.ndarray, float, float]:
    """Convert metric depth to normalized inverse-depth PNG (DA3-compatible).

    Returns (uint8_array, p02, p98).
    """
    valid = (
        foreground
        & np.isfinite(depth)
        & (depth > depth_threshold)
    )
    if int(valid.sum()) < 100:
        raise RuntimeError(
            f"Too few valid foreground depth pixels: {valid.sum()}"
        )

    inverse_depth = np.zeros_like(depth, dtype=np.float32)
    inverse_depth[valid] = 1.0 / depth[valid]
    low, high = np.percentile(inverse_depth[valid], [2.0, 98.0])
    if not high > low:
        raise RuntimeError(
            f"Degenerate MoGe depth range: low={low}, high={high}"
        )

    normalized = np.clip((inverse_depth - low) / (high - low), 0.0, 1.0)
    normalized[~foreground] = 0.0

    depth_u8 = np.round(normalized * 255.0).astype(np.uint8)
    return depth_u8, float(low), float(high)


# ---------------------------------------------------------------------------
# Normal map processing
# ---------------------------------------------------------------------------

def process_normal(
    normal: np.ndarray,
    foreground: np.ndarray,
) -> np.ndarray:
    """Convert MoGe normals (OpenCV: Z+ into scene) to OpenGL normal map (Y up, Z out).

    Returns uint8 RGB array (H, W, 3) with R=right, G=up, B=out-of-surface.
    Background pixels are set to (128, 128, 255) = flat forward-facing.
    """
    # MoGe is OpenCV: X right, Y down, Z into scene
    # OpenGL normal map:  X right, Y up,   Z out of surface
    # Transform: flip Y and Z signs
    n_gl = normal.copy()
    n_gl[..., 1] = -n_gl[..., 1]   # Y: down → up
    n_gl[..., 2] = -n_gl[..., 2]   # Z: into scene → out of surface

    # Map [-1, 1] → [0, 1]
    n_vis = (n_gl * 0.5 + 0.5).clip(0.0, 1.0)

    # Zero out background
    n_vis[~foreground] = [0.5, 0.5, 1.0]  # flat blue = forward-facing

    n_u8 = np.round(n_vis * 255.0).astype(np.uint8)
    return n_u8


# ---------------------------------------------------------------------------
# Three-panel comparison generation
# ---------------------------------------------------------------------------

def make_comparison_panel(
    da3_depth_path: Path | None,
    moge_depth_u8: np.ndarray,
    moge_normal_u8: np.ndarray,
) -> Image.Image | None:
    """Create a horizontal 3-panel comparison: DA3 depth | MoGe depth | MoGe normals."""
    panels: list[Image.Image] = []

    # Panel 1: DA3-SMALL depth baseline (if available)
    if da3_depth_path is not None and da3_depth_path.exists():
        da3_img = Image.open(da3_depth_path).convert("RGB")
        panels.append(da3_img)
    else:
        return None  # can't build comparison without the baseline

    # Panel 2: MoGe depth
    panels.append(Image.fromarray(
        np.stack([moge_depth_u8] * 3, axis=-1), mode="RGB"
    ))

    # Panel 3: MoGe normals
    panels.append(Image.fromarray(moge_normal_u8, mode="RGB"))

    # Resize all panels to the same height
    max_h = max(p.height for p in panels)
    resized = []
    for p in panels:
        if p.height != max_h:
            new_w = int(p.width * max_h / p.height)
            resized.append(p.resize((new_w, max_h), Image.Resampling.LANCZOS))
        else:
            resized.append(p)

    total_w = sum(p.width for p in resized)
    canvas = Image.new("RGB", (total_w, max_h), (255, 255, 255))
    x = 0
    for p in resized:
        canvas.paste(p, (x, 0))
        x += p.width

    return canvas


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    # Validate inputs
    for required in (args.source, args.foreground_mask, args.model_path):
        if not required.exists():
            raise FileNotFoundError(required)

    # Set GPU
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)

    # Load source image
    source = Image.open(args.source).convert("RGB")
    src_w, src_h = source.size
    print(f"Source: {args.source} ({src_w}×{src_h})")

    # Load foreground mask (same convention as DA3 script: threshold ≥ 32)
    mask_img = Image.open(args.foreground_mask).convert("L")
    mask_img = mask_img.resize(source.size, Image.Resampling.BILINEAR)
    foreground = np.asarray(mask_img, dtype=np.uint8) >= 32
    fg_pct = 100.0 * foreground.sum() / foreground.size
    print(f"Foreground mask: {foreground.sum()} px ({fg_pct:.1f}%)")

    # Load MoGe model
    print(f"Loading MoGe v2 from {args.model_path} …")
    model = load_moge_model(args.model_path, gpu=args.gpu)

    # Run inference
    print(f"Running inference (resolution_level={args.resolution_level}) …")
    depth, mask_pred, normal = run_moge_inference(
        model,
        source,
        foreground,
        resolution_level=args.resolution_level,
        gpu=args.gpu,
    )

    # Depth statistics (metric, before masking)
    depth_fg = depth[foreground & np.isfinite(depth) & (depth > 1e-6)]
    if len(depth_fg) > 0:
        print(
            f"Raw depth (foreground): "
            f"min={depth_fg.min():.4f}  "
            f"median={np.median(depth_fg):.4f}  "
            f"max={depth_fg.max():.4f}  "
            f"mean={depth_fg.mean():.4f}"
        )
    else:
        print("WARNING: No valid foreground depth pixels in raw output!")

    # Process depth
    depth_u8, p02, p98 = process_depth(depth, foreground)
    print(f"Inverse depth percentiles: p02={p02:.6f}, p98={p98:.6f}")

    # Process normals
    if normal is None:
        raise RuntimeError(
            "MoGe v2 model did not produce normal output. "
            "Ensure you are using the 'moge-2-vitl-normal' checkpoint."
        )
    normal_u8 = process_normal(normal, foreground)

    # Normal coverage statistics
    normal_valid = foreground & np.isfinite(normal).all(axis=-1) & (np.abs(normal).max(axis=-1) > 1e-6)
    normal_coverage = normal_valid.sum() / max(foreground.sum(), 1)
    print(f"Normal coverage (foreground with valid normals): {normal_coverage:.1%}")

    # Warn if large flat regions (indicates model degradation on anime content)
    from scipy import ndimage
    normal_mag = np.linalg.norm(normal, axis=-1)
    normal_mag_valid = np.where(foreground, normal_mag, 0)
    # Check for regions where normal magnitude is near-zero (degraded)
    degraded = foreground & (normal_mag < 0.01)
    degraded_pct = 100.0 * degraded.sum() / max(foreground.sum(), 1)
    if degraded_pct > 5.0:
        print(
            f"WARNING: {degraded_pct:.1f}% of foreground has near-zero normal magnitude — "
            f"MoGe may be struggling with anime-style flat shading regions."
        )
    else:
        print(f"Degraded normal regions: {degraded_pct:.1f}% of foreground")

    # -----------------------------------------------------------------------
    # Write outputs
    # -----------------------------------------------------------------------
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.output_stem

    depth_png_path = args.output_dir / f"{stem}_moge_depth.png"
    normal_png_path = args.output_dir / f"{stem}_moge_normal.png"
    depth_npy_path = args.output_dir / f"{stem}_moge_depth_raw.npy"

    # Depth PNG (3-channel grayscale, same as DA3 script)
    depth_rgb = Image.merge("RGB", [Image.fromarray(depth_u8)] * 3)
    atomic_png(depth_rgb, depth_png_path)
    print(f"Depth PNG:  {depth_png_path}")

    # Normal PNG
    normal_rgb = Image.fromarray(normal_u8, mode="RGB")
    atomic_png(normal_rgb, normal_png_path)
    print(f"Normal PNG: {normal_png_path}")

    # Raw depth .npy (for mesh construction in Phase 3)
    atomic_npy(depth, depth_npy_path)
    print(f"Raw depth:  {depth_npy_path}  shape={depth.shape}  dtype={depth.dtype}")

    # Three-panel comparison
    if not args.no_comparison:
        comparison = make_comparison_panel(args.da3_depth, depth_u8, normal_u8)
        if comparison is not None:
            comparison_path = args.output_dir / f"{stem}_moge_comparison.png"
            atomic_png(comparison, comparison_path)
            print(f"Comparison: {comparison_path}")

    # -----------------------------------------------------------------------
    # Manifest (same pattern as DA3 script)
    # -----------------------------------------------------------------------
    manifest = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "provider": "server_local_moge_v2_offline",
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "foreground_mask": str(args.foreground_mask.resolve()),
        "foreground_mask_sha256": sha256(args.foreground_mask),
        "model": str(args.model_path.resolve()),
        "model_revision": args.model_path.parent.name,
        "resolution_level": args.resolution_level,
        "moge_version": "v2",
        "depth_shape": list(depth.shape),
        "inverse_depth_percentiles": {"p02": p02, "p98": p98},
        "normal_coverage": round(normal_coverage, 4),
        "depth_png": str(depth_png_path.resolve()),
        "depth_png_sha256": sha256(depth_png_path),
        "normal_png": str(normal_png_path.resolve()),
        "normal_png_sha256": sha256(normal_png_path),
        "depth_raw_npy": str(depth_npy_path.resolve()),
        "network_policy": "offline_local_files_only",
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "conda_env": "air310",
    }
    manifest_path = depth_png_path.with_suffix(".json")
    atomic_json(manifest_path, manifest)
    print(f"Manifest:   {manifest_path}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
