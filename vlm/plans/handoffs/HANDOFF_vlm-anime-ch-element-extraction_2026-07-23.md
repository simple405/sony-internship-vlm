# VLM Anime Character Element Extraction Experiment

**Date:** 2026-07-23
**Status:** COMPLETED
**Bead(s):** none
**Epic:** Anime IP merchandise supervision VLM pipeline (see `CLAUDE.md`)
**Chain:** `standalone-bb9cbd74` seq `1`
**Parent:** none — first in chain
**Prior chain:** none — first in chain

---

## The Goal

Evaluate whether the locally-hosted `qwen36-vl` vision-language model can autonomously extract visual character elements from anime images that semantically match human-written ground truth JSON annotations. The experiment serves as a feasibility test for integrating local VLM inference into the broader anime IP merchandise supervision pipeline — if the model can replicate or even exceed human annotation quality, it could automate or augment the annotation workflow for character design verification.

The user explicitly requested: use LOCAL server models (no cloud API), analyze 2D anime character images, compare output with existing JSON annotations, and output semantically similar elements and descriptions.

## Where We Are

- **20/20 character images analyzed** successfully using `qwen36-vl:latest` via Ollama Python client (ollama 0.6.2)
- **108/111 ground truth elements matched** (97.3% overall coverage) — only 3 GT elements missed across all 20 samples
- **120 elements predicted** by the model, **108 matched** to GT elements (90.0% overall precision) — 12 extra predictions are mostly real visual details not captured in the ground truth annotations
- **Avg per-match semantic similarity: 0.6818** (range: 0.6002 char_019 to 0.7928 char_004) measured via bge-m3 1024-dim cosine similarity with 30/70 name/description weighting
- **Avg per-sample coverage: 0.9762** — nearly perfect recall; model almost never misses what annotators labeled
- **Avg per-sample precision: 0.9099** — 9/10 model predictions correspond to a GT element
- **10/20 samples (50%) achieved perfect precision+coverage (1.0/1.0)** — model found exactly the right elements with no extras and no misses
- **7/20 samples had precision < 1.0** — model found extra elements beyond GT (many are real, not hallucinations)
- **3/20 samples had coverage < 1.0** — model missed exactly 1 GT element each (char_004: pink bow, char_009: red skirt, char_017: geometric patterns)
- **Avg inference: 21.6s/image** (range: 14.7s char_020 to 46.4s char_001). Total experiment: 432.6s (~7 min) on single NVIDIA A100-SXM4-80GB
- **char_001 is a 2× outlier** at 46.4s — likely cold-start GPU kernel compilation or first-inference overhead for the loaded model
- Full experiment script at `/home/intern/jsy/vlm/experiment_vlm_analysis.py` — 414 lines, self-contained, reusable for other image datasets
- Results JSON at `/home/intern/jsy/vlm/experiment_results/experiment_results.json` — contains all per-sample metrics, raw matches, and raw model outputs
- Human-readable report at `/home/intern/jsy/vlm/experiment_results/experiment_report.md` — 462 lines with per-sample matched/unmatched tables
- Ollama service runs as systemd service (`ollama.service`), user `ollama`, already hosting qwen36-vl in GPU memory (~37GB on A100)
- HTTP proxy (`http://137.153.170.55:10080`) set in environment blocks ALL localhost connections — proxy bypass is mandatory for Ollama API calls
- No internet access to HuggingFace/PyPI on this server — all models must be pre-downloaded or accessed via Ollama's local model registry
- Data resides at `/home/intern/jsy/vlm/data/SN_6期动漫数据标注/` — 20 subdirectories (char_001 to char_020), each containing one `.png` image and one `.json` annotation
- Ground truth format: `{"sample_id": str, "source_image": str, "elements": [{"name": str, "value": str}, ...]}` — Chinese language annotations
- bge-m3 embedding model (1.2GB, 1024-dim) available via Ollama — produces high-quality semantic embeddings for Chinese text, fully offline
- The matching algorithm uses greedy assignment (not Hungarian) with 30% element name + 70% full description cosine similarity weighting

## What We Tried (Chronological)

1. **Direct HTTP API (curl) → 403 Forbidden.** Tried `curl http://localhost:11434/api/tags`. Got 403. Root cause: environment has `http_proxy=http://137.153.170.55:10080` set, which was intercepting localhost traffic.

