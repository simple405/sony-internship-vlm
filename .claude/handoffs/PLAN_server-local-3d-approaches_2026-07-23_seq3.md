# Plan: IC-Light relighting to break the 3D gate bottleneck

**Date:** 2026-07-23
**Status:** PLANNED
**Bead(s):** none
**Epic:** char_001 2D-to-3D conversion with detail fidelity
**Chain:** `standalone-38ec30d8` seq `3`
**Context:** See `HANDOFF_server-local-3d-approaches_2026-07-23_seq3.md` for session data, Phase 3 results, and review iterations.

---

## Problem Statement

char_001's 2D-to-3D conversion must pass two simultaneous gates: (1) identity_match ≥ 0.85 and all 5 annotated elements preserved, and (2) `three_dimensional=true`. After three phases of server-local experimentation, we have a clear pattern: **100% non-generative approaches (MoGe PBR, MoGe mesh+Phong) consistently achieve identity=1.0 with 5/5 elements preserved, but fail `three_dimensional`**. The only passing candidate (Codex reference edit round 3) uses generative AI — suggesting some level of learned relighting/repainting is required to convince Qwen-VL of 3D appearance. Phase 5 (IC-Light) is the best remaining server-local option: it's fully cached at `/home/intern/ssr/IC-Light/` and uses a diffusion model fine-tuned specifically for realistic image relighting. The challenge is running it at low enough denoising strength (0.10-0.25) to preserve character identity while introducing convincing 3D lighting.

See "Evidence & Data" and "What We Tried" in `HANDOFF_server-local-3d-approaches_2026-07-23_seq3.md`.

## Key Findings

- **Non-generative Phong cannot pass `three_dimensional`** — proven across 4 review rounds with mesh normals, MoGe normals, different depth amplifications, and both PBR and mesh-based rendering. All achieve identity=1.0 but `three_dimensional=false`. → drives Phase 1 (generative approach needed)
- **MoGe normals are superior to mesh geometry normals** — MoGe v2 predicted normals pass watermark/frame gates cleanly; mesh normals from amplified depth create noisy shading that Qwen misinterprets. → drives Phase 1 (use MoGe normals as IC-Light condition)
- **Inverse mapping is the correct parallax approach** — forward mapping creates unfilled holes; inverse mapping (dest→source) is clean and fast. → reference for any future multi-view rendering
- **Open3D EGL rendering is unreliable on this server** — segfault on second OffscreenRenderer creation. All future rendering should use numpy-based approaches or trimesh. → anti-goal
- **IC-Light sd15 is fully cached server-local** — model file at `/home/intern/ssr/IC-Light/models/iclight_sd15_fbc.safetensors` (1.7 GB). No download needed. → unblocks Phase 1
- **Depth amplification at factor=0.35, gamma=0.4** gives max displacement of 143px (35% of character width) with visible parallax (40% pixel difference between ±12° views). → reference for any mesh-based work
- **Image dimension mismatch is a recurring bug** — `cleaned_white.png` (776×405) ≠ MoGe depth (780×408). All scripts must resize to match depth dimensions. → gotcha for IC-Light input prep
- **Corporate proxy blocks localhost** — `http_proxy` routes through 137.153.170.55:10080. MUST unset proxy vars before Ollama calls. → gotcha for review

## Anti-Goals (What NOT To Do)

- **Do NOT try Open3D filament rendering again** — it segfaults on multi-view. Use numpy/trimesh approaches.
- **Do NOT iterate further on non-generative Phong shading** — four rounds of review across two phases (PBR and mesh) confirm it cannot pass `three_dimensional` for anime characters with Qwen-VL.
- **Do NOT download new models** — IC-Light, Zero123++, and all dependencies are already cached. If a model isn't cached, discuss with user before downloading.
- **Do NOT use GPU 1** — it's reserved for other users' processes. GPU 2 (RTX 3090, 24 GB) is our target.
- **Do NOT use the Codex reference edit as a fallback** — it violates the server-local-only constraint. The goal is to match its quality with local models.

## Plan

### Phase 1: IC-Light relighting at conservative denoise

**Goal:** Run IC-Light sd15 on char_001 with MoGe normal conditioning at denoise=0.20, producing a relit image that passes Qwen-VL review with identity ≥ 0.85 and three_dimensional=true.

**Why this approach:** IC-Light is the only server-local model designed specifically for image relighting. Unlike our hand-crafted Phong shader, it has learned what "3D lighting" looks like from real data. Running at low denoise (0.20) preserves most source detail while adjusting lighting. This is the best remaining option before accepting that server-local non-generative approaches cannot pass the 3D gate.

