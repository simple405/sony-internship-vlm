# Plan: MoGe-first server-local 2D-to-3D pipeline for char_001

**Date:** 2026-07-23
**Status:** PLANNED
**Bead(s):** none
**Epic:** char_001 2D-to-3D conversion with detail fidelity
**Chain:** `standalone-38ec30d8` seq `1`
**Context:** See `HANDOFF_server-local-3d-approaches_2026-07-23.md` for session data, model inventory, and prior approaches.

---

## Problem Statement

char_001 needs a 3D-style front view that passes two hard gates simultaneously: (1) one-to-one source detail fidelity across all 5 annotated elements, and (2) unmistakable 3D appearance. Four server-local approaches (SDXL+IP-Adapter, FLUX Depth+Redux, Step1X-3D, DA3-SMALL+PBR) each fail one gate. The only candidate that passed both (Codex reference edit round 3, identity_match=1.0, visual_quality=0.95) violates the server-local-only requirement. This plan implements a new approach — MoGe-based geometry with non-generative source texture — that combines real 3D geometry (passing the 3D gate) with zero detail loss (passing the fidelity gate), using only fully cached server-local models.

## Key Findings

- **DA3-SMALL is the bottleneck in the PBR pipeline** — the deterministic approach is correct but was fed weak depth (SMALL variant) and potentially misaligned Step1X normals. MoGe v2 (1.3 GB, fully cached) provides both better depth and directly estimated surface normals in one inference pass. → drives Phase 1
- **Non-generative texture preservation is proven possible** — the PBR script's `source_pixel_policy: no_generative_repaint` achieved perfect pixel fidelity. The only gap was insufficient 3D appearance from weak geometry inputs. → drives Phase 2
- **MoGe replaces two weak dependencies** — instead of DA3-SMALL depth + Step1X geometry normals (which carry fidelity errors from the 3D reconstruction), MoGe outputs metric depth AND surface normals from the same model with consistent coordinate space. → drives Phase 2
- **Depth-to-mesh + texture projection is the novel approach** — unlike Step1X (which generates new texture via SDXL and loses details), projecting the source image as texture onto a depth-derived mesh preserves every pixel while achieving real 3D render capability. → drives Phase 3
- **Zero123++ is fully cached and never used** — 6-view multi-view generation could dramatically improve Step1X geometry quality if single-view MoGe depth proves insufficient. → drives Phase 4 (fallback)
- **IC-Light sd15 (1.7 GB) provides learned relighting** — if hand-crafted Phong shading with MoGe normals still looks flat, IC-Light offers a middle ground between non-generative PBR and full generative repaint. → drives Phase 5 (enhancement)
- **3D toolchain is ready** — Step1X conda environment has trimesh, open3d, pytorch3d, nvdiffrast, xatlas, pymeshlab installed. No package installation needed. → unblocks all phases

## Anti-Goals (What NOT To Do)

- **Do NOT download new models** — TRELLIS, DA3-GIANT, VGGT-1B are tempting but require download approval that has not been granted. All phases use only fully cached models.
- **Do NOT resume the Qwen image edit partial download** — the 938 MiB / 35.9 GB sparse file stays paused. Do not touch it.
- **Do NOT use GPU 1** — it's occupied by another user's Python process (PID 2998670, ~59.6 GiB). All GPU work targets GPU 0 or GPU 2.
- **Do NOT restart ComfyUI** — it was deliberately terminated in the prior session and is not needed for this plan. All new scripts run as standalone Python pipelines.
- **Do NOT use the Codex reference edit approach** — it's proven to work but violates the server-local-only constraint. The goal is to match its quality with local models, not use it as a fallback.
- **Do NOT start batch generation** — the fixed production output path must not be overwritten until a single candidate passes review and is human-approved.

## Plan

### Phase 1: MoGe depth + normal extraction for char_001

