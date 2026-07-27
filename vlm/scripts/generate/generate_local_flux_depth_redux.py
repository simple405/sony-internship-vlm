#!/usr/bin/env python3
"""
FLUX Depth + Redux offline inference pipeline for anime figure 3D-view generation.

What this pipeline does
-----------------------
It combines two complementary conditioning signals to guide FLUX.1 image generation:

1. **Depth conditioning (FLUX.1-Depth-dev)** — a ControlNet-style depth map extracted
   from an existing render drives the output geometry, perspective, and silhouette so the
   generated figure matches the 3D pose of the reference depth image.

2. **Identity conditioning (FLUX.1-Redux-dev)** — an image-embedding pipeline encodes the
   source character illustration into FLUX's token space.  These identity tokens are
   appended after the text tokens so the denoiser simultaneously attends to the written
   description *and* the visual appearance of the source character, preserving fine costume
   and facial details.

Inputs
------
- ``--source``:  RGB reference image (character illustration, cleaned white background).
- ``--depth``:   Depth map rendered for the target pose (white = near, black = far, or
                 whatever convention the DA3 depth estimator outputs — FLUX treats it as a
                 structural constraint, not a metric depth).

Outputs
-------
- ``<output>.png``:  Generated 3D-render candidate at the requested resolution.
- ``<output>.json``: Reproducibility manifest with all settings, file hashes, and model
                     snapshot IDs.

GPU requirements
----------------
- Requires a CUDA-capable GPU.  The transformer and text encoder are loaded in bfloat16;
  ``enable_sequential_cpu_offload`` moves model layers to CPU immediately after each
  forward pass, so peak VRAM can be as low as ~6-8 GB at 512×992, at the cost of slower
  throughput (each layer is shuttled back to GPU per denoiser step).
- The Redux image-encoder pipeline is loaded fully onto GPU, run in one shot, then deleted
  before the main Depth pipeline is loaded, keeping total peak VRAM manageable.

Offline mode
------------
HuggingFace Hub environment variables are set to ``"1"`` at module import time so *no*
network request is made.  All model weights must already be present in the local snapshot
directories defined by ``FLUX_DEPTH_MODEL`` and ``FLUX_REDUX_MODEL``.
"""

from __future__ import annotations

import argparse
import gc        # CPython garbage collector — used for explicit cleanup between model stages
import hashlib   # SHA-256 hashing for reproducibility manifests
import json
import os
import uuid      # Random suffix for atomic temp-file names
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


# ---------------------------------------------------------------------------
# Force HuggingFace Hub into fully offline mode before any Hub import occurs.
# "1" disables network access; if the env var is already set we leave it alone
# (setdefault) so a caller can still override from the outside environment.
# ---------------------------------------------------------------------------
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# ---------------------------------------------------------------------------
# Absolute paths — this script runs on the Linux inference server, not on the
# Windows project root, so paths are POSIX.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path("/home/intern/Supervised 2D to 3D")

# Pinned snapshot hash ensures we always load the exact tested revision of
# FLUX.1-Depth-dev regardless of what else may exist in the HF cache.
FLUX_DEPTH_MODEL = Path(
    "/home/intern/.cache/huggingface/hub/"
    "models--black-forest-labs--FLUX.1-Depth-dev/snapshots/"
    "fb5e9b1bae41b8c8adcea4ea2a87b74dd298f07a"
)

# Pinned snapshot hash for FLUX.1-Redux-dev (image-embedding prior pipeline).
FLUX_REDUX_MODEL = Path(
    "/home/intern/.cache/huggingface/hub/"
    "models--black-forest-labs--FLUX.1-Redux-dev/snapshots/"
    "c95859fbf7703ca4d6824b4da4407d7cd0434f81"
)

# Default input/output paths used when the script is run without CLI flags.
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

