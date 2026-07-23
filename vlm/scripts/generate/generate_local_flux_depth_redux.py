#!/usr/bin/env python3
"""Run an offline FLUX Depth + Redux identity/3D smoke candidate."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

PROJECT_ROOT = Path("/home/intern/Supervised 2D to 3D")
FLUX_DEPTH_MODEL = Path(
    "/home/intern/.cache/huggingface/hub/"
    "models--black-forest-labs--FLUX.1-Depth-dev/snapshots/"
    "fb5e9b1bae41b8c8adcea4ea2a87b74dd298f07a"
)
FLUX_REDUX_MODEL = Path(
    "/home/intern/.cache/huggingface/hub/"
    "models--black-forest-labs--FLUX.1-Redux-dev/snapshots/"
    "c95859fbf7703ca4d6824b4da4407d7cd0434f81"
)
DEFAULT_SOURCE = Path(
    "/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/cleaned_white.png"
)
DEFAULT_DEPTH = (
    PROJECT_ROOT
    / "vlm/experiments/comfyui_output/front_view_local/char_001/candidates/"
    "char_001_da3_depth.png"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "vlm/experiments/comfyui_output/front_view_local/char_001/candidates/"
    "char_001_flux_depth_redux_round1.png"
)

PROMPT = (
    "A high-end stylized 3D resin anime figure render of exactly the same young woman in the reference, "
    "strict straight-on front view and identical waist-up crop, identical face proportions and expression. "
    "Preserve every visible design detail one-for-one: long pale golden hair with peach-pink tips, one huge "
    "black bow centered on top of the head, vivid red eyes, tiny blue earrings, white shirt with the exact "
    "vertical ruffled placket and dark buttons, small black neck ribbon with one round blue gemstone ornament, "
    "dark skirt and waist with exactly two parallel gray horizontal bands, loose white coat with the same lapels, "
    "pockets, black buttons and arm placement. Clearly sculpted three-dimensional hair locks and garment thickness, "
    "painted PVC and resin materials, coherent soft studio key light, contact shading and rounded volume, clean pure "
    "white studio background. No redesign, no added accessory, no missing seam, no text, no watermark, no border."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--depth", type=Path, default=DEFAULT_DEPTH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--flux-model", type=Path, default=FLUX_DEPTH_MODEL)
    parser.add_argument("--redux-model", type=Path, default=FLUX_REDUX_MODEL)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=992)
    parser.add_argument("--steps", type=int, default=28)
    parser.add_argument("--guidance", type=float, default=10.0)
    parser.add_argument("--redux-strength", type=float, default=0.65)
    parser.add_argument("--seed", type=int, default=20260722004)
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


def validate_local_models(flux_model: Path, redux_model: Path) -> None:
    required = [
        flux_model / "model_index.json",
        flux_model / "transformer/diffusion_pytorch_model.safetensors.index.json",
        flux_model / "text_encoder_2/model.safetensors.index.json",
        flux_model / "vae/diffusion_pytorch_model.safetensors",
        redux_model / "model_index.json",
        redux_model / "image_encoder/model.safetensors",
        redux_model / "image_embedder/diffusion_pytorch_model.safetensors",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Incomplete local model snapshot:\n" + "\n".join(missing))


def main() -> None:
    args = parse_args()
    for path in (args.source, args.depth):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.width % 16 or args.height % 16:
        raise ValueError("FLUX width and height must be divisible by 16")
    validate_local_models(args.flux_model, args.redux_model)

    import torch
    from diffusers import FluxControlPipeline, FluxPriorReduxPipeline

    dtype = torch.bfloat16
    device = torch.device("cuda")
    source = Image.open(args.source).convert("RGB").resize(
        (args.width, args.height), Image.Resampling.LANCZOS
    )
    depth = Image.open(args.depth).convert("RGB").resize(
        (args.width, args.height), Image.Resampling.BICUBIC
    )

    redux = FluxPriorReduxPipeline.from_pretrained(
        args.redux_model,
        torch_dtype=dtype,
        local_files_only=True,
    ).to(device)
    with torch.inference_mode():
        redux_output = redux(source)
        image_prompt_embeds = redux_output.prompt_embeds[:, 512:].detach().cpu()
    del redux_output, redux
    gc.collect()
    torch.cuda.empty_cache()

    pipe = FluxControlPipeline.from_pretrained(
        args.flux_model,
        torch_dtype=dtype,
        local_files_only=True,
    )
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()
    pipe.enable_sequential_cpu_offload(gpu_id=0)

    with torch.inference_mode():
        text_prompt_embeds, pooled_prompt_embeds, _ = pipe.encode_prompt(
            prompt=PROMPT,
            device=device,
            max_sequence_length=512,
        )
        prompt_embeds = torch.cat(
            [text_prompt_embeds, image_prompt_embeds.to(device) * args.redux_strength],
            dim=1,
        )
        del text_prompt_embeds, image_prompt_embeds
        generator = torch.Generator(device="cpu").manual_seed(args.seed)
        output = pipe(
            prompt=None,
            control_image=depth,
            width=args.width,
            height=args.height,
            num_inference_steps=args.steps,
            guidance_scale=args.guidance,
            generator=generator,
            prompt_embeds=prompt_embeds,
            pooled_prompt_embeds=pooled_prompt_embeds,
        ).images[0]

    atomic_png(output, args.output)
    manifest = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "provider": "server_local_flux_depth_plus_redux_offline",
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "depth": str(args.depth.resolve()),
        "depth_sha256": sha256(args.depth),
        "flux_model": str(args.flux_model.resolve()),
        "flux_revision": args.flux_model.name,
        "redux_model": str(args.redux_model.resolve()),
        "redux_revision": args.redux_model.name,
        "prompt": PROMPT,
        "settings": {
            "width": args.width,
            "height": args.height,
            "steps": args.steps,
            "guidance": args.guidance,
            "redux_strength": args.redux_strength,
            "seed": args.seed,
            "dtype": str(dtype),
            "offload": "sequential_cpu_offload",
        },
        "output": str(args.output.resolve()),
        "output_sha256": sha256(args.output),
        "network_policy": "offline_local_files_only",
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }
    atomic_json(args.output.with_suffix(".json"), manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