**Goal:** Write a standalone script that loads MoGe v2 from HF cache, runs inference on char_001 source, and outputs metric depth + surface normal maps for visual comparison against DA3-SMALL baseline.

**Why this approach:** Before integrating MoGe into any pipeline, we must verify it produces usable geometry for anime characters. MoGe was trained on real-world images — anime line art with flat shading regions may produce degraded or noisy depth/normals. A quick extraction + side-by-side comparison against the existing DA3-SMALL depth output answers this in under an hour. If it fails, we pivot to Phase 4 (Zero123++) immediately without wasting time on Phases 2-3.

- Write `vlm/scripts/generate/prepare_local_moge_depth_normal.py` following the pattern of `prepare_local_da3_depth.py`
- Load MoGe v2 from `/home/intern/.cache/huggingface/hub/models--Ruicheng--moge-2-vitl-normal/snapshots/b135031bae30b5ac2ae141a0e68717795ce38340/`
- Accept `--source`, `--foreground-mask`, `--output-dir` arguments with defaults pointing to char_001 paths
- Run inference on GPU 2 (CUDA_VISIBLE_DEVICES=2); MoGe v2 is ~1.3 GB, fits comfortably on RTX 3090 24 GB
- Output three files to `candidates/` dir: `char_001_moge_depth.png` (inverse depth normalized, 3-channel), `char_001_moge_normal.png` (RGB normal map, 3-channel), `char_001_moge_depth_raw.npy` (raw metric depth for mesh construction)
- Apply foreground mask (threshold ≥ 32, same as DA3 script) to both depth and normal outputs
- Normalize depth with same 2%-98% percentile clipping as DA3 script for fair comparison
- Print summary statistics: depth range (min/max/median in metric units), normal coverage (% of foreground with valid normals)
- Save a side-by-side comparison PNG: DA3-SMALL depth | MoGe depth | MoGe normals (3-panel horizontal)

**Files:** `vlm/scripts/generate/prepare_local_moge_depth_normal.py` (CREATE)
**Validates with:** Visual inspection of 3-panel comparison; MoGe depth min/max/median printed to stdout; confirm normal map has no large flat regions (indicates model degraded on anime content)
**Rollback:** Script is standalone — if MoGe depth is worse than DA3-SMALL, delete the script and skip to Phase 4. No other files modified.

### Phase 2: MoGe-enhanced PBR relighting

**Goal:** Modify the existing PBR relighting script to use MoGe depth + normals instead of DA3-SMALL depth + Step1X geometry normals, and compare output quality against the DA3-SMALL PBR baseline.

**Why this approach:** The PBR script's architecture is correct — deterministic shading on source pixels. The 78/22 normal blending was a workaround because Step1X normals carried fidelity errors and DA3 gradient normals were too smooth. MoGe provides clean, metric-consistent normals directly, eliminating the blending compromise. This phase produces a reviewable image with minimal code changes, giving fast feedback on whether better geometry alone solves the "visually 2D" problem.

- Copy `render_local_depth_pbr.py` to `render_local_moge_pbr.py` (keep original intact for comparison)
- Replace `--depth` and `--geometry-normal` arguments with single `--moge-dir` pointing to Phase 1 output directory
- Load MoGe depth from `_depth.png` (pre-normalized) and normals from `_normal.png` (RGB normal map)
- Remove the 78/22 normal blending logic — use 100% MoGe normals
- Remove the `normal_strength` parameter (was needed to amplify weak DA3 gradient normals) — MoGe normals should be naturally strong
- Keep all other parameters identical: `--scale 2`, same Phong lighting (key light -0.42, -0.48, 0.77), same material estimation, same compositing
- Run on GPU 0 or CPU (PBR is pure numpy/Pillow, no GPU needed after depth/normal extraction)
- Output: `char_001_moge_pbr.png` to candidates dir
- Run Qwen-VL review on the output using the semantic review variant (with waist/placket clarifications)

