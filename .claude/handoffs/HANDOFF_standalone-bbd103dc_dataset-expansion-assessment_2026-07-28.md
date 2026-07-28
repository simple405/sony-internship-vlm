# Handoff: VLM Extraction Bias Analysis + Dataset Expansion Strategy — 7 Bias Patterns Documented, Prompt Fix Plan Ready

**Date:** 2026-07-28
**Status:** IN PROGRESS (bias analysis complete, prompt fix plan written, awaiting execution)
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-bbd103dc` seq `4`
**Parent:** `HANDOFF_standalone-bbd103dc_embedding-comparison-executed_2026-07-28.md`
**Prior chain:** `HANDOFF_standalone-bbd103dc_batch-supervision-34-complete_2026-07-28.md` > `HANDOFF_standalone-bbd103dc_embedding-baseline-comparison_2026-07-28.md` > parent > this

---

## Since Last Handoff

- **Parent's 7 "Where We're Going" steps were NOT executed** — no code changes, no re-runs. This was a strategic assessment + bias analysis session.
- **User asked whether to expand from 34 to ~54 samples** before applying P0 fixes. Context: user had "approximately 54 samples" available.
- **Discovered the 20 additional samples** — they live in `vlm/data/smoke_test/char_001–020` (RunningHub batch evaluation data). Each has GT annotations (2-3 JSON files per char, different format from SN_6_3D_dataset). But NONE have VLM element extraction output.
- **Data gap confirmed**: smoke_test samples were used for RunningHub 3D generation evaluation (identity score, visual score), not for 2D element extraction. Their GT format may differ from the `list[dict]` format the evaluation script expects.
- **Strategic recommendation delivered + accepted**: Apply prompt fixes first, then extract on 20 new samples, then evaluate all 54.
- **User asked for full bias analysis** — read the extraction prompt (`vlm/prompts/supervision/element_extraction_from_2d.txt`, 97 lines), cross-referenced against all 7 failure patterns and per-sample match data, produced comprehensive 3-category taxonomy (Prompt → Over-extraction → Calibration).
- **7 bias patterns documented with specific line-number fixes** — 4 fixable by editing the `.txt` prompt alone, 3 requiring evaluation-script or architecture changes.

## The Goal

Evaluate and improve `qwen36-vl:latest`'s 2D element extraction quality against human annotations. The parent session established a 34-sample baseline (95.1% coverage, 71.3% precision, 7 failure patterns). The immediate question is whether to expand the evaluation dataset from 34 to 54 samples, and if so, when relative to applying the P0 prompt fixes documented in the parent handoff.

## Where We Are

- **Code state unchanged** from parent — 3 modified files + 2 new untracked files. No commits this session.
- **`experiment_vlm_analysis.py`** (343 lines) — adapted from 452 lines in parent session. Key components:
  - `OllamaEmbedder.encode()` — batch embedding via `POST /api/embed`, 10x speedup over per-text API
  - `load_vlm_extraction()` — reads pre-extracted elements from `supervision_agent_output/{char}/extraction/{char}/extracted_elements.json`
  - `load_ground_truth()` — reads `SN_6_3D_dataset/{char}/{char}.json`, normalizes typos (`value:` → `value`), deduplicates. Currently hardcoded to SN_6_3D_dataset path.
  - `match_elements()` — greedy pred→GT matching, 30/70 name/text weighted cosine similarity, `MIN_SIMILARITY = 0.5` threshold
  - `run_experiment()` — iterates over characters, computes per-category metrics, writes JSON + markdown report
- **20 additional GT samples identified** in `vlm/data/smoke_test/char_001–020/` — these are from the RunningHub batch evaluation run. Each dir has 2-3 char_*.json files (GT annotations for different viewpoints/versions). Format may differ from SN_6_3D_dataset's single `char_NNN.json` per directory.
- **VLM extraction gap**: `vlm/tmp/supervision_agent_output/` only covers the 34 SN_6_3D_dataset samples. The 20 smoke_test samples have never been run through the element extraction pipeline. No `extracted_elements.json` exists for any smoke_test character.
- **Two datasets, two GT formats**:
  - `SN_6_3D_dataset`: 34 samples, 1 JSON per char, `list[dict]` format with `{name, value}` elements. Clean, normalized by parent session.
  - `smoke_test`: 20 samples, 2-3 JSON per char, multiple versions per character. Format unverified — likely includes RunningHub-specific fields (identity_score, visual_score, generated_images). May need format extraction/adapter before feeding to `load_ground_truth()`.
- **4 additional samples** in `vlm/data/element_extraction_results_sn6_local/` (char_001–004) — purpose unclear, not yet investigated. May be early extraction test outputs from a different pipeline run.
- **Strategic recommendation on the table**: P0 prompt fixes first → VLM extraction on 20 new samples → 54-sample re-evaluation. Awaiting user decision.
- **bge-m3 embedding model** still running on Ollama at `localhost:11434`. Batch `/api/embed` endpoint confirmed working (1.95s for 5 texts, 120s timeout). System python3 (`/usr/bin/python3`) has numpy 1.24.4 + requests. Venv python3 is broken (Windows-path shebang).
- **All parent's open questions remain open** — MIN_SIMILARITY threshold, pose/gesture scope alignment, batch size ceiling, embedding cache persistence.
- **`vlm/data/SN_6_3D_dataset/` contains front_view images** — parent session verified `char_021–034` have `_front_view.png` files. The evaluation script currently does NOT use images (only text-based embedding matching), but images would be needed for VLM re-extraction after prompt changes.

## What We Tried (Chronological)

### 1. Context restoration from parent handoff
**Action**: Read `HANDOFF_standalone-bbd103dc_embedding-comparison-executed_2026-07-28.md` (323 lines). Summarized key metrics, 7 failure patterns, 6 P0-P3 recommendations for the user.
**Result**: ✅ User now has full picture of evaluation state and next steps.

### 2. Data inventory — located the "~54 samples"
**Hypothesis**: User mentioned having ~54 samples. Need to find where the extra ~20 beyond the 34 in SN_6_3D_dataset live.
**Method**: Searched all `char_*` directories and JSON files across `vlm/data/` and `vlm/tmp/supervision_agent_output/`.
**Result**: Found the breakdown:
| Dataset | Count | Has GT | Has VLM Extraction |
|---------|-------|--------|---------------------|
| `SN_6_3D_dataset` | 34 | ✅ (1 JSON/char) | ✅ |
| `smoke_test` | 20 | ✅ (2-3 JSON/char) | ❌ |
| `element_extraction_results_sn6_local` | 4 | unknown | partial |
| **Total** | **54–58** | — | — |

### 3. Assessed whether to expand now vs after P0 fixes
**Analysis**: The P0 recommendations (constrain footwear prompt, raise MIN_SIMILARITY) would change VLM extraction behavior and evaluation metrics. Running extraction on 20 new samples with the current prompt would reproduce known problems (28.6% footwear precision, cascading false matches). Running after P0 fixes would validate whether the fixes actually improve metrics on unseen data.
**Recommendation**: P0 fixes first, then expand. 34→54 is still directional, not statistically significant — the real value is using the 20 new samples as a validation set for prompt improvements.

## Key Decisions

| Decision | Rationale | Rejected |
|----------|-----------|----------|
| Recommended P0-first over expand-now | Current prompt has known footwear over-extraction defect. Expanding now wastes the 20 new samples as a validation set — they'd just confirm known problems. P0-first makes them a meaningful test of whether fixes work. | Expanding immediately (20 new samples × broken prompt = more broken footwear data, no new insights) |
| Did NOT auto-execute any code changes | User asked a strategic question ("有必要扩大吗"). Answered with analysis, not execution. P0 execution requires user go-ahead. | Jumping into editing experiment_vlm_analysis.py without discussion |

## Evidence & Data

### Dataset Inventory

```
vlm/data/SN_6_3D_dataset/          → 34 samples (char_001–034)
  Each: char_NNN.json (GT) + char_NNN.png + char_NNN_front_view.png

