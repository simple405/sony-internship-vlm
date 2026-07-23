# Handoff: MoGe PBR fails 3D gate — mesh approach next

**Date:** 2026-07-23
**Status:** IN PROGRESS
**Bead(s):** none
**Epic:** char_001 2D-to-3D conversion with detail fidelity
**Chain:** `standalone-38ec30d8` seq `2`
**Parent:** `HANDOFF_server-local-3d-approaches_2026-07-23.md`
**Prior chain:** `HANDOFF_server-local-3d-approaches_2026-07-23.md` > this

---

## Since Last Handoff

- Parent planned 5 phases. **Phase 1 completed** (MoGe depth/normal extraction works, normals are rich despite flat depth). **Phase 2 completed** (MoGe PBR achieved identity=1.0 but **failed** the three_dimensional gate — planes_remain, same pattern as DA3-SMALL+PBR).
- Parent's key risk ("MoGe may not produce better depth than DA3-SMALL for anime") **partially materialized** — depth IS flat (Δ=0.99 units across entire character), but normals exceeded expectations (79% pixels >10° tilt, 36.7% >20°). The normals are good enough to drive Phong shading; what's insufficient is the 2.5D approach itself, not the normal quality.
- Parent's "Where We're Going" Phase 3 (mesh+texture projection) is now the **highest-priority next step** — it addresses the root cause (2.5D bas-relief vs real 3D rendering) rather than iterating on normal inputs.
- Project directory structure clarified: `/home/intern/Supervised 2D to 3D/` is sparse/wip; real full project is at `/home/intern/jsy/`.
- 58M → 17M experiment directory cleanup completed, all failed intermediates and API audit logs removed.

## Reference Documents

- `CLAUDE.md` — project conventions, installed skills, DeepSeek model switching
- `PLAN_server-local-3d-approaches_2026-07-23.md` — master 5-phase implementation plan
- `HANDOFF_server-local-3d-approaches_2026-07-23.md` — parent session (model inventory, approach analysis)
- `HANDOFF_3D_FIDELITY_PROVENANCE_07_22_16_29.md` — grandparent session (prior approaches, gates established)

## Stale References

- **`step1x` conda env name**: parent handoff says "Step1X conda environment" without an explicit name. Discovered correct name is **`step1xlhl`** at `/home/intern/anaconda3/envs/step1xlhl/`. Contains trimesh, open3d, xatlas. Use `step1xlhl` for Phase 3 mesh work, NOT a generic `step1x` env.

## The Goal

Convert char_001 (408×780 anime character PNG) to a 3D-style front view that passes two simultaneous hard gates: (1) one-to-one source detail fidelity across all 5 annotated elements, and (2) unmistakable 3D appearance. Must use only server-local cached models — no downloads, no cloud APIs, no Codex built-in services. The Codex reference edit round 3 proved both gates CAN be passed (identity=1.0, 3D=true, 5/5 elements), but that approach violates the server-local requirement. The mission is to match or exceed that quality with local models.

## Where We Are

### Infrastructure confirmed
- **Python environment**: `/home/intern/anaconda3/envs/air310/bin/python` (ComfyUI conda env, PyTorch 2.6.0+cu124, has all comfy.ldm.moge modules)
- **MoGe v2 checkpoint**: fully cached at HF hub snapshot `b135031bae...`, 1.3 GB, loads via `MoGeModel(state_dict)` → `.infer()`
- **Ollama**: running (PID 2988661), `qwen36-vl:latest` available, proxy must be unset for localhost access
- **3D toolchain**: conda env **`step1xlhl`** at `/home/intern/anaconda3/envs/step1xlhl/` has trimesh 4.3.2, open3d 0.19.0, xatlas 0.0.10. nvdiffrast and pytorch3d also reported installed per parent inventory but NOT verified in this session. Test before Phase 3: `conda run -n step1xlhl python -c "import trimesh, open3d, xatlas"` ✅ confirmed in this session.
- **GPUs**: GPU 0: ~18 GB used (grew from 0 → 18 GB — new process started between handoffs). GPU 1: 0 MB (still free but plan says avoid). GPU 2: RTX 3090 24 GB, ~1 MB used — our target.