- Write `vlm/scripts/generate/relight_local_iclight.py` following the project's argparse+atomic I/O pattern
- Check `/home/intern/ssr/IC-Light/` for example scripts — IC-Light repos typically include a `demo.py` or `gradio_app.py` that shows the loading pattern
- Load IC-Light sd15 model from `/home/intern/ssr/IC-Light/models/iclight_sd15_fbc.safetensors` using diffusers
- Accept CLI args: `--source` (cleaned_white.png), `--normal` (MoGe normal map), `--denoise` (default 0.20), `--output-dir`
- Resize source and normal to match (must handle the 776×405 vs 780×408 mismatch — resize both to 512×992 for sd15 compatibility)
- Run img2img with source as base image, MoGe normal as lighting condition, denoise=0.20
- Save output as `char_001_iclight_relit.png` to candidates dir
- Run Qwen-VL review with `--generated-image` pointing to output
- If identity < 0.85: re-run at denoise=0.15, then 0.10
- If three_dimensional=false: re-run at denoise=0.25, then 0.30 (accepting identity risk)

**Files:** `vlm/scripts/generate/relight_local_iclight.py` (CREATE)
**Validates with:** Qwen-VL review; target: three_dimensional=true AND identity_match ≥ 0.85 AND 5/5 elements preserved
**Rollback:** Script is standalone — if IC-Light fails at all denoise levels, delete outputs and proceed to Phase 2

### Phase 2: PBR pre-shading + IC-Light hybrid

**Goal:** If pure IC-Light at denoise=0.20 passes 3D but drops identity below 0.85, use the Phase 3 Phong-shaded front render as img2img input at denoise=0.10 to reduce generative change.

**Why this approach:** The PBR/Phong pre-shading already applies directional lighting that suggests 3D form. IC-Light at even lower denoise (0.10) only needs to "polish" this into convincing 3D appearance rather than invent lighting from scratch. Less generative work = less identity drift.

- Modify `relight_local_iclight.py` to accept `--pre-shaded` argument (path to Phase 3 front render)
- Use Phong-shaded render (`char_001_moge_mesh_render_front_moge_normals.png`) as img2img base
- Keep MoGe normal as lighting condition
- Run at denoise=0.10 (very conservative — only subtle lighting enhancement)
- If identity ≥ 0.85 but 3D still false: increase to denoise=0.15
- Run Qwen-VL review

**Files:** `vlm/scripts/generate/relight_local_iclight.py` (MODIFY — add `--pre-shaded` arg)
**Validates with:** Qwen-VL review; target: three_dimensional=true AND identity_match ≥ 0.85
**Rollback:** If hybrid also fails, this confirms even learned relighting can't make anime look 3D without significant repainting

### Phase 3: Accept limitation, document finding

**Goal:** If both Phase 1 and Phase 2 fail to pass `three_dimensional` at identity ≥ 0.85, document the conclusive evidence that server-local approaches cannot match the Codex reference edit quality for this task.

**Why this is necessary:** We now have 6+ review rounds across 3 distinct approaches (MoGe PBR, MoGe mesh+Phong, IC-Light) all failing the 3D gate while preserving identity. This is a statistically meaningful result, not a single-point failure. The user needs to decide: accept non-3D output with perfect fidelity, or pursue cloud API approval for Codex-level quality.

- Write a brief summary document or handoff addendum: `vlm/experiments/comfyui_output/front_view_local/char_001/candidates/supervision/approach_summary.md`
- Table comparing all approaches: approach name, 3D gate, identity_match, visual_quality, elements preserved, generative (yes/no), server-local (yes/no)
- Include the key conclusion: "Only generative approaches (Codex reference edit) pass both gates. Server-local non-generative approaches achieve perfect fidelity but fail 3D."
- Present findings to user with clear recommendation: either accept non-generative quality ceiling or authorize cloud API for Codex approach

**Files:** `vlm/experiments/comfyui_output/front_view_local/char_001/candidates/supervision/approach_summary.md` (CREATE)
**Validates with:** User feedback on next direction
**Rollback:** N/A — this is documentation, not code

## Dependencies & Order

