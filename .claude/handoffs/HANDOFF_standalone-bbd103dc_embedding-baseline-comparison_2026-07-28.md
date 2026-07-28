# Handoff: Embedding-Based Baseline Comparison — VLM Extraction vs Human Annotation

**Date:** 2026-07-28
**Status:** IN PROGRESS (comparison script EXISTS, needs adaptation — not from scratch)
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-bbd103dc` seq `3`
**Parent:** `HANDOFF_standalone-bbd103dc_batch-supervision-34-complete_2026-07-28.md`
**Prior chain:** `HANDOFF_batch-supervision-and-finetune-direction_2026-07-27.md` > `HANDOFF_standalone-bbd103dc_batch-supervision-34-complete_2026-07-28.md` > this

---

## Since Last Handoff

- **Parent's P0 "baseline comparison (VLM vs human annotation)" was deferred** — this session clarified the goal and discovered the ground truth data was already on the server, then designed the matching methodology.
- **Parent's goal was ambiguous about 2D vs 3D** — user corrected this: the core experiment is VLM's 2D element extraction ability, not the 3D supervision review pipeline (Step 3 is a separate business concern).
- **No code was written this session** — work was analysis, clarification, and design. The implementation (comparison script) is the next session's task.
- **All experimental data pushed to GitHub** — 3 commits pushed: code changes (7371770), summary results (d127629), full extraction/review outputs (third commit with 543 files).
- **Server SSH port still unknown** — but ground truth data found locally at `vlm/data/SN_6_3D_dataset/`, removing the blocker for baseline comparison.

---

## The Goal

Evaluate `qwen36-vl:latest`'s ability to extract structured character elements from 2D anime images by comparing VLM outputs against human annotations. This is the critical validation step before the model can be trusted for the element extraction pipeline, and it determines whether the 34-sample batch supervision results are reliable.

The comparison must handle semantic matching (not exact string matching) because human annotators frequently merge multiple elements into a single compound name (e.g., "金色长发与黑色蝴蝶结" = hair + headwear), while VLM outputs are more granular.

---

## Where We Are

### Ground truth discovered on server
- Human annotations at `vlm/data/SN_6_3D_dataset/char_XXX/char_XXX.json` for all 34 samples
- Format: `{"sample_id": str, "source_image": str, "elements": {name: description}}` — elements are keyed by compound names, each value is a Chinese description sentence
- Element count per sample: 4–8 (char_034 has 8, char_003 has 4)
- Human annotations merge logically related elements into one name (e.g., "金色长发与黑色蝴蝶结" combines hair color/style AND headwear)

### VLM extraction outputs
- 34 × `extracted_elements.json` at `vlm/tmp/supervision_agent_output/char_XXX/extraction/char_XXX/`
- Format: list of `{element_id, name, value, category, attributes: {color, material, shape}, confidence}`
- Element count per sample: 4–11 (char_002/008/024/031 have 11, char_003 has 4)
- VLM splits elements more granularly (separate hair, headwear, clothing items)
- All confidence values are "high" (no self-calibration)

### Embedding model available
- **bge-m3:latest** (1.2 GB) on server Ollama — confirmed working via API
- 1024-dim vectors, multilingual (BAAI), handles Chinese well
- API endpoint: `http://127.0.0.1:11434/api/embeddings`
- Must bypass corporate proxy for localhost: `--noproxy '*'` or `proxies={"http": None, "https": None}`
- GPU memory: negligible (qwen36-vl uses 38GB/42GB, bge-m3 fits in remaining ~4GB or CPU)

### GitHub state
- All experimental data pushed to origin/main (3 recent commits: code, summary, full outputs)
- Working tree clean, no uncommitted changes

### Key insight: element count mismatch by design
| Sample | Human elements | VLM elements | Discrepancy reason |
|--------|---------------|--------------|---------------------|
| char_001 | 5 | 8 | "金色长发与黑色蝴蝶结" → VLM splits to 头发 + 头饰; VLM adds 外套, 裙子, 腰带 |
| char_015 | 5 | 9 | Human merges hair+headwear, VLM separates each piece |
| char_034 | 8 | 6 | Rare case where VLM extracts fewer than human |