### Scripts created
- [vlm/scripts/generate/prepare_local_moge_depth_normal.py](vlm/scripts/generate/prepare_local_moge_depth_normal.py) — standalone MoGe v2 inference, outputs depth PNG + normal PNG + raw .npy + 3-panel comparison + manifest JSON. Follows DA3 script argparse pattern. Command:
  ```bash
  CUDA_VISIBLE_DEVICES=2 /home/intern/anaconda3/envs/air310/bin/python \
    vlm/scripts/generate/prepare_local_moge_depth_normal.py
  ```
- [vlm/scripts/generate/render_local_moge_pbr.py](vlm/scripts/generate/render_local_moge_pbr.py) — MoGe PBR relighting, replaces DA3+Step1X+78/22 blending with 100% MoGe v2 normals, identical Phong/edge/compositing/upscale to render_local_depth_pbr.py. Pure numpy/Pillow (no GPU). Command:
  ```bash
  python3 vlm/scripts/generate/render_local_moge_pbr.py
  ```

### Phase 1 quality metrics (MoGe v2 on char_001)
| Metric | Value | Assessment |
|--------|-------|------------|
| Raw depth range (metric) | 4.33 – 5.32 (Δ=0.99) | ⚠️ Nearly flat — anime cel-shading confuses depth head |
| Normal coverage | 100% valid, 0% degraded | ✅ No model degradation on anime |
| Mean surface angle from camera | 18.1° | ✅ Sufficient for highlights |
| Pixels with >10° tilt | 79.0% | ✅ Rich surface variation |
| Pixels with >20° tilt | 36.7% | ✅ Will produce specular response |
| Max surface angle | 67.2° | ✅ Silhouette edges well-detected |
| Azimuth distribution std | 107.9° | ✅ Wide directional spread |
| Normal vector norms | mean=1.0001, std=0.0023 | ✅ Perfect unit vectors |
| Sobel edge magnitude X/Y/Z | max 4.89 / 3.33 / 1.90 | ✅ Strong edge response |

### Phase 2 review results (MoGe PBR, Qwen-VL semantic review)
| Gate | Result |
|------|--------|
| front_view | ✅ true |
| single_subject | ✅ true |
| white_background | ✅ true |
| **three_dimensional** | **❌ false** — "画面仍为2D平面插画风格，未呈现3D手办材质与立体光影" |
| no_text_watermark | ✅ true |
| no_red_frame | ✅ true |
| **identity_match** | **1.0** |
| **visual_quality** | **0.95** |
| **elements preserved** | **5/5** (all) |
| **decision** | **FAIL** |

### Experiment directory state (after cleanup)
- 58M → 17M. Retained: da3_depth baseline, reference_edit_round3 (passing target), Step1X round2 meshes+renders, front_view v1/v2 references, prompts, manifests, failure_taxonomy.md. Deleted: all failed SDXL outputs, all PBR PNGs, FLUX output, ref edit rounds 1-2, Step1X round1, texture_intermediates (13MB SDXL textures), all API audit logs, MoGe intermediates, .tmp files.
- Full retained inventory: 26 files across 3 subdirectories.

## What We Tried (Chronological)

### 1. Phase 1: MoGe v2 depth + normal extraction (SUCCESS)
- **Hypothesis**: MoGe v2 produces better depth AND directly-estimated normals for anime characters, replacing both DA3-SMALL depth and Step1X geometry normals.
- **How**: Wrote `prepare_local_moge_depth_normal.py`, loaded MoGe via ComfyUI's `MoGeModel` wrapper from air310 conda env, ran on GPU 2 with resolution_level=9, applied foreground mask (threshold ≥ 32), output inverse-depth PNG + OpenGL normal PNG + raw metric depth .npy.
- **Result**: Depth nearly flat (4.33-5.32, only ~1 unit variation) — confirms plan's risk about anime degradation. But normals are surprisingly rich: 79% pixels >10° tilt, wide azimuth distribution (std 108°), strong Sobel edge response. **Normal head is usable; depth head is not.**
- **Files**: `prepare_local_moge_depth_normal.py`, 5 output files + manifest