**Files:** `vlm/scripts/generate/render_local_moge_pbr.py` (CREATE — copy + modify from render_local_depth_pbr.py)
**Validates with:** Qwen-VL semantic review on output; target: three_dimensional=true AND identity_match ≥ 0.85 AND all 5 elements preserved
**Rollback:** If review fails, the original `render_local_depth_pbr.py` is untouched. Analyze failure mode: if 3D gate still false → MoGe normals aren't sufficient for anime content, proceed to Phase 3 (mesh approach) or Phase 5 (IC-Light). If identity drops → MoGe normals introduced artifacts, revert normal blending.

### Phase 3: Depth-to-mesh + source texture projection

**Goal:** Build a 3D mesh from MoGe depth, project the source image as texture, and render with 3D lighting. This is the novel approach — real 3D geometry with zero generative detail loss.

**Why this approach:** The PBR approach (Phase 2) applies 3D-like shading to a flat image — it's 2.5D and may still look like a bas-relief. Building an actual 3D mesh and rendering it with perspective projection creates genuine 3D appearance: parallax, occlusion, specular response to surface curvature. Meanwhile, projecting the source image as texture preserves perfect pixel fidelity — unlike Step1X which generates new texture via SDXL and loses details.

- Write `vlm/scripts/generate/generate_local_moge_mesh.py`
- Use Step1X conda environment (has trimesh, open3d, pytorch3d, nvdiffrast, xatlas)
- Load raw metric depth from `char_001_moge_depth_raw.npy` (Phase 1 output)
- Create triangle mesh via depth displacement: each pixel → vertex at (x, y, depth), connect to neighbors → quad mesh → triangulate
- Apply foreground mask to trim background vertices (creates clean silhouette edges)
- Optionally apply mild mesh smoothing (Laplacian, 1-2 iterations) to reduce depth noise while preserving sharp edges
- UV-unwrap using xatlas (parameterization) for texture mapping
- Project source image onto mesh as albedo texture: for each visible face, sample corresponding source pixel → write to texture atlas
- Render from 3 viewpoints: front (0°), slight left (-8°), slight right (+8°) using nvdiffrast or trimesh rendering
- Apply same Phong lighting as PBR script for consistency
- Output: `char_001_moge_mesh.obj` (or .glb), `char_001_moge_render_front.png`, `char_001_moge_render_left.png`, `char_001_moge_render_right.png`
- Run Qwen-VL review on front render using semantic variant

**Files:** `vlm/scripts/generate/generate_local_moge_mesh.py` (CREATE)
**Validates with:** Qwen-VL semantic review on front render; target: three_dimensional=true AND identity_match ≥ 0.95 (should be near-perfect since texture IS the source). Multi-view renders should show visible parallax (different silhouette edges between left/right views) confirming real 3D.
**Rollback:** If mesh looks bas-relief-like (no parallax between views) → depth range is too compressed, try amplifying depth contrast. If texture has visible seams → improve UV unwrapping or use screen-space projection instead of atlas. If both fail → proceed to Phase 4.

### Phase 4: Zero123++ multi-view → Step1X enhanced geometry (FALLBACK)

**Goal:** If MoGe-only approaches (Phases 1-3) don't achieve sufficient 3D appearance, generate 6 consistent multi-views using Zero123++ and feed them into Step1X for improved 3D reconstruction.

**Why this approach:** Zero123++ is fully cached and provides true multi-view information (6 angles around the subject) rather than inferring 3D from a single depth map. Step1X's main limitation was single-view input causing poor geometry. Multi-view input directly addresses this. The trade-off is that Zero123++ is generative — it may alter character details in generated views — and Step1X texture generation still drifts. But if MoGe proves insufficient, this is the next-best cached option.