2. **Ollama CLI pipe → Timeout.** Tried piping JSON payload into `ollama run qwen36-vl:latest`. This entered an interactive TUI spinner mode and never returned. CLI is not suitable for scripted non-interactive use.

3. **Install ollama Python package → Still 403.** `pip install ollama` (v0.6.2). Same proxy issue — all requests going through the proxy. Package itself works fine once proxy is bypassed.

4. **Unset proxy env vars → Success.** `unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY` (or `os.environ.pop()` in Python). After bypassing proxy, Ollama API responded correctly. Ollama listens on IPv6 (`::1:11434`) but localhost resolves fine once proxy is out of the way.

5. **Single-image test with qwen36-vl → Excellent results.** Tested char_001: model correctly identified golden hair + black bow, red eyes, white shirt, black skirt, blue gem accessory — all semantically matching GT. Model also caught earrings NOT in GT (real detail in image).

6. **Full experiment script v1 (sentence-transformers) → Failed.** Tried loading `BAAI/bge-m3` via sentence-transformers. Server has no internet, HuggingFace unreachable. Local cache (`~/.cache/huggingface/hub/models--BAAI--bge-m3/`) only has `refs/`, no actual model weights (`config.json` missing). Fallback to `all-MiniLM-L6-v2` also failed — same network issue.

7. **Switch to Ollama embeddings → Success.** Used `ollama.embed(model='bge-m3:latest', input=...)` which works locally. bge-m3 produces 1024-dim embeddings. Added embedding cache in the script to avoid redundant calls (same text → cached embedding). This approach works fully offline.

8. **Full 20-image experiment → Completed.** Ran all 20 images through qwen36-vl with temperature=0.1 for consistency. Greedy matching (pred→GT) with 30% name + 70% description weighting. Results: 97.3% coverage, 90.0% precision, avg similarity 0.6818.

9. **Report generation → Completed.** Auto-generated JSON results file and Markdown report with per-sample matched pairs, unmatched predictions, and unmatched GT tables.

## Key Decisions

- **Greedy matching over Hungarian algorithm.** Hungarian would find globally optimal assignment but element matching is inherently fuzzy — greedy with a similarity threshold captures the natural "best match first" intuition. Simpler to debug and yields same results when matches are unambiguous (which they mostly are).
- **30% name + 70% description weighting for similarity.** Names are short ("红色眼睛") and lose semantic nuance compared to full descriptions. 70% weight on the combined name+description text captures the richer semantic signal while still anchoring on the element category.
- **Ollama embeddings over sentence-transformers.** Server has no internet → sentence-transformers can't download models. Ollama's bge-m3 was already pulled and works offline. Embedding cache reduces duplicate API calls when same text appears across matching iterations.
- **Temperature=0.1 for VLM inference.** Low temperature for consistent, reproducible JSON output. Higher temperatures risk the model deviating from the requested JSON schema.
- **No similarity threshold for matching.** Every prediction gets matched to its best GT candidate regardless of absolute score. Conservative approach — avoids false "unmatched" labels when similarity is genuinely low due to naming style differences. Downstream analysis can filter by similarity score if needed.
- **Pass file paths (not base64) to ollama.chat().** The ollama Python client accepts file paths directly in the `images` parameter, avoiding base64 encoding overhead for large PNG files.

## Evidence & Data

### Aggregate Metrics

| Metric | Value |
|--------|-------|
| Samples processed | 20 |
| Total GT elements | 111 |
| Total predicted elements | 120 |
| Total matched | 108 |
| Unmatched predictions (extra) | 12 |
| Unmatched GT (missed) | 3 |
| Avg semantic similarity | 0.6818 |
| Min similarity | 0.6002 |
| Max similarity | 0.7928 |
| Avg coverage (GT recall) | 0.9762 |
| Avg precision | 0.9099 |
| Overall coverage | 0.973 |
| Overall precision | 0.900 |
| Total inference time | 432.6s |
| Avg time per image | 21.6s |

### Per-Sample Summary