### 2. Phase 2: MoGe PBR relighting (FAILED 3D GATE)
- **Hypothesis**: MoGe normals are richer than DA3 gradient normals (which needed 20× `normal_strength` amplification). Using 100% MoGe normals with no blending should produce more convincing Phong shading, passing the 3D gate.
- **How**: Wrote `render_local_moge_pbr.py` — loaded MoGe normals from Phase 1 PNG, converted [0,255] → [-1,1] unit vectors, applied identical Phong lighting (key=(-0.42,-0.48,0.77), specular exponent=42, rim power=1.7), same material estimation, same inner_edge shadow (Gaussian blur radius 7→11), same compositing (shadow offset (5,7), Gaussian blur 9, 2× upscale + sharpen 1.12). No depth used — pure normal-driven shading.
- **Result**: identity_match=1.0, visual_quality=0.95, all 5 elements preserved. **three_dimensional=false.** "画面仍为2D平面插画风格" — same failure mode as DA3-SMALL+PBR. The 2.5D Phong approach is the bottleneck, not the normal inputs.
- **Key takeaway**: Even strong normals can't make a flat 2D image look 3D. Need real geometry with perspective projection.
- **Files**: `render_local_moge_pbr.py`, `char_001_moge_pbr.png` + review JSONs

### 3. Proxy issue discovered during Ollama review
- **Problem**: curl to 127.0.0.1:11434 was routed through corporate proxy (137.153.170.55:10080), returning 403.
- **Fix**: The review script (`review_local_comfyui_output.py`) handles this — it unsets all proxy env vars before calling Ollama. Running with `unset http_proxy https_proxy... && python3 review_local_comfyui_output.py ...` worked correctly.

### 4. Experiment directory cleanup
- **What**: User requested deletion of all non-reusable experiment outputs from `/home/intern/jsy/vlm/experiments/`.
- **Kept** (with rationale): DA3 depth baseline (future comparison), reference_edit_round3 (quality target, only passing candidate), Step1X round2 meshes+renders (reusable 3D assets), front_view v1/v2 (style references), manifests (generation parameter records), prompts, failure_taxonomy.md.
- **Deleted**: All SDXL outputs (v1-v3, two-pass), all PBR PNGs (rounds 1-3), FLUX output, ref edit rounds 1-2, Step1X round1 (superseded), texture_intermediates (13MB SDXL-generated textures), all `*_raw.txt` / `*_request.json` audit logs, MoGe intermediates, .tmp file, `__pycache__/` directories. 58M → 17M.

### 5. Project directory location discovered
- **Problem**: Initial script writes targeted `/home/intern/Supervised 2D to 3D/`, but this directory was sparse (only `vlm/scripts/generate/`) and NOT a git repo.
- **Discovery**: `find` revealed the actual full project at `/home/intern/jsy/` — complete git repo with all data, experiments, scripts, .venv, and .claude/handoffs.
- **Resolution**: All subsequent work uses `/home/intern/jsy/` as canonical project root. The `Supervised 2D to 3D/` directory is a sparsely-populated wip directory — the files written there also exist in jsy. Both copies are untracked in their respective locations.

## Key Decisions

