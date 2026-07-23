#!/usr/bin/env python3
"""Generate an offline Step1X-3D mesh and texture from the char_001 reference."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

PROJECT_ROOT = Path("/home/intern/Supervised 2D to 3D")
STEP1X_CODE = Path("/home/intern/liuhongliang/Step1X-3D")
STEP1X_MODEL = Path(
    "/home/intern/.cache/huggingface/hub/"
    "models--stepfun-ai--Step1X-3D/snapshots/"
    "bf7084495b3a72222f36549b7942948aa4d9daa7"
)
SDXL_MODEL = Path("/home/intern/local-ai-models/comfyui/diffusers/sdxl-base-1.0")
SDXL_VAE = Path(
    "/home/intern/.cache/huggingface/hub/"
    "models--madebyollin--sdxl-vae-fp16-fix/snapshots/"
    "207b116dae70ace3637169f1ddd2434b91b3a8cd"
)
DEFAULT_SOURCE = Path(
    "/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/cleaned_white.png"
)
DEFAULT_MASK = Path(
    "/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/foreground_mask.png"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "vlm/experiments/comfyui_output/front_view_local/char_001/candidates/"
    "char_001_step1x3d_round1"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--foreground-mask", type=Path, default=DEFAULT_MASK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stage", choices=("geometry", "texture", "all"), default="all")
    parser.add_argument("--geometry-steps", type=int, default=30)
    parser.add_argument("--texture-steps", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260722005)
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


def validate_local_inputs(source: Path, foreground_mask: Path) -> None:
    required = [
        source,
        foreground_mask,
        STEP1X_MODEL / "Step1X-3D-Geometry-1300m/model_index.json",
        STEP1X_MODEL
        / "Step1X-3D-Geometry-1300m/transformer/diffusion_pytorch_model.safetensors",
        STEP1X_MODEL / "Step1X-3D-Texture/step1x-3d-ig2v.safetensors",
        SDXL_MODEL / "model_index.json",
        SDXL_MODEL / "unet/diffusion_pytorch_model.safetensors",
        SDXL_VAE / "diffusion_pytorch_model.safetensors",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Incomplete server-local inputs:\n" + "\n".join(missing))


def main() -> None:
    args = parse_args()
    validate_local_inputs(args.source, args.foreground_mask)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    geometry_path = args.output_dir / "char_001_geometry.glb"
    textured_path = args.output_dir / "char_001_textured.glb"
    intermediate_dir = args.output_dir / "texture_intermediates"
    transparent_source = args.output_dir / "char_001_transparent_input.png"

    source_image = Image.open(args.source).convert("RGB")
    alpha = Image.open(args.foreground_mask).convert("L").resize(
        source_image.size, Image.Resampling.BILINEAR
    )
    rgba = source_image.convert("RGBA")
    rgba.putalpha(alpha)
    rgba.save(transparent_source, format="PNG", optimize=True)

    sys.path.insert(0, str(STEP1X_CODE))
    import torch
    import trimesh
    from step1x3d_geometry.models.pipelines.pipeline import Step1X3DGeometryPipeline
    from step1x3d_geometry.models.pipelines.pipeline_utils import (
        reduce_face,
        remove_degenerate_face,
    )
    from step1x3d_texture.pipelines.step1x_3d_texture_synthesis_pipeline import (
        Step1X3DTextureConfig,
        Step1X3DTexturePipeline,
    )

    if args.stage in {"geometry", "all"}:
        geometry = Step1X3DGeometryPipeline.from_pretrained(
            STEP1X_MODEL,
            subfolder="Step1X-3D-Geometry-1300m",
            local_files_only=True,
            torch_dtype=torch.float16,
        ).to("cuda")
        generator = torch.Generator(device=geometry.device).manual_seed(args.seed)
        output = geometry(
            str(transparent_source),
            guidance_scale=8.0,
            num_inference_steps=args.geometry_steps,
            generator=generator,
            force_remove_background=False,
            foreground_ratio=0.95,
            octree_resolution=384,
            max_facenum=200000,
        )
        output.mesh[0].export(geometry_path)
        del output, generator, geometry
        gc.collect()
        torch.cuda.empty_cache()

    if args.stage in {"texture", "all"}:
        if not geometry_path.is_file():
            raise FileNotFoundError(geometry_path)
        mesh = trimesh.load(geometry_path, force="mesh")
        mesh = remove_degenerate_face(mesh)
        mesh = reduce_face(mesh)

        config = Step1X3DTextureConfig()
        config.base_model = str(SDXL_MODEL)
        config.vae_model = str(SDXL_VAE)
        config.adapter_path = str(STEP1X_MODEL / "Step1X-3D-Texture")
        config.adapter_weight_name = "step1x-3d-ig2v.safetensors"
        config.device = "cuda"
        config.dtype = torch.float16
        config.num_inference_steps = args.texture_steps
        config.guidance_scale = 3.5
        config.reference_conditioning_scale = 1.2
        config.text = "high quality 3D anime resin figure, exact reference colors and costume"
        config.negative_prompt = (
            "watermark, text, logo, redesigned costume, missing accessory, wrong colors, "
            "deformed face, noisy, blurry, low detail"
        )
        config.render_size = 1024
        config.texture_size = 1024
        config.texture_sync_config["texture_size"] = 1024
        config.save_intermediates = True
        config.intermediate_dir = str(intermediate_dir)

        texture = Step1X3DTexturePipeline(config)
        texture.ig2mv_pipe.vae.enable_slicing()
        texture.ig2mv_pipe.vae.enable_tiling()
        textured_mesh = texture(str(args.source), mesh, remove_bg=False, seed=args.seed)
        textured_mesh.export(textured_path)
        del textured_mesh, texture, mesh
        gc.collect()
        torch.cuda.empty_cache()

    manifest = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "provider": "server_local_step1x3d_offline",
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "foreground_mask": str(args.foreground_mask.resolve()),
        "foreground_mask_sha256": sha256(args.foreground_mask),
        "transparent_geometry_input": str(transparent_source.resolve()),
        "transparent_geometry_input_sha256": sha256(transparent_source),
        "stage": args.stage,
        "models": {
            "step1x": str(STEP1X_MODEL.resolve()),
            "step1x_revision": STEP1X_MODEL.name,
            "sdxl": str(SDXL_MODEL.resolve()),
            "sdxl_vae": str(SDXL_VAE.resolve()),
        },
        "settings": {
            "geometry_steps": args.geometry_steps,
            "texture_steps": args.texture_steps,
            "seed": args.seed,
            "octree_resolution": 384,
            "max_facenum": 200000,
            "texture_size": 1024,
            "render_size": 1024,
            "reference_conditioning_scale": 1.2,
        },
        "geometry": str(geometry_path.resolve()) if geometry_path.is_file() else None,
        "geometry_sha256": sha256(geometry_path) if geometry_path.is_file() else None,
        "textured": str(textured_path.resolve()) if textured_path.is_file() else None,
        "textured_sha256": sha256(textured_path) if textured_path.is_file() else None,
        "intermediates": str(intermediate_dir.resolve()),
        "network_policy": "offline_local_files_only",
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }
    atomic_json(args.output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
