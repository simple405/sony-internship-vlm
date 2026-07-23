#!/usr/bin/env python3
"""Relight the exact source pixels with server-local depth for a 3D/PBR candidate."""

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


PROJECT_ROOT = Path("/home/intern/Supervised 2D to 3D")
DEFAULT_SOURCE = Path(
    "/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/cleaned_white.png"
)
DEFAULT_MASK = Path(
    "/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/foreground_mask.png"
)
DEFAULT_DEPTH = (
    PROJECT_ROOT
    / "vlm/experiments/comfyui_output/front_view_local/char_001/candidates/"
    "char_001_da3_depth.png"
)
DEFAULT_GEOMETRY_NORMAL = (
    PROJECT_ROOT
    / "vlm/experiments/comfyui_output/front_view_local/char_001/candidates/"
    "char_001_step1x3d_round2/geometry_renders/normal_000.png"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "vlm/experiments/comfyui_output/front_view_local/char_001/candidates/"
    "char_001_depth_pbr_round1.png"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--foreground-mask", type=Path, default=DEFAULT_MASK)
    parser.add_argument("--depth", type=Path, default=DEFAULT_DEPTH)
    parser.add_argument("--geometry-normal", type=Path, default=DEFAULT_GEOMETRY_NORMAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--normal-strength", type=float, default=20.0)
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


def normalize(vector: np.ndarray) -> np.ndarray:
    return vector / np.maximum(np.linalg.norm(vector, axis=-1, keepdims=True), 1e-6)


def main() -> None:
    args = parse_args()
    for path in (args.source, args.foreground_mask, args.depth, args.geometry_normal):
        if not path.is_file():
            raise FileNotFoundError(path)

    source_pil = Image.open(args.source).convert("RGB")
    size = source_pil.size
    mask_pil = Image.open(args.foreground_mask).convert("L").resize(
        size, Image.Resampling.BILINEAR
    )
    depth_pil = Image.open(args.depth).convert("L").resize(size, Image.Resampling.BICUBIC)
    depth_pil = depth_pil.filter(ImageFilter.GaussianBlur(radius=3.0))

    source = np.asarray(source_pil, dtype=np.float32) / 255.0
    mask = np.asarray(mask_pil, dtype=np.float32) / 255.0
    depth = np.asarray(depth_pil, dtype=np.float32) / 255.0

    height, width = depth.shape
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    x = xx / max(width - 1, 1)
    y = yy / max(height - 1, 1)

    # DA3 supplies the silhouette and coarse depth. Smooth semantic convexity
    # adds figure-like face/torso volume without repainting any source pixels.
    head = np.exp(-(((x - 0.50) / 0.28) ** 2 + ((y - 0.29) / 0.21) ** 2) * 1.4)
    torso = np.exp(-(((x - 0.50) / 0.42) ** 2 + ((y - 0.67) / 0.34) ** 2) * 1.6)
    left_sleeve = np.exp(-(((x - 0.12) / 0.22) ** 2 + ((y - 0.60) / 0.30) ** 2) * 1.5)
    right_sleeve = np.exp(-(((x - 0.88) / 0.22) ** 2 + ((y - 0.60) / 0.30) ** 2) * 1.5)
    height_field = np.clip(
        0.56 * depth + 0.28 * head + 0.12 * torso + 0.08 * (left_sleeve + right_sleeve),
        0.0,
        1.0,
    ) * mask

    grad_y, grad_x = np.gradient(height_field)
    depth_normals = np.stack(
        [
            -grad_x * args.normal_strength,
            -grad_y * args.normal_strength,
            np.ones_like(depth),
        ],
        axis=-1,
    )
    depth_normals = normalize(depth_normals)

    geometry_image = Image.open(args.geometry_normal).convert("RGB")
    geometry_array = np.asarray(geometry_image, dtype=np.uint8)
    geometry_foreground = np.any(geometry_array < 250, axis=-1)
    geometry_points = np.argwhere(geometry_foreground)
    source_points = np.argwhere(mask >= 0.12)
    if geometry_points.size == 0 or source_points.size == 0:
        raise RuntimeError("Cannot align geometry normal map to the source foreground")
    gy1, gx1 = geometry_points.min(axis=0)
    gy2, gx2 = geometry_points.max(axis=0) + 1
    sy1, sx1 = source_points.min(axis=0)
    sy2, sx2 = source_points.max(axis=0) + 1
    geometry_crop = geometry_image.crop((int(gx1), int(gy1), int(gx2), int(gy2)))
    geometry_crop = geometry_crop.resize(
        (int(sx2 - sx1), int(sy2 - sy1)), Image.Resampling.BICUBIC
    )
    aligned_geometry = np.ones((height, width, 3), dtype=np.float32)
    aligned_geometry[sy1:sy2, sx1:sx2] = (
        np.asarray(geometry_crop, dtype=np.float32) / 255.0
    )
    geometry_normals = normalize(aligned_geometry * 2.0 - 1.0)
    normals = normalize(0.78 * geometry_normals + 0.22 * depth_normals)
    normals = np.where(mask[..., None] >= 0.12, normals, np.array([0.0, 0.0, 1.0]))

    light = normalize(np.array([-0.42, -0.48, 0.77], dtype=np.float32))
    view = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    half_vector = normalize(light + view)
    diffuse = np.clip(np.sum(normals * light, axis=-1), 0.0, 1.0)
    specular = np.clip(np.sum(normals * half_vector, axis=-1), 0.0, 1.0) ** 42
    rim = np.clip(1.0 - normals[..., 2], 0.0, 1.0) ** 1.7

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

    maximum = source.max(axis=-1)
    minimum = source.min(axis=-1)
    saturation = maximum - minimum
    bright_material = np.clip((maximum - 0.72) / 0.28, 0.0, 1.0)
    glossy_material = np.clip(0.16 + 0.42 * saturation + 0.20 * bright_material, 0.0, 0.62)

    linear = np.power(np.clip(source, 0.0, 1.0), 2.2)
    lit = linear * shade[..., None]
    highlight = (0.32 * specular * glossy_material + 0.12 * rim) * mask
    highlight = np.asarray(
        Image.fromarray(np.round(np.clip(highlight, 0.0, 1.0) * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius=3.0)
        ),
        dtype=np.float32,
    ) / 255.0
    highlight_color = np.array([1.0, 0.96, 0.90], dtype=np.float32)
    lit += highlight[..., None] * highlight_color
    lit = np.power(np.clip(lit, 0.0, 1.0), 1.0 / 2.2)

    # A soft rear shadow separates the figure from the white studio backdrop.
    shadow_source = Image.new("L", size, 0)
    shadow_source.paste(mask_pil, (5, 7))
    shadow = np.asarray(
        shadow_source.filter(ImageFilter.GaussianBlur(radius=9.0)), dtype=np.float32
    ) / 255.0
    background = np.ones_like(source)
    background *= (1.0 - 0.10 * shadow[..., None] * (1.0 - mask[..., None]))
    composed = lit * mask[..., None] + background * (1.0 - mask[..., None])

    output = Image.fromarray(np.round(np.clip(composed, 0.0, 1.0) * 255).astype(np.uint8))
    if args.scale > 1:
        output = output.resize(
            (output.width * args.scale, output.height * args.scale),
            Image.Resampling.LANCZOS,
        )
        output = ImageEnhance.Sharpness(output).enhance(1.12)
    atomic_png(output, args.output)

    manifest = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "provider": "deterministic_source_pixels_plus_server_local_da3_depth",
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "foreground_mask": str(args.foreground_mask.resolve()),
        "foreground_mask_sha256": sha256(args.foreground_mask),
        "depth": str(args.depth.resolve()),
        "depth_sha256": sha256(args.depth),
        "geometry_normal": str(args.geometry_normal.resolve()),
        "geometry_normal_sha256": sha256(args.geometry_normal),
        "settings": {
            "scale": args.scale,
            "normal_strength": args.normal_strength,
            "lighting": "pbr_key_fill_specular_rim",
            "source_pixel_policy": "no_generative_repaint",
        },
        "output": str(args.output.resolve()),
        "output_sha256": sha256(args.output),
        "network_policy": "no_network_required",
    }
    atomic_json(args.output.with_suffix(".json"), manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