- **Two-phase execution strategy**: Run Phase 1 (extraction) → Phase 2 (PBR) in immediate sequence. Phase 2 was the fast-path validation; its failure confirms Phase 3 (mesh) is the correct next investment.
- **GPU 2 for all GPU work**: Consistent with plan. GPU 0 has ~18 GB used by other processes; GPU 1 was explicitly flagged "do not use". GPU 2 (RTX 3090 24 GB) handled MoGe comfortably (1.3 GB model, 408×780 image).
- **PBR is pure CPU**: After MoGe extraction, PBR rendering needs no GPU — only numpy + Pillow. Run with system python3, not air310.
- **Source image split**: MoGe inference uses original `char_001.png` (408×780 RGB); PBR compositing uses `cleaned_white.png` (white background, needed for shadow compositing). Both paths proven to work.
- **All outputs written to candidates/ under project root**: Both scripts follow the DA3 pattern of writing to `vlm/experiments/comfyui_output/front_view_local/char_001/candidates/` with atomic I/O.
- **No normal_strength parameter**: MoGe normals are naturally unit-length and correctly oriented — the 20× amplification hack needed for DA3 gradient normals is unnecessary. Removing it simplified the pipeline without quality loss.
- **100% MoGe normals, no blending**: Unlike the original PBR which blended 78% Step1X geometry normals + 22% DA3 gradient normals, MoGe normals are used at full strength. The failure is geometric (2.5D), not normal-quality.
- **No downloads triggered**: Both phases used only fully-cached HF snapshots (MoGe v2, DINOv2 backbone) and existing conda environments. HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1 enforced.
- **Cleanup was aggressive but justified**: Every deleted file was either (a) a failed output that will never be reused, (b) an intermediate superseded by a later round, (c) an API audit log with zero future value, or (d) a Python bytecode cache.

## Evidence & Data

### Phase 1 raw MoGe output statistics
```
Raw depth (foreground): min=4.3344  median=4.7235  max=5.2901  mean=4.7500
Inverse depth percentiles: p02=0.194925, p98=0.228755
Normal coverage (foreground with valid normals): 100.0%
Degraded normal regions: 0.0% of foreground
```

### Phase 1 normal vector analysis
```
Normal vector norms: mean=1.0001, std=0.0023, min=0.9937
X (right): mean=-0.0090, std=0.2867
Y (up):    mean=0.0240, std=0.2097
Z (out):   mean=0.9304, std=0.0872
Angle from forward: mean=18.1°, max=67.2°, std=12.0°
Pixels with >10° tilt: 79.0%
Pixels with >20° tilt: 36.7%
Theta (azimuth): mean=16.3°, std=107.9°
Sobel mag X: mean=0.2258, max=4.8863
Sobel mag Y: mean=0.1157, max=3.3333
Sobel mag Z: mean=0.0650, max=1.8980
```

### char_001 annotation elements (the 5 items that define "fidelity")
These are the ground truth from `vlm/data/SN_6期动漫数据标注/char_001/char_001.json`. Any generated output must preserve ALL 5:
1. **金色长发与黑色蝴蝶结** (golden hair + black bow) — head region
2. **红色眼睛** (red eyes) — face region
3. **白色衬衫与蓝色宝石领饰** (white shirt + blue gem collar ornament) — upper torso
4. **黑色短裙与腰带** (black skirt + gray waist bands) — exactly TWO horizontal gray bands
5. **白色外套** (white coat/jacket) — outer layer with narrow white placket edging

Semantic review clarification (from parent handoff, enabled round 3 pass): waist detail = exactly two gray horizontal bands; placket = narrow white edging visible on source.

### Phase 2 Qwen-VL review (full semantic review JSON)
```json
{
  "gates": {
    "front_view": true,
    "single_subject": true,
    "white_background": true,
    "three_dimensional": false,
    "no_text_watermark": true,
    "no_red_frame": true
  },
  "elements": [
    {"name": "金色长发与黑色蝴蝶结", "status": "preserved"},
    {"name": "红色眼睛", "status": "preserved"},
    {"name": "白色衬衫与蓝色宝石领饰", "status": "preserved"},
    {"name": "黑色短裙与腰带", "status": "preserved"},
    {"name": "白色外套", "status": "preserved"}
  ],
  "identity_match": 1.0,
  "visual_quality": 0.95,
  "decision": "fail",
  "summary_cn": "生成图准确还原了原图的所有关键视觉元素...但画面仍为2D平面插画风格，未呈现3D手办材质与立体光影。"
}
```

