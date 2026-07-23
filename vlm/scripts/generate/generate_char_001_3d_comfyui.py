#!/usr/bin/env python3
"""Generate a 3D-style front view for char_001 using ComfyUI.

Two-pass pipeline:
  Pass 1 — Identity anchor: IP-Adapter composition + strong Canny ControlNet
  Pass 2 — 3D material: light IP-Adapter style transfer with regional masking
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter
import numpy as np

PROJECT_ROOT = Path("/home/intern/Supervised 2D to 3D")
COMFY_INPUT = Path("/home/intern/wmy/ComfyUI/input")
COMFY_OUTPUT = PROJECT_ROOT / "vlm/experiments/comfyui_output"
SERVER = "http://127.0.0.1:8188"

SOURCE_IMAGE = Path("/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/cleaned_white.png")
STYLE_REFS = [
    PROJECT_ROOT / "vlm/data/2028670/2028670_pvc_figurine.png",
    PROJECT_ROOT / "vlm/data/2028688/2028688_figurine.png",
    PROJECT_ROOT / "vlm/data/2149386/2149386_figurine.png",
]

# ── settings ─────────────────────────────────────────────────────────
MODEL = "sdxl-base-1.0"
W, H = 768, 1472
PRESET = "PLUS (high strength)"
CN_MODEL = "controlnet-canny-sdxl-1.0-fp16.safetensors"
SEED = 20260722009

# Pass 1 — identity fidelity with moderate structural freedom
P1 = {
    "denoise": 0.62,
    "composition_weight": 0.85,
    "composition_end": 0.85,
    "canny_low": 0.15,
    "canny_high": 0.50,
    "cn_strength": 0.60,
}

# Pass 2 — 3D material infusion
P2 = {
    "denoise": 0.58,
    "style_weight": 0.30,
    "style_boost": 3.0,
    "style_end": 0.55,
    "canny_low": 0.12,
    "canny_high": 0.48,
    "cn_strength": 0.55,
}

# ── prompts ──────────────────────────────────────────────────────────
CHARACTER_TRAITS = [
    "flowing long blonde hair with subtle pink-orange tips, "
    "one very large black bow centered on top of head",
    "vivid red eyes, exact same facial identity and expression",
    "white shirt with small black neck ribbon and round blue gemstone collar ornament",
    "dark waist and skirt, exactly two continuous parallel gray horizontal bands",
    "loose white outer coat with visible black buttons",
]

POSITIVE_P1 = ", ".join(
    [
        "exact replica of the reference anime character, preserve every detail identically",
        *CHARACTER_TRAITS,
        "single character, strict front view, identical pose and framing",
        "pure white seamless background #FFFFFF, clean white studio backdrop, "
        "no border, no frame, no vignette, no gradient background",
        "studio product photo lighting, soft even illumination",
    ]
)

POSITIVE_P2 = ", ".join(
    [
        "professional 3D PVC anime figurine, matte painted resin sculpture, "
        "sculpted volume with realistic material depth and shading, "
        "soft studio key light with subtle rim light, glossy hair finish, matte clothing texture",
        *CHARACTER_TRAITS,
        "single character, strict front view, identical pose and framing",
        "pure white seamless background #FFFFFF, clean white studio backdrop, "
        "no border, no frame, no vignette",
    ]
)

NEGATIVE = ", ".join(
    [
        "2D, flat, drawing, illustration, anime cell, cartoon, cel-shaded, "
        "line art, sketch, flat color, vector art, watercolor",
        "different character, identity mismatch, wrong hair, wrong eyes, "
        "costume redesign, missing accessory, wrong colors, invented detail",
        "chibi, doll face, round face, heavy blush, oversized eyes, "
        "side view, back view, turntable, extra character, duplicate, "
        "prop, base, stand, text, letters, numbers, watermark, logo, border, red frame, "
        "dark background, black background, gray background, scenery",
        "blurry, low detail, deformed, bad anatomy, messy, noisy",
    ]
)


# ── helpers ──────────────────────────────────────────────────────────

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def api_json(path: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{SERVER}{path}", data=data,
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=30) as resp:
        return json.load(resp)


def copy_to_input(src: Path, name: str) -> str:
    dest_dir = COMFY_INPUT / "char_001_3d_pipeline"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    shutil.copy2(src, dest)
    return dest.relative_to(COMFY_INPUT).as_posix()


def build_regional_mask(source_path: Path, output_path: Path) -> Path:
    """Build a mask that protects identity zones from material infusion."""
    src = Image.open(source_path).convert("L") if source_path.suffix == ".png" else None
    mask = Image.new("L", (W, H), 255)  # default: allow material everywhere
    draw = ImageDraw.Draw(mask)
    # Protect face, eyes, hair bow, collar, waist bands, coat details
    draw.ellipse(
        (int(W * 0.25), int(H * 0.10), int(W * 0.75), int(H * 0.38)),
        fill=0,
    )
    draw.rectangle(
        (int(W * 0.25), int(H * 0.02), int(W * 0.75), int(H * 0.18)),
        fill=0,
    )
    draw.rectangle(
        (int(W * 0.35), int(H * 0.36), int(W * 0.65), int(H * 0.50)),
        fill=0,
    )
    draw.rectangle(
        (int(W * 0.35), int(H * 0.48), int(W * 0.65), int(H * 0.68)),
        fill=0,
    )
    draw.rectangle(
        (int(W * 0.20), int(H * 0.65), int(W * 0.80), int(H * 0.76)),
        fill=0,
    )
    # Soften mask edges
    mask = mask.filter(ImageFilter.GaussianBlur(radius=10))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(output_path, format="PNG", optimize=True)
    return output_path


def wait_for(prompt_id: str, timeout: int = 600) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = api_json(f"/history/{prompt_id}").get(prompt_id)
        if history:
            status = history.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False, indent=2))
            if status.get("completed"):
                outputs = history.get("outputs", {})
                # SaveImage is always node 32 (last node)
                for node_id in sorted(outputs.keys(), key=int, reverse=True):
                    imgs = outputs[node_id].get("images", [])
                    if imgs:
                        img = imgs[0]
                        return (COMFY_OUTPUT / img.get("subfolder", "") / img["filename"]).resolve()
        time.sleep(2)
    raise TimeoutError(f"Workflow {prompt_id} exceeded {timeout}s")


def submit_and_wait(workflow: dict) -> Path:
    submitted = api_json("/prompt", {
        "prompt": workflow,
        "client_id": f"char001-{uuid.uuid4().hex[:8]}",
    })
    prompt_id = submitted["prompt_id"]
    print(f"  prompt_id={prompt_id}")
    path = wait_for(prompt_id)
    print(f"  output: {path}")
    return path


# ── workflow builders ────────────────────────────────────────────────

def build_pass1_identity(source_rel: str, output_prefix: str) -> dict:
    """Pass 1: Anchor identity with IP-Adapter composition + strong Canny."""
    w: dict[str, Any] = {}

    # model
    w["1"] = {"class_type": "DiffusersLoader", "inputs": {"model_path": MODEL}}

    # source
    w["2"] = {"class_type": "LoadImage", "inputs": {"image": source_rel}}
    w["3"] = {
        "class_type": "ImageScale",
        "inputs": {"image": ["2", 0], "upscale_method": "lanczos",
                    "width": W, "height": H, "crop": "disabled"},
    }
    w["4"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["3", 0], "vae": ["1", 2]}}

    # prompts
    w["5"] = {"class_type": "CLIPTextEncode", "inputs": {"text": POSITIVE_P1, "clip": ["1", 1]}}
    w["6"] = {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["1", 1]}}

    # IP-Adapter — composition only (identity anchor)
    w["7"] = {"class_type": "IPAdapterUnifiedLoader",
              "inputs": {"model": ["1", 0], "preset": PRESET}}
    w["8"] = {"class_type": "LoadImage", "inputs": {"image": source_rel}}
    w["9"] = {
        "class_type": "IPAdapterPreciseComposition",
        "inputs": {
            "model": ["7", 0], "ipadapter": ["7", 1],
            "image": ["8", 0],
            "weight": P1["composition_weight"],
            "composition_boost": 0.25,
            "combine_embeds": "average",
            "start_at": 0.0, "end_at": P1["composition_end"],
            "embeds_scaling": "K+V w/ C penalty",
        },
    }

    # Canny + ControlNet
    w["10"] = {"class_type": "Canny",
               "inputs": {"image": ["3", 0], "low_threshold": P1["canny_low"],
                           "high_threshold": P1["canny_high"]}}
    w["11"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": CN_MODEL}}
    w["12"] = {
        "class_type": "ControlNetApplyAdvanced",
        "inputs": {
            "positive": ["5", 0], "negative": ["6", 0],
            "control_net": ["11", 0], "image": ["10", 0],
            "strength": P1["cn_strength"],
            "start_percent": 0.0, "end_percent": 1.0,
        },
    }

    # KSampler
    w["13"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["9", 0],
            "seed": SEED, "steps": 30, "cfg": 7.0,
            "sampler_name": "dpmpp_2m", "scheduler": "karras",
            "positive": ["12", 0], "negative": ["12", 1],
            "latent_image": ["4", 0],
            "denoise": P1["denoise"],
        },
    }

    # decode + save
    w["14"] = {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["1", 2]}}
    w["15"] = {"class_type": "SaveImage",
               "inputs": {"filename_prefix": output_prefix, "images": ["14", 0]}}

    return w


def build_pass2_material(
    source_rel: str,
    style_rel: str,
    regional_mask_rel: str,
    pass1_latent_image: list,  # ["<pass1_img_node>", 0]
    output_prefix: str,
) -> dict:
    """Pass 2: Light 3D material infusion with regional mask protection."""
    w: dict[str, Any] = {}

    # model
    w["1"] = {"class_type": "DiffusersLoader", "inputs": {"model_path": MODEL}}

    # source (for Canny reference from clean upscaled source)
    w["2a"] = {"class_type": "LoadImage", "inputs": {"image": source_rel}}
    w["2b"] = {
        "class_type": "ImageScale",
        "inputs": {"image": ["2a", 0], "upscale_method": "lanczos",
                    "width": W, "height": H, "crop": "disabled"},
    }

    # load pass-1 output and encode for img2img
    w["3a"] = {"class_type": "LoadImage", "inputs": {"image": pass1_latent_image[0]}}
    w["3b"] = {
        "class_type": "ImageScale",
        "inputs": {"image": ["3a", 0], "upscale_method": "lanczos",
                    "width": W, "height": H, "crop": "disabled"},
    }
    w["3c"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["3b", 0], "vae": ["1", 2]}}

    # prompts — 3D focused for pass 2
    w["4"] = {"class_type": "CLIPTextEncode", "inputs": {"text": POSITIVE_P2, "clip": ["1", 1]}}
    w["5"] = {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["1", 1]}}

    # IP-Adapter setup
    w["6"] = {"class_type": "IPAdapterUnifiedLoader",
              "inputs": {"model": ["1", 0], "preset": PRESET}}

    # Identity anchor (weak composition from source)
    w["7"] = {"class_type": "LoadImage", "inputs": {"image": source_rel}}
    w["8"] = {
        "class_type": "IPAdapterPreciseComposition",
        "inputs": {
            "model": ["6", 0], "ipadapter": ["6", 1],
            "image": ["7", 0],
            "weight": 0.65,
            "composition_boost": 0.15,
            "combine_embeds": "average",
            "start_at": 0.0, "end_at": 1.0,
            "embeds_scaling": "K+V w/ C penalty",
        },
    }

    # 3D style infusion (light weight)
    w["9"] = {"class_type": "LoadImage", "inputs": {"image": style_rel}}
    w["10"] = {"class_type": "LoadImageMask", "inputs": {"image": regional_mask_rel, "channel": "red"}}
    w["11"] = {
        "class_type": "IPAdapterPreciseStyleTransfer",
        "inputs": {
            "model": ["8", 0], "ipadapter": ["6", 1],
            "image": ["9", 0],
            "weight": P2["style_weight"],
            "style_boost": P2["style_boost"],
            "combine_embeds": "average",
            "start_at": 0.0, "end_at": P2["style_end"],
            "embeds_scaling": "K+V w/ C penalty",
            "attn_mask": ["10", 0],
        },
    }

    # Canny + ControlNet (from source, not from pass1 output)
    w["12"] = {"class_type": "Canny",
               "inputs": {"image": ["2b", 0], "low_threshold": P2["canny_low"],
                           "high_threshold": P2["canny_high"]}}
    w["13"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": CN_MODEL}}
    w["14"] = {
        "class_type": "ControlNetApplyAdvanced",
        "inputs": {
            "positive": ["4", 0], "negative": ["5", 0],
            "control_net": ["13", 0], "image": ["12", 0],
            "strength": P2["cn_strength"],
            "start_percent": 0.0, "end_percent": 1.0,
        },
    }

    # KSampler
    w["15"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["11", 0],
            "seed": SEED + 1, "steps": 30, "cfg": 6.5,
            "sampler_name": "dpmpp_2m", "scheduler": "karras",
            "positive": ["14", 0], "negative": ["14", 1],
            "latent_image": ["3c", 0],
            "denoise": P2["denoise"],
        },
    }

    # decode + save
    w["16"] = {"class_type": "VAEDecode", "inputs": {"samples": ["15", 0], "vae": ["1", 2]}}
    w["17"] = {"class_type": "SaveImage",
               "inputs": {"filename_prefix": output_prefix, "images": ["16", 0]}}

    return w


# ── main ─────────────────────────────────────────────────────────────

def main():
    # Validate server
    info = api_json("/object_info")
    required = {
        "DiffusersLoader", "IPAdapterUnifiedLoader", "IPAdapterPreciseComposition",
        "IPAdapterPreciseStyleTransfer", "ControlNetLoader", "ControlNetApplyAdvanced",
        "Canny", "KSampler", "VAEDecode", "VAEEncode", "SaveImage", "LoadImage",
        "ImageScale", "CLIPTextEncode",
    }
    missing = sorted(required - set(info))
    if missing:
        raise SystemExit(f"Missing ComfyUI nodes: {missing}")

    # Prepare inputs
    source_rel = copy_to_input(SOURCE_IMAGE, "char_001_source.png")
    style_rel = copy_to_input(STYLE_REFS[1], "style_ref_2028688.png")  # best fit
    mask_path = COMFY_INPUT / "char_001_3d_pipeline" / "regional_mask.png"
    build_regional_mask(SOURCE_IMAGE, mask_path)
    mask_rel = mask_path.relative_to(COMFY_INPUT).as_posix()
    print(f"source:  {source_rel}")
    print(f"style:   {style_rel}")
    print(f"mask:    {mask_rel}")

    # ── Pass 1: Identity anchor ──
    print("\n=== Pass 1: Identity Anchor ===")
    w1 = build_pass1_identity(source_rel, "char_001/p1_identity")
    p1_path = submit_and_wait(w1)

    # Use pass-1 output as img2img base for pass 2
    p1_copy = COMFY_INPUT / "char_001_3d_pipeline" / "p1_identity.png"
    p1_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p1_path, p1_copy)
    p1_input_rel = p1_copy.relative_to(COMFY_INPUT).as_posix()

    # ── Pass 2: 3D material infusion ──
    print("\n=== Pass 2: 3D Material ===")
    w2 = build_pass2_material(
        source_rel, style_rel, mask_rel,
        [p1_input_rel, 0],
        "char_001/p2_3d_material",
    )
    p2_path = submit_and_wait(w2)

    # ── Manifest ──
    manifest = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "pass1_identity": str(p1_path),
        "pass1_sha256": sha256(p1_path),
        "pass2_final": str(p2_path),
        "pass2_sha256": sha256(p2_path),
        "source": str(SOURCE_IMAGE),
        "source_sha256": sha256(SOURCE_IMAGE),
        "style_ref": str(STYLE_REFS[1]),
        "style_ref_sha256": sha256(STYLE_REFS[1]),
        "pass1_settings": P1,
        "pass2_settings": P2,
    }
    manifest_path = COMFY_OUTPUT / "char_001" / "comfyui_3d_front_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nManifest: {manifest_path.resolve()}")
    print(f"Final output: {p2_path.resolve()}")


if __name__ == "__main__":
    main()