vlm/data/smoke_test/               → 20 samples (char_001–020)
  Each: 2-3 char_NNN*.json files + images

vlm/data/element_extraction_results_sn6_local/  → 4 samples (char_001–004)

vlm/tmp/supervision_agent_output/  → 34 samples (char_001–034)
  Each: extraction/char_NNN/extracted_elements.json
```

### Smoke Test GT Format (spot check needed)

The smoke_test GT files likely have a different structure from SN_6_3D_dataset. The smoke_test was used for RunningHub 3D generation evaluation — JSON files may include fields like:
- `identity_score` — cosine similarity between 2D reference and 3D output
- `visual_score` — aesthetic quality rating
- `generated_images` — paths to RunningHub outputs
- Element annotations may be nested differently

**This format difference is a risk for dataset merging** — the evaluation script's `load_ground_truth()` assumes `list[dict]` with `{name, value}`. Smoke test GT may need format adaptation.

### Smoke Test File Listing (char_001 example)

```
vlm/data/smoke_test/char_001/
├── char_001.json          # GT annotations (primary?)
├── char_001_batch.json    # Batch review results (identity/visual scores?)
├── char_001_front_view.png
└── ... (generated images from RunningHub)
```

The 2-3 JSON files per character likely represent:
- `char_NNN.json` — original human GT annotations (element list)
- `char_NNN_batch.json` — batch processing results with RunningHub scores
- Possibly a third file for multi-angle or re-annotation

**Spot check command for next session:**
```bash
python3 -c "
import json
for f in ['char_001.json', 'char_001_batch.json']:
    d = json.load(open(f'/home/intern/jsy/vlm/data/smoke_test/char_001/{f}'))
    print(f'--- {f} ---')
    print(f'  type: {type(d).__name__}')
    if isinstance(d, dict):
        print(f'  keys: {list(d.keys())[:15]}')
        for k in list(d.keys())[:5]:
            v = d[k]
            print(f'  {k}: {type(v).__name__} = {str(v)[:120]}')
    elif isinstance(d, list):
        print(f'  len: {len(d)}')
        if d: print(f'  first: {str(d[0])[:200]}')