### Approach comparison (updated with Phase 2 results)
| Approach | 3D Quality | Detail Fidelity | Server-Local | Generative |
|----------|-----------|-----------------|--------------|------------|
| SDXL+IP-Adapter+ControlNet | Low (2D) | Medium (0.75-0.85) | ✅ | Yes |
| FLUX Depth+Redux | Low (2D) | Low | ✅ | Yes |
| Step1X-3D | **High (real 3D)** | Low | ✅ | Yes |
| DA3-SMALL+PBR | Low (flat) | **Perfect (1.0)** | ✅ | No |
| MoGe+PBR (Phase 2) | Low (flat) | **Perfect (1.0)** | ✅ | No |
| Codex ref edit | **High** | **Perfect (1.0)** | ❌ | Yes |
| **MoGe mesh+texture (Phase 3)** | **High (predicted)** | **Perfect (1.0, predicted)** | ✅ | No |

### Experiment cleanup: retained file inventory
```
candidates/
├── char_001_da3_depth.png + .json          — DA3-SMALL depth baseline
├── char_001_depth_pbr_round3.json          — best PBR settings record
├── char_001_flux_depth_redux_round1.json   — FLUX failure mode record
├── char_001_reference_edit_3d_round3.png   — PASSING target (Codex, not local)
├── char_001_reference_edit_3d_round3_prompt.txt
├── char_001_reference_edit_3d_round3_review.json + _semantic.json
├── char_001_step1x3d_round2/
│   ├── char_001_geometry.glb + textured.glb  — reusable 3D meshes
│   ├── char_001_transparent_input.png
│   ├── geometry_renders/normal_000-003.png   — 4-view geometry
│   ├── textured_renders/render_000-003.png   — 4-view textured
│   └── manifest.json
front_view/char_001/
├── char_001_front_view_3d_v1.png + v2.png  — reusable style references
├── edit_prompt_v2.txt + generation_prompt_v1.txt
supervision/failure_taxonomy.md
README.md
```

## Code Analysis

### `prepare_local_moge_depth_normal.py` (236 lines)
- Signature: `parse_args()` → `load_moge_model(checkpoint, gpu=2)` → `run_moge_inference(model, source, resolution_level=9)` → `process_depth(depth, foreground)` → `process_normal(normal, foreground)` → `atomic_png()` / `atomic_npy()` / `atomic_json()`
- Key imports: `comfy.ldm.moge.model.MoGeModel` via `sys.path.insert(0, '/home/intern/wmy/ComfyUI')`
- MoGe loading: `torch.load(checkpoint_path, map_location='cpu')` → `MoGeModel(state_dict)` — dispatches v1/v2 internally
- Inference: `model.infer(image_tensor, resolution_level=9, fov_x=None, force_projection=False, apply_mask=False, apply_metric_scale=True)` → dict with `points`, `depth`, `intrinsics`, `mask`, `normal`
- Normal convention: MoGe OpenCV (Z+ into scene) → OpenGL (Y up, Z out of surface) via Y-negate + Z-negate
- Depth convention: same as DA3 script — inverse depth, 2%-98% percentile clipping
- Foreground mask: threshold ≥ 32 (same as DA3)

### `render_local_moge_pbr.py` (222 lines)
- Signature: `parse_args()` → `load_moge_normals(path, target_size)` → `main()` with Phong/composite/upscale pipeline
- Normal loading: PNG [0,255] → [-1,1] → re-normalize (resampling correction)
- Key removal: no `height_field`, no `gradient_normals`, no `normal_strength`, no 78/22 blending, no Step1X alignment
- Lighting: key=(-0.42,-0.48,0.77), view=(0,0,1), half=normalize(L+V), diffuse=dot(N,L), specular=dot(N,H)^42, rim=(1-Nz)^1.7
- Shade: `np.clip(0.38 + 0.78*diffuse - 0.22*inner_edge, 0.30, 1.18)` → GaussianBlur(11) → `0.90*smoothed + 0.10*raw`
- Material: `glossy = clip(0.16 + 0.42*saturation + 0.20*bright_material, 0.0, 0.62)`
- Compositing: linear(γ=2.2) → shade → specular+rim highlight (blur 3, warm tint 1.0/0.96/0.90) → γ^-1(2.2) → mask composite → shadow offset(5,7) blur(9) 10% opacity → 2× upscale Lanczos → sharpen 1.12
- Source pixel policy: `no_generative_repaint` — all output pixels from source; shading changes only