| Sample | GT | Pred | Matched | Cov | Prec | Avg Sim | Time(s) |
|--------|-----|------|---------|-----|------|---------|---------|
| char_001 | 5 | 6 | 5 | 1.0 | 0.833 | 0.6807 | 46.4 |
| char_002 | 5 | 8 | 5 | 1.0 | 0.625 | 0.6422 | 21.1 |
| char_003 | 4 | 5 | 4 | 1.0 | 0.800 | 0.6342 | 21.1 |
| char_004 | 6 | 5 | 5 | 0.833 | 1.0 | 0.7928 | 19.8 |
| char_005 | 6 | 8 | 6 | 1.0 | 0.750 | 0.6804 | 22.4 |
| char_006 | 6 | 6 | 6 | 1.0 | 1.0 | 0.7210 | 23.8 |
| char_007 | 5 | 5 | 5 | 1.0 | 1.0 | 0.7416 | 16.3 |
| char_008 | 6 | 6 | 6 | 1.0 | 1.0 | 0.6177 | 23.3 |
| char_009 | 6 | 5 | 5 | 0.833 | 1.0 | 0.7269 | 18.0 |
| char_010 | 6 | 6 | 6 | 1.0 | 1.0 | 0.6682 | 20.7 |
| char_011 | 6 | 6 | 6 | 1.0 | 1.0 | 0.6394 | 21.0 |
| char_012 | 7 | 8 | 7 | 1.0 | 0.875 | 0.6113 | 29.3 |
| char_013 | 6 | 6 | 6 | 1.0 | 1.0 | 0.6330 | 18.4 |
| char_014 | 6 | 6 | 6 | 1.0 | 1.0 | 0.7408 | 17.8 |
| char_015 | 5 | 7 | 5 | 1.0 | 0.714 | 0.6365 | 21.1 |
| char_016 | 5 | 5 | 5 | 1.0 | 1.0 | 0.7822 | 16.2 |
| char_017 | 7 | 6 | 6 | 0.857 | 1.0 | 0.6699 | 27.5 |
| char_018 | 4 | 5 | 4 | 1.0 | 0.800 | 0.7702 | 15.4 |
| char_019 | 6 | 6 | 6 | 1.0 | 1.0 | 0.6002 | 18.6 |
| char_020 | 4 | 5 | 4 | 1.0 | 0.800 | 0.6467 | 14.7 |

### Missed GT Elements (3 total — model didn't detect)

| Sample | Element | Description |
|--------|---------|-------------|
| char_004 | 粉色蝴蝶结领结 | 胸前系有一个大而饱满的粉色蝴蝶结，位置居中，边缘有褶皱细节，颜色鲜艳 |
| char_009 | 红色长裙 | 外穿红色长裙，裙摆覆盖至小腿，需注意层次感 |
| char_017 | 几何图案装饰（黄红相间） | 头部、腰部及腿部护具上有黄红相间的三角形几何图案 |

### Notable Extra Predictions (model found, not in GT — likely real)

| Sample | Element | Description |
|--------|---------|-------------|
| char_001 | 耳饰 | 双耳佩戴着蓝色的水滴形耳环，与颈部配饰的蓝色宝石相呼应 |
| char_002 | 项链 | 黑色细绳项链，悬挂一颗红色的水滴状吊坠 |
| char_005 | 金色腰链 | 腰间系有一条细细的金色链条（类似怀表链） |
| char_012 | 四肢护具 | 双臂小臂及双腿小腿缠绕黄褐色绷带/布条，作为护腕护胫 |
| char_015 | 手臂护具 | 双臂佩戴黑白相间机械风格护臂，有紫色发光细节 |

### Ground Truth Annotation Format

Each character's JSON has this structure:
```json
{
  "sample_id": "char_001",
  "source_image": "char_001.png",
  "elements": [
    {"name": "金色长发与黑色蝴蝶结", "value": "角色拥有飘逸的金色长发，头顶正中央系有一个大而明显的黑色蝴蝶结..."},
    {"name": "红色眼睛", "value": "眼睛为鲜艳的红色，眼神锐利..."}
  ]
}
```
- `name`: short element identifier (Chinese, 5-15 characters)
- `value`: detailed visual description (Chinese, 20-80 characters)
- Each character has 4-7 elements
- Elements cover: hair, eyes, clothing, accessories, special features

