#!/usr/bin/env python3
"""Generate identity-faithful front views with the local, offline ComfyUI stack."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
import types
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


PROJECT_ROOT = Path("/home/intern/Supervised 2D to 3D")
COMFY_ROOT = Path("/home/intern/wmy/ComfyUI")
COMFY_INPUT_ROOT = COMFY_ROOT / "input"
OUTPUT_ROOT = PROJECT_ROOT / "vlm/experiments/comfyui_output"
DEFAULT_SOURCE_ROOT = PROJECT_ROOT / "vlm/data/SN_6期动漫数据标注"
DEFAULT_BIREFNET = Path(
    "/home/intern/.cache/huggingface/hub/"
    "models--ZhengPeng7--BiRefNet/snapshots/"
    "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4"
)
MODEL_AUDIT = Path("/home/intern/local-ai-models/comfyui/model_audit.json")
IPADAPTER_PLUGIN = COMFY_ROOT / "custom_nodes/comfyui-ipadapter"
DEFAULT_STYLE_REFERENCE = (
    OUTPUT_ROOT
    / "front_view_local/char_001/char_001_sdxl_img2img_v3_00001_.png"
)

CHARACTER_PROMPTS = {
    "char_001": [
        "flowing long blonde hair with subtle pink-orange tips",
        "one very large black bow centered on top of her head",
        "vivid red eyes and the same facial identity",
        "white shirt with a small black neck ribbon and a round blue gemstone collar ornament",
        "dark waist and skirt area with exactly two continuous parallel gray horizontal bands",
        "loose white outer coat with visible black buttons",
    ],
}

SETTINGS: dict[str, Any] = {
    "model": "sdxl-base-1.0",
    "width": 768,
    "height": 1472,
    "seed": 20260722003,
    "steps": 30,
    "cfg": 7.0,
    "sampler_name": "dpmpp_2m",
    "scheduler": "karras",
    "denoise": 0.93,
    "ipadapter_preset": "PLUS (high strength)",
    "ipadapter_start": 0.0,
    "ipadapter_end": 0.80,
    "ipadapter_style_weight": 0.75,
    "ipadapter_composition_weight": 0.85,
    "controlnet": "controlnet-canny-sdxl-1.0-fp16.safetensors",
    "controlnet_strength": 0.50,
    "controlnet_start": 0.0,
    "controlnet_end": 1.0,
    "canny_low": 0.20,
    "canny_high": 0.60,
}

# The three profiles are deliberately ordered from identity preservation to
# stronger material conversion.  They are smoke-test profiles, not a batch
# sweep: char_001 must pass review before any wider run is allowed.
ROUND_PROFILES: dict[str, dict[str, Any]] = {
    "round1_fidelity": {
        "denoise": 0.30,
        "source_weight": 1.00,
        "composition_boost": 0.30,
        "source_end": 0.95,
        "style_weight": 0.00,
        "style_end": 0.00,
        "controlnet_strength": 0.90,
        "regional_style": False,
    },
    "round2_light_3d": {
        "denoise": 0.36,
        "source_weight": 1.00,
        "composition_boost": 0.30,
        "source_end": 0.95,
        "style_weight": 0.16,
        "style_end": 0.45,
        "controlnet_strength": 0.88,
        "regional_style": False,
    },
    "round3_regional_3d": {
        "denoise": 0.68,
        "base_denoise": 0.30,
        "source_weight": 1.05,
        "composition_boost": 0.35,
        "source_end": 1.00,
        "style_weight": 0.45,
        "style_end": 0.60,
        "controlnet_strength": 0.90,
        "regional_style": True,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local BiRefNet + IP-Adapter Plus + Canny ControlNet + SDXL."
    )
    parser.add_argument(
        "sample_dirs",
        nargs="*",
        type=Path,
        help="Sample directories containing <sample_id>.json and its source image.",
    )
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--birefnet-dir", type=Path, default=DEFAULT_BIREFNET)
    parser.add_argument("--preprocess-device", default="cuda:2")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--skip-preprocess", action="store_true")
    parser.add_argument(
        "--style-reference",
        type=Path,
        default=None,
        help="Optional character-free material reference; a neutral local board is used by default.",
    )
    parser.add_argument(
        "--round-profile",
        choices=sorted(ROUND_PROFILES),
        default="round1_fidelity",
        help="Identity-first three-round smoke profile.",
    )
    parser.add_argument(
        "--candidate-only",
        action="store_true",
        help="Write a tagged candidate without replacing the accepted fixed-path output.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def atomic_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    image.save(temp, format="PNG", optimize=True)
    os.replace(temp, path)


def api_json(server: str, path: str, payload: Any | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{server.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as response:
        return json.load(response)


def validate_local_stack(server: str) -> None:
    object_info = api_json(server, "/object_info")
    required_nodes = {
        "DiffusersLoader",
        "IPAdapterUnifiedLoader",
        "IPAdapterAdvanced",
        "IPAdapterPreciseComposition",
        "IPAdapterPreciseStyleTransfer",
        "ControlNetLoader",
        "ControlNetApplyAdvanced",
        "Canny",
        "LoadImageMask",
        "SetLatentNoiseMask",
    }
    missing = sorted(required_nodes.difference(object_info))
    if missing:
        raise RuntimeError(f"ComfyUI is missing required nodes: {missing}")

    controlnets = object_info["ControlNetLoader"]["input"]["required"]["control_net_name"][0]
    if SETTINGS["controlnet"] not in controlnets:
        raise RuntimeError(f"ControlNet is not registered: {SETTINGS['controlnet']}")

    presets = object_info["IPAdapterUnifiedLoader"]["input"]["required"]["preset"][0]
    if SETTINGS["ipadapter_preset"] not in presets:
        raise RuntimeError(f"IP-Adapter preset is unavailable: {SETTINGS['ipadapter_preset']}")


def load_local_birefnet(model_dir: Path, device: str):
    """Import audited local model files directly; never invoke trust_remote_code."""
    import torch
    from safetensors.torch import load_file

    required = ["BiRefNet_config.py", "birefnet.py", "model.safetensors"]
    missing = [name for name in required if not (model_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Incomplete local BiRefNet snapshot: {missing}")

    package_name = "_audited_local_birefnet"
    package = types.ModuleType(package_name)
    package.__path__ = [str(model_dir)]
    sys.modules[package_name] = package

    config_spec = importlib.util.spec_from_file_location(
        f"{package_name}.BiRefNet_config", model_dir / "BiRefNet_config.py"
    )
    if config_spec is None or config_spec.loader is None:
        raise ImportError("Cannot load local BiRefNet config")
    config_module = importlib.util.module_from_spec(config_spec)
    sys.modules[config_spec.name] = config_module
    config_spec.loader.exec_module(config_module)

    model_spec = importlib.util.spec_from_file_location(
        f"{package_name}.birefnet", model_dir / "birefnet.py"
    )
    if model_spec is None or model_spec.loader is None:
        raise ImportError("Cannot load local BiRefNet architecture")
    model_module = importlib.util.module_from_spec(model_spec)
    sys.modules[model_spec.name] = model_module
    model_spec.loader.exec_module(model_module)

    config = config_module.BiRefNetConfig(bb_pretrained=False)
    model = model_module.BiRefNet(config=config)
    state = load_file(str(model_dir / "model.safetensors"), device="cpu")
    model.load_state_dict(state, strict=True)
    return model.to(torch.device(device)).eval()


def red_frame_crop_box(image: Image.Image, search_width: int = 8) -> tuple[int, int, int, int]:
    pixels = np.asarray(image.convert("RGB"))
    red = (
        (pixels[:, :, 0] >= 130)
        & (pixels[:, :, 0] >= pixels[:, :, 1] * 1.6)
        & (pixels[:, :, 0] >= pixels[:, :, 2] * 1.6)
    )
    height, width = red.shape

    def covered_rows(indices) -> list[int]:
        return [index for index in indices if float(red[index, :].mean()) >= 0.55]

    def covered_cols(indices) -> list[int]:
        return [index for index in indices if float(red[:, index].mean()) >= 0.55]

    top_lines = covered_rows(range(min(search_width, height)))
    bottom_lines = covered_rows(range(max(0, height - search_width), height))
    left_lines = covered_cols(range(min(search_width, width)))
    right_lines = covered_cols(range(max(0, width - search_width), width))

    left = max(left_lines) + 1 if left_lines else 0
    top = max(top_lines) + 1 if top_lines else 0
    right = min(right_lines) if right_lines else width
    bottom = min(bottom_lines) if bottom_lines else height
    if right - left < width * 0.8 or bottom - top < height * 0.8:
        return (0, 0, width, height)
    return (left, top, right, bottom)


def preprocess_reference(
    source: Path,
    cleaned_path: Path,
    square_path: Path,
    mask_path: Path,
    model,
    device: str,
) -> dict[str, Any]:
    import torch
    import torch.nn.functional as torch_functional

    original = Image.open(source).convert("RGB")
    crop_box = red_frame_crop_box(original)
    cropped = original.crop(crop_box)
    source_array = np.asarray(cropped, dtype=np.float32) / 255.0
    resized = cropped.resize((1024, 1024), Image.Resampling.BILINEAR)
    tensor = torch.from_numpy(np.asarray(resized, dtype=np.float32) / 255.0)
    tensor = tensor.permute(2, 0, 1).unsqueeze(0)
    mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
    tensor = ((tensor - mean) / std).to(torch.device(device))

    with torch.inference_mode():
        predictions = model(tensor)
        logits = predictions[-1]
        mask = torch.sigmoid(logits)
        mask = torch_functional.interpolate(
            mask,
            size=(cropped.height, cropped.width),
            mode="bilinear",
            align_corners=False,
        )[0, 0]
    mask_array = mask.float().cpu().clamp(0, 1).numpy()
    del tensor, predictions, logits, mask

    # Suppress faint background remnants while retaining anti-aliased edges.
    alpha = np.clip((mask_array - 0.08) / 0.84, 0.0, 1.0)[..., None]
    composite = source_array * alpha + (1.0 - alpha)
    cleaned = Image.fromarray(np.uint8(np.round(composite * 255.0)), mode="RGB")
    mask_image = Image.fromarray(np.uint8(np.round(alpha[:, :, 0] * 255.0)), mode="L")

    square = Image.new("RGB", (1024, 1024), "white")
    max_side = 960
    scale = min(max_side / cleaned.width, max_side / cleaned.height)
    fitted = cleaned.resize(
        (max(1, round(cleaned.width * scale)), max(1, round(cleaned.height * scale))),
        Image.Resampling.LANCZOS,
    )
    square.paste(fitted, ((1024 - fitted.width) // 2, (1024 - fitted.height) // 2))

    atomic_png(cleaned, cleaned_path)
    atomic_png(square, square_path)
    atomic_png(mask_image, mask_path)
    return {
        "model_dir": str(DEFAULT_BIREFNET if model is not None else ""),
        "device": device,
        "input_size": [1024, 1024],
        "source_size": list(original.size),
        "crop_box": list(crop_box),
        "cropped_size": list(cropped.size),
        "cleaned_path": str(cleaned_path),
        "cleaned_sha256": sha256(cleaned_path),
        "ipadapter_square_path": str(square_path),
        "ipadapter_square_sha256": sha256(square_path),
        "mask_path": str(mask_path),
        "mask_sha256": sha256(mask_path),
    }


def prepare_style_reference(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(f"Missing local 3D style reference: {source}")
    image = Image.open(source).convert("RGB")
    square = Image.new("RGB", (1024, 1024), "white")
    scale = max(1024 / image.width, 1024 / image.height)
    fitted = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = (fitted.width - 1024) // 2
    top = (fitted.height - 1024) // 2
    square.paste(fitted.crop((left, top, left + 1024, top + 1024)))
    atomic_png(square, destination)
    return {
        "source": str(source.resolve()),
        "source_sha256": sha256(source),
        "prepared_path": str(destination),
        "prepared_sha256": sha256(destination),
        "provenance": "local_comfyui_sdxl_output",
    }


def prepare_neutral_style_reference(destination: Path) -> dict[str, Any]:
    """Create a character-free 3D material board without model downloads."""
    size = 1024
    canvas = Image.new("RGB", (size, size), "white")
    pixels = np.asarray(canvas, dtype=np.float32).copy()
    yy, xx = np.mgrid[:size, :size]
    spheres = [
        (230, 330, 175, np.array([244, 208, 126], dtype=np.float32)),
        (512, 330, 175, np.array([245, 245, 242], dtype=np.float32)),
        (794, 330, 175, np.array([45, 45, 52], dtype=np.float32)),
        (370, 720, 150, np.array([208, 171, 177], dtype=np.float32)),
        (654, 720, 150, np.array([83, 90, 99], dtype=np.float32)),
    ]
    for cx, cy, radius, base in spheres:
        distance = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        inside = distance <= radius
        nx = (xx - cx) / radius
        ny = (yy - cy) / radius
        light = np.clip(1.05 - 0.42 * nx - 0.48 * ny, 0.50, 1.35)
        rim = np.clip((distance / radius) ** 2, 0.0, 1.0)
        shade = light * (1.0 - 0.28 * rim)
        for channel in range(3):
            values = np.clip(base[channel] * shade + 12.0, 0, 255)
            pixels[:, :, channel][inside] = values[inside]
    board = Image.fromarray(np.uint8(np.round(pixels)), mode="RGB")
    draw = ImageDraw.Draw(board)
    for cx, cy, radius, _ in spheres:
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            outline=(215, 215, 215),
            width=3,
        )
    board = board.filter(ImageFilter.GaussianBlur(radius=0.8))
    atomic_png(board, destination)
    return {
        "source": "generated_character_free_material_board",
        "prepared_path": str(destination),
        "prepared_sha256": sha256(destination),
        "provenance": "deterministic_local_pillow",
    }


def prepare_style_masks(
    foreground_mask_path: Path,
    full_mask_path: Path,
    regional_mask_path: Path,
) -> dict[str, Any]:
    foreground = Image.open(foreground_mask_path).convert("L").resize(
        (SETTINGS["width"], SETTINGS["height"]),
        Image.Resampling.LANCZOS,
    )
    foreground = foreground.point(lambda value: 255 if value >= 96 else 0)
    atomic_png(foreground, full_mask_path)

    regional = foreground.copy()
    draw = ImageDraw.Draw(regional)
    width, height = regional.size
    # Protect identity-bearing face/eye geometry, head bow, collar ornament,
    # shirt placket, and exact waist bands from material-reference leakage.
    draw.ellipse(
        (int(width * 0.25), int(height * 0.15), int(width * 0.75), int(height * 0.42)),
        fill=0,
    )
    draw.rectangle(
        (int(width * 0.25), int(height * 0.03), int(width * 0.75), int(height * 0.20)),
        fill=0,
    )
    draw.rectangle(
        (int(width * 0.35), int(height * 0.40), int(width * 0.65), int(height * 0.55)),
        fill=0,
    )
    draw.rectangle(
        (int(width * 0.40), int(height * 0.52), int(width * 0.60), int(height * 0.74)),
        fill=0,
    )
    draw.rectangle(
        (int(width * 0.24), int(height * 0.73), int(width * 0.76), int(height * 0.82)),
        fill=0,
    )
    # Repaint the visible lower diagonal watermark band.  This is deliberately
    # below the face/collar and is softly feathered before latent masking.
    draw.line(
        (int(width * -0.05), int(height * 1.02), int(width * 0.72), int(height * 0.66)),
        fill=255,
        width=max(24, int(width * 0.08)),
    )
    regional = regional.filter(ImageFilter.GaussianBlur(radius=12))
    atomic_png(regional, regional_mask_path)
    return {
        "full_mask_path": str(full_mask_path),
        "full_mask_sha256": sha256(full_mask_path),
        "regional_mask_path": str(regional_mask_path),
        "regional_mask_sha256": sha256(regional_mask_path),
    }


def resolve_sample(sample_dir: Path) -> tuple[str, Path, Path, dict[str, Any]]:
    sample_dir = sample_dir.resolve()
    json_candidates = sorted(sample_dir.glob("*.json"))
    if len(json_candidates) != 1:
        raise ValueError(f"Expected exactly one annotation JSON in {sample_dir}")
    annotation_path = json_candidates[0]
    with annotation_path.open(encoding="utf-8") as handle:
        annotation = json.load(handle)
    sample_id = str(annotation.get("sample_id", "")).strip()
    if not sample_id or sample_id != sample_dir.name:
        raise ValueError(f"sample_id does not match directory name: {sample_dir}")
    source_name = str(annotation.get("source_image", "")).strip()
    source_path = sample_dir / source_name
    if not source_name or not source_path.is_file():
        raise FileNotFoundError(f"Missing source image declared by annotation: {source_path}")
    elements = annotation.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError(f"No annotation elements in {annotation_path}")
    return sample_id, source_path, annotation_path, annotation


def build_prompts(
    sample_id: str,
    annotation: dict[str, Any],
    profile_name: str,
) -> tuple[str, str]:
    traits = CHARACTER_PROMPTS.get(sample_id)
    if traits is None:
        traits = [
            f"preserve this annotated trait exactly from the reference: {element['name']}"
            for element in annotation["elements"]
        ]
    positive = ", ".join(
        [
            "faithful three-dimensional reconstruction of the exact reference anime character",
            "toon-shaded 3D render with subtle sculpted volume, garment thickness, and soft studio lighting",
            "retain the original anime facial geometry, eye size, expression, silhouette, pose, and camera framing",
            "preserve every visible hairstyle section, color boundary, costume seam, accessory, and proportion exactly",
            *traits,
            "single character, strict front view, identical body coverage and arm placement",
            "centered on pure white, no border or text, precise original paint separation",
            f"identity-first smoke profile {profile_name}",
        ]
    )
    negative = ", ".join(
        [
            "different character, identity mismatch, facial drift, wrong eye color, hairstyle redesign",
            "costume redesign, missing accessory, wrong colors, simplified clothing, asymmetrical costume",
            "chibi proportions, round doll face, heavy blush, oversized glossy eyes, tiny nose, open doll lips",
            "turquoise collar ornament, gold piping, invented belt, invented jewelry, extra buttons",
            "side view, back view, three views, turntable, extra character, duplicate body",
            "added prop, base, stand, text, letters, numbers, watermark, logo, border, red frame",
            "black background, dark background, scenery, photorealistic human",
            "blurry, low detail, deformed face, bad anatomy, extra fingers, missing fingers",
        ]
    )
    return positive, negative


def comfy_relative(path: Path) -> str:
    return path.resolve().relative_to(COMFY_INPUT_ROOT.resolve()).as_posix()


def build_workflow(
    cleaned_input: str,
    ipadapter_input: str,
    style_input: str,
    style_mask_input: str,
    output_prefix: str,
    positive: str,
    negative: str,
    profile_name: str,
) -> dict[str, Any]:
    profile = ROUND_PROFILES[profile_name]
    workflow: dict[str, Any] = {
        "1": {"class_type": "DiffusersLoader", "inputs": {"model_path": SETTINGS["model"]}},
        "2": {"class_type": "LoadImage", "inputs": {"image": cleaned_input}},
        "3": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["2", 0],
                "upscale_method": "lanczos",
                "width": SETTINGS["width"],
                "height": SETTINGS["height"],
                "crop": "disabled",
            },
        },
        "4": {"class_type": "VAEEncode", "inputs": {"pixels": ["3", 0], "vae": ["1", 2]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["1", 1]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
        "7": {"class_type": "LoadImage", "inputs": {"image": ipadapter_input}},
        "16": {"class_type": "LoadImage", "inputs": {"image": style_input}},
        "18": {
            "class_type": "LoadImageMask",
            "inputs": {"image": style_mask_input, "channel": "red"},
        },
        "8": {
            "class_type": "IPAdapterUnifiedLoader",
            "inputs": {"model": ["1", 0], "preset": SETTINGS["ipadapter_preset"]},
        },
        "9": {
            "class_type": "IPAdapterPreciseComposition",
            "inputs": {
                "model": ["8", 0],
                "ipadapter": ["8", 1],
                "image": ["7", 0],
                "weight": profile["source_weight"],
                "composition_boost": profile["composition_boost"],
                "combine_embeds": "average",
                "start_at": 0.0,
                "end_at": profile["source_end"],
                "embeds_scaling": "K+V w/ C penalty",
            },
        },
        "10": {
            "class_type": "Canny",
            "inputs": {
                "image": ["3", 0],
                "low_threshold": SETTINGS["canny_low"],
                "high_threshold": SETTINGS["canny_high"],
            },
        },
        "11": {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": SETTINGS["controlnet"]},
        },
        "12": {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "positive": ["5", 0],
                "negative": ["6", 0],
                "control_net": ["11", 0],
                "image": ["10", 0],
                "strength": SETTINGS["controlnet_strength"],
                "start_percent": SETTINGS["controlnet_start"],
                "end_percent": SETTINGS["controlnet_end"],
            },
        },
        "13": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["9", 0],
                "seed": SETTINGS["seed"],
                "steps": SETTINGS["steps"],
                "cfg": SETTINGS["cfg"],
                "sampler_name": SETTINGS["sampler_name"],
                "scheduler": SETTINGS["scheduler"],
                # Do not reapply the watermarked Canny map during repaint.
                # Pass one has already locked the global structure.
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["4", 0],
                "denoise": profile["denoise"],
            },
        },
        "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["1", 2]}},
        "15": {"class_type": "SaveImage", "inputs": {"filename_prefix": output_prefix, "images": ["14", 0]}},
    }
    workflow["12"]["inputs"]["strength"] = profile["controlnet_strength"]
    if profile["style_weight"] > 0:
        workflow["17"] = {
            "class_type": "IPAdapterPreciseStyleTransfer",
            "inputs": {
                "model": ["9", 0],
                "ipadapter": ["8", 1],
                "image": ["16", 0],
                "weight": profile["style_weight"],
                "style_boost": 2.0,
                "combine_embeds": "average",
                "start_at": 0.0,
                "end_at": profile["style_end"],
                "embeds_scaling": "K+V w/ C penalty",
                "attn_mask": ["18", 0],
            },
        }
        workflow["13"]["inputs"]["model"] = ["17", 0]
    if profile["regional_style"]:
        # Pass one establishes the identity-faithful base globally.  Pass two
        # adds stronger 3D material only where the regional mask permits it.
        workflow["13"]["inputs"]["model"] = ["9", 0]
        workflow["13"]["inputs"]["denoise"] = profile["base_denoise"]
        workflow["19"] = {
            "class_type": "SetLatentNoiseMask",
            "inputs": {"samples": ["13", 0], "mask": ["18", 0]},
        }
        workflow["20"] = {
            "class_type": "KSampler",
            "inputs": {
                "model": ["17", 0],
                "seed": SETTINGS["seed"] + 17,
                "steps": SETTINGS["steps"],
                "cfg": 6.5,
                "sampler_name": SETTINGS["sampler_name"],
                "scheduler": SETTINGS["scheduler"],
                "positive": ["12", 0],
                "negative": ["12", 1],
                "latent_image": ["19", 0],
                "denoise": profile["denoise"],
            },
        }
        workflow["14"]["inputs"]["samples"] = ["20", 0]
    return workflow


def wait_for_output(server: str, prompt_id: str, timeout: int) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = api_json(server, f"/history/{prompt_id}").get(prompt_id)
        if history:
            status = history.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False))
            if status.get("completed"):
                images = history.get("outputs", {}).get("15", {}).get("images", [])
                if len(images) != 1:
                    raise RuntimeError(f"Expected one saved image, got {len(images)}")
                image = images[0]
                return (OUTPUT_ROOT / image.get("subfolder", "") / image["filename"]).resolve()
        time.sleep(1)
    raise TimeoutError(f"ComfyUI workflow {prompt_id} exceeded {timeout} seconds")


def plugin_revision() -> str:
    head = IPADAPTER_PLUGIN / ".git/HEAD"
    if not head.is_file():
        return "unknown"
    value = head.read_text(encoding="utf-8").strip()
    if value.startswith("ref: "):
        ref = IPADAPTER_PLUGIN / ".git" / value.removeprefix("ref: ")
        if ref.is_file():
            return ref.read_text(encoding="utf-8").strip()
    return value


def generate_one(
    sample_dir: Path,
    server: str,
    timeout: int,
    preprocess_record: dict[str, Any],
    style_record: dict[str, Any],
    style_mask_record: dict[str, Any],
    profile_name: str,
    candidate_only: bool,
) -> Path:
    sample_id, source_path, annotation_path, annotation = resolve_sample(sample_dir)
    sample_output_dir = OUTPUT_ROOT / "front_view_local" / sample_id
    if candidate_only:
        candidate_dir = sample_output_dir / "candidates"
        final_output = candidate_dir / f"{sample_id}_{profile_name}.png"
        manifest_path = candidate_dir / f"{sample_id}_{profile_name}_manifest.json"
    else:
        final_output = sample_output_dir / f"{sample_id}_front_view.png"
        manifest_path = sample_output_dir / "run_manifest.json"
    error_path = sample_output_dir / "last_error.json"
    input_dir = COMFY_INPUT_ROOT / "local_pipeline" / sample_id
    cleaned_path = input_dir / "cleaned_white.png"
    square_path = input_dir / "ipadapter_reference.png"
    style_path = input_dir / "style_reference.png"
    style_mask_path = input_dir / (
        "style_mask_regional.png"
        if ROUND_PROFILES[profile_name]["regional_style"]
        else "style_mask_foreground.png"
    )

    positive, negative = build_prompts(sample_id, annotation, profile_name)
    work_token = uuid.uuid4().hex
    output_prefix = f"front_view_local/{sample_id}/_working_{work_token}"
    workflow = build_workflow(
        comfy_relative(cleaned_path),
        comfy_relative(square_path),
        comfy_relative(style_path),
        comfy_relative(style_mask_path),
        output_prefix,
        positive,
        negative,
        profile_name,
    )
    submitted = api_json(
        server,
        "/prompt",
        {"prompt": workflow, "client_id": f"local-pipeline-{sample_id}-{work_token}"},
    )
    if "error" in submitted:
        raise RuntimeError(json.dumps(submitted, ensure_ascii=False))
    prompt_id = submitted["prompt_id"]
    temporary_output = wait_for_output(server, prompt_id, timeout)
    if not temporary_output.is_file():
        raise FileNotFoundError(f"ComfyUI reported a missing output: {temporary_output}")

    final_output.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporary_output, final_output)
    manifest = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "provider": "local_comfyui_offline",
        "server": server,
        "device": "cuda:0 NVIDIA A100-SXM4-80GB",
        "sample_id": sample_id,
        "source_image": str(source_path),
        "source_image_sha256": sha256(source_path),
        "source_json": str(annotation_path),
        "source_json_sha256": sha256(annotation_path),
        "annotation_elements": annotation["elements"],
        "preprocess": preprocess_record,
        "style_reference": style_record,
        "style_masks": style_mask_record,
        "round_profile": profile_name,
        "positive_prompt": positive,
        "negative_prompt": negative,
        "settings": {**SETTINGS, **ROUND_PROFILES[profile_name]},
        "model_audit": str(MODEL_AUDIT),
        "model_audit_sha256": sha256(MODEL_AUDIT),
        "ipadapter_plugin_revision": plugin_revision(),
        "network_policy": {
            "runtime": "offline",
            "hf_hub_offline": os.environ.get("HF_HUB_OFFLINE"),
            "transformers_offline": os.environ.get("TRANSFORMERS_OFFLINE"),
            "telemetry_disabled": os.environ.get("HF_HUB_DISABLE_TELEMETRY"),
        },
        "candidate_only": candidate_only,
        "overwrite_output": not candidate_only,
        "atomic_replace": True,
        "comfyui_prompt_id": prompt_id,
        "output": {"path": str(final_output), "sha256": sha256(final_output)},
    }
    atomic_json(manifest_path, manifest)
    if error_path.exists():
        error_path.unlink()
    print(final_output)
    print(manifest_path)
    return final_output


def main() -> None:
    args = parse_args()
    sample_dirs = args.sample_dirs or [DEFAULT_SOURCE_ROOT / "char_001"]
    sample_dirs = [path.resolve() for path in sample_dirs]

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    for proxy_name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(proxy_name, None)

    validate_local_stack(args.server)
    model = None if args.skip_preprocess else load_local_birefnet(args.birefnet_dir.resolve(), args.preprocess_device)
    failures: list[str] = []
    try:
        for sample_dir in sample_dirs:
            sample_id = sample_dir.name
            output_dir = OUTPUT_ROOT / "front_view_local" / sample_id
            error_path = output_dir / "last_error.json"
            try:
                _, source_path, _, _ = resolve_sample(sample_dir)
                input_dir = COMFY_INPUT_ROOT / "local_pipeline" / sample_id
                cleaned_path = input_dir / "cleaned_white.png"
                square_path = input_dir / "ipadapter_reference.png"
                mask_path = input_dir / "foreground_mask.png"
                style_path = input_dir / "style_reference.png"
                full_style_mask_path = input_dir / "style_mask_foreground.png"
                regional_style_mask_path = input_dir / "style_mask_regional.png"
                if args.skip_preprocess:
                    for required in (cleaned_path, square_path, mask_path):
                        if not required.is_file():
                            raise FileNotFoundError(f"Missing cached preprocessing output: {required}")
                    preprocess_record = {
                        "reused": True,
                        "cleaned_path": str(cleaned_path),
                        "cleaned_sha256": sha256(cleaned_path),
                        "ipadapter_square_path": str(square_path),
                        "ipadapter_square_sha256": sha256(square_path),
                        "mask_path": str(mask_path),
                        "mask_sha256": sha256(mask_path),
                    }
                else:
                    preprocess_record = preprocess_reference(
                        source_path,
                        cleaned_path,
                        square_path,
                        mask_path,
                        model,
                        args.preprocess_device,
                    )
                    preprocess_record["model_dir"] = str(args.birefnet_dir.resolve())
                    preprocess_record["model_sha256"] = sha256(args.birefnet_dir / "model.safetensors")
                style_mask_record = prepare_style_masks(
                    mask_path,
                    full_style_mask_path,
                    regional_style_mask_path,
                )
                if args.style_reference is None:
                    style_record = prepare_neutral_style_reference(style_path)
                else:
                    style_record = prepare_style_reference(args.style_reference.resolve(), style_path)
                generate_one(
                    sample_dir,
                    args.server,
                    args.timeout,
                    preprocess_record,
                    style_record,
                    style_mask_record,
                    args.round_profile,
                    args.candidate_only,
                )
            except Exception as exc:
                failures.append(sample_id)
                atomic_json(
                    error_path,
                    {
                        "failed_at": datetime.now(timezone.utc).astimezone().isoformat(),
                        "sample_id": sample_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "previous_valid_output_preserved": (
                            output_dir / f"{sample_id}_front_view.png"
                        ).is_file(),
                    },
                )
                print(f"ERROR {sample_id}: {exc}", file=sys.stderr)
                break
    finally:
        if model is not None:
            del model
            try:
                import torch

                torch.cuda.empty_cache()
            except Exception:
                pass
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