### `review_local_comfyui_output.py` (299 lines, at /home/intern/jsy/)
- Uses `/api/chat` endpoint (not `/api/generate`) with `format="json"`, `temperature=0`, `keep_alive=0`, `think=False`
- Semantic prompt includes waist/placket clarifications from prior handoff
- Extracts JSON from fenced or raw response via `extract_json()`
- Gate check: ALL 6 gates true + ALL elements preserved + identity_match ≥ 0.85
- `keep_alive: 0` — Ollama unloads model after review to free GPU memory
- MUST unset HTTP_PROXY/HTTPS_PROXY before calling (corporate proxy intercepts localhost)

## Files Changed

### Created (all untracked)
- `vlm/scripts/generate/prepare_local_moge_depth_normal.py` — Phase 1 MoGe extraction script (also in `/home/intern/Supervised 2D to 3D/`)
- `vlm/scripts/generate/render_local_moge_pbr.py` — Phase 2 MoGe PBR script (also in `/home/intern/Supervised 2D to 3D/`)

### Experiment outputs (untracked, partially cleaned)
- `vlm/experiments/comfyui_output/front_view_local/char_001/candidates/char_001_moge_pbr.png` — Phase 2 PBR output
- `vlm/experiments/comfyui_output/front_view_local/char_001/candidates/char_001_moge_pbr.json` — PBR manifest
- `vlm/experiments/comfyui_output/front_view_local/char_001/candidates/char_001_moge_pbr_review_semantic` — review result

### Deleted (experiment directory cleanup)
- All SDXL outputs (char_001/comfyui_output, front_view_local SDXL PNGs, SDXL rounds 1-3)
- All PBR PNGs (rounds 1-3), FLUX PNG, ref edit rounds 1-2 PNGs
- Step1X round1 (entire directory), Step1X round2 texture_intermediates (entire directory)
- All `*_raw.txt`, `*_request.json` audit logs
- MoGe Phase 1 intermediate outputs (depth PNG, normal PNG, raw .npy, comparison)
- `__pycache__/` directories across `/home/intern/jsy/`
- `.tmp.npy` stale atomic write

## User Feedback & Preferences

- **"生图只能使用服务器上部署的模型进行本地开发"** — server-local ONLY. No cloud APIs, no Codex services. This is the driving constraint.
- **"不要干扰其他人的进程"** — explicitly avoid GPU 1 and other users' processes. GPU discipline is expected.
- **"把失败的产出物全部删除掉，只保留一份输出结果供我进行查看"** — delete failed outputs, keep only the final result for inspection.
- **"你要保留哪些图片给出你的理由"** — explain retention rationale for every kept file. User wants to understand decisions, not just see results.
- **"整理一下/home/intern/jsy这个路径下的工作目录，删除临时文件"** — clean up the jsy project directory, remove temp files (executed: __pycache__, .pyc, .tmp all removed).
- **"继续完成下一步"** — user wants pipeline execution, not deliberation. Just build and run.
- **User wants to see the PBR output themselves** — kept `char_001_moge_pbr.png` + review for their visual inspection before Phase 3.

## Where We're Going

1. **Phase 3: Depth-to-mesh + source texture projection** (NEXT — highest priority). The root cause of Phase 2 failure is that 2.5D Phong shading on a flat image can't produce convincing 3D. Build a real 3D mesh from MoGe raw depth (.npy), UV-unwrap with xatlas, project source image as albedo texture, render with perspective projection from 3 viewpoints (±8°). This is the novel approach: real 3D geometry + zero generative detail loss. Expected identity_match ≈ 1.0 (texture IS the source) and three_dimensional=true (real perspective rendering with parallax).
2. **Phase 5: IC-Light relighting** (ENHANCEMENT — if mesh approach still insufficient). IC-Light (1.7 GB, cached at `/home/intern/ssr/IC-Light/models/iclight_sd15_fbc.safetensors`) provides learned real-image relighting. Run at very low denoise (0.15-0.25) with source as img2img base and MoGe normal as condition. Trade-off: generative (may alter details). Bar: identity_match ≥ 0.85.
3. **Phase 4: Zero123++ multi-view → Step1X enhanced geometry** (FALLBACK — if both MoGe approaches fail). Zero123++ v1.2 is fully cached and generates 6 consistent multi-views. Feed into Step1X for improved geometry reconstruction. Risk: Zero123++ is generative and may drift character identity.
4. **Return to Phase 2 with IC-Light enhancement** if Phase 3 mesh quality matches Step1X but 3D gate still marginal — combine PBR pre-shading with IC-Light polish at even lower denoise.

