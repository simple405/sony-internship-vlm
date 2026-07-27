#!/usr/bin/env python3
"""Prepare an offline Depth Anything 3 control image for a local FLUX run.

This script implements the DA3-SMALL depth estimation pipeline for generating
ControlNet-compatible depth maps used in local FLUX image generation. It runs
fully offline against a locally cached Hugging Face model snapshot, producing
a normalised 8-bit grayscale PNG depth image and a JSON provenance manifest.

High-level pipeline
-------------------
1. Load the source (cleaned white-background) image and its foreground mask.
2. Run DA3-SMALL inference (GPU) to obtain a float32 metric depth map.
3. Resize the raw depth prediction back to the original image resolution.
4. Convert to inverse-depth so that closer objects are brighter (ControlNet
   convention: white = near, black = far).
5. Robust-normalise via 2 %/98 % percentile clipping to suppress outliers.
6. Zero-out background pixels so the depth cue is strictly foreground-only.
7. Write the result as an optimised PNG (atomic write to avoid partial files).
8. Write a JSON manifest with SHA-256 checksums and run metadata for
   reproducibility and provenance tracking.

Dependencies
------------
- depth_anything_3  (loaded from DA3_SOURCE_ROOT at runtime)
- torch             (CUDA required)
- numpy, Pillow
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


# ---------------------------------------------------------------------------
# Offline mode: prevent any accidental network calls to the Hugging Face hub.
# HF_HUB_OFFLINE and TRANSFORMERS_OFFLINE together ensure that both the hub
# client and the transformers library refuse to download anything at runtime.
# HF_HUB_DISABLE_TELEMETRY suppresses usage-metrics pings.
# ---------------------------------------------------------------------------
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# ---------------------------------------------------------------------------
# Path constants — centralised so they are easy to update per deployment.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path("/home/intern/Supervised 2D to 3D")

# DA3 ships its Python package under src/, which is not installed into the
# virtualenv; we add it to sys.path at runtime inside main() so the import
# works without a local editable install.
DA3_SOURCE_ROOT = Path("/home/intern/kcc/code/Depth-Anything-3/src")

# Full path to the specific model snapshot (immutable content-addressed dir).
DA3_MODEL = Path(
    "/home/intern/.cache/huggingface/hub/"
    "models--depth-anything--DA3-SMALL/snapshots/"
    "e08cab65ca0ec38e7826075418411ab90cab4da3"
)
DEFAULT_SOURCE = Path(
    "/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/cleaned_white.png"
)
DEFAULT_MASK = Path(
    "/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/foreground_mask.png"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "vlm/experiments/comfyui_output/front_view_local/char_001/candidates/"
    "char_001_da3_depth.png"
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the depth preparation script.

    All arguments are optional; defaults point to the canonical char_001
    test asset so the script can be run stand-alone without any flags during
    development.

    Returns
    -------
    argparse.Namespace
        Parsed arguments with attributes: source, foreground_mask, model,
        output, process_res.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--foreground-mask", type=Path, default=DEFAULT_MASK)
    parser.add_argument("--model", type=Path, default=DA3_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    # process_res controls the internal inference resolution of DA3-SMALL.
    # 504 is the value recommended by the DA3 authors for the SMALL variant;
    # higher values increase accuracy at the cost of VRAM and latency.
    parser.add_argument("--process-res", type=int, default=504)
    return parser.parse_args()


def sha256(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file.

    SHA-256 checksums serve as tamper-evident provenance tokens in the JSON
    manifest: they let downstream users verify that the exact same source
    image, foreground mask, and output depth map were used/produced, and
    detect accidental file corruption or unintended regeneration.

    The file is read in 1 MiB chunks to keep peak memory usage flat
    regardless of file size.

    Parameters
    ----------
    path : Path
        Absolute path to the file to hash.

    Returns
    -------
    str
        64-character lowercase hex string (256 bits).
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        # Read in 1 MiB chunks; sentinel b"" signals end-of-file.
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    """Write a JSON-serialisable value to *path* atomically.

    The file is first written to a randomly named sibling temp file (with a
    .tmp extension) in the same directory, then renamed over the target path
    via os.replace().  On POSIX systems os.replace() is a single syscall
    (rename(2)) which is guaranteed to be atomic: readers never see a
    partially-written file.  On Windows it is as close to atomic as the
    filesystem allows.

    Using a .tmp extension (rather than .part) distinguishes in-progress JSON
    writes from in-progress PNG writes, making stale temp files easier to
    identify and clean up manually if a run is interrupted.

    Parameters
    ----------
    path : Path
        Destination path for the finished JSON file.
    value : object
        Any JSON-serialisable Python object (dict, list, str, …).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # uuid4 in the temp name prevents collisions when multiple processes write
    # to the same output directory concurrently.
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Atomic rename: the destination either contains the old content or the
    # new content — never a partial write.
    os.replace(temp, path)


