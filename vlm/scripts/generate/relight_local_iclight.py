#!/usr/bin/env python3
"""Relight char_001 with IC-Light FBC (Foreground-Background Conditioned) at low denoise.

IC-Light is a diffusion model fine-tuned to preserve foreground content while
changing lighting based on a background image.  We use the FBC variant
(iclight_sd15_fbc.safetensors) which conditions on both FG (character) and BG
(lighting context) through 12-channel UNet concat.

The key insight for 3D conversion: the FG tells the model "this is the
character", the BG tells the model "this is the lighting I want".  Running at
low highres_denoise (0.15-0.25) adds 3D lighting cues while the FG condition
preserves most identity detail.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import safetensors.torch as sf
import torch
from PIL import Image
from diffusers import (
    AutoencoderKL,
    DDIMScheduler,
    DPMSolverMultistepScheduler,
    EulerAncestralDiscreteScheduler,
    StableDiffusionImg2ImgPipeline,
    StableDiffusionPipeline,
    UNet2DConditionModel,
)
from diffusers.models.attention_processor import AttnProcessor2_0
from transformers import CLIPTextModel, CLIPTokenizer

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path("/home/intern/Supervised 2D to 3D")
SCRIPT_ROOT = Path("/home/intern/jsy/vlm")
OUTPUT_ROOT = PROJECT_ROOT / "vlm/experiments/comfyui_output/front_view_local"
ICLIGHT_DIR = Path("/home/intern/ssr/IC-Light")
ICLIGHT_MODEL = ICLIGHT_DIR / "models" / "iclight_sd15_fbc.safetensors"
DEFAULT_SOURCE = (
    Path("/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/cleaned_white.png")
)
DEFAULT_NORMAL = OUTPUT_ROOT / "char_001/candidates/char_001_moge_normal.png"
DEFAULT_PRESHADED = (
    OUTPUT_ROOT
    / "char_001/candidates/char_001_moge_mesh"
    / "char_001_moge_mesh_render_front_moge_normals.png"
)

# ── SD1.5 base ─────────────────────────────────────────────────────────
SD15_NAME = "stablediffusionapi/realistic-vision-v51"

# ── Lighting BG presets ────────────────────────────────────────────────
LIGHTING_PRESETS: dict[str, dict[str, Any]] = {
    "left": {"description": "Left directional light"},
    "right": {"description": "Right directional light"},
    "top": {"description": "Top directional light"},
    "bottom": {"description": "Bottom directional light"},
    "ambient": {"description": "Flat ambient (no direction)"},
    "studio": {"description": "Soft three-point studio lighting"},
}


# ── helpers ────────────────────────────────────────────────────────────


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


def resize_and_center_crop(
    pil_image: Image.Image, target_width: int, target_height: int
) -> Image.Image:
    """Scale to cover target, then center-crop (same as IC-Light upstream)."""
    original_width, original_height = pil_image.size
    scale_factor = max(target_width / original_width, target_height / original_height)
    resized_width = int(round(original_width * scale_factor))
    resized_height = int(round(original_height * scale_factor))
    resized = pil_image.resize((resized_width, resized_height), Image.LANCZOS)
    left = (resized_width - target_width) / 2
    top = (resized_height - target_height) / 2
    right = (resized_width + target_width) / 2
    bottom = (resized_height + target_height) / 2
    return resized.crop((int(left), int(top), int(right), int(bottom)))


def numpy2pytorch(imgs: list[np.ndarray]) -> torch.Tensor:
    h = torch.from_numpy(np.stack(imgs, axis=0)).float() / 127.0 - 1.0
    return h.movedim(-1, 1)


def pytorch2numpy(imgs: torch.Tensor, quant: bool = True) -> list[np.ndarray]:
    results: list[np.ndarray] = []
    for x in imgs:
        y = x.movedim(0, -1)
        if quant:
            y = y * 127.5 + 127.5
            y = y.detach().float().cpu().numpy().clip(0, 255).astype(np.uint8)
        else:
            y = y * 0.5 + 0.5
            y = y.detach().float().cpu().numpy().clip(0, 1).astype(np.float32)
        results.append(y)
    return results


# ── Lighting BG builders ───────────────────────────────────────────────


def build_directional_bg(
    direction: str, width: int, height: int
) -> np.ndarray:
    """Build a directional gradient BG in [-1, 1] range for IC-Light concat."""
    if direction == "left":
        gradient = np.linspace(224, 32, width)
        image = np.tile(gradient, (height, 1))
    elif direction == "right":
        gradient = np.linspace(32, 224, width)
        image = np.tile(gradient, (height, 1))
    elif direction == "top":
        gradient = np.linspace(224, 32, height)[:, None]
        image = np.tile(gradient, (1, width))
    elif direction == "bottom":
        gradient = np.linspace(32, 224, height)[:, None]
        image = np.tile(gradient, (1, width))
    elif direction == "ambient":
        image = np.full((height, width), 64, dtype=np.float32)
    else:
        raise ValueError(f"Unknown direction: {direction}")
    return np.stack((image,) * 3, axis=-1).astype(np.uint8)


def build_studio_bg(width: int, height: int) -> np.ndarray:
    """Soft three-point lighting: key (left-warm) + fill (right-cool) + rim (top)."""
    xx, yy = np.meshgrid(np.linspace(0, 1, width), np.linspace(0, 1, height))
    # Key light: strong warm from upper-left
    key = np.exp(-((xx - 0.15) ** 2 + (yy - 0.1) ** 2) / 0.12) * 180
    # Fill light: soft cool from right
    fill = np.exp(-((xx - 0.85) ** 2 + (yy - 0.3) ** 2) / 0.25) * 80
    # Rim light: from top
    rim = np.exp(-((yy - 0.02) ** 2) / 0.08) * 120
    base = 32.0
    luminance = base + key + fill + rim
    # Tint: warm key region, cool fill region
    r = np.clip(luminance * 1.15, 0, 255)
    g = np.clip(luminance * 1.02, 0, 255)
    b = np.clip(luminance * 0.92, 0, 255)
    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def build_bg_from_image(image_path: Path, width: int, height: int) -> np.ndarray:
    """Resize an existing image to use as BG."""
    img = Image.open(image_path).convert("RGB")
    cropped = resize_and_center_crop(img, width, height)
    return np.array(cropped)


# ── Model loader ───────────────────────────────────────────────────────


class ICLightRelighter:
    """Encapsulates the IC-Light FBC pipeline."""

    def __init__(self, device: str = "cuda"):
        self.device = torch.device(device)

        # --- base SD1.5 components ---
        self.tokenizer = CLIPTokenizer.from_pretrained(
            SD15_NAME, subfolder="tokenizer", local_files_only=True
        )
        self.text_encoder = CLIPTextModel.from_pretrained(
            SD15_NAME, subfolder="text_encoder", local_files_only=True
        )
        self.vae = AutoencoderKL.from_pretrained(
            SD15_NAME, subfolder="vae", local_files_only=True
        )
        self.unet = UNet2DConditionModel.from_pretrained(
            SD15_NAME, subfolder="unet", local_files_only=True
        )

        # --- modify UNet for 12-channel input (4 latents + 4 FG + 4 BG) ---
        with torch.no_grad():
            new_conv_in = torch.nn.Conv2d(
                12,
                self.unet.conv_in.out_channels,
                self.unet.conv_in.kernel_size,
                self.unet.conv_in.stride,
                self.unet.conv_in.padding,
            )
            new_conv_in.weight.zero_()
            new_conv_in.weight[:, :4, :, :].copy_(self.unet.conv_in.weight)
            new_conv_in.bias = self.unet.conv_in.bias
            self.unet.conv_in = new_conv_in

        self._original_unet_forward = self.unet.forward

        def hooked_forward(sample, timestep, encoder_hidden_states, **kwargs):
            c_concat = kwargs["cross_attention_kwargs"]["concat_conds"].to(sample)
            c_concat = torch.cat(
                [c_concat] * (sample.shape[0] // c_concat.shape[0]), dim=0
            )
            new_sample = torch.cat([sample, c_concat], dim=1)
            kwargs["cross_attention_kwargs"] = {}
            return self._original_unet_forward(
                new_sample, timestep, encoder_hidden_states, **kwargs
            )

        self.unet.forward = hooked_forward

        # --- load IC-Light offset ---
        if not ICLIGHT_MODEL.is_file():
            raise FileNotFoundError(f"IC-Light model missing: {ICLIGHT_MODEL}")
        sd_offset = sf.load_file(str(ICLIGHT_MODEL))
        sd_origin = self.unet.state_dict()
        sd_merged = {k: sd_origin[k] + sd_offset[k] for k in sd_origin}
        self.unet.load_state_dict(sd_merged, strict=True)
        del sd_offset, sd_origin, sd_merged

        # --- move to GPU ---
        self.text_encoder = self.text_encoder.to(
            device=self.device, dtype=torch.float16
        )
        self.vae = self.vae.to(device=self.device, dtype=torch.bfloat16)
        self.unet = self.unet.to(device=self.device, dtype=torch.float16)

        # --- SDP ---
        self.unet.set_attn_processor(AttnProcessor2_0())
        self.vae.set_attn_processor(AttnProcessor2_0())

        # --- scheduler ---
        self.dpmpp_scheduler = DPMSolverMultistepScheduler(
            num_train_timesteps=1000,
            beta_start=0.00085,
            beta_end=0.012,
            algorithm_type="sde-dpmsolver++",
            use_karras_sigmas=True,
            steps_offset=1,
        )

        # --- pipelines ---
        self.t2i_pipe = StableDiffusionPipeline(
            vae=self.vae,
            text_encoder=self.text_encoder,
            tokenizer=self.tokenizer,
            unet=self.unet,
            scheduler=self.dpmpp_scheduler,
            safety_checker=None,
            requires_safety_checker=False,
            feature_extractor=None,
            image_encoder=None,
        )

        self.i2i_pipe = StableDiffusionImg2ImgPipeline(
            vae=self.vae,
            text_encoder=self.text_encoder,
            tokenizer=self.tokenizer,
            unet=self.unet,
            scheduler=self.dpmpp_scheduler,
            safety_checker=None,
            requires_safety_checker=False,
            feature_extractor=None,
            image_encoder=None,
        )

    @torch.inference_mode()
    def _encode_prompt(self, txt: str) -> torch.Tensor:
        max_len = self.tokenizer.model_max_length
        chunk_len = max_len - 2
        bos = self.tokenizer.bos_token_id
        eos = self.tokenizer.eos_token_id
        pad = eos

        tokens = self.tokenizer(txt, truncation=False, add_special_tokens=False)[
            "input_ids"
        ]
        chunks = [
            [bos] + tokens[i : i + chunk_len] + [eos]
            for i in range(0, len(tokens), chunk_len)
        ]
        chunks = [
            ck[:max_len] if len(ck) >= max_len else ck + [pad] * (max_len - len(ck))
            for ck in chunks
        ]
        token_ids = torch.tensor(chunks).to(device=self.device, dtype=torch.int64)
        return self.text_encoder(token_ids).last_hidden_state

    @torch.inference_mode()
    def _encode_prompt_pair(
        self, positive: str, negative: str
    ) -> tuple[torch.Tensor, torch.Tensor]:
        c = self._encode_prompt(positive)
        uc = self._encode_prompt(negative)
        c_len = float(len(c))
        uc_len = float(len(uc))
        max_count = max(c_len, uc_len)
        c_repeat = int(math.ceil(max_count / c_len))
        uc_repeat = int(math.ceil(max_count / uc_len))
        max_chunk = max(len(c), len(uc))
        c = torch.cat([c] * c_repeat, dim=0)[:max_chunk]
        uc = torch.cat([uc] * uc_repeat, dim=0)[:max_chunk]
        c = torch.cat([p[None, ...] for p in c], dim=1)
        uc = torch.cat([p[None, ...] for p in uc], dim=1)
        return c, uc

    @torch.inference_mode()
    def relight(
        self,
        fg_image: np.ndarray,
        bg_image: np.ndarray,
        prompt: str = "",
        a_prompt: str = "best quality, sharp focus",
        n_prompt: str = (
            "lowres, bad anatomy, bad hands, cropped, worst quality, "
            "text, watermark, logo, signature, flat, 2D, cel-shaded"
        ),
        seed: int = 20260723,
        steps: int = 25,
        cfg: float = 2.0,
        highres_scale: float = 1.0,
        highres_denoise: float = 0.50,
        num_samples: int = 1,
    ) -> list[np.ndarray]:
        """Run IC-Light FBC relighting.

        Parameters
        ----------
        highres_denoise : float
            Strength of the highres img2img pass.  Lower = more identity
            preservation.  This is the primary knob for the fidelity vs 3D tradeoff.
            Values 0.10-0.30 are reasonable for identity-first relighting.
        """
        image_width: int = fg_image.shape[1]  # set inside, typed for pyright
        image_height: int = fg_image.shape[0]

        # Ensure dimensions are multiples of 64
        image_width = (image_width // 64) * 64
        image_height = (image_height // 64) * 64
        # Clamp to reasonable SD1.5 range
        image_width = max(256, min(image_width, 768))
        image_height = max(256, min(image_height, 768))

        rng = torch.Generator(device=self.device).manual_seed(int(seed))

        # Resize inputs to target size
        fg_pil = Image.fromarray(fg_image)
        bg_pil = Image.fromarray(bg_image)
        fg = resize_and_center_crop(fg_pil, image_width, image_height)
        bg = resize_and_center_crop(bg_pil, image_width, image_height)

        # Build concat condition: VAE(FG) || VAE(BG)
        concat_conds = numpy2pytorch(
            [np.array(fg), np.array(bg)]
        ).to(device=self.vae.device, dtype=self.vae.dtype)
        concat_conds = (
            self.vae.encode(concat_conds).latent_dist.mode()
            * self.vae.config.scaling_factor
        )
        concat_conds = torch.cat([c[None, ...] for c in concat_conds], dim=1)

        # Encode prompts
        full_positive = f"{prompt}, {a_prompt}".strip(", ")
        conds, unconds = self._encode_prompt_pair(full_positive, n_prompt)

        # --- Pass 1: txt2img conditioned on FG + BG ---
        latents = self.t2i_pipe(
            prompt_embeds=conds,
            negative_prompt_embeds=unconds,
            width=image_width,
            height=image_height,
            num_inference_steps=steps,
            num_images_per_prompt=num_samples,
            generator=rng,
            output_type="latent",
            guidance_scale=cfg,
            cross_attention_kwargs={"concat_conds": concat_conds},
        ).images.to(self.vae.dtype) / self.vae.config.scaling_factor

        pixels = self.vae.decode(latents).sample
        pixels_list = pytorch2numpy(pixels)

        # --- Pass 2: highres img2img ---
        if highres_scale > 1.0:
            highres_w = int(round(image_width * highres_scale / 64.0) * 64)
            highres_h = int(round(image_height * highres_scale / 64.0) * 64)
            pixels_list = [
                Image.fromarray(p).resize((highres_w, highres_h), Image.LANCZOS)
                for p in pixels_list
            ]
            pixels_list = [np.array(p) for p in pixels_list]

        pixels_pt = numpy2pytorch(pixels_list).to(
            device=self.vae.device, dtype=self.vae.dtype
        )
        latents = (
            self.vae.encode(pixels_pt).latent_dist.mode()
            * self.vae.config.scaling_factor
        )
        latents = latents.to(device=self.unet.device, dtype=self.unet.dtype)

        # Re-encode FG + BG at updated resolution
        hr_h, hr_w = latents.shape[2] * 8, latents.shape[3] * 8
        fg_hr = resize_and_center_crop(fg_pil, hr_w, hr_h)
        bg_hr = resize_and_center_crop(bg_pil, hr_w, hr_h)
        concat_conds = numpy2pytorch(
            [np.array(fg_hr), np.array(bg_hr)]
        ).to(device=self.vae.device, dtype=self.vae.dtype)
        concat_conds = (
            self.vae.encode(concat_conds).latent_dist.mode()
            * self.vae.config.scaling_factor
        )
        concat_conds = torch.cat([c[None, ...] for c in concat_conds], dim=1)

        effective_steps = max(1, int(round(steps / highres_denoise)))
        latents = self.i2i_pipe(
            image=latents,
            strength=highres_denoise,
            prompt_embeds=conds,
            negative_prompt_embeds=unconds,
            width=hr_w,
            height=hr_h,
            num_inference_steps=effective_steps,
            num_images_per_prompt=num_samples,
            generator=rng,
            output_type="latent",
            guidance_scale=cfg,
            cross_attention_kwargs={"concat_conds": concat_conds},
        ).images.to(self.vae.dtype) / self.vae.config.scaling_factor

        pixels = self.vae.decode(latents).sample
        return pytorch2numpy(pixels, quant=False)


# ── CLI ────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="IC-Light FBC relighting for 2D-to-3D conversion."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Foreground image (cleaned character on white).",
    )
    parser.add_argument(
        "--bg-preset",
        choices=sorted(LIGHTING_PRESETS),
        default="studio",
        help="Lighting background preset.",
    )
    parser.add_argument(
        "--bg-image",
        type=Path,
        default=None,
        help="Override BG with a specific image (e.g. Phong render).",
    )
    parser.add_argument(
        "--prompt",
        default=(
            "anime PVC figurine of this exact character, sculpted 3D volume, "
            "matte painted resin, soft studio lighting, subtle rim light, "
            "glossy hair, matte clothing, white seamless background"
        ),
    )
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--seed", type=int, default=20260723)
    parser.add_argument("--steps", type=int, default=25)
    parser.add_argument("--cfg", type=float, default=2.0)
    parser.add_argument("--highres-scale", type=float, default=1.0)
    parser.add_argument("--highres-denoise", type=float, default=0.20)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--num-samples", type=int, default=1)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to candidates dir under char_001 output tree.",
    )
    parser.add_argument(
        "--tag",
        default=None,
        help="Short label embedded in output filenames.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # --- validate inputs ---
    if not args.source.is_file():
        raise FileNotFoundError(f"Source image not found: {args.source}")
    source = np.array(Image.open(args.source).convert("RGB"))
    orig_h, orig_w = source.shape[:2]
    print(f"Source: {args.source} ({orig_w}×{orig_h})")

    # --- resolve target size ---
    w = (max(256, min(args.width, 768)) // 64) * 64
    h = (max(256, min(args.height, 768)) // 64) * 64

    # --- build BG ---
    bg: np.ndarray
    bg_provenance: dict[str, Any]
    if args.bg_image is not None and args.bg_image.is_file():
        bg = build_bg_from_image(args.bg_image, w, h)
        bg_provenance = {
            "source": str(args.bg_image.resolve()),
            "sha256": sha256(args.bg_image),
            "method": "upload",
        }
        print(f"BG: uploaded {args.bg_image} → {bg.shape}")
    else:
        preset = args.bg_preset
        if preset in ("left", "right", "top", "bottom", "ambient"):
            bg = build_directional_bg(preset, w, h)
        elif preset == "studio":
            bg = build_studio_bg(w, h)
        else:
            raise ValueError(f"Unknown BG preset: {preset}")
        bg_provenance = {"source": f"preset:{preset}", "method": "generated"}
        print(f"BG: preset '{preset}' → {bg.shape}")

    # --- load model & run ---
    print(f"Loading IC-Light FBC on {args.device} ...")
    relighter = ICLightRelighter(device=args.device)
    print(
        f"Relighting: denoise={args.highres_denoise}, "
        f"steps={args.steps}, cfg={args.cfg}, seed={args.seed}"
    )
    tag = args.tag or f"bg{args.bg_preset}_d{int(args.highres_denoise*100):02d}"
    results = relighter.relight(
        fg_image=source,
        bg_image=bg,
        prompt=args.prompt,
        seed=args.seed,
        steps=args.steps,
        cfg=args.cfg,
        highres_scale=args.highres_scale,
        highres_denoise=args.highres_denoise,
        num_samples=args.num_samples,
    )

    # --- save ---
    output_dir = args.output_dir or (
        OUTPUT_ROOT / "char_001/candidates/iclight"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    for idx, result in enumerate(results):
        result_uint8 = (result * 255.0).clip(0, 255).astype(np.uint8)
        out_img = output_dir / f"char_001_iclight_{tag}_s{args.seed}_{idx}.png"
        atomic_png(Image.fromarray(result_uint8), out_img)

        # Also save a downscaled version matching original aspect for review
        out_native = output_dir / f"char_001_iclight_{tag}_s{args.seed}_{idx}_native.png"
        native = Image.fromarray(result_uint8).resize(
            (orig_w, orig_h), Image.LANCZOS
        )
        atomic_png(native, out_native)

        manifest = {
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "provider": "iclight_fbc_local",
            "device": str(args.device),
            "model": str(ICLIGHT_MODEL),
            "model_sha256": sha256(ICLIGHT_MODEL),
            "base_model": SD15_NAME,
            "source": str(args.source.resolve()),
            "source_sha256": sha256(args.source),
            "source_size": [orig_w, orig_h],
            "target_size": [w, h],
            "bg": bg_provenance,
            "prompt": args.prompt,
            "seed": args.seed,
            "steps": args.steps,
            "cfg": args.cfg,
            "highres_scale": args.highres_scale,
            "highres_denoise": args.highres_denoise,
            "tag": tag,
            "output_path": str(out_img),
            "output_native_path": str(out_native),
            "output_sha256": sha256(out_img),
            "network_policy": {
                "hf_hub_offline": os.environ.get("HF_HUB_OFFLINE"),
                "transformers_offline": os.environ.get("TRANSFORMERS_OFFLINE"),
            },
        }
        manifest_path = output_dir / f"char_001_iclight_{tag}_s{args.seed}_{idx}_manifest.json"
        atomic_json(manifest_path, manifest)
        print(f"Saved: {out_img}")
        print(f"Native: {out_native}")
        print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