## Risks & Blockers

- **MoGe depth flatness may produce bas-relief mesh** — with only ~1 unit depth variation, the mesh will have minimal 3D volume. Phase 3 needs to either amplify depth contrast or accept mild 3D effect. The ±8° perspective rotation may reveal flat geometry.
- **xatlas UV unwrapping may produce visible seams** — texture seams at mesh boundaries could break the "perfect fidelity" advantage. Fall back to screen-space projection if atlas approach fails.
- **Step1X conda env not tested for Phase 3** — the plan says packages are installed but this session only used air310 env. Verify `conda run -n <env> python -c "import trimesh, open3d, xatlas"` before starting Phase 3.
- **GPU discipline** — GPU 0 usage has grown (was 0 MiB per parent handoff, now ~18 GB). Someone started work there. GPU 2 remains free for our use.

## Open Questions

- [ ] Does MoGe's flat depth (Δ=0.99 units) produce a convincing 3D mesh, or will it look like a slightly-displaced plane?
- [ ] Which conda env has Step1X's 3D toolchain (trimesh, open3d, xatlas, nvdiffrast)? The handoff says "Step1X conda env" but doesn't name it explicitly.
- [ ] Should Phase 3 render from perspective (±8°) or orthographic projection? Perspective creates parallax (good for 3D) but may distort the character; orthographic preserves proportions but loses depth cues.
- [ ] Is the user willing to accept IC-Light generative risk (identity ≥ 0.85) if non-generative mesh fails the 3D gate?

## Quick Start for Next Session

```bash
# Restore context
cat '/home/intern/jsy/.claude/handoffs/HANDOFF_server-local-3d-approaches_2026-07-23_seq2.md'
cat '/home/intern/jsy/.claude/handoffs/PLAN_server-local-3d-approaches_2026-07-23.md'

# Verify GPU state
nvidia-smi --query-gpu=index,name,memory.used --format=csv,noheader

# Verify 3D toolchain (find Step1X conda env first)
conda env list | grep -i step
# Then: conda run -n <env> python -c "import trimesh, open3d, xatlas; print('3D toolchain OK')"

# Key source files
# PBR script (Phase 2 — reference for rendering pipeline)
cat '/home/intern/jsy/vlm/scripts/generate/render_local_moge_pbr.py'
# MoGe extraction (rerun if depth files needed for mesh)
cat '/home/intern/jsy/vlm/scripts/generate/prepare_local_moge_depth_normal.py'
# Step1X mesh example (format reference for Phase 3 output)
file '/home/intern/jsy/vlm/experiments/comfyui_output/front_view_local/char_001/candidates/char_001_step1x3d_round2/char_001_geometry.glb'

# Phase 2 output for visual inspection
file '/home/intern/jsy/vlm/experiments/comfyui_output/front_view_local/char_001/candidates/char_001_moge_pbr.png'
cat '/home/intern/jsy/vlm/experiments/comfyui_output/front_view_local/char_001/candidates/char_001_moge_pbr_review_semantic'

# Phase 3 first action
# Write vlm/scripts/generate/generate_local_moge_mesh.py:
#   1. Load char_001_moge_depth_raw.npy (rerun Phase 1 if needed)
#   2. Create triangle mesh via depth displacement
#   3. UV-unwrap with xatlas
#   4. Project source as albedo texture
#   5. Render from 3 viewpoints with nvdiffrast or trimesh
```