The count mismatch is NOT a VLM error — it's a granularity difference. Embedding-based matching is required for meaningful comparison.

---

## CRITICAL: Comparison Script Already Exists

**`vlm/experiment_vlm_analysis.py`** (452 lines) already implements the full baseline comparison pipeline:

```python
# Key components already built:
class OllamaEmbedder:    # bge-m3 wrapper with caching
def match_elements():     # Greedy semantic matching (pred→GT)
    # 30% name similarity + 70% full text similarity
    # Uses bge-m3 via ollama.embed()
def run_experiment():     # Full loop: load GT → VLM inference → match → metrics
def generate_report():    # Markdown report with per-sample detail
```

**What it does right:**
- Uses `ollama` Python library (not raw HTTP), already imported
- Bypasses proxy by popping env vars
- Embedding cache (`_cache` dict) for efficiency
- Greedy matching: best unmatched GT for each prediction
- Weighted similarity: 30% name embedding + 70% full text embedding
- Per-sample metrics: coverage, precision, avg_similarity
- Aggregate summary with total counts
- Outputs both JSON (`experiment_results.json`) and Markdown report

**What needs to change to use it for this eval:**

| Current | Needed |
|---------|--------|
| `DATA_DIR = "vlm/data/SN_6期动漫数据标注"` | → `vlm/data/SN_6_3D_dataset` (doesn't exist on server) |
| Runs VLM inference fresh each time | → Use pre-existing `extracted_elements.json` from `vlm/tmp/supervision_agent_output/` |
| GT format expects `list[dict]` elements | → GT is actually `dict{name: description}` — needs format conversion |
| `ollama` Python package required | → NOT installed (`import ollama` would fail). Server uses raw HTTP. |

**Decision needed:** Adapt the existing script (change data paths + GT format handling + switch `ollama` to `requests`) OR write a minimal script that only does matching (skips VLM inference, reads pre-extracted elements).

---

## What We Tried (Chronological)

### 1. Pushed code + handoff to GitHub (2 commits)
**Action**: Staged 3 modified Python files + 1 new batch script + 5 deleted handoffs + 1 new handoff (force-add: gitignored), then pushed summary results.
**Result**: Commits `7371770` and `d127629` pushed, origin/main synced. ✅
**Issue**: User noticed only `agent_summary.json` was pushed, not the actual extraction outputs.

### 2. Pushed full experimental data (third commit)
**Action**: `git add -f vlm/tmp/supervision_agent_output/` — force-added all 543 remaining files (extracted_elements.json, qwen_prediction_v3.json, raw responses, QC reports).
**Result**: Full 40MB / 578-file dataset pushed. ✅

### 3. Summarized experimental results — wrong frame
**Hypothesis**: Batch supervision results (pass/fail, billable) were what the user wanted to evaluate.
**User correction**: The experiment is about 2D element extraction quality. The 3D supervision review (Step 3, billable issues) is a separate business pipeline. We should be evaluating Step 1 (element extraction), not Step 3 (review).
**Result**: Reframed the goal. ❌→✅

### 4. Checked for embedding model on server
**Hypothesis**: Need embedding model for semantic matching since human+VLM element names won't align exactly.
**Method**: `ollama list` → found bge-m3:latest; tested via `curl --noproxy '*' http://127.0.0.1:11434/api/embeddings`.
**Result**: bge-m3 works, 1024-dim vectors, small footprint (1.2 GB). ✅

### 5. Compared human vs VLM annotation formats
**Human format** (`char_XXX.json`):
```json
{"elements": {"金色长发与黑色蝴蝶结": "角色拥有飘逸的金色长发，头顶正中央系有一个大而明显的黑色蝴蝶结...", ...}}
```
**VLM format** (`extracted_elements.json`):
```json
{"elements": [{"name": "头发", "value": "金色长发，发梢带有明显的橙红色渐变。", "category": "hair", ...}, ...]}
```
**Finding**: Human uses merged element names with narrative descriptions; VLM uses individual element names with structured attributes. Direct name matching fails. Embedding matching on `value`/description text is the right approach.

---

## Key Decisions

| Decision | Rationale | Rejected |
|----------|-----------|----------|
| Embedding-based matching, not string matching | Human merges elements (e.g., "金色长发与黑色蝴蝶结"), VLM splits them. cosine similarity can match one human element to multiple VLM elements. | Fuzzy string matching (would miss semantic equivalence), manual review (not scalable) |
| Use bge-m3 via Ollama API, not sentence_transformers | bge-m3 already on server, no pip install needed, API consistent with existing qwen36-vl pattern. 1024-dim multilingual. | sentence_transformers (not installed, would need download), OpenAI embeddings (external API, cost) |
| Match on element `value` descriptions, not `name` | Descriptions carry semantic content ("金色长发，发梢带有明显的橙红色渐变"); names are too short ("头发"). | Name-only matching (too sparse for cosine) |
| Cosine similarity with threshold, not clustering | Simple, interpretable, gives precision/recall per human element. | Clustering (overkill for 34 samples, harder to interpret) |
| Baseline comparison on existing 34 samples, not waiting for 6000 | 34 is small but sufficient to validate methodology and identify VLM failure patterns. Method scales to larger dataset later. | Wait for Windows data transfer (SSH blocked, indefinite delay) |
| Keep 3D review as separate evaluation track | User confirmed element extraction is the core experiment; 3D supervision is a downstream business pipeline. Evaluating them separately avoids conflation. | Merged evaluation |

---

## Evidence & Data

### Human annotation format (char_001.json)
```json
{
  "sample_id": "char_001",
  "source_image": "vlm/data/SN_6_3D_dataset/char_001/char_001.png",
  "elements": {
    "金色长发与黑色蝴蝶结": "角色拥有飘逸的金色长发，头顶正中央系有一个大而明显的黑色蝴蝶结，是其标志性特征。",
    "红色眼睛": "眼睛为鲜艳的红色，眼神锐利，是角色的重要面部特征。",
    "白色衬衫与蓝色宝石领饰": "穿着一件白色衬衫，领口处有黑色小领结和一枚镶嵌蓝色宝石的圆形领饰，细节需清晰绘制。",
    "白色西装外套": "外面套着一件白色西装外套，开襟穿着，版型修身。",
    "深色百褶裙": "下身穿着深棕色百褶裙，裙摆呈自然散射状褶皱。"
  }
}
```

### VLM extraction format (char_001 extracted_elements.json)
```json
{
  "elements": [
    {"name": "头发", "value": "金色长发，发梢带有明显的橙红色渐变。", "category": "hair", "confidence": "high"},
    {"name": "眼睛", "value": "红色瞳孔。", "category": "face", "confidence": "high"},
    {"name": "头饰", "value": "头顶佩戴黑色大蝴蝶结。", "category": "headwear", "confidence": "high"},
    {"name": "外套", "value": "白色长袖西装外套，开襟穿着。", "category": "clothing", "confidence": "high"},
    {"name": "衬衫", "value": "白色立领衬衫。", "category": "clothing", "confidence": "high"},
    {"name": "领饰", "value": "黑色领结及垂坠装饰，中央镶嵌醒目的蓝色圆形宝石，下方连接垂直排列的黑色装饰扣链。", "category": "accessory", "confidence": "high"},
    {"name": "裙子", "value": "深棕色百褶裙。", "category": "clothing", "confidence": "high"},
    {"name": "腰带", "value": "深色腰带，配有金属扣环。", "category": "accessory", "confidence": "high"}
  ]
}
```

### Human vs VLM element count comparison (sample)
| Sample | Human count | VLM count | Δ |
|--------|------------|-----------|---|
| char_001 | 5 | 8 | +3 (VLM splits hair+headwear, adds 腰带) |
| char_002 | 5 | 11 | +6 |
| char_003 | 4 | 4 | 0 (rare exact match) |
| char_015 | 5 | 9 | +4 |
| char_034 | 8 | 6 | −2 (VLM fewer) |

### bge-m3 embedding test
```bash
curl -s --noproxy '*' http://127.0.0.1:11434/api/embeddings \
  -d '{"model":"bge-m3:latest","prompt":"金色长发与黑色蝴蝶结"}'
# → 1024-dim vector, response time <1s
```

### Proposed matching algorithm (not implemented)
```
For each sample:
  1. Load human elements: {name: description}
  2. Load VLM elements: [{name, value, category, ...}]
  3. Compute bge-m3 embeddings for all human descriptions + all VLM values
  4. For each human element h_i:
     - Compute cosine similarity against all VLM elements
     - Find best match: max(similarity) ≥ threshold → matched
     - If no match ≥ threshold → VLM missed this element (false negative)
  5. Remaining unmatched VLM elements → VLM extra (false positive / over-extraction)
  6. Aggregate across all 34 samples:
     - Precision = matched / (matched + extra)
     - Recall = matched / (matched + missed)
     - F1 = 2 * P * R / (P + R)
     - Per-category breakdown (hair, face, clothing, accessory, etc.)
```

### Key threshold consideration
Threshold needs tuning — too high and merged descriptions won't match (false negatives), too low and unrelated elements will match (false positives). Recommend testing at 0.6, 0.7, 0.75, 0.8 and reporting the curve.

---

## Code Analysis

### Data paths (all on server)
```
vlm/data/SN_6_3D_dataset/char_XXX/char_XXX.json          # Human annotation (ground truth)
vlm/data/SN_6_3D_dataset/char_XXX/char_XXX.png            # 2D source image
vlm/data/SN_6_3D_dataset/char_XXX/char_XXX_front_view.png # 3D front view (not needed for this eval)
vlm/tmp/supervision_agent_output/char_XXX/extraction/char_XXX/extracted_elements.json  # VLM output
```

### Ollama embedding API signature
```python
# Request
POST http://127.0.0.1:11434/api/embeddings
{"model": "bge-m3:latest", "prompt": "text to embed"}

# Response
{"embedding": [0.12, -0.34, ...]}  # 1024 floats

# Must set proxies=None for localhost (corporate proxy blocks 127.0.0.1)
```

### Existing pipeline scripts (for reference, not needed for comparison)
- `vlm/scripts/supervise/run_element_extraction.py` — Step 1: calls qwen36-vl for element extraction
- `vlm/scripts/supervise/run_supervision_agent.py` — orchestrates Step 1→2→3
- `vlm/scripts/supervise/run_multicategory_supervision_review.py` — Step 3: 3D review
- `vlm/scripts/supervise/batch_supervision_34.py` — batch runner

---

## Files Changed

### No code changed this session
- All git operations (push only, no new commits)
- Working tree is clean

### Data referenced
- `vlm/data/SN_6_3D_dataset/char_001~034/char_XXX.json` — human annotations (34 files)
- `vlm/tmp/supervision_agent_output/char_001~034/extraction/char_XXX/extracted_elements.json` — VLM outputs (34 files)
- `vlm/tmp/supervision_agent_output/batch_summary.json` — batch run summary

### GitHub (pushed in this session)
- Commit `d127629`: batch_summary.json + 34×agent_summary.json (summary results)
- Commit `7371770`: code changes + handoff cleanup + new handoff
- Third commit: full experimental outputs incl. extracted_elements, raw responses, QC reports

---

## User Feedback & Preferences

- **"为什么这个实验会和3D图有关啊，我是想要锻炼视觉模型提取2D图元素的能力"** — Critical correction. The experiment is about 2D element extraction quality. 3D supervision review is a separate downstream concern. Next session must stay focused on extraction evaluation.
- **"这个路径下不是有吗，只是体量不够大"** — User knew the ground truth data was at `vlm/data/SN_6_3D_dataset/`. Validates that 34-sample baseline is the right starting point, not waiting for 6000.
- **"由于人工进行标注的时候可能会把多个元素合并到一个元素名"** — User identified the core matching challenge. Human annotators merge; VLM splits. This drives the embedding approach.
- **"不需要你推送只需要给我命令"** — Preference for receiving commands to execute, not auto-execution of git operations.
- **User accepted the bge-m3 embedding approach without debate** — comfortable with semantic matching methodology.
- **User opened `atomic_rules_generated.json` in IDE** — exploring the pipeline outputs, familiarizing with data formats.

---

## Where We're Going

1. **Adapt `vlm/experiment_vlm_analysis.py` for local data** — script already exists with full matching logic (bge-m3 embeddings, greedy matching, metrics). Needs: (a) point at `SN_6_3D_dataset` not `SN_6期动漫数据标注`, (b) load pre-extracted elements instead of re-running VLM inference, (c) handle GT format `dict{name: desc}` not `list`, (d) replace `ollama` library calls with raw `requests` (ollama pkg not installed). This is the immediate next action.

2. **Tune similarity threshold** — run at multiple thresholds (0.6, 0.65, 0.7, 0.75, 0.8) and pick the best balance. Report the curve.

3. **Identify VLM failure patterns** — per category (hair, face, clothing, accessory), per confidence level. Which elements does VLM consistently miss? Which does it hallucinate?

4. **Separately evaluate 3D supervision review** — once extraction quality is validated, independently assess the Step 3 review pipeline's ability to catch real 3D defects (the 7 failed samples).

5. **Scale methodology to larger dataset** — the comparison script should work with any number of samples, for when the 6000-sample dataset becomes available.

---

## Risks & Blockers

- **Ollama API unreachable via curl without `--noproxy`** — corporate proxy at `http://137.153.170.55:10080` blocks localhost. The comparison script must use `proxies={"http": None, "https": None}` for localhost URLs, same pattern as the existing extraction/review scripts.
- **bge-m3 may be slow with many sequential calls** — 34 samples × (5–11 VLM elements + 4–8 human elements) ≈ 500–700 single-text embeddings. If each call takes 200ms, that's ~2 minutes. Batch embedding API may exist but is untested.
- **Threshold choice is subjective** — no objective ground truth for what constitutes a "match" between merged and split descriptions. The 0.7 default is a starting point; manual spot-checking of borderline cases will be needed.
- **34 samples is small for statistical significance** — per-category breakdowns may have single-digit counts. Results should be treated as directional, not definitive.

---

## Open Questions

- [ ] Does Ollama support batch embeddings? (`/api/embed` with multiple inputs) — would reduce API calls from ~600 to 34.
- [ ] What is a reasonable cosine similarity threshold for Chinese anime character descriptions? Start at 0.7, but need empirical validation.
- [ ] Should we normalize descriptions before embedding (strip punctuation, etc.)? Chinese text is relatively clean already.
- [ ] How to handle the "human element merges 3+ VLM sub-elements" case? One-to-many matching vs many-to-one? Current plan is many-to-one (multiple VLM elements match one human element if all above threshold), which inflates recall.

---

## Quick Start for Next Session

```bash
# Verify ground truth data exists
ls vlm/data/SN_6_3D_dataset/char_*/char_*.json | wc -l  # should be 34

# Verify VLM extraction outputs exist
ls vlm/tmp/supervision_agent_output/char_*/extraction/char_*/extracted_elements.json | wc -l  # should be 34

# Verify bge-m3 is available
ollama list | grep bge-m3
# Test embedding API
curl -s --noproxy '*' http://127.0.0.1:11434/api/embeddings \
  -d '{"model":"bge-m3:latest","prompt":"金色长发与黑色蝴蝶结"}' | python3 -c "import json,sys; print(len(json.load(sys.stdin)['embedding']))"
# Expected: 1024

# Check if ollama Python pkg is installed (needed if adapting the existing script)
python3 -c "import ollama" 2>&1  # likely fails — not installed
pip list 2>/dev/null | grep ollama  # check if installable

# Key files to read first
# - vlm/experiment_vlm_analysis.py (EXISTING comparison script — 452 lines, has embedder + matcher + report)
# - vlm/data/SN_6_3D_dataset/char_001/char_001.json (human annotation format: dict{name: desc})
# - vlm/tmp/supervision_agent_output/char_001/extraction/char_001/extracted_elements.json (VLM output: list of dicts)
# - vlm/scripts/supervise/run_element_extraction.py (see how existing code calls Ollama via raw HTTP requests, not ollama pkg)

# Next action
# Adapt vlm/experiment_vlm_analysis.py:
#   1. Change DATA_DIR → vlm/data/SN_6_3D_dataset
#   2. Replace ollama.chat() VLM inference → load pre-extracted extracted_elements.json
#   3. Convert GT format: dict{name: desc} → list[{name, value}] for match_elements()
#   4. Replace ollama.embed() → requests.post(http://127.0.0.1:11434/api/embeddings) with proxy bypass
#   5. Run on all 34 samples, report precision/recall/F1 per category
```