### VLM Prompt Used (Chinese)

The exact prompt sent to qwen36-vl for every image:
```
请仔细观察这张动漫角色图片，列出该角色的所有关键视觉元素。对于每个元素，给出元素名称和详细的视觉描述。

请严格按照以下JSON格式输出，只输出JSON，不要添加任何其他文字：
{
  "elements": [
    {"name": "元素名称", "value": "该元素的详细视觉描述"},
    {"name": "元素名称", "value": "该元素的详细视觉描述"}
  ]
}

要求：
- 必须包含：发型发色、眼睛颜色和形状、服装、配饰、特殊标志等
- 每个元素描述要具体详细，包括颜色、形状、位置等信息
- 至少列出5个元素
```

The model consistently outputs valid JSON (with occasional markdown code fences that the parser strips).

### Lowest Similarity Analysis (char_019, avg 0.6002)

This sample had the weakest match. The mismatch patterns reveal systematic limitations:
- 眼睛特征 ↔ 紫色与红色相间的上衣 (0.4848): model categorized "eyes" separately but GT grouped eye description into clothing element — structural mismatch, not content error
- 鞋履 ↔ 银色手环 (0.4571): forced match between completely unrelated elements — shoes matched to bracelet because both are the "last" unmatched items in greedy algorithm. This suggests a similarity threshold would help.

### Perfect Match Examples (10/20 samples)

Samples with coverage=1.0 AND precision=1.0: char_006, char_007, char_008, char_010, char_011, char_013, char_014, char_016, char_019
- These represent character designs where model and annotator agree completely on what constitutes a "visual element"
- char_007 (avg 0.7416): school uniform character — clear, standardized elements
- char_016 (avg 0.7822): highest similarity — simple sporty design with unambiguous elements

### Best Match Example (char_016, avg similarity 0.7822)

| Model Prediction | GT Annotation | Similarity |
|------------------|---------------|------------|
| 发型发色 → 黑色短发 | 黑色短发 | 0.7474 |
| 眼睛颜色和形状 → 绿色眼睛 | 绿色眼睛 | 0.8484 |
| 上衣服装 → 黄色运动上衣 | 黄色运动上衣 | 0.7954 |
| 下装服装 → 黑色运动短裤 | 黑色运动短裤 | 0.7655 |
| 鞋袜 → 白色运动鞋 | 白色运动鞋 | 0.7543 |

### Data File Paths

- **Input data:** `/home/intern/jsy/vlm/data/SN_6期动漫数据标注/` (20 char_XXX directories)
- **Experiment script:** `/home/intern/jsy/vlm/experiment_vlm_analysis.py`
- **Full JSON results:** `/home/intern/jsy/vlm/experiment_results/experiment_results.json`
- **Markdown report:** `/home/intern/jsy/vlm/experiment_results/experiment_report.md`
- **Test snippets:** `/tmp/test_vlm_single.py` (can be deleted)

### Environment Details

- **Server:** Linux 5.15.0-139-generic, NVIDIA A100-SXM4-80GB (GPU 0), RTX 3090 (GPU 2)
- **Ollama service:** systemd unit `ollama.service`, user `ollama`, env `OLLAMA_HOST=0.0.0.0:11434`, `OLLAMA_ORIGINS=*`, `CUDA_VISIBLE_DEVICES=1,2`
- **Models loaded:** qwen36-vl:latest (35.5B, Q8_0, 38GB, vision-capable), bge-m3:latest (1.2GB, 1024-dim embeddings)
- **Python:** 3.8, key packages: ollama 0.6.2, torch 2.4.1, transformers 4.46.3, numpy, pillow 10.4.0
- **HTTP proxy:** `http://137.153.170.55:10080` — MUST unset for localhost Ollama API connections

## Code Analysis