- **Phase 1 must complete before Phase 2** — you need to know IC-Light's baseline denoise vs identity trade-off before deciding if hybrid is needed
- **Phase 2 is conditional** — only if Phase 1 passes 3D but drops identity below 0.85
- **Phase 3 is conditional** — only if both Phase 1 and Phase 2 fail OR if Phase 1 fails at all denoise levels
- Phases 1 and 2 can share the same script (`relight_local_iclight.py`); write the full version with all options in Phase 1

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| IC-Light requires packages not in air310/step1xlhl envs | Medium — IC-Light may need diffusers, controlnet_aux, or specific transformers version | Check `/home/intern/ssr/IC-Light/requirements.txt` or `environment.yml` first. Install missing packages with `pip install --no-deps` in the conda env |
| IC-Light at denoise=0.20 still fails `three_dimensional` | Medium-High — even learned relighting may not be enough for anime flat colors | Phase 2 (hybrid with pre-shading) or increase denoise to 0.30. If still fails at 0.30, Phase 3 (accept limitation) |
| IC-Light alters character identity at any denoise > 0.10 | Medium — diffusion models can change fine details even at low denoise | Phase 2 at denoise=0.10 with pre-shaded input. If identity still drops, this approach is a dead end — generative and non-generative both fail |
| GPU 2 OOM during IC-Light inference | Low — sd15 is ~2 GB, RTX 3090 has 24 GB. Input image 512×992 | Monitor with nvidia-smi. If OOM, try CPU offload or sequential attention slicing |
| IC-Light model loading fails (wrong format, missing config) | Medium — safetensors file exists but may need specific pipeline config | Read IC-Light source code at `/home/intern/ssr/IC-Light/` for the correct loading pattern. May need to construct pipeline manually from components |

## Success Criteria

### Minimum viable success
- [ ] IC-Light script runs without model loading errors or OOM
- [ ] At least one denoise level (0.10, 0.15, 0.20, 0.25, 0.30) produces identity ≥ 0.85 with three_dimensional=true
- [ ] All generation uses only server-local cached models — zero downloads, zero cloud APIs

### Full success
- [ ] IC-Light at denoise ≤ 0.20 passes Qwen-VL review with identity ≥ 0.90 AND three_dimensional=true
- [ ] Output matches or exceeds the visual quality of the Codex reference edit round 3
- [ ] Pipeline is reproducible: single command from source → IC-Light → reviewed output

### Failure documentation
- [ ] If all denoise levels fail: approach_summary.md written with conclusive evidence
- [ ] User informed of the server-local quality ceiling with clear recommendation

## Quick Start

```bash
# Restore full context
cat '/home/intern/jsy/.claude/handoffs/HANDOFF_server-local-3d-approaches_2026-07-23_seq3.md'
cat '/home/intern/jsy/.claude/handoffs/PLAN_server-local-3d-approaches_2026-07-23.md'

# Check GPU state
nvidia-smi --query-gpu=index,name,memory.used --format=csv,noheader

# Verify IC-Light model exists and explore the repo
ls -lh /home/intern/ssr/IC-Light/models/iclight_sd15_fbc.safetensors
ls /home/intern/ssr/IC-Light/
find /home/intern/ssr/IC-Light/ -name "*.py" | head -20

# Key source files for Phase 1
# Existing Phase 3 renderer (reference for normal loading pattern)
cat '/home/intern/jsy/vlm/scripts/generate/generate_local_moge_mesh.py'
# Existing PBR script (reference for Phong constants to match)
cat '/home/intern/jsy/vlm/scripts/generate/render_local_moge_pbr.py'
# Review script (understand gate criteria)
cat '/home/intern/jsy/vlm/scripts/supervise/review_local_comfyui_output.py'

# Inputs needed for IC-Light
# Source image (cleaned white bg)
file '/home/intern/wmy/ComfyUI/input/local_pipeline/char_001/cleaned_white.png'
# MoGe normal map for lighting condition
file '/home/intern/jsy/vlm/experiments/comfyui_output/front_view_local/char_001/candidates/char_001_moge_normal.png'
# Pre-shaded render (for Phase 2 hybrid, if needed)
file '/home/intern/jsy/vlm/experiments/comfyui_output/front_view_local/char_001/candidates/char_001_moge_mesh/char_001_moge_mesh_render_front_moge_normals.png'

# Verify Ollama is running for review
curl -s http://127.0.0.1:11434/api/tags 2>&1 | head -5 || echo "Ollama not running!"

# First concrete action
# Explore /home/intern/ssr/IC-Light/ for example scripts and understand the loading pattern.
# Then write vlm/scripts/generate/relight_local_iclight.py:
#   1. Load iclight_sd15_fbc.safetensors
#   2. Resize source+normal to 512×992
#   3. Run img2img at denoise=0.20 with MoGe normal as condition
#   4. Save output + manifest
#   5. Run Qwen-VL review (remember: unset http_proxy https_proxy!)
```
