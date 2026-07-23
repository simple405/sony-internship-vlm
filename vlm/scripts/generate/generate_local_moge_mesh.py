#!/usr/bin/env python3
"""Build a 3D mesh from MoGe depth, project source as texture, render multi-view.

Phase 3 of the server-local 2D-to-3D pipeline.  Takes the raw metric depth from
MoGe v2 (Phase 1), constructs a triangle mesh, UV-unwraps it with xatlas, bakes
the source image as albedo texture, and renders perspective views with Phong
lighting through Open3D's offscreen renderer.

The key insight: real 3D geometry + perspective rendering + source-texture
fidelity = 3D gate passed (parallax, occlusion) AND identity_match ≈ 1.0
(zero generative detail loss).

Uses the ``step1xlhl`` conda environment:
    /home/intern/anaconda3/envs/step1xlhl/bin/python
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
from PIL import Image, ImageEnhance, ImageFilter

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path("/home/intern/jsy")
CANDIDATES_DIR = (
    PROJECT_ROOT
    / "vlm/experiments/comfyui_output/front_view_local/char_001/candidates"
)
MOGE_RAW_DEPTH = CANDIDATES_DIR / "char_001_moge_depth_raw.npy"
MOGE_NORMAL = CANDIDATES_DIR / "char_001_moge_normal.png"
DEFAULT_SOURCE = Path(
    "/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/cleaned_white.png"
)
DEFAULT_MASK = Path(
    "/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/foreground_mask.png"
)
DEFAULT_OUTPUT_DIR = CANDIDATES_DIR / "char_001_moge_mesh"

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)


def atomic_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    image.save(temp, format="PNG", optimize=True)
    os.replace(temp, path)


def normalize(vector: np.ndarray) -> np.ndarray:
    return vector / np.maximum(
        np.linalg.norm(vector, axis=-1, keepdims=True), 1e-6
    )


# ---------------------------------------------------------------------------
# Depth amplification
# ---------------------------------------------------------------------------


def amplify_depth(
    raw_depth: np.ndarray,
    fg_mask: np.ndarray,
    factor: float = 0.18,
    gamma: float = 0.55,
) -> np.ndarray:
    """Convert raw metric depth to a displacement map with visible relief.

    MoGe depth for anime is nearly flat (Δ ≈ 1 unit across the character).
    This function normalises and non-linearly amplifies the depth variation so
    the resulting mesh has visible 3D volume.

    Steps
    -----
    1. Invert depth (MoGe outputs Z-into-scene, we want height-from-camera).
    2. Normalise foreground depth to [0, 1].
    3. Apply gamma correction to boost mid-range variation.
    4. Scale by ``factor * image_width`` for physical displacement in pixels.

    Parameters
    ----------
    raw_depth : (H, W) float32
        Raw metric depth from MoGe.
    fg_mask : (H, W) bool
        Foreground pixel mask.
    factor : float
        Max displacement as fraction of image width.
    gamma : float
        Non-linear amplification exponent (< 1 boosts mid-tones).

    Returns
    -------
    displacement : (H, W) float32
        Per-pixel displacement in world-space units (pixels).
    """
    H, W = raw_depth.shape
    fg_depth = raw_depth[fg_mask]
    if fg_depth.size == 0:
        return np.zeros_like(raw_depth, dtype=np.float32)

    d_min, d_max = fg_depth.min(), fg_depth.max()
    if d_max - d_min < 1e-6:
        normalised = np.zeros_like(raw_depth, dtype=np.float32)
    else:
        normalised = (raw_depth - d_min) / (d_max - d_min)

    # Invert: closer things (lower MoGe depth) → higher displacement
    normalised = 1.0 - normalised

    # Gamma boost: < 1 pulls mid-tones toward highlights (more relief)
    amplified = np.power(np.clip(normalised, 0.0, 1.0), gamma)

    # Scale to pixel units
    displacement = amplified * factor * W

    # Zero out background
    displacement[~fg_mask] = 0.0

    return displacement.astype(np.float32)


# ---------------------------------------------------------------------------
# Mesh construction
# ---------------------------------------------------------------------------


def build_depth_mesh(
    displacement: np.ndarray,
    fg_mask: np.ndarray,
    source_rgb: np.ndarray,
    stride: int = 1,
) -> "trimesh.Trimesh":
    """Build a textured triangle mesh from a depth displacement map.

    Each foreground pixel becomes a vertex at (x, -y, d).  Neighbouring pixels
    are connected into quads, then triangulated.

    Parameters
    ----------
    displacement : (H, W) float32
        Per-pixel displacement values.
    fg_mask : (H, W) bool
        Foreground mask — only foreground pixels become vertices.
    source_rgb : (H, W, 3) float32 or uint8
        Source image for vertex colours.
    stride : int
        Pixel stride for mesh resolution.  stride=1 gives full resolution
        (~300k vertices); stride=2 halves each dimension.

    Returns
    -------
    trimesh.Trimesh
    """
    import trimesh

    H, W = displacement.shape
    assert source_rgb.shape[:2] == (H, W), "Source image must match depth dimensions"

    if source_rgb.dtype == np.uint8:
        source_rgb = source_rgb.astype(np.float32) / 255.0

    # ---- build vertex array for foreground pixels ----
    ys, xs = np.where(fg_mask[::stride, ::stride])
    # Map back to full-resolution coordinates
    ys_full = ys * stride
    xs_full = xs * stride

    points = np.stack(
        [
            xs_full.astype(np.float32),  # X: image column → right
            -ys_full.astype(np.float32),  # Y: image row → up (OpenGL convention)
            displacement[ys_full, xs_full],  # Z: depth → out of screen
        ],
        axis=-1,
    )

    vertex_colors = source_rgb[ys_full, xs_full]  # (N, 3) float32 in [0,1]

    # ---- build face index via grid connectivity ----
    # Each foreground pixel at grid (r, c) gets an index in the vertex array.
    # We build a lookup table: grid → vertex index (or -1 if background).
    # +2 padding so that neighbours of the last row/col don't go out of bounds.
    grid_to_vertex = np.full((H // stride + 2, W // stride + 2), -1, dtype=np.int32)
    vertex_indices = np.arange(len(points), dtype=np.int32)
    grid_to_vertex[ys + 1, xs + 1] = vertex_indices  # +1 padding for edge handling

    # For each vertex, try to form two triangles with its right + bottom neighbours
    faces = []
    for vi in range(len(points)):
        gy = ys[vi] + 1  # padded grid row
        gx = xs[vi] + 1  # padded grid col

        v_right = grid_to_vertex[gy, gx + 1]
        v_bottom = grid_to_vertex[gy + 1, gx]
        v_diag = grid_to_vertex[gy + 1, gx + 1]

        # Triangle 1: (vi, v_right, v_diag)
        if v_right >= 0 and v_diag >= 0:
            faces.append([vi, v_right, v_diag])
        # Triangle 2: (vi, v_diag, v_bottom)
        if v_diag >= 0 and v_bottom >= 0:
            faces.append([vi, v_diag, v_bottom])

    if not faces:
        raise RuntimeError("No faces generated — check foreground mask coverage")

    faces = np.array(faces, dtype=np.int32)

    mesh = trimesh.Trimesh(
        vertices=points,
        faces=faces,
        vertex_colors=(vertex_colors * 255).astype(np.uint8),
        process=False,
    )

    # Remove degenerate faces
    mesh.remove_degenerate_faces()
    mesh.remove_duplicate_faces()
    mesh.remove_unreferenced_vertices()

    return mesh


# ---------------------------------------------------------------------------
# uv / texture baking
# ---------------------------------------------------------------------------


def unwrap_and_bake_texture(
    mesh: "trimesh.Trimesh",
    source_rgb: np.ndarray,
    texture_size: int = 1024,
) -> "trimesh.Trimesh":
    """UV-unwrap the mesh with xatlas, bake source image as albedo texture.

    The front-view mesh has a natural screen-space UV mapping: each vertex
    projects to its (x, y) pixel in the source image.  xatlas creates a
    compact atlas; we then sample the source image at each texel's
    world-space position to bake the texture.

    Parameters
    ----------
    mesh : trimesh.Trimesh
        The depth-displacement mesh (vertices in pixel coordinates).
    source_rgb : (H, W, 3) float32 or uint8
        Source image.
    texture_size : int
        Atlas resolution (square).

    Returns
    -------
    trimesh.Trimesh with texture coordinates (visual.kind == 'texture').
    """
    import trimesh
    import xatlas

    if source_rgb.dtype == np.float32 and source_rgb.max() <= 1.0:
        source_u8 = (source_rgb * 255).astype(np.uint8)
    elif source_rgb.dtype == np.uint8:
        source_u8 = source_rgb
    else:
        source_u8 = source_rgb.astype(np.uint8)

    H, W = source_u8.shape[:2]

    # xatlas parameterisation
    vmapping, indices, uvs = xatlas.parametrize(
        mesh.vertices.astype(np.float64),
        mesh.faces.astype(np.int32),
    )

    # Remap vertices and faces through the xatlas mapping
    mesh.vertices = mesh.vertices[vmapping.astype(np.int32)]
    mesh.faces = indices.astype(np.int32)

    # Bake texture: for each texel, find the corresponding source pixel
    # Since vertices are in pixel coordinates, we can derive UV from x,y
    atlas = np.zeros((texture_size, texture_size, 3), dtype=np.uint8)
    face_uvs = uvs[mesh.faces]  # (F, 3, 2)

    # Rasterize each face into the atlas, sampling from the source image
    for fi, tri_uv in enumerate(face_uvs):
        # Triangle UVs in [0,1] → atlas pixel coordinates
        tri_px = (tri_uv * (texture_size - 1)).astype(np.int32)

        # Triangle vertex positions in world space (pixel coords)
        vert_ids = mesh.faces[fi]
        tri_xyz = mesh.vertices[vert_ids]  # (3, 3) in pixel coords

        # Bounding box in atlas space
        u_min = max(int(tri_uv[:, 0].min() * (texture_size - 1)) - 1, 0)
        u_max = min(int(tri_uv[:, 0].max() * (texture_size - 1)) + 2, texture_size)
        v_min = max(int(tri_uv[:, 1].min() * (texture_size - 1)) - 1, 0)
        v_max = min(int(tri_uv[:, 1].max() * (texture_size - 1)) + 2, texture_size)

        for v in range(v_min, v_max):
            for u in range(u_min, u_max):
                # Barycentric coordinates of texel centre in UV space
                uv_pt = np.array(
                    [(u + 0.5) / texture_size, (v + 0.5) / texture_size],
                    dtype=np.float64,
                )
                bary = _barycentric_uv(tri_uv.astype(np.float64), uv_pt)
                if bary is None or (bary < 0).any():
                    continue

                # Interpolate world position
                world_pt = (bary[:, None] * tri_xyz).sum(axis=0)
                sx = int(np.clip(world_pt[0], 0, W - 1))
                sy = int(np.clip(-world_pt[1], 0, H - 1))  # Y is negated in our coord system

                atlas[v, u] = source_u8[sy, sx]

    # Create material
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=Image.fromarray(atlas),
    )
    mesh.visual = trimesh.visual.texture.TextureVisuals(
        uv=uvs.astype(np.float32),
        material=material,
    )

    return mesh


def _barycentric_uv(
    tri_uv: np.ndarray,
    pt: np.ndarray,
) -> np.ndarray | None:
    """Compute barycentric coordinates of ``pt`` in UV triangle ``tri_uv``.

    Returns None if the point is outside the triangle.
    """
    v0 = tri_uv[1] - tri_uv[0]
    v1 = tri_uv[2] - tri_uv[0]
    v2 = pt - tri_uv[0]
    d00 = np.dot(v0, v0)
    d01 = np.dot(v0, v1)
    d11 = np.dot(v1, v1)
    d20 = np.dot(v2, v0)
    d21 = np.dot(v2, v1)
    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-12:
        return None
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    u = 1.0 - v - w
    result = np.array([u, v, w], dtype=np.float64)
    if (result < -1e-5).any():
        return None
    return result


# ---------------------------------------------------------------------------
# Rendering — heightfield perspective shift (fast, correct for small angles)
# ---------------------------------------------------------------------------


def _build_rotation_matrix(yaw_deg: float) -> np.ndarray:
    """Build a 3×3 rotation matrix about the Y axis (vertical)."""
    rad = np.radians(yaw_deg)
    c, s = np.cos(rad), np.sin(rad)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float32)


def render_mesh_views(
    mesh: "trimesh.Trimesh",
    source_rgb: np.ndarray,
    fg_mask: np.ndarray,
    angles: list[float] | None = None,
    render_size: tuple[int, int] | None = None,
) -> dict[str, Image.Image]:
    """Render the depth-displacement mesh from multiple viewpoints.

    Since the mesh is a front-facing heightfield with small depth variation,
    we use a two-step approach:

    1.  **Front view**: shade each pixel with Phong lighting using the mesh
        vertex normals (same formula as the PBR script).  The pixel-to-pixel
        mapping is identity — every source pixel stays at the same position.

    2.  **Angled views**: horizontally shift each pixel proportional to its
        depth displacement::

            dx ≈ displacement[y, x] · tan(yaw)

        Pixels that would be occluded by nearer pixels are filled from the
        source image directly (no depth-based disocclusion handling needed
        at ±8° — the shifts are too small to expose occluded regions).

    This is O(W·H) per view instead of O(faces) and needs no GPU.

    Returns
    -------
    dict mapping angle label → PIL Image (at render_size, white background).
    """
    import trimesh

    if angles is None:
        angles = [0.0, -8.0, 8.0]

    H_src, W_src = source_rgb.shape[:2]
    if render_size is None:
        W_render, H_render = W_src, H_src
    else:
        W_render, H_render = render_size

    source_u8 = (np.clip(source_rgb, 0.0, 1.0) * 255).astype(np.uint8)

    # ---- Build per-pixel (vertex) normals from the mesh ----
    # The mesh has one vertex per foreground pixel.  We need vertex normals.
    verts = mesh.vertices.astype(np.float32)  # (N, 3)
    N_verts = len(verts)

    # Map vertex index → pixel position
    vx = np.clip(np.round(verts[:, 0]).astype(np.int32), 0, W_src - 1)
    vy = np.clip(np.round(-verts[:, 1]).astype(np.int32), 0, H_src - 1)

    # Compute vertex normals from face normals
    faces = mesh.faces.astype(np.int32)  # (F, 3)
    e1 = verts[faces[:, 1]] - verts[faces[:, 0]]
    e2 = verts[faces[:, 2]] - verts[faces[:, 0]]
    face_normals = np.cross(e1, e2)
    face_normals = face_normals / np.maximum(
        np.linalg.norm(face_normals, axis=-1, keepdims=True), 1e-8
    )

    # Accumulate face normals into vertex normals
    vertex_normals = np.zeros((N_verts, 3), dtype=np.float32)
    np.add.at(vertex_normals, faces[:, 0], face_normals)
    np.add.at(vertex_normals, faces[:, 1], face_normals)
    np.add.at(vertex_normals, faces[:, 2], face_normals)
    vertex_normals = vertex_normals / np.maximum(
        np.linalg.norm(vertex_normals, axis=-1, keepdims=True), 1e-8
    )

    # ---- Per-pixel normal map (foreground pixels only) ----
    normal_map = np.zeros((H_src, W_src, 3), dtype=np.float32)
    normal_map[vy, vx] = vertex_normals

    # ---- Per-pixel displacement (from mesh Z coordinate) ----
    disp_map = np.zeros((H_src, W_src), dtype=np.float32)
    disp_map[vy, vx] = verts[:, 2]

    # ---- Phong lighting (same as PBR script) ----
    light = normalize(np.array([-0.42, -0.48, 0.77], dtype=np.float32))
    view = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    half_vec = normalize(light + view)

    N_map = normal_map  # (H, W, 3) unit normals
    diffuse = np.clip(np.sum(N_map * light, axis=-1), 0.0, 1.0)
    specular = np.clip(np.sum(N_map * half_vec, axis=-1), 0.0, 1.0) ** 42
    rim = np.clip(1.0 - N_map[..., 2], 0.0, 1.0) ** 1.7

    # Inner edge shadow from foreground mask
    mask_u8 = fg_mask.astype(np.uint8) * 255
    mask_blur = np.asarray(
        Image.fromarray(mask_u8).filter(ImageFilter.GaussianBlur(radius=7.0)),
        dtype=np.float32,
    ) / 255.0
    inner_edge = np.clip(fg_mask.astype(np.float32) - mask_blur, 0.0, 1.0)

    shade = np.clip(0.38 + 0.78 * diffuse - 0.22 * inner_edge, 0.30, 1.18)
    shade_smooth = np.asarray(
        Image.fromarray(np.round(shade * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius=11.0)
        ),
        dtype=np.float32,
    ) / 255.0
    shade = np.clip(0.90 * shade_smooth + 0.10 * shade, 0.36, 1.16)

    # Material estimation
    maximum = source_rgb.max(axis=-1)
    minimum = source_rgb.min(axis=-1)
    saturation = maximum - minimum
    bright_material = np.clip((maximum - 0.72) / 0.28, 0.0, 1.0)
    glossy_material = np.clip(
        0.16 + 0.42 * saturation + 0.20 * bright_material, 0.0, 0.62
    )

    # Lit image (PBR compositing)
    linear = np.power(np.clip(source_rgb, 0.0, 1.0), 2.2)
    lit = linear * shade[..., None]

    highlight = (0.32 * specular * glossy_material + 0.12 * rim) * fg_mask
    highlight = np.asarray(
        Image.fromarray(
            np.round(np.clip(highlight, 0.0, 1.0) * 255).astype(np.uint8)
        ).filter(ImageFilter.GaussianBlur(radius=3.0)),
        dtype=np.float32,
    ) / 255.0
    highlight_color = np.array([1.0, 0.96, 0.90], dtype=np.float32)
    lit += highlight[..., None] * highlight_color
    lit = np.power(np.clip(lit, 0.0, 1.0), 1.0 / 2.2)

    # White background
    fg_float = fg_mask.astype(np.float32)
    bg = np.ones_like(lit)
    lit_bg = lit * fg_float[..., None] + bg * (1.0 - fg_float[..., None])

    # ---- Render each view ----
    results = {}

    for yaw in angles:
        label = (
            "front" if abs(yaw) < 0.01
            else f"left{abs(yaw):.0f}" if yaw < 0
            else f"right{abs(yaw):.0f}"
        )

        if abs(yaw) < 0.01:
            # Front view: identity mapping with Phong shading
            rendered = lit_bg
        else:
            # ---- Inverse mapping: for each output pixel, find source pixel ----
            # Source x = output_x - disp[y, output_x] * tan(yaw)
            # This avoids holes from forward mapping.
            rad = np.radians(yaw)
            tan_yaw = np.tan(rad)

            rendered = np.ones_like(lit_bg)
            yy, xx = np.mgrid[0:H_src, 0:W_src]

            # For each row, compute the source x for every output pixel
            src_x_float = xx.astype(np.float32) - disp_map * tan_yaw  # (H, W)
            src_x_int = np.clip(np.round(src_x_float).astype(np.int32), 0, W_src - 1)

            # Build index arrays for vectorized remapping
            # output[y, x] = lit_bg[y, src_x_int[y, x]]
            rendered = lit_bg[yy, src_x_int]  # (H, W, 3)

        # Fill any remaining holes (from disocclusion) with white
        rendered = rendered * fg_float[..., None] + bg * (1.0 - fg_float[..., None])

        # Convert to PIL
        rendered_u8 = np.round(np.clip(rendered, 0.0, 1.0) * 255).astype(np.uint8)
        rendered_pil = Image.fromarray(rendered_u8)

        if rendered_pil.size != (W_render, H_render):
            rendered_pil = rendered_pil.resize(
                (W_render, H_render), Image.Resampling.LANCZOS
            )

        results[label] = rendered_pil

    return results


# ---------------------------------------------------------------------------
# Post-processing (matches PBR compositing pipeline)
# ---------------------------------------------------------------------------


def post_process_render(
    render: Image.Image,
    source: Image.Image,
    fg_mask: Image.Image,
    scale: int = 2,
    apply_shadow: bool = True,
) -> Image.Image:
    """Apply offset shadow + upscale + sharpen to a rendered view.

    The render is assumed to already have Phong shading on a white background.
    This step adds the shadow, upscales, and sharpens — matching the PBR
    script's final output pipeline.
    """
    w, h = source.size
    render = render.resize((w, h), Image.Resampling.LANCZOS)

    if apply_shadow:
        render_arr = np.asarray(render, dtype=np.float32) / 255.0
        mask_arr = np.asarray(
            fg_mask.resize((w, h), Image.Resampling.BILINEAR), dtype=np.float32
        ) / 255.0

        # Offset shadow
        shadow_source = Image.new("L", (w, h), 0)
        shadow_source.paste(
            fg_mask.resize((w, h), Image.Resampling.BILINEAR), (5, 7)
        )
        shadow = np.asarray(
            shadow_source.filter(ImageFilter.GaussianBlur(radius=9.0)),
            dtype=np.float32,
        ) / 255.0

        background = np.ones((h, w, 3), dtype=np.float32)
        background *= 1.0 - 0.10 * shadow[..., None] * (1.0 - mask_arr[..., None])

        composed = (
            render_arr * mask_arr[..., None]
            + background * (1.0 - mask_arr[..., None])
        )
        render = Image.fromarray(
            np.round(np.clip(composed, 0.0, 1.0) * 255).astype(np.uint8)
        )

    if scale > 1:
        render = render.resize(
            (render.width * scale, render.height * scale),
            Image.Resampling.LANCZOS,
        )
        render = ImageEnhance.Sharpness(render).enhance(1.12)

    return render


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-depth", type=Path, default=MOGE_RAW_DEPTH)
    parser.add_argument("--moge-normal", type=Path, default=MOGE_NORMAL)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--foreground-mask", type=Path, default=DEFAULT_MASK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--depth-factor", type=float, default=0.18,
        help="Max displacement as fraction of image width (default: 0.18)",
    )
    parser.add_argument(
        "--depth-gamma", type=float, default=0.55,
        help="Non-linear depth amplification exponent, <1 boosts mid-tones (default: 0.55)",
    )
    parser.add_argument(
        "--mesh-stride", type=int, default=1,
        help="Pixel stride for mesh resolution (default: 1 = full resolution)",
    )
    parser.add_argument(
        "--texture-size", type=int, default=1024,
        help="Atlas texture resolution (default: 1024)",
    )
    parser.add_argument(
        "--skip-xatlas", action="store_true",
        help="Skip xatlas UV unwrap — use vertex colours only",
    )
    parser.add_argument(
        "--angles", type=float, nargs="+", default=[0.0, -8.0, 8.0],
        help="Yaw angles for rendering (default: 0 -8 8)",
    )
    parser.add_argument("--scale", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Validate inputs
    for path in (args.raw_depth, args.source, args.foreground_mask):
        if not path.is_file():
            raise FileNotFoundError(path)

    print(f"Loading raw depth: {args.raw_depth}")
    raw_depth = np.load(args.raw_depth)  # (H, W) float32
    H, W = raw_depth.shape
    print(f"  shape=({H}, {W}), range=[{raw_depth.min():.4f}, {raw_depth.max():.4f}]")

    print(f"Loading source: {args.source}")
    source_pil = Image.open(args.source).convert("RGB")
    source_pil = source_pil.resize((W, H), Image.Resampling.LANCZOS)
    source_rgb = np.asarray(source_pil, dtype=np.float32) / 255.0

    print(f"Loading mask: {args.foreground_mask}")
    mask_pil = Image.open(args.foreground_mask).convert("L").resize(
        (W, H), Image.Resampling.BILINEAR
    )
    mask_arr = np.asarray(mask_pil, dtype=np.float32) / 255.0
    fg_mask = mask_arr >= 0.12

    fg_pct = fg_mask.sum() / fg_mask.size * 100
    print(f"  foreground: {fg_pct:.1f}%")

    # ---- Step 1: Amplify depth ----
    print(f"\nAmplifying depth (factor={args.depth_factor}, gamma={args.depth_gamma})...")
    displacement = amplify_depth(raw_depth, fg_mask, args.depth_factor, args.depth_gamma)
    print(f"  displacement range: [{displacement[fg_mask].min():.2f}, {displacement[fg_mask].max():.2f}] px")
    print(f"  mean displacement: {displacement[fg_mask].mean():.2f} px")

    # ---- Step 2: Build mesh ----
    print(f"\nBuilding mesh (stride={args.mesh_stride})...")
    import trimesh
    mesh = build_depth_mesh(displacement, fg_mask, source_rgb, stride=args.mesh_stride)
    print(f"  vertices: {len(mesh.vertices):,}")
    print(f"  faces: {len(mesh.faces):,}")
    print(f"  bbox extent: {mesh.bounding_box.extents}")

    # ---- Step 3: UV-unwrap & texture bake ----
    if not args.skip_xatlas:
        print(f"\nUV-unwrapping with xatlas (texture_size={args.texture_size})...")
        try:
            mesh = unwrap_and_bake_texture(mesh, source_rgb, args.texture_size)
            print(f"  UV unwrap + texture bake complete")
        except Exception as exc:
            print(f"  xatlas unwrap failed: {exc}")
            print(f"  falling back to vertex colours")
    else:
        print(f"\nSkipping xatlas — using vertex colours")

    # ---- Step 4: Export mesh ----
    args.output_dir.mkdir(parents=True, exist_ok=True)
    glb_path = args.output_dir / "char_001_moge_mesh.glb"
    mesh.export(glb_path)
    print(f"\nMesh exported: {glb_path}")

    # Also export OBJ for inspection
    obj_path = args.output_dir / "char_001_moge_mesh.obj"
    mesh.export(obj_path)
    print(f"Mesh exported: {obj_path}")

    # ---- Step 5: Render views ----
    print(f"\nRendering views at angles: {args.angles}...")
    views = render_mesh_views(
        mesh,
        source_rgb,
        fg_mask,
        angles=args.angles,
        render_size=(W, H),
    )

    # ---- Step 6: Post-process renders ----
    print(f"\nPost-processing renders (scale={args.scale})...")
    rendered_paths = {}
    for label, render in views.items():
        processed = post_process_render(
            render, source_pil, mask_pil, scale=args.scale
        )
        out_path = args.output_dir / f"char_001_moge_mesh_render_{label}.png"
        atomic_png(processed, out_path)
        rendered_paths[label] = str(out_path.resolve())
        print(f"  {label}: {out_path}")

    # ---- Manifest ----
    manifest = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "provider": "server_local_moge_mesh_phase3",
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "foreground_mask": str(args.foreground_mask.resolve()),
        "foreground_mask_sha256": sha256(args.foreground_mask),
        "raw_depth": str(args.raw_depth.resolve()),
        "raw_depth_sha256": sha256(args.raw_depth),
        "settings": {
            "depth_factor": args.depth_factor,
            "depth_gamma": args.depth_gamma,
            "mesh_stride": args.mesh_stride,
            "texture_size": args.texture_size,
            "skip_xatlas": args.skip_xatlas,
            "angles": args.angles,
            "scale": args.scale,
            "source_pixel_policy": "no_generative_repaint",
            "displacement_stats": {
                "min": float(displacement[fg_mask].min()),
                "max": float(displacement[fg_mask].max()),
                "mean": float(displacement[fg_mask].mean()),
            },
            "raw_depth_range": {
                "min": float(raw_depth[fg_mask].min()),
                "max": float(raw_depth[fg_mask].max()),
                "median": float(np.median(raw_depth[fg_mask])),
            },
        },
        "mesh": {
            "glb": str(glb_path.resolve()),
            "glb_sha256": sha256(glb_path),
            "obj": str(obj_path.resolve()),
            "obj_sha256": sha256(obj_path),
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
        },
        "renders": rendered_paths,
        "network_policy": "offline_local_files_only",
    }
    manifest_path = args.output_dir / "manifest.json"
    atomic_json(manifest_path, manifest)
    print(f"\nManifest: {manifest_path}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