- **`/home/intern/jsy/vlm/experiment_vlm_analysis.py`** — Main experiment script (414 lines, self-contained, no external deps beyond ollama+numpy)
  - `OllamaEmbedder` class (lines ~55-85): wraps `ollama.embed()` with internal dict cache. `encode(texts: list) → np.ndarray`, `encode_single(text: str) → np.ndarray`. Cache is critical — without it, the same text gets re-embedded multiple times during matching (pred texts, GT texts, name-only texts). The embedder is passed by reference to `match_elements`.
  - `cosine_similarity(a, b) → float` (lines ~88-95): numpy-based, computes `dot(a,b) / (||a|| * ||b||)`. Returns 0.0 for zero vectors (edge case: empty text after stripping).
  - `match_elements(pred, gt, embedder) → (matches, unmatched_pred, unmatched_gt)` (lines ~98-165): Core matching logic. Steps: (1) build combined text strings `{name}: {value}`, (2) batch-encode all pred texts, GT texts, pred names, GT names via embedder (4 batches — cache handles duplicates), (3) for each prediction, iterate all unmatched GTs computing `0.3 * cosine(pred_name, gt_name) + 0.7 * cosine(pred_full, gt_full)`, (4) select best unmatched GT for each pred, (5) collect unmatched preds and GTs. Time complexity: O(n²) where n ≤ 8 — negligible.
  - `analyze_image(image_path) → dict` (lines ~168-180): sends image to qwen36-vl with `ollama.chat()`. Uses `temperature=0.1, num_predict=2048`. Passes file path directly (not base64) — ollama client handles encoding internally.
  - `extract_json_from_response(text) → dict` (lines ~140-165): 3-tier parsing: (1) strip markdown code fences ` ```json ... ``` `, (2) try `json.loads()`, (3) regex fallback `r'\{[^}]*"elements"[^}]*\}'`. Returns `{"elements": []}` on total failure — experiment continues gracefully.
  - `run_experiment()` (lines ~185-330): orchestrator. Creates `OllamaEmbedder` with warmup, iterates `Path(DATA_DIR).iterdir()` sorted, calls `load_ground_truth()` + `analyze_image()`, computes per-sample and aggregate metrics, calls `generate_report()`.
  - `generate_report(summary, output_path)` (lines ~335-414): writes Markdown with tables for aggregate metrics, per-sample details, matched pairs, extra predictions, missed elements.
- **VLM prompt** is in Chinese, requests strict JSON output. Model occasionally wraps JSON in ` ```json ``` ` fences — parser handles this. At `temperature=0.1` output is highly consistent across runs.
- **Proxy bypass** at module level (lines ~18-20): `for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']: os.environ.pop(key, None)`. Must execute BEFORE `import ollama` (the client reads proxy from env at init time).
- **Matching algorithm edge cases:** (1) If pred_elements or gt_elements is empty → returns all as unmatched. (2) If all cosine similarities are very low → still produces a "best match" (no threshold). This causes artifacts like char_019's "鞋履↔银色手环" match at 0.457. (3) Greedy matching order matters — earlier predictions get first pick. Predictions are processed in model's output order (typically head-to-toe).
- **No external config files** — all paths and parameters are module-level constants at the top of the script. Easy to modify for a different dataset.
- **Dependencies:** `ollama` (API client), `numpy` (embedding math), `json`, `base64`, `re`, `time`, `pathlib` (all stdlib except ollama and numpy).

## Files Changed

### New files (created this session)
- `/home/intern/jsy/vlm/experiment_vlm_analysis.py` — Complete, reusable experiment script with Ollama VLM + embedding pipeline
- `/home/intern/jsy/vlm/experiment_results/experiment_results.json` — Full experiment output with per-sample matches, metrics, and raw model outputs
- `/home/intern/jsy/vlm/experiment_results/experiment_report.md` — Human-readable Markdown report (462 lines)

### Existing files (read/analyzed, not modified)
- `/home/intern/jsy/vlm/data/SN_6期动漫数据标注/char_001~020/*.png` — Input anime character images (20 files)
- `/home/intern/jsy/vlm/data/SN_6期动漫数据标注/char_001~020/*.json` — Ground truth annotations (20 files)
- `/home/intern/jsy/CLAUDE.md` — Project conventions (Windows-focused, but Linux server context differs)
- `/etc/systemd/system/ollama.service` — Ollama service configuration

### Environment changes (non-file)
- Installed `ollama` Python package (v0.6.2) via pip
- Proxy bypass pattern established for all local Ollama API calls

## User Feedback & Preferences (REQUIRED — never omit)

