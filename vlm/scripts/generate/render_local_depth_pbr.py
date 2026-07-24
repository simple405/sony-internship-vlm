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
    """Parse command-line arguments for the depth-based PBR relighting pipeline.

    Key parameters
    --------------
    --source            Clean white-background source PNG (source pixels are never
                        repainted — only lighting is applied on top of them).
    --foreground-mask   Grayscale mask; pixels >= 0.12 are treated as foreground.
    --depth             DA3-SMALL monocular depth PNG (8-bit L, near=bright).
    --geometry-normal   Step1X-3D geometry render normal map (OpenGL RGB convention).
    --output            Destination PNG path; a sibling ``.json`` manifest is also
                        written.
    --scale             Integer upscale factor applied after compositing (default 2).
    --normal-strength   Gradient amplification for depth-derived normals (default
                        20.0).  Higher values make depth edges sharper; lower values
                        yield rounder, smoother surfaces.
    """
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
    """Return the lowercase hex SHA-256 digest of a file, read in 1MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    """Write *value* as pretty-printed UTF-8 JSON to *path* atomically.

    Creates the parent directories if they do not exist. The file is first
    written to a sibling ``.tmp`` file with a random suffix and then renamed
    over *path* via ``os.replace``, so a concurrent reader never sees a
    partial write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def atomic_png(image: Image.Image, path: Path) -> None:
    """Save *image* as an optimised PNG to *path* atomically.

    Uses the same write-to-temp-then-rename strategy as ``atomic_json`` to
    guarantee that *path* is either the previous complete file or the new
    complete file — never a truncated intermediate state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    image.save(temp, format="PNG", optimize=True)
    os.replace(temp, path)


def normalize(vector: np.ndarray) -> np.ndarray:
    """Return *vector* divided by its per-pixel L2 norm.

    A small epsilon (1e-6) guards against division by zero for background
    pixels whose normal vector is the zero vector. The operation is applied
    along the last axis so it works on arrays of shape (..., 3).
    """
    return vector / np.maximum(np.linalg.norm(vector, axis=-1, keepdims=True), 1e-6)


def main() -> None:
    """Run the full depth-based PBR relighting pipeline and write outputs.

    Pipeline overview
    -----------------
    1. Load source RGB, foreground mask, DA3 depth, and Step1X geometry normals.
    2. Build a smooth *height field* that blends DA3 depth with analytic Gaussian
       lobes centred on the head, torso, and sleeves.  This adds sculpted figure
       volume without any generative repaint.
    3. Derive *gradient normals* from the height field (via ``np.gradient``) and
       amplify them with ``--normal-strength`` (default 20.0).
    4. Align the Step1X geometry normal map to the source foreground bounding box
       and blend: **78% geometry normals + 22% gradient normals**.  The blend
       preserves the clean 3D structure from Step1X while the depth gradients
       fill gaps at the silhouette.
    5. Apply Blinn-Phong lighting (key light, specular, rim) driven by the blended
       normal field.
    6. Estimate per-pixel glossiness from source saturation and brightness.
    7. Add a soft warm specular highlight and a Fresnel-like rim highlight.
    8. Composite over a white background with a subtle drop-shadow.
    9. Optionally upscale 2× with Lanczos + light sharpening.
    10. Write the output PNG and a sibling JSON manifest atomically.
    """
    args = parse_args()
    for path in (args.source, args.foreground_mask, args.depth, args.geometry_normal):
        if not path.is_file():
            raise FileNotFoundError(path)

    source_pil = Image.open(args.source).convert("RGB")
    size = source_pil.size
    mask_pil = Image.open(args.foreground_mask).convert("L").resize(
        size, Image.Resampling.BILINEAR
    )
    # Bicubic resize preserves edge sharpness in the depth map better than bilinear.
    # Pre-blur radius=3.0 removes DA3 quantisation noise before gradient estimation;
    # without it, np.gradient would amplify single-pixel ringing into spiky normals.
    depth_pil = Image.open(args.depth).convert("L").resize(size, Image.Resampling.BICUBIC)
    depth_pil = depth_pil.filter(ImageFilter.GaussianBlur(radius=3.0))

    source = np.asarray(source_pil, dtype=np.float32) / 255.0
    mask = np.asarray(mask_pil, dtype=np.float32) / 255.0
    # Depth is 8-bit: 0=far, 255=near.  Normalising to [0,1] gives a relative
    # height field (closer objects map to higher values).
    depth = np.asarray(depth_pil, dtype=np.float32) / 255.0

    height, width = depth.shape
    # Normalised image-space coordinates: x,y ∈ [0,1].  Used for the analytic
    # Gaussian lobes that add figure-like convexity on top of the DA3 depth.
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    x = xx / max(width - 1, 1)
    y = yy / max(height - 1, 1)

    # DA3 supplies the silhouette and coarse depth. Smooth semantic convexity
    # adds figure-like face/torso volume without repainting any source pixels.
    # Each Gaussian lobe is defined as exp(-[(x-cx)^2/sx^2 + (y-cy)^2/sy^2] * scale).
    # Parameters (cx, cy): normalised image centre of the body region.
    # Parameters (sx, sy): normalised spread (standard-deviation-like radii).
    head = np.exp(-(((x - 0.50) / 0.28) ** 2 + ((y - 0.29) / 0.21) ** 2) * 1.4)
    # head centred at 50% width, 29% height (upper-centre); compact vertical sigma.
    torso = np.exp(-(((x - 0.50) / 0.42) ** 2 + ((y - 0.67) / 0.34) ** 2) * 1.6)
    # torso centred at 50% width, 67% height; wider horizontal spread for the body.
    left_sleeve = np.exp(-(((x - 0.12) / 0.22) ** 2 + ((y - 0.60) / 0.30) ** 2) * 1.5)
    # left sleeve centred at 12% width (image-left), 60% height.
    right_sleeve = np.exp(-(((x - 0.88) / 0.22) ** 2 + ((y - 0.60) / 0.30) ** 2) * 1.5)
    # right sleeve centred at 88% width (image-right), mirrored from left sleeve.
    #
    # Blend weights for the height field:
    #   0.56 × DA3 depth   — primary source of true depth variation
    #   0.28 × head lobe   — rounds the face/head region
    #   0.12 × torso lobe  — adds subtle body convexity
    #   0.08 × sleeve lobes — rounds the shoulder/sleeve areas
    height_field = np.clip(
        0.56 * depth + 0.28 * head + 0.12 * torso + 0.08 * (left_sleeve + right_sleeve),
        0.0,
        1.0,
    ) * mask  # zero-out the background so gradients don't bleed across the silhouette

    # Compute image-space gradients of the height field.
    # np.gradient returns (grad_y, grad_x) in row-major order.
    # The surface normal from a height field h(x,y) is proportional to
    #   (-dh/dx, -dh/dy, 1) — negated gradients point "uphill" away from
    #   the viewer when depth is near=high.
    # normal_strength (default 20.0) amplifies the flat depth gradients so
    # they produce meaningful normals; without scaling they would be near-zero
    # and the surface would appear perfectly flat.
    grad_y, grad_x = np.gradient(height_field)
    depth_normals = np.stack(
        [
            -grad_x * args.normal_strength,
            -grad_y * args.normal_strength,
            np.ones_like(depth),  # +Z always points toward the camera
        ],
        axis=-1,
    )
    depth_normals = normalize(depth_normals)

    # ------------------------------------------------------------------
    # Align Step1X geometry normal map to source foreground bounding box.
    # Step1X outputs a fixed-size render; its foreground may not match the
    # source image crop exactly.  We find both bounding boxes via argwhere
    # and resize the geometry crop to fit the source foreground bbox.
    # Threshold < 250 (not 255) tolerates mild JPEG/resize artefacts on white.
    # ------------------------------------------------------------------
    geometry_image = Image.open(args.geometry_normal).convert("RGB")
    geometry_array = np.asarray(geometry_image, dtype=np.uint8)
    geometry_foreground = np.any(geometry_array < 250, axis=-1)
    geometry_points = np.argwhere(geometry_foreground)
    # Threshold 0.12 matches the main foreground mask threshold used throughout.
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
    # Place the aligned geometry crop into a canvas initialised to white (1,1,1).
    # White in an OpenGL normal map decodes to (1,1,1)*2-1 = (1,1,1), which
    # after normalisation gives approximately (0.577,0.577,0.577) — a 45° flat
    # normal.  Background pixels never contribute to shading because they are
    # masked out in the 'normals' assignment below.
    aligned_geometry = np.ones((height, width, 3), dtype=np.float32)
    aligned_geometry[sy1:sy2, sx1:sx2] = (
        np.asarray(geometry_crop, dtype=np.float32) / 255.0
    )
    # Decode OpenGL normal map: [0,1] → [-1,1], then re-normalise.
    geometry_normals = normalize(aligned_geometry * 2.0 - 1.0)
    # Blend: 78% geometry (clean Step1X 3D) + 22% depth gradients (DA3 edges).
    # The majority weight on geometry_normals preserves the well-formed 3D shape;
    # the small depth gradient contribution sharpens silhouette edges that
    # Step1X may not resolve at the source image's original resolution.
    normals = normalize(0.78 * geometry_normals + 0.22 * depth_normals)
    # Background pixels get a flat front-facing normal [0,0,1] so they receive
    # full ambient lighting and no specular/rim contribution.
    normals = np.where(mask[..., None] >= 0.12, normals, np.array([0.0, 0.0, 1.0]))

    # ------------------------------------------------------------------
    # Blinn-Phong lighting model
    # ------------------------------------------------------------------
    # Key light direction (normalised).  Components: X=-0.42 (slightly right of
    # the camera → light comes from the left side of the image), Y=-0.48 (slightly
    # above centre → light comes from above), Z=0.77 (mostly toward the camera →
    # front-lit so the anime flat colours stay visible).  Negative Y because image
    # Y increases downward but the lighting convention is Y-up.
    light = normalize(np.array([-0.42, -0.48, 0.77], dtype=np.float32))
    # Orthographic camera points straight down the +Z axis.
    view = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    # Blinn-Phong half-vector: halfway between light and view directions.
    # Using H instead of the reflection vector R avoids the R·V calculation
    # and is more physically plausible for rough anime surfaces.
    half_vector = normalize(light + view)
    # Lambertian diffuse: cosine of the angle between the surface normal and
    # the light direction.  Clamped to [0,1] (back-lit surfaces get 0 diffuse).
    diffuse = np.clip(np.sum(normals * light, axis=-1), 0.0, 1.0)
    # Blinn-Phong specular: (N·H)^n.  Exponent 42 is a moderately tight
    # highlight — soft enough to avoid a plastic look on flat-coloured anime
    # but sharp enough to read as a 3D render at thumbnail size.
    specular = np.clip(np.sum(normals * half_vector, axis=-1), 0.0, 1.0) ** 42
    # Fresnel-like rim: 1 - N.z measures how much a surface faces sideways
    # (N.z ≈ 0 for edge-on surfaces, N.z ≈ 1 for front-facing surfaces).
    # Power 1.7 gives a wide, soft rim — narrower than a true Schlick Fresnel
    # but wide enough to define silhouette edges on the anime figure.
    rim = np.clip(1.0 - normals[..., 2], 0.0, 1.0) ** 1.7

    # Inner-edge shadow: blurring the mask (radius=7) and subtracting the
    # original isolates a thin bright band just inside the silhouette.
    # Multiplying by -0.22 darkens those pixels, creating a contact-shadow
    # effect that reinforces the sense of depth at garment edges.
    blurred_mask = np.asarray(
        mask_pil.filter(ImageFilter.GaussianBlur(radius=7.0)), dtype=np.float32
    ) / 255.0
    inner_edge = np.clip(mask - blurred_mask, 0.0, 1.0)
    # Shade formula: ambient(0.38) + diffuse_weight(0.78)×diffuse
    #                            - edge_shadow(0.22)×inner_edge
    # Clamp [0.30, 1.18]: floor prevents fully black shadows on back-lit areas
    # (anime figures always retain some ambient light); ceiling 1.18 allows
    # slightly super-bright highlights before gamma compression.
    shade = np.clip(0.38 + 0.78 * diffuse - 0.22 * inner_edge, 0.30, 1.18)
    # Smooth the shade map with a large kernel (radius=11) to suppress
    # normal-map artefacts and preserve the flat-colour look of anime.
    # The 90/10 blend keeps the smoothed version dominant but retains 10%
    # of the high-frequency detail so garment seams remain slightly visible.
    # Final clamp [0.36, 1.16] is tighter than the raw clamp above because
    # the smoothed ambient is guaranteed to be non-zero.
    shade_smooth = np.asarray(
        Image.fromarray(np.round(shade * 255.0).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius=11.0)
        ),
        dtype=np.float32,
    ) / 255.0
    shade = np.clip(0.90 * shade_smooth + 0.10 * shade, 0.36, 1.16)

    # ------------------------------------------------------------------
    # PBR material estimation heuristics (per-pixel, no separate material map)
    # ------------------------------------------------------------------
    # HSV-style saturation: max(RGB) - min(RGB) ∈ [0,1].
    # Highly saturated pixels (vivid costume colours) are treated as glossier.
    maximum = source.max(axis=-1)
    minimum = source.min(axis=-1)
    saturation = maximum - minimum
    # Bright-material mask: pixels with max(RGB) > 0.72 are likely highlights
    # or white/near-white surfaces (shirt, outer coat).  The 0.28 divisor
    # normalises the range [0.72, 1.0] → [0, 1] so the contribution is gradual.
    bright_material = np.clip((maximum - 0.72) / 0.28, 0.0, 1.0)
    # Glossy weight formula:
    #   base 0.16  — every surface has a small baseline specularity
    #   + 0.42 × saturation — colourful areas (hair, accessories) are glossier
    #   + 0.20 × bright_material — near-white surfaces also specular (fabric sheen)
    # Cap at 0.62 to prevent over-saturated specular on very vivid colours.
    glossy_material = np.clip(0.16 + 0.42 * saturation + 0.20 * bright_material, 0.0, 0.62)

    # ------------------------------------------------------------------
    # Compose lit image: sRGB → linear → shade → add highlights → sRGB
    # ------------------------------------------------------------------
    # Convert sRGB source pixels to linear light (gamma 2.2 approximation)
    # before multiplying by the shade term.  Without linearisation, the shade
    # multiplication would happen in a perceptually non-uniform space and
    # produce an overly dark, compressed-looking result.
    linear = np.power(np.clip(source, 0.0, 1.0), 2.2)
    lit = linear * shade[..., None]
    # Specular highlight: 0.32 × specular × glossy controls reflectance
    # strength per-pixel.  0.12 × rim adds a secondary edge glow.
    # Both terms are masked to stay within the foreground silhouette.
    highlight = (0.32 * specular * glossy_material + 0.12 * rim) * mask
    # Blur the highlight slightly (radius=3) to soften the hard specular lobe
    # into a smooth gloss that reads better at anime scale.
    highlight = np.asarray(
        Image.fromarray(np.round(np.clip(highlight, 0.0, 1.0) * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius=3.0)
        ),
        dtype=np.float32,
    ) / 255.0
    # Warm-white highlight tint: R=1.0, G=0.96, B=0.90 gives a slightly
    # yellow-warm specular (typical for studio key lights) rather than a
    # neutral or cold blue gloss.
    highlight_color = np.array([1.0, 0.96, 0.90], dtype=np.float32)
    lit += highlight[..., None] * highlight_color
    # Encode back to sRGB (gamma 1/2.2) for display.
    lit = np.power(np.clip(lit, 0.0, 1.0), 1.0 / 2.2)

    # A soft rear shadow separates the figure from the white studio backdrop.
    # Offset paste (5px right, 7px down) simulates light coming from the upper-left,
    # casting a shadow to the lower-right.  The Gaussian blur (radius=9) feathers
    # the shadow edge so it reads as a soft area-light shadow rather than a
    # hard drop-shadow.  Strength 0.10 keeps the white background nearly white
    # (max darkening: 10%).  The (1 - mask) term restricts the shadow to pixels
    # that are not covered by the foreground figure.
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
        # Sharpness factor 1.12: a mild post-upscale sharpening pass to recover
        # the slight softening that LANCZOS introduces.  Values > 1.5 would
        # produce ringing artefacts on anime line-art edges.
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