# ---------------------------------------------------------------------------
# Text prompt passed to FLUX's text encoder.
# Highly detailed to lock down every design element so the model does not
# invent or omit costume features that must match the original 2D illustration.
# ---------------------------------------------------------------------------
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
    """
    Parse command-line arguments for the Depth+Redux generation pipeline.

    All arguments have sensible defaults so the script can be run without any
    flags for the char_001 test case.

    Returns
    -------
    argparse.Namespace
        Parsed arguments with the following attributes:

        source        : Path  — source character image (RGB reference illustration).
        depth         : Path  — depth-map image that drives geometry conditioning.
        output        : Path  — destination PNG path for the generated image.
        flux_model    : Path  — local snapshot directory for FLUX.1-Depth-dev.
        redux_model   : Path  — local snapshot directory for FLUX.1-Redux-dev.
        width         : int   — output image width in pixels (must be divisible by 16).
        height        : int   — output image height in pixels (must be divisible by 16).
        steps         : int   — number of DDPM/DDIM denoising steps (default 28).
        guidance      : float — classifier-free guidance scale (default 10.0).
        redux_strength: float — scalar multiplier applied to the Redux image tokens
                                before concatenation with text tokens (default 0.65).
        seed          : int   — RNG seed for the CPU-side torch.Generator.
    """
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
    """
    Compute the SHA-256 hex digest of a file for reproducibility logging.

    Reads the file in 1 MiB chunks to handle large image or model files
    without loading the entire content into memory at once.

    Parameters
    ----------
    path : Path
        Absolute path to the file to hash.

    Returns
    -------
    str
        Lowercase hex string of the SHA-256 digest (64 characters).
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        # Read successive 1 MiB chunks; stop when read() returns b"" (EOF).
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    """
    Write a JSON-serialisable value to ``path`` atomically.

    The value is first serialised to a randomly-named sibling temp file in the
    same directory, then renamed over the target path with ``os.replace``.
    Because ``os.replace`` is atomic on POSIX (and best-effort on Windows), a
    reader of ``path`` will never see a partially-written file.

    Parameters
    ----------
    path : Path
        Destination file path.  Parent directories are created if absent.
    value : object
        Any JSON-serialisable Python object (dict, list, str, …).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp name in the same directory so the final os.replace rename
    # stays on the same filesystem and is therefore atomic.
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def atomic_png(image: Image.Image, path: Path) -> None:
    """
    Save a PIL image to ``path`` as a PNG file atomically.

    Uses the same write-to-temp-then-rename strategy as ``atomic_json`` so
    the destination file is never left in a partial/corrupted state if the
    process is interrupted mid-save.

    Parameters
    ----------
    image : PIL.Image.Image
        The image to save.
    path : Path
        Destination PNG file path.  Parent directories are created if absent.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    image.save(temp, format="PNG", optimize=True)
    os.replace(temp, path)


def validate_local_models(flux_model: Path, redux_model: Path) -> None:
    """
    Check that all required model weight files are present in the local cache.

    Raises a clear ``FileNotFoundError`` listing every missing file rather than
    letting PyTorch / diffusers fail with a cryptic internal error during
    model loading.

    The checked files are the minimal set of shards and index files that
    diffusers needs to instantiate both pipelines:

    - ``model_index.json``:  pipeline component registry used by ``from_pretrained``.
    - Transformer / text-encoder sharded safetensors index files.
    - VAE single-shard safetensors (not sharded for Depth-dev).
    - Redux image encoder and image embedder weights.

    Parameters
    ----------
    flux_model : Path
        Local snapshot directory for FLUX.1-Depth-dev.
    redux_model : Path
        Local snapshot directory for FLUX.1-Redux-dev.

    Raises
    ------
    FileNotFoundError
        If one or more expected weight files are absent.
    """
    required = [
        flux_model / "model_index.json",
        # FLUX transformer is too large for a single safetensors file and is
        # stored as shards; the index JSON maps parameter names to shard files.
        flux_model / "transformer/diffusion_pytorch_model.safetensors.index.json",
        # T5-XXL text encoder is also sharded.
        flux_model / "text_encoder_2/model.safetensors.index.json",
        # VAE is small enough to fit in a single shard.
        flux_model / "vae/diffusion_pytorch_model.safetensors",
        redux_model / "model_index.json",
        # SigLIP/CLIP image encoder backbone weights.
        redux_model / "image_encoder/model.safetensors",
        # MLP projection head that maps image encoder features → FLUX token space.
        redux_model / "image_embedder/diffusion_pytorch_model.safetensors",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Incomplete local model snapshot:\n" + "\n".join(missing))


def main() -> None:
    """
    Execute the full Depth + Redux generation pipeline.

    Pipeline stages
    ---------------
    1. Argument parsing and input validation.
    2. Image loading and resizing to the target resolution.
    3. **Redux stage**: load FluxPriorReduxPipeline, encode the source image into
       FLUX identity tokens, then immediately unload the pipeline to free VRAM.
    4. **Depth stage**: load FluxControlPipeline with sequential CPU offload,
       encode the text prompt, concatenate text + identity tokens, run the
       diffusion loop conditioned on the depth map.
    5. Atomic save of the output PNG and reproducibility JSON manifest.

    CPU offload strategy
    --------------------
    ``enable_sequential_cpu_offload`` is used instead of ``enable_model_cpu_offload``
    because it offloads at the *sub-module* (layer) level rather than the
    *module* level.  This means only the currently-executing layer occupies
    GPU memory at any given time, which is slower but reduces peak VRAM by
    roughly 50-70 % compared to keeping the full transformer on GPU, making it
    viable on 24 GB cards at 512×992 resolution.

    The Redux pipeline does *not* use CPU offload because it runs a single
    short forward pass (image encoder + MLP) and is deleted immediately after,
    so keeping it fully on GPU for that brief window is fine.
    """
    args = parse_args()

    # -----------------------------------------------------------------------
    # Input validation — fail fast before any heavy model loading.
    # -----------------------------------------------------------------------
    for path in (args.source, args.depth):
        if not path.is_file():
            raise FileNotFoundError(path)

    # FLUX VAE operates on latent patches of size 2×2 (spatial compression
    # factor 8); the transformer patchify step requires the latent spatial
    # dimensions to be even, so the pixel dimensions must be divisible by 16.
    if args.width % 16 or args.height % 16:
        raise ValueError("FLUX width and height must be divisible by 16")

    validate_local_models(args.flux_model, args.redux_model)

    # -----------------------------------------------------------------------
    # Deferred imports — torch and diffusers are large and slow to import;
    # placing them here means argument errors are caught immediately without
    # waiting for the import overhead.
    # -----------------------------------------------------------------------
    import torch
    from diffusers import FluxControlPipeline, FluxPriorReduxPipeline

    # bfloat16 is FLUX's native training dtype and is well-supported on
    # Ampere+ GPUs; it uses half the VRAM of float32 with minimal quality loss.
    dtype = torch.bfloat16
    device = torch.device("cuda")

    # -----------------------------------------------------------------------
    # Image loading and resizing.
    # Shape after resize: (H, W, 3) PIL image.  Diffusers will convert to
    # tensor of shape (B=1, C=3, H, W) internally.
    # -----------------------------------------------------------------------
    source = Image.open(args.source).convert("RGB").resize(
        (args.width, args.height),
        # LANCZOS (Lanczos3) is a high-quality downsampling filter that
        # minimises aliasing — preferred for the character illustration which
        # has fine linework.
        Image.Resampling.LANCZOS,
    )
    depth = Image.open(args.depth).convert("RGB").resize(
        (args.width, args.height),
        # BICUBIC is used for the depth map because it smoothly interpolates
        # continuous depth values without introducing the ringing that LANCZOS
        # can cause on near-constant regions.  The depth map is treated as a
        # control signal, not an artistic image, so smooth gradients matter more
        # than sharp edge preservation.
        Image.Resampling.BICUBIC,
    )
    # Note: no explicit pixel-value normalisation is performed here.  Diffusers'
    # image processor normalises PIL images to [-1, 1] internally before passing
    # them to the VAE or ControlNet encoder, so manual normalisation would
    # double-apply the transform and corrupt the conditioning signal.

    # -----------------------------------------------------------------------
    # Stage 1 — Redux: encode the source image into FLUX identity tokens.
    # The entire Redux pipeline lives on GPU only for this brief encoding step
    # and is deleted afterwards to recover VRAM before the much larger Depth
    # pipeline is loaded.
    # -----------------------------------------------------------------------
    redux = FluxPriorReduxPipeline.from_pretrained(
        args.redux_model,
        torch_dtype=dtype,
        local_files_only=True,  # Never attempt a network download.
    ).to(device)

    with torch.inference_mode():  # Disable gradient tracking — inference only.
        redux_output = redux(source)

        # redux_output.prompt_embeds shape: (B, seq_len, hidden_dim)
        # where B=1, hidden_dim=3072 (FLUX T5-XXL embedding dimension).
        #
        # The Redux pipeline produces a combined token sequence whose first 512
        # positions are reserved for text-conditioning slots (filled with zero /
        # null embeddings when no text prompt is supplied to Redux).  Positions
        # 512 onward are the actual image identity tokens produced by the SigLIP
        # image encoder + MLP projection.
        #
        # We slice [:, 512:] to discard the empty text prefix and keep only the
        # image identity tokens.  These will later be concatenated *after* our
        # own text embeddings (from pipe.encode_prompt), so that the denoiser
        # attends to both the written description and the visual appearance.
        #
        # .detach() breaks the autograd graph; .cpu() moves the tensor off GPU
        # so VRAM is freed when the Redux pipeline is deleted below.
        image_prompt_embeds = redux_output.prompt_embeds[:, 512:].detach().cpu()

    # Explicitly delete the Redux pipeline and its output, then trigger Python
    # GC and the CUDA allocator cache flush.  This reclaims the ~8 GB that
    # Redux occupies so the Depth pipeline can be loaded into the same GPU.
    del redux_output, redux
    gc.collect()
    torch.cuda.empty_cache()

    # -----------------------------------------------------------------------
    # Stage 2 — Depth pipeline: load FluxControlPipeline with CPU offload.
    # -----------------------------------------------------------------------
    pipe = FluxControlPipeline.from_pretrained(
        args.flux_model,
        torch_dtype=dtype,
        local_files_only=True,
    )

    # VAE memory optimisations — the VAE decodes a (B, C=16, H/8, W/8) latent
    # back to a full-resolution image; at 512×992 the latent is 64×124 channels.
    # slicing  — processes one batch element at a time through the decoder.
    # tiling   — splits the spatial dimensions into overlapping tiles that are
    #            decoded separately and blended, keeping peak VRAM proportional
    #            to tile size rather than full latent size.
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()

    # Move each sub-module to GPU just before its forward pass and back to CPU
    # immediately after.  Slower than keeping everything on GPU but dramatically
    # reduces peak VRAM (see docstring for discussion of the tradeoff).
    pipe.enable_sequential_cpu_offload(gpu_id=0)

    with torch.inference_mode():
        # encode_prompt returns three tensors:
        #   text_prompt_embeds   : (B, 512, 3072) — T5-XXL token embeddings.
        #   pooled_prompt_embeds : (B, 768)       — CLIP pooled sentence embedding
        #                          used for the global conditioning vector in FLUX.
        #   _                    : (B, 512)        — token attention mask (unused here).
        #
        # max_sequence_length=512 matches the Redux text-slot count so that
        # when we concatenate text + image tokens the text occupies exactly the
        # first 512 positions, consistent with how Redux structured its output.
        text_prompt_embeds, pooled_prompt_embeds, _ = pipe.encode_prompt(
            prompt=PROMPT,
            device=device,
            max_sequence_length=512,
        )

        # Concatenate along the sequence dimension (dim=1):
        #   text tokens  : shape (1, 512, 3072)
        #   image tokens : shape (1, N_img, 3072) — N_img ≈ 729 (SigLIP 27×27 grid)
        # Result shape   : (1, 512 + N_img, 3072)
        #
        # redux_strength scales the image tokens; values < 1.0 reduce the visual
        # identity pull so the depth and text conditioning are not overwhelmed.
        # 0.65 was found empirically to preserve costume details while still
        # following the depth map faithfully.
        prompt_embeds = torch.cat(
            [text_prompt_embeds, image_prompt_embeds.to(device) * args.redux_strength],
            dim=1,
        )
        # Free the separate text and image embedding tensors; the concatenated
        # prompt_embeds now holds the only reference we need.
        del text_prompt_embeds, image_prompt_embeds

        # Use a CPU-side generator so the seed is device-agnostic and
        # reproducible across different GPU models/drivers.
        generator = torch.Generator(device="cpu").manual_seed(args.seed)

        output = pipe(
            prompt=None,             # Text is supplied via prompt_embeds; no raw string needed.
            control_image=depth,     # Depth map drives the ControlNet geometry conditioning.
            width=args.width,
            height=args.height,
            num_inference_steps=args.steps,
            guidance_scale=args.guidance,
            generator=generator,
            prompt_embeds=prompt_embeds,
            pooled_prompt_embeds=pooled_prompt_embeds,
        ).images[0]                  # .images is a list of PIL Images; take the first (batch=1).

    # -----------------------------------------------------------------------
    # Save outputs atomically so a crash during write never corrupts the file.
    # -----------------------------------------------------------------------
    atomic_png(output, args.output)

    # Build a reproducibility manifest that records every setting and the
    # SHA-256 hashes of all input/output files so results can be exactly
    # reproduced or audited later.
    manifest = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "provider": "server_local_flux_depth_plus_redux_offline",
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "depth": str(args.depth.resolve()),
        "depth_sha256": sha256(args.depth),
        "flux_model": str(args.flux_model.resolve()),
        "flux_revision": args.flux_model.name,   # snapshot hash directory name
        "redux_model": str(args.redux_model.resolve()),
        "redux_revision": args.redux_model.name, # snapshot hash directory name
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
        # Log which GPU(s) were visible so the manifest captures the hardware
        # context; None means all available GPUs were visible.
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }
    atomic_json(args.output.with_suffix(".json"), manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