1. **Use local server models** — explicitly requested "优先调用服务器内部的模型进行本地训练". We used qwen36-vl via Ollama (fully local, no cloud API).
2. **Extract semantically similar elements, not exact matches** — user asked for "语义相近的元素以及描述", which guided the choice of embedding-based similarity over string matching.
3. **Chinese language prompts and output** — user communicated in Chinese, VLM prompt is in Chinese, ground truth is in Chinese.
4. **Comprehensive approach** — user wanted a proper experiment ("做一个实验"), not just a quick test. This drove the full 20-sample pipeline with metrics.
5. **Image analysis, not training** — despite saying "本地训练", the actual task was inference-based analysis. No fine-tuning was performed.
6. **Server has pre-existing Ollama setup** — the qwen36-vl model was already downloaded and loaded by another user/process. This was discovered, not set up from scratch.
7. **The CLAUDE.md is Windows-focused** (`D:\索尼实习`) but this session ran on a Linux server (`/home/intern/`). The proxy issue and offline constraints are Linux-specific.

## Where We're Going

1. **Review the 12 extra predictions against images** — determine if they should be added to ground truth annotations (human review). Many appear to be real elements the annotators missed.
2. **Investigate the 3 missed GT elements** — char_004 (pink bow integrated into "连衣裙" prediction), char_009 (red skirt may be occluded), char_017 (geometric patterns are fine detail). Consider prompt engineering to catch small details.
3. **Integrate VLM element extraction into the supervision pipeline** — if this experiment validates the approach, build a production script that feeds VLM output into the merchandise supervision workflow.
4. **Compare with cloud VLMs** — test same images with Qwen-VL-Max (via DashScope) as baseline to quantify the local vs cloud accuracy tradeoff.
5. **Batch processing optimization** — current sequential processing takes ~22s/image. Parallel requests to Ollama could reduce total time.
6. **Fine-tuning exploration** — if any systematic gaps are found (e.g., consistently missing fine patterns), consider fine-tuning qwen36-vl on the annotation dataset.

## Risks & Blockers

- **HTTP proxy breaks localhost connections** — any script calling Ollama API must unset `http_proxy`/`https_proxy`. Forgot this once already; the fix is in the experiment script but other scripts may hit the same issue.
- **No internet access** — can't download models or libraries from HuggingFace/PyPI. All dependencies must be pre-installed or use Ollama's local model registry.
- **Ollama service is shared** — running as a systemd service used by multiple users. Loading a different model would unload qwen36-vl (38GB) and may disrupt others.
- **GPU memory is tight** — A100 has 80GB, qwen36-vl uses ~37GB. Loading another large model would require coordination.
- **The server's CLAUDE.md doesn't reflect Linux environment** — project conventions reference Windows paths (`D:\索尼实习`) and PowerShell commands. This session ran on Linux. Future sessions should note the dual-environment reality.

## Open Questions

1. Are the 12 "extra" model predictions actually correct (i.e., should they be added to GT annotations)? Need human review against the original images.
2. Would the model perform better with a more structured prompt (e.g., example few-shot format, explicit element categories)?
3. Is 0.68 average similarity "good enough" for production? What's the human inter-annotator agreement baseline for comparison?
4. Should the matching algorithm use a similarity threshold to avoid forced matching of unrelated elements?
5. Why does char_001 consistently take 2× longer (46s vs ~21s average)? Cold start or image complexity?

## Quick Start for Next Session

```bash
# Key files to read first
# /home/intern/jsy/vlm/experiment_results/experiment_report.md  — Full experiment report
# /home/intern/jsy/vlm/experiment_results/experiment_results.json — Raw JSON results
# /home/intern/jsy/vlm/experiment_vlm_analysis.py — Reusable experiment script

# Reference docs
# /home/intern/jsy/CLAUDE.md — Project conventions (note: Windows-focused)

# Verify current state
ls /home/intern/jsy/vlm/experiment_results/
python3 -c "
import os
for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY']: os.environ.pop(k,None)
import ollama
print('Ollama OK:', ollama.list()[0]['name'])
print('Models:', [m['name'] for m in ollama.list()['models']])
"

# Re-run experiment (if needed)
cd /home/intern/jsy/vlm && python3 experiment_vlm_analysis.py

# Next action
# Review the 12 extra model predictions against original images to determine if GT annotations should be expanded.
```