"
```

### Full Dataset Cross-Reference Matrix

| Char | SN_6_3D GT | SN_6_3D VLM | Smoke GT | Smoke VLM | elem_extract |
|------|-----------|-------------|----------|-----------|--------------|
| char_001–020 | ✅ | ✅ | ✅ | ❌ | char_001–004 only |
| char_021–034 | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Total usable** | 34 | 34 | 20 | 0 | 4 (mystery) |

char_001–020 are the overlap — they exist in both datasets. This means we could compare GT annotations between SN_6_3D_dataset and smoke_test for the same characters, potentially identifying annotation differences or version drift.

### Merge Strategy Options

| Strategy | Effort | Risk | Outcome |
|----------|--------|------|---------|
| A) Copy smoke_test chars into SN_6_3D_dataset dir | Low (file copy) | File conflicts (char_001–020 already exist) | Lose one dataset's GT for overlap chars |
| B) Create merged dir with symlinks | Low | Symlink portability | Clean, preserves both sources |
| C) Modify script to iterate multiple DATA_DIRs | Medium (code change) | Regression (breaks single-dir mode) | Most flexible, supports future expansion |
| D) Run smoke_test separately, compare reports | Low (no code change) | Manual merge, no unified metrics | Fastest to execute, weakest analysis |

### Parent Baseline Metrics (for reference)

| Metric | Value |
|--------|-------|
| Samples | 34 |
| GT elements | 204 |
| VLM predictions | 272 |
| Coverage (recall) | 95.1% |
| Precision | 71.3% |
| Avg similarity | 0.678 |
| Footwear precision | 28.6% (worst) |
| Runtime | 139s (batch embedding) |

## Code Analysis

### Integration Points for Smoke Test GT

The evaluation script currently makes two assumptions that would break with smoke_test data:

1. **`DATA_DIR` hardcoded to `SN_6_3D_dataset`** (line ~28): `DATA_DIR = "vlm/data/SN_6_3D_dataset"`. To support both datasets, this needs to become a list or the script needs a `--data-dir` CLI argument. Simplest approach: copy/link smoke_test chars into SN_6_3D_dataset, or create a merged directory.

2. **`load_ground_truth(char_dir)` expects single `char_NNN.json`** (line ~80): `gt_path = os.path.join(char_dir, f"{char_name}.json")`. Smoke_test has 2-3 JSON files per char. Need to either: (a) identify which JSON is the canonical GT, or (b) merge elements from all JSONs for that character.

3. **GT format assumption: `list[dict]` with `{name, value}`** (line ~95): The function iterates `gt_data` expecting it to be a list of element dicts. Smoke test JSONs may wrap elements in a nested structure (e.g., `{"elements": [...], "identity_score": 0.85}`). Would need a format adapter or `load_ground_truth()` branch.

4. **VLM extraction path assumption** (line ~60): `load_vlm_extraction()` constructs path as `vlm/tmp/supervision_agent_output/{char}/extraction/{char}/extracted_elements.json`. This is consistent for all characters regardless of which GT dataset they belong to — no change needed here, but the `run_experiment()` loop only iterates characters found in `DATA_DIR`. Adding smoke_test chars means ensuring they also have VLM extraction output at this path.

### Functions That Need Modification for Dataset Merge

| Function | Change Needed | Impact |
|----------|--------------|--------|
| `load_ground_truth()` | Accept smoke_test format variant | Medium — format detection + adapter |
| `run_experiment()` | Iterate over merged char list | Low — change directory scan logic |
| `DATA_DIR` constant | Support multiple source dirs | Low — list or CLI flag |
| VLM extraction pipeline (separate script) | Run on 20 new chars | High — 160 min GPU time, separate codebase |

### Environment Constants (verified this session)

```python
OLLAMA_BASE = "http://127.0.0.1:11434"
EMBED_MODEL = "bge-m3:latest"        # 1024-dim vectors, multilingual
EMBED_BATCH_ENDPOINT = "/api/embed"   # accepts input: [str, ...]
PYTHON_BIN = "/usr/bin/python3"       # system python3 (venv broken)
MIN_SIMILARITY = 0.5                  # current; recommend 0.6
```

## Files Changed

None this session. Parent state preserved:
- `vlm/experiment_vlm_analysis.py` — MODIFIED (343 lines, adapted for local data)
- `vlm/experiment_results/experiment_results.json` — MODIFIED (190KB, 34-sample results)
- `vlm/experiment_results/experiment_report.md` — MODIFIED (30KB, per-sample tables)
- `vlm/experiment_results/failure_patterns.md` — NEW, untracked (11KB, 7 patterns)
- `vlm/experiment_vlm_analysis.py.bak` — NEW, untracked (17.9KB, original backup)

## User Feedback & Preferences

- **"现在有必要扩大这个数据的体量吗"** — User is thinking strategically about sample size vs effort. Values efficiency.
- **"我现在有大约五十四个样本了"** — User has been collecting/annotating data and wants to leverage it.
- **"你觉得只要做这个修复吗，你可以把当前vlm提取元素中的偏误问题输出给我吗"** — User wants comprehensive bias analysis, not just the footwear fix. Wants to understand ALL problems before acting.
- **"写到最新的handoff文档中，然后commit到我的git仓库"** — User wants analysis persisted to handoff AND committed. Values documentation + traceability.
- **Paste prompt style (inherited from parent):** "Do NOT onboard, explore, or ask questions. The plan has everything. Build." — User prefers execution over deliberation when a plan exists.
- **No auto-commit/push (inherited from parent):** Give git commands, don't auto-commit. No commits were made this session.
- **Core focus is 2D extraction (inherited from parent):** 3D supervision review is a separate downstream pipeline. Keep evaluation focused on extraction quality.
- **User opened `atomic_rules_generated.json`** in IDE — exploring pipeline outputs, familiarizing with data formats across the supervision pipeline.

---

## VLM Extraction Bias Analysis — Complete Taxonomy

*Cross-referenced from: `failure_patterns.md` (7 patterns), `experiment_report.md` (34-sample per-sample matches), `element_extraction_from_2d.txt` (97-line prompt template).*

### Category A: Prompt Defects (fixable by editing `.txt` alone)

| # | Bias | Severity | Evidence | Root Cause in Prompt |
|---|------|----------|----------|---------------------|
| **A1** | **Footwear over-extraction** | CRITICAL | 35 preds, only 10 matched (28.6% precision). 25 false positives across 34 samples. | Line 31: `鞋靴（清晰可见时提取）` has NO constraint. Compare line 21 (eyes): `仅当颜色特殊时单独提取` — same pattern should apply to footwear. |
| **A2** | **"Inner layer" hallucination** | MODERATE | char_014 extracted `内搭: 灰色衣物，正面可见一排黑色纽扣` — completely obscured by outer jacket. char_002: `白色高领内搭` matched to wrong GT (0.698 but semantically off). | Line 25 says `不可见的层次不提取` but model ignores it. The anti-hallucination section (lines 5-8) needs a stronger, explicit constraint about occluded items. |
| **A3** | **Prop hallucination** | MODERATE | 4 prop preds, 0 matched (0% precision). char_014: `双持枪械` extracted but human GT merges weapons into compound `双枪武器`. | Line 32: `手持道具、武器` has no quality gate — model invents weapon-like elements from ambiguous details (belt attachments, folds). |
| **A4** | **Pose/gesture scope mismatch** | MODERATE | 5 of 10 missed GT elements are pose descriptions: `右手姿势`, `左手自然下垂`, `蹲姿与右手部姿势`, `左手部姿势`, `右手自然垂下`. | Prompt never asks for poses — model correctly ignores them. This is a scope alignment issue, not extraction failure. Either add pose instruction or exclude from GT eval. |

### Category B: Over-Extraction Tendency (systematic, partly by design)

| # | Bias | Severity | Evidence | Root Cause |
|---|------|----------|----------|------------|
| **B1** | **Accessory splitting** | MODERATE | 65 preds, 67.7% precision. VLM splits `右臂金属护具`, `项链`, `胡须`, `耳饰` — human annotators merge into compound names. | Prompt line 13: `不同物品不要合并到同一个元素中` — VLM follows this correctly! The mismatch is that human GT violates this rule by merging. |
| **B2** | **8.0 preds/sample vs human 6.0 (+33%)** | MODERATE | 272 vs 204 total. char_002 extreme: 11 VLM vs 5 human. char_006: 10 VLM vs 6 human. char_014: 9 VLM vs 6 human. | Prompt line 12: `每角色通常提取 5–8 个元素` is a soft guideline, not enforced. Line 12 also says `精准为主，覆盖为辅` but model defaults to coverage. |
| **B3** | **Face elements swallowed by compound GT** | MODERATE | 65% face precision. `面部纹路` → matched to `红色长外套与金色火焰纹饰` (0.502). `胡须` → matched to `红色披风` (0.504). `耳饰` → matched to `左手黑色手套与袖套` (0.570). | Cascading greedy match failure — face is always last to match, gets garbage. GT merges face into clothing compounds. |

### Category C: Calibration Failures

| # | Bias | Severity | Evidence | Root Cause |
|---|------|----------|----------|------------|
| **C1** | **All 272 preds marked confidence="high"** | LOW (systemic) | Includes 4 hallucinated props, 25 unmatched footwear, all cascading false matches. Zero `medium` or `low` usage. | Model has no self-calibration. Prompt line 9 provides `confidence=low` option but model never uses it. |
| **C2** | **No "unsure" signal** | LOW | `胡须` (matched to cape, sim 0.504) still gets `high`. `内搭` (occluded) still gets `high`. | Structured output field is filled mechanically — the confidence field is a compliance exercise, not a quality signal. |

### Concrete Examples of Cascading Failures (char_011)

```
Human GT: ["粉色猫耳与猫尾", "粉色长卷发与发饰", "棕色腰带与黄色大蝴蝶结",
           "淡紫色和服上衣与花卉图案", "深棕色下裙与底部花纹", "白色袜子与木屐"]

