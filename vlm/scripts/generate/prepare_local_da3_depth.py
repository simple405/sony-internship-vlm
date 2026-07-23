#!/usr/bin/env python3
"""Prepare an offline Depth Anything 3 control image for a local FLUX run."""

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

PROJECT_ROOT = Path("/home/intern/Supervised 2D to 3D")
DA3_SOURCE_ROOT = Path("/home/intern/kcc/code/Depth-Anything-3/src")
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--foreground-mask", type=Path, default=DEFAULT_MASK)
    parser.add_argument("--model", type=Path, default=DA3_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--process-res", type=int, default=504)
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
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def atomic_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    image.save(temp, format="PNG", optimize=True)
    os.replace(temp, path)


def main() -> None:
    args = parse_args()
    for required in (args.source, args.foreground_mask, args.model / "model.safetensors"):
        if not required.exists():
            raise FileNotFoundError(required)

    sys.path.insert(0, str(DA3_SOURCE_ROOT))
    import torch
    from depth_anything_3.api import DepthAnything3

    model = DepthAnything3.from_pretrained(
        args.model,
        local_files_only=True,
    ).to(device=torch.device("cuda"))
    prediction = model.inference(
        [str(args.source)],
        process_res=args.process_res,
        process_res_method="upper_bound_resize",
    )

    depth = np.asarray(prediction.depth[0], dtype=np.float32)
    source = Image.open(args.source).convert("RGB")
    depth_image = Image.fromarray(depth, mode="F").resize(source.size, Image.Resampling.BICUBIC)
    depth = np.asarray(depth_image, dtype=np.float32)

    mask_image = Image.open(args.foreground_mask).convert("L").resize(
        source.size, Image.Resampling.BILINEAR
    )
    foreground = np.asarray(mask_image, dtype=np.uint8) >= 32
    valid = foreground & np.isfinite(depth) & (depth > 1e-6)
    if int(valid.sum()) < 100:
        raise RuntimeError("DA3 returned too few valid foreground depth pixels")

    inverse_depth = np.zeros_like(depth, dtype=np.float32)
    inverse_depth[valid] = 1.0 / depth[valid]
    low, high = np.percentile(inverse_depth[valid], [2.0, 98.0])
    if not high > low:
        raise RuntimeError(f"Degenerate DA3 depth range: low={low}, high={high}")
    normalized = np.clip((inverse_depth - low) / (high - low), 0.0, 1.0)
    normalized[~foreground] = 0.0
    depth_u8 = np.round(normalized * 255.0).astype(np.uint8)
    output_image = Image.merge("RGB", [Image.fromarray(depth_u8)] * 3)
    atomic_png(output_image, args.output)

    manifest = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "provider": "server_local_depth_anything_3_offline",
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "foreground_mask": str(args.foreground_mask.resolve()),
        "foreground_mask_sha256": sha256(args.foreground_mask),
        "model": str(args.model.resolve()),
        "model_revision": args.model.name,
        "process_res": args.process_res,
        "raw_depth_shape": list(prediction.depth[0].shape),
        "inverse_depth_percentiles": {"p02": float(low), "p98": float(high)},
        "output": str(args.output.resolve()),
        "output_sha256": sha256(args.output),
        "network_policy": "offline_local_files_only",
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }
    atomic_json(args.output.with_suffix(".json"), manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