def atomic_png(image: Image.Image, path: Path) -> None:
    """Save a Pillow image to *path* as an optimised PNG, atomically.

    Like atomic_json(), this function writes to a uniquely-named temp file
    first, then renames it into place.  This guarantees that:

    * A ComfyUI watcher polling the output directory never loads an
      incomplete PNG and raises a decode error.
    * If this script is interrupted (OOM, keyboard interrupt, power loss),
      the previous valid depth image at *path* is preserved unchanged.

    The .tmp extension marks the file as "in-flight" so that any cleanup
    script can safely remove files matching ``.*.<hex>.tmp`` that are older
    than a few minutes without touching finished outputs.

    Parameters
    ----------
    image : Image.Image
        Pillow image to save.
    path : Path
        Destination path for the finished PNG file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp name in the same directory to guarantee same-filesystem
    # rename (cross-device rename would not be atomic).
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    image.save(temp, format="PNG", optimize=True)
    os.replace(temp, path)


def main() -> None:
    """Run the DA3-SMALL depth estimation pipeline end-to-end.

    Raises
    ------
    FileNotFoundError
        If the source image, foreground mask, or model weights are missing.
    RuntimeError
        If DA3 returns too few valid foreground depth pixels (< 100), or if
        the foreground inverse-depth range is degenerate (all pixels equal).
    """
    args = parse_args()

    # Fail fast before loading the model: check that all required input files
    # exist so we do not waste ~10 s of model-load time on a missing input.
    for required in (args.source, args.foreground_mask, args.model / "model.safetensors"):
        if not required.exists():
            raise FileNotFoundError(required)

    # Add the DA3 source tree to sys.path so "from depth_anything_3.api …"
    # resolves correctly without a pip-installed package.
    sys.path.insert(0, str(DA3_SOURCE_ROOT))
    import torch
    from depth_anything_3.api import DepthAnything3

    # Load model weights from the local snapshot; local_files_only=True
    # raises an error rather than silently falling back to the network,
    # which would violate the offline policy set at the top of this module.
    model = DepthAnything3.from_pretrained(
        args.model,
        local_files_only=True,
    ).to(device=torch.device("cuda"))

    # Run inference at process_res=504 (upper_bound_resize keeps the longer
    # side ≤ 504 px before feeding into the ViT backbone, then the model
    # outputs a depth map at that reduced resolution).
    prediction = model.inference(
        [str(args.source)],
        process_res=args.process_res,
        process_res_method="upper_bound_resize",
    )

    # -----------------------------------------------------------------------
    # Step 1: resize raw depth back to the original image resolution.
    # DA3 runs on a downsampled input; we upscale with BICUBIC interpolation
    # to recover smooth depth transitions at full resolution.
    # -----------------------------------------------------------------------
    depth = np.asarray(prediction.depth[0], dtype=np.float32)
    source = Image.open(args.source).convert("RGB")
    depth_image = Image.fromarray(depth, mode="F").resize(source.size, Image.Resampling.BICUBIC)
    depth = np.asarray(depth_image, dtype=np.float32)

    # -----------------------------------------------------------------------
    # Step 2: load and apply the foreground mask.
    # The mask is an 8-bit single-channel PNG where white (255) = foreground
    # and black (0) = background.  The threshold of 32 (out of 255) is
    # intentionally low — it is ~12.5 % of full white — so that soft/
    # anti-aliased mask edges (values 1–31, produced by matting tools or
    # feathered selections) are still classified as background, while any
    # pixel that was clearly painted as foreground (≥ 32) is included.
    # Using a strict >0 threshold would pull in JPEG compression artefacts
    # and mask anti-aliasing noise; 32 gives a clean binary boundary.
    # -----------------------------------------------------------------------
    mask_image = Image.open(args.foreground_mask).convert("L").resize(
        source.size, Image.Resampling.BILINEAR
    )
    foreground = np.asarray(mask_image, dtype=np.uint8) >= 32  # see note above

    # A pixel is "valid" only if it is in the foreground, has a finite depth
    # value (no NaN/Inf from the model), and has a positive depth > 1e-6
    # (avoid division-by-zero in the inverse-depth step below).
    valid = foreground & np.isfinite(depth) & (depth > 1e-6)
    if int(valid.sum()) < 100:
        raise RuntimeError("DA3 returned too few valid foreground depth pixels")

    # -----------------------------------------------------------------------
    # Step 3: compute inverse depth (1 / depth).
    # DA3 outputs metric depth in metres (larger value = further away).
    # ControlNet depth maps follow the opposite convention used by MiDaS and
    # most monocular depth networks: brighter pixels are closer to the camera.
    # Taking the reciprocal 1/d converts metric depth to "disparity-like"
    # inverse depth, where small d (near) → large 1/d (bright) and large d
    # (far) → small 1/d (dark), matching the ControlNet expectation.
    # -----------------------------------------------------------------------
    inverse_depth = np.zeros_like(depth, dtype=np.float32)
    inverse_depth[valid] = 1.0 / depth[valid]  # only valid pixels; rest stay 0

    # -----------------------------------------------------------------------
    # Step 4: robust 2 %/98 % percentile normalisation.
    # A simple min/max normalisation would be dominated by outlier depth
    # values (e.g. a single spurious very-near or very-far pixel collapses
    # almost the entire scene to mid-grey).  Clipping at the 2nd and 98th
    # percentiles of the valid foreground pixels discards ~4 % of the most
    # extreme values, giving a stable and contrast-rich normalisation that
    # is robust to depth outliers and specular highlights.
    # The resulting range [low, high] spans the "normal" inverse-depth spread
    # of the character, and values outside it are clipped to [0, 1].
    # -----------------------------------------------------------------------
    low, high = np.percentile(inverse_depth[valid], [2.0, 98.0])
    if not high > low:
        raise RuntimeError(f"Degenerate DA3 depth range: low={low}, high={high}")
    normalized = np.clip((inverse_depth - low) / (high - low), 0.0, 1.0)

    # Force background pixels to 0 (pure black) after normalisation.
    # Even though inverse_depth was 0 in the background, floating-point
    # subtraction of `low` could produce a small positive value there; this
    # explicit zero-out guarantees a clean separation.
    normalized[~foreground] = 0.0

    # Quantise to 8-bit: round first to minimise systematic bias from
    # floor-truncation, then cast.
    depth_u8 = np.round(normalized * 255.0).astype(np.uint8)

    # Replicate the single channel across R, G, B to produce a standard
    # 3-channel grayscale PNG.  ComfyUI's ControlNet preprocessor expects
    # an RGB image even for grayscale depth maps.
    output_image = Image.merge("RGB", [Image.fromarray(depth_u8)] * 3)
    atomic_png(output_image, args.output)

    # -----------------------------------------------------------------------
    # Step 5: write a provenance manifest alongside the depth image.
    # SHA-256 checksums of the source image, foreground mask, and output
    # depth PNG provide a tamper-evident audit trail: any re-run with
    # different inputs will produce different hashes, making accidental
    # overwrite or silent regeneration detectable by comparing manifests.
    # The manifest also records the exact model snapshot revision (directory
    # name = git commit SHA of the weights), inference resolution, raw depth
    # shape, and normalisation parameters so that the depth image can be
    # reproduced exactly from the manifest alone.
    # -----------------------------------------------------------------------
    manifest = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "provider": "server_local_depth_anything_3_offline",
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "foreground_mask": str(args.foreground_mask.resolve()),
        "foreground_mask_sha256": sha256(args.foreground_mask),
        "model": str(args.model.resolve()),
        "model_revision": args.model.name,  # = HF snapshot commit SHA
        "process_res": args.process_res,
        "raw_depth_shape": list(prediction.depth[0].shape),
        "inverse_depth_percentiles": {"p02": float(low), "p98": float(high)},
        "output": str(args.output.resolve()),
        "output_sha256": sha256(args.output),  # hash of the finished PNG
        "network_policy": "offline_local_files_only",
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }
    atomic_json(args.output.with_suffix(".json"), manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