- Write `vlm/scripts/generate/generate_local_zero123plus_views.py`
- Load Zero123++ v1.2 from HF cache (`models--sudo-ai--zero123plus-v1.2`)
- Generate 6 views of char_001 (front, 60°, 120°, 180°, 240°, 300°)
- Review generated views for identity consistency (do all 6 look like the same character?)
- Feed 6 views into Step1X-3D Geometry pipeline (modify `generate_local_step1x3d.py` to accept multi-view input)
- Use source image (not Zero123++ views) as texture reference for Step1X Texture pipeline
- Run Qwen-VL review on rendered output

**Files:** `vlm/scripts/generate/generate_local_zero123plus_views.py` (CREATE), modify `generate_local_step1x3d.py` (multi-view input support)
**Validates with:** Visual check of 6 Zero123++ views for identity consistency; Qwen-VL review of final output
**Rollback:** If Zero123++ views have identity drift → this route is a dead end for fidelity requirements. Return to Phase 5 (IC-Light enhancement) or request download approval for TRELLIS.

### Phase 5: IC-Light relighting enhancement (ENHANCEMENT)

**Goal:** If non-generative PBR with MoGe normals still looks insufficiently 3D, integrate IC-Light for learned relighting while using strong identity constraints to minimize detail alteration.

**Why this approach:** IC-Light (1.7 GB, fully cached) is specifically designed for realistic image relighting. Unlike the hand-crafted Phong shader, it has learned what "3D lighting" looks like from real data. The risk is that it's generative and may alter source details. Mitigation: run at very low denoising strength (0.15-0.25) with the source as img2img base, and use the MoGe normal map as conditioning input.

- Write `vlm/scripts/generate/relight_local_iclight.py`
- Load IC-Light sd15 from `/home/intern/ssr/IC-Light/models/iclight_sd15_fbc.safetensors`
- Use source image as img2img base at low denoise (0.15-0.25)
- Use MoGe normal map as lighting condition
- Run on GPU 2 (24 GB sufficient for sd15)
- Output: `char_001_iclight_relit.png`
- Run Qwen-VL review

**Files:** `vlm/scripts/generate/relight_local_iclight.py` (CREATE)
**Validates with:** Qwen-VL review; target: three_dimensional=true. Acceptable identity_match ≥ 0.85 (lower bar because IC-Light is generative — some detail change is expected)
**Rollback:** If identity drops below 0.85 → IC-Light is too destructive for anime content. Mark as explored-but-failed. If successful → consider combining with Phase 2 PBR output as input (PBR pre-shading + IC-Light polish).

## Dependencies & Order

- **Phase 1 must complete first** — all other phases depend on knowing whether MoGe produces usable anime depth/normals
- **Phases 2 and 3 can be planned in parallel** after Phase 1 confirms MoGe quality — Phase 2 is the fast path (low effort, quick review), Phase 3 is the thorough path (higher effort, better 3D)
- **Phase 4 is the fallback** — only if MoGe depth quality is poor (Phase 1 failure) OR MoGe-based rendering still looks 2D (Phases 2-3 failure)
- **Phase 5 is the enhancement** — only if non-generative approaches still look insufficiently 3D despite good MoGe geometry
- **Phases 3 and 4 both need Step1X conda environment** — activate it before running: `conda activate` (check env name from Step1X setup)

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| MoGe produces poor depth/normals on anime content (trained on real photos) | Medium — anime has flat shading regions, line art edges that confuse monocular depth | **Phase 1 is the validation gate.** Test within first hour. If depth is noisy/flat, immediately pivot to Phase 4 (Zero123++) or Phase 5 (IC-Light). Do not proceed to Phases 2-3. |
| Depth-to-mesh looks like bas-relief, not 3D (2.5D limitation) | Medium-High — single depth map can't separate clothing layers | Acceptable for front-view render with slight perspective rotation (±8°). The goal is 3D *appearance*, not full 3D asset. If even slight rotation reveals flat geometry, fall back to Phase 2 (pure PBR) and enhance with Phase 5 (IC-Light). |
| GPU 2 (RTX 3090, 24 GB) OOM during MoGe inference or mesh rendering | Low — MoGe v2 is 1.3 GB, mesh from 408×780 depth is small | Monitor with nvidia-smi during inference. If OOM, fall back to CPU inference for MoGe (slower but works). Mesh rendering is lightweight (CPU-only with trimesh/pymeshlab). |
| Step1X conda environment missing or broken | Low — packages confirmed installed by prior session inventory | Verify with `conda run -n <env> python -c "import trimesh, open3d, xatlas"` before starting Phase 3. If broken, create minimal venv with only needed packages. |
| Zero123++ alters character identity in generated views | Medium-High — generative multi-view models often drift on specific character designs | Visual inspection of all 6 views before feeding to Step1X. If identity differs between views, abort Phase 4 — inconsistent multi-view input produces worse geometry than single-view. |

