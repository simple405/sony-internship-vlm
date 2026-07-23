#!/usr/bin/env python3
"""Relight the exact source pixels using MoGe v2 surface normals for a 3D/PBR candidate.

Key differences from ``render_local_depth_pbr.py``:
- Uses MoGe v2 directly-predicted surface normals (no gradient-from-depth).
- No DA3-SMALL depth, no Step1X geometry normals, no 78/22 blending hack.
- No ``--normal-strength`` parameter — MoGe normals are naturally strong.
- All other Phong lighting, material estimation, compositing, and post-processing
  are identical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


PROJECT_ROOT = Path("/home/intern/jsy")
CANDIDATES_DIR = (
    PROJECT_ROOT
    / "vlm/experiments/comfyui_output/front_view_local/char_001/candidates"
)

DEFAULT_SOURCE = Path(
    "/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/cleaned_white.png"
)
DEFAULT_MASK = Path(
    "/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/foreground_mask.png"
)
DEFAULT_MOGE_DEPTH = CANDIDATES_DIR / "char_001_moge_depth.png"
DEFAULT_MOGE_NORMAL = CANDIDATES_DIR / "char_001_moge_normal.png"
DEFAULT_OUTPUT = CANDIDATES_DIR / "char_001_moge_pbr.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--foreground-mask", type=Path, default=DEFAULT_MASK)
    parser.add_argument("--moge-depth", type=Path, default=DEFAULT_MOGE_DEPTH)
    parser.add_argument("--moge-normal", type=Path, default=DEFAULT_MOGE_NORMAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--scale", type=int, default=2)
    return parser.parse_args()


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


def normalize(vector: np.ndarray) -> np.ndarray:
    return vector / np.maximum(np.linalg.norm(vector, axis=-1, keepdims=True), 1e-6)


def load_moge_normals(
    normal_path: Path, target_size: tuple[int, int]
) -> np.ndarray:
    """Load an OpenGL RGB normal map from PNG and convert to unit vectors.

    Phase 1 saves normals as OpenGL convention (R=right, G=up, B=out-of-surface)
    with values [0,255] mapped to [-1,1].
    Returns (H, W, 3) float32 array of unit-length normal vectors.
    """
    pil_img = Image.open(normal_path).convert("RGB").resize(
        target_size, Image.Resampling.BICUBIC
    )
    normals_u8 = np.asarray(pil_img, dtype=np.float32)
    # [0, 255] → [0, 1] → [-1, 1]
    normals = normals_u8 / 255.0 * 2.0 - 1.0
    # Re-normalize (resampling may have introduced small length errors)
    return normalize(normals)


def load_moge_depth(
    depth_path: Path, target_size: tuple[int, int]
) -> np.ndarray:
    """Load the MoGe depth PNG for reference / depth cue blending.

    The depth range is very narrow for anime (~1 unit variation), so it
    contributes minimally to shading.  Included for consistency and optional
    depth-aware compositing.
    """
    pil_img = (
        Image.open(depth_path).convert("L").resize(target_size, Image.Resampling.BICUBIC)
    )
    return np.asarray(pil_img, dtype=np.float32) / 255.0


def main() -> None:
    args = parse_args()
    for path in (args.source, args.foreground_mask, args.moge_depth, args.moge_normal):
        if not path.is_file():
            raise FileNotFoundError(path)

    # ------------------------------------------------------------------
    # Load inputs
    # ------------------------------------------------------------------
    source_pil = Image.open(args.source).convert("RGB")
    size = source_pil.size
    w, h = size

    mask_pil = Image.open(args.foreground_mask).convert("L").resize(
        size, Image.Resampling.BILINEAR
    )

    source = np.asarray(source_pil, dtype=np.float32) / 255.0
    mask = np.asarray(mask_pil, dtype=np.float32) / 255.0
    fg_mask = mask >= 0.12  # same threshold as original PBR script

    # MoGe normals are the primary shading driver
    normals = load_moge_normals(args.moge_normal, size)

    # Load depth for informational purposes only (not used for gradient normals)
    moge_depth = load_moge_depth(args.moge_depth, size)

    # ------------------------------------------------------------------
    # Phong lighting (SAME as render_local_depth_pbr.py)
    # ------------------------------------------------------------------
    light = normalize(np.array([-0.42, -0.48, 0.77], dtype=np.float32))
    view = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    half_vector = normalize(light + view)

    diffuse = np.clip(np.sum(normals * light, axis=-1), 0.0, 1.0)
    specular = np.clip(np.sum(normals * half_vector, axis=-1), 0.0, 1.0) ** 42
    rim = np.clip(1.0 - normals[..., 2], 0.0, 1.0) ** 1.7

    # ------------------------------------------------------------------
    # Inner edge shadow (from mask, same as original)
    # ------------------------------------------------------------------
    blurred_mask = np.asarray(
        mask_pil.filter(ImageFilter.GaussianBlur(radius=7.0)), dtype=np.float32
    ) / 255.0
    inner_edge = np.clip(mask - blurred_mask, 0.0, 1.0)

    shade = np.clip(0.38 + 0.78 * diffuse - 0.22 * inner_edge, 0.30, 1.18)
    shade_smooth = np.asarray(
        Image.fromarray(np.round(shade * 255.0).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius=11.0)
        ),
        dtype=np.float32,
    ) / 255.0
    shade = np.clip(0.90 * shade_smooth + 0.10 * shade, 0.36, 1.16)

    # ------------------------------------------------------------------
    # Material estimation (SAME — based on source pixel properties)
    # ------------------------------------------------------------------
    maximum = source.max(axis=-1)
    minimum = source.min(axis=-1)
    saturation = maximum - minimum
    bright_material = np.clip((maximum - 0.72) / 0.28, 0.0, 1.0)
    glossy_material = np.clip(
        0.16 + 0.42 * saturation + 0.20 * bright_material, 0.0, 0.62
    )

    # ------------------------------------------------------------------
    # Compose lit image (SAME linear → shade → gamma pipeline)
    # ------------------------------------------------------------------
    linear = np.power(np.clip(source, 0.0, 1.0), 2.2)
    lit = linear * shade[..., None]

    highlight = (0.32 * specular * glossy_material + 0.12 * rim) * mask
    highlight = np.asarray(
        Image.fromarray(
            np.round(np.clip(highlight, 0.0, 1.0) * 255).astype(np.uint8)
        ).filter(ImageFilter.GaussianBlur(radius=3.0)),
        dtype=np.float32,
    ) / 255.0
    highlight_color = np.array([1.0, 0.96, 0.90], dtype=np.float32)
    lit += highlight[..., None] * highlight_color
    lit = np.power(np.clip(lit, 0.0, 1.0), 1.0 / 2.2)

    # ------------------------------------------------------------------
    # Background with offset shadow (SAME)
    # ------------------------------------------------------------------
    shadow_source = Image.new("L", size, 0)
    shadow_source.paste(mask_pil, (5, 7))
    shadow = np.asarray(
        shadow_source.filter(ImageFilter.GaussianBlur(radius=9.0)), dtype=np.float32
    ) / 255.0
    background = np.ones_like(source)
    background *= 1.0 - 0.10 * shadow[..., None] * (1.0 - mask[..., None])
    composed = lit * mask[..., None] + background * (1.0 - mask[..., None])

    # ------------------------------------------------------------------
    # Upscale + sharpen (SAME)
    # ------------------------------------------------------------------
    output = Image.fromarray(
        np.round(np.clip(composed, 0.0, 1.0) * 255).astype(np.uint8)
    )
    if args.scale > 1:
        output = output.resize(
            (output.width * args.scale, output.height * args.scale),
            Image.Resampling.LANCZOS,
        )
        output = ImageEnhance.Sharpness(output).enhance(1.12)

    atomic_png(output, args.output)

    # ------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------
    manifest = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "provider": "deterministic_source_pixels_plus_server_local_moge_v2_normals",
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "foreground_mask": str(args.foreground_mask.resolve()),
        "foreground_mask_sha256": sha256(args.foreground_mask),
        "moge_depth": str(args.moge_depth.resolve()),
        "moge_depth_sha256": sha256(args.moge_depth),
        "moge_normal": str(args.moge_normal.resolve()),
        "moge_normal_sha256": sha256(args.moge_normal),
        "settings": {
            "scale": args.scale,
            "normal_blending": "100% MoGe v2 (no DA3, no Step1X, no gradient blending)",
            "lighting": "pbr_key_fill_specular_rim",
            "source_pixel_policy": "no_generative_repaint",
            "light_direction": [-0.42, -0.48, 0.77],
            "specular_exponent": 42,
            "rim_power": 1.7,
        },
        "output": str(args.output.resolve()),
        "output_sha256": sha256(args.output),
        "network_policy": "no_network_required",
    }
    atomic_json(args.output.with_suffix(".json"), manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