VLM: 兽耳(0.679✓) → 尾巴(0.605✓) → 头发(0.572→"腰带与蝴蝶结"✗) →
     蝴蝶结发饰(0.559→"和服上衣"✗) → 和服上衣(0.605→"下裙"✗) → 腰带(0.529→"袜子与木屐"✗)

Extra (correctly extracted but no dedicated GT): 眼睛, 下身裙装, 木屐
```

Only 2/6 matches are semantically correct. 4/6 are cascading false matches. The 3 "extras" are actually correct sub-elements that human GT merged into compounds.

### Fixability Matrix

| Fix | Type | What to Edit | Expected Impact |
|-----|------|-------------|-----------------|
| Footwear constraint | **Prompt** | Line 31: add `仅当设计特征明显时提取` gate, mirroring eyes (line 21) pattern | ~25 false positives eliminated, precision +8% |
| Anti-inner-layer hallucination | **Prompt** | Lines 5-8: add `被外层衣物完全遮挡的内搭一律不提取。确有可见内搭时，只描述露出部分。` | Eliminates occluded inner-layer fabrications |
| Prop guard | **Prompt** | Line 32: add `仅当武器/道具清晰可见且为角色标志性装备时提取。不确定时省略。` | Props from 0% → est. 50% precision |
| Pose scope alignment | **Prompt** | Add line ~12: `如角色姿势/手势有显著特征（特殊手势、战斗姿态等），可单独提取。` | Closes 5/10 missed GT gap |
| Face sub-prompt | **Architecture** | Two-pass extraction: full-body first, then face-only crop | Face precision 65% → est. 80%+ |
| MIN_SIMILARITY → 0.6 | **Eval script** | Line 30: change `0.5` to `0.6` | Filters 31% cascading false matches |
| Relaxed precision metric | **Eval script** | New metric: any-GT-match above 0.6 | Better reflects true quality under granularity mismatch |

### Prompt Edits — Exact Changes Needed

**File:** `vlm/prompts/supervision/element_extraction_from_2d.txt`

**Edit 1 — Line 7 (anti-hallucination, add after existing line):**
```
- 被外层衣物完全遮挡的内搭一律不提取。确有可见内搭（领口、袖口、下摆露出部分）时，只描述露出部分。
```

**Edit 2 — Line 12 (extraction principle, modify):**
```
- 精准为主，覆盖为辅。每角色通常提取 5–8 个元素；提取"对监修最重要的可见特征"，而非穷举所有可见物品。如有疑问，省略该元素。
```

**Edit 3 — Line 31 (footwear, replace entirely):**
```
- 鞋靴：仅当设计特征明显（特殊颜色、独特造型、绑带/扣件等装饰细节）时提取。普通黑色/棕色皮鞋、常见运动鞋、基本款凉鞋不提取。袜类同理，仅当有明显图案、特殊长度或独特设计时提取。
```

**Edit 4 — Line 32 (props, replace):**
```
- 手持道具、武器：仅当清晰可见且为角色标志性装备时提取。不确定时省略。
```

**Edit 5 — Line 12 area (pose, add new line):**
```
- 姿势/手势：如角色姿势或手势有显著性特征（特殊手势、战斗姿态、标志性站姿等），可单独提取为一个元素。
```

## Where We're Going

1. **Apply 5 prompt edits to `element_extraction_from_2d.txt`** — exact changes documented in "Prompt Edits" section above. One file, 5 line changes.
2. **Re-extract VLM elements on 20 smoke_test samples** using the fixed prompt — `python -m vlm.scripts.supervise.run_element_extraction --data-root vlm/data/smoke_test --output-root vlm/tmp/supervision_agent_output` (verify CLI flags first). ~160 min GPU time.
3. **Raise MIN_SIMILARITY to 0.6** in `experiment_vlm_analysis.py` line 30.
4. **Re-run evaluation on all 54 samples** — `PYTHONUNBUFFERED=1 /usr/bin/python3 vlm/experiment_vlm_analysis.py`. Compare pre-fix vs post-fix metrics.
5. **Add relaxed precision metric** — new metric column in report: % of VLM preds with similarity > 0.6 to ANY GT element.
6. **After metrics stabilize**: Face sub-prompt (architectural change), numeric confidence scoring (P3).

## Risks & Blockers

- **Smoke test GT format is unverified** — may require format adaptation before it works with `load_ground_truth()`. The smoke_test JSONs have 2-3 files per character (different versions/viewpoints), unlike SN_6_3D_dataset's single file. Need to determine which file is the canonical GT.
- **20-sample VLM extraction takes ~160 min GPU time** — qwen36-vl inference is the bottleneck. Must run sequentially or with controlled concurrency to avoid OOM (qwen36-vl uses 38GB/42GB VRAM).
- **P0 recommendation is not yet user-approved** — the parent handoff listed it as "needs user approval." This session reinforced the recommendation but didn't get explicit confirmation.
- **Working tree is dirty** — 5 files in modified/untracked state. Should be committed or cleaned before next code changes to avoid confusion.

## Open Questions

- [ ] **P0-first or expand-now?** User asked the question, got a recommendation, but hasn't confirmed. This is the entry point for next session.
- [ ] **What is the smoke_test GT format exactly?** Need to spot-check one file to determine if format adaptation is needed.
- [ ] **Which smoke_test JSON per character is canonical?** 2-3 files exist per char. May correspond to different viewpoints or annotation rounds.
- [ ] **What are the 4 samples in `element_extraction_results_sn6_local/`?** Purpose and format unknown — may be early extraction test outputs.
- [ ] **All 6 parent open questions remain open** — threshold, pose scope, batch ceiling, cache persistence, relaxed precision, confidence scores.

## Quick Start for Next Session

```bash
# Restore context
cat /home/intern/jsy/.claude/handoffs/HANDOFF_standalone-bbd103dc_dataset-expansion-assessment_2026-07-28.md

# Key files to read first
# 1. vlm/prompts/supervision/element_extraction_from_2d.txt — THE prompt to edit (5 line changes)
# 2. vlm/experiment_results/failure_patterns.md — 7 patterns, 6 recommendations (reference)
# 3. vlm/experiment_vlm_analysis.py — evaluation script (MIN_SIMILARITY at line 30)

# Verify environment
python3 -c "import requests; print('requests OK')"
curl -s --noproxy '*' http://127.0.0.1:11434/api/embed \
  -d '{"model":"bge-m3:latest","input":["测试"]}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Embedding OK: {len(d[\"embeddings\"][0])}d')"

# Step 1: Apply the 5 prompt edits (documented in "Prompt Edits" section above)
# Step 2: Re-extract on 20 smoke_test samples with fixed prompt
# Step 3: Raise MIN_SIMILARITY to 0.6 in experiment_vlm_analysis.py line 30
# Step 4: Re-run evaluation
PYTHONUNBUFFERED=1 /usr/bin/python3 vlm/experiment_vlm_analysis.py

# Step 5: Compare pre-fix vs post-fix metrics
```