## Success Criteria

### Minimum viable success
- [ ] MoGe depth + normal extraction runs on char_001 without OOM or model loading errors (Phase 1)
- [ ] At least one MoGe-based pipeline (PBR, mesh, or IC-Light) produces output that passes Qwen-VL review with identity_match ≥ 0.85 AND three_dimensional=true (Phases 2-5)
- [ ] All generation uses only server-local cached models — zero downloads, zero cloud APIs

### Full success
- [ ] MoGe mesh + source texture projection passes Qwen-VL review with identity_match ≥ 0.95 AND three_dimensional=true (matching or exceeding Codex round 3 quality, but server-local)
- [ ] Multi-view renders from mesh show visible parallax confirming real 3D geometry
- [ ] Pipeline is reproducible: single command from source image → reviewed output

### Stretch
- [ ] Pipeline generalized to accept any sample_id (not hardcoded to char_001)
- [ ] Performance benchmarked: total wall-clock time from source → 3D output

## Quick Start

```bash
# Restore full context
cat '/home/intern/Supervised 2D to 3D/.claude/handoffs/HANDOFF_server-local-3d-approaches_2026-07-23.md'

# Key source files for Phase 1
# 1. Existing DA3 depth script (pattern to follow)
cat '/home/intern/Supervised 2D to 3D/vlm/scripts/generate/prepare_local_da3_depth.py'
# 2. Existing PBR script (understand the rendering target)
cat '/home/intern/Supervised 2D to 3D/vlm/scripts/generate/render_local_depth_pbr.py'
# 3. MoGe model checkpoint
ls -la /home/intern/.cache/huggingface/hub/models--Ruicheng--moge-2-vitl-normal/snapshots/b135031bae30b5ac2ae141a0e68717795ce38340/
# 4. Source image and foreground mask
file '/home/intern/Supervised 2D to 3D/vlm/data/SN_6期动漫数据标注/char_001/char_001.png'
file '/home/intern/Supervised 2D to 3D/vlm/experiments/comfyui_output/front_view_local/char_001/cleaned_white.png' 2>/dev/null
# 5. Review script (understand gate criteria)
cat '/home/intern/Supervised 2D to 3D/vlm/scripts/supervise/review_local_comfyui_output.py'

# Baseline data to reference
ls '/home/intern/Supervised 2D to 3D/vlm/experiments/comfyui_output/front_view_local/char_001/candidates/'*depth*
ls '/home/intern/Supervised 2D to 3D/vlm/experiments/comfyui_output/front_view_local/char_001/candidates/'*review*

# Verify starting state
nvidia-smi
# Confirm GPU 2 is free (should show ~1 MiB used)
# Confirm GPU 1 is still occupied — do NOT use

# First concrete action
# Write vlm/scripts/generate/prepare_local_moge_depth_normal.py:
#   1. Copy argparse pattern from prepare_local_da3_depth.py
#   2. Load MoGe v2 model from HF cache path above
#   3. Run inference on char_001 source with foreground mask
#   4. Output: _moge_depth.png, _moge_normal.png, _moge_depth_raw.npy
#   5. Generate 3-panel comparison: DA3-SMALL | MoGe depth | MoGe normals
```
