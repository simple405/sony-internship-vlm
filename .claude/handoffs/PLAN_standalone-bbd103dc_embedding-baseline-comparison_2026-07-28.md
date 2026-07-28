# Plan: Adapt Existing Comparison Script for 34-Sample Baseline Evaluation

**Date:** 2026-07-28
**Status:** PLANNED
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-bbd103dc` seq `3`
**Context:** See `HANDOFF_standalone-bbd103dc_embedding-baseline-comparison_2026-07-28.md` for session data, element formats, and bge-m3 configuration.

---

## Problem Statement

Evaluate `qwen36-vl:latest`'s 2D element extraction quality against human annotations for 34 samples. A comparison script already exists (`vlm/experiment_vlm_analysis.py`, 452 lines) with embedding-based semantic matching via bge-m3, but it's hardcoded for a dataset not on this server and uses the `ollama` Python package which isn't installed. Adapt it to work with local data and raw HTTP API calls, then run the comparison and report precision/recall/F1 with per-category breakdown.

## Key Findings

- **Comparison script exists** (`vlm/experiment_vlm_analysis.py`) — 30% name + 70% text weighted cosine matching via bge-m3, greedy pred→GT matching, both JSON + Markdown output. Don't write from scratch. → drives Phase 1
- **Ground truth is on server** at `vlm/data/SN_6_3D_dataset/char_XXX/char_XXX.json` — 34 samples, elements as `dict{name: description}`. → drives Phase 1
- **VLM extraction outputs exist** at `vlm/tmp/supervision_agent_output/char_XXX/extraction/char_XXX/extracted_elements.json` — no need to re-run inference. → drives Phase 1
- **bge-m3 works via raw HTTP** (`curl --noproxy '*' http://127.0.0.1:11434/api/embeddings`) — 1024-dim vectors.→ drives Phase 1
- **`ollama` Python package not installed** — server uses raw `requests` for all Ollama calls. Must replace `ollama.chat()` / `ollama.embed()` with `requests.post()`. → drives Phase 1
- **Human annotations merge multiple elements into one name** (e.g., "金色长发与黑色蝴蝶结" = hair + headwear) — counts will differ by design. Embedding matching handles this; exact name matching would fail. → drives Phase 2 threshold analysis
- **34 samples is directional, not definitive** — per-category counts may be single-digit. Results validate methodology, not statistical significance. → drives Phase 2 interpretation

## Anti-Goals (What NOT To Do)

- **Do NOT re-run VLM inference.** 34 pre-extracted `extracted_elements.json` already exist. Re-inference wastes ~160 min of GPU time with no benefit.
- **Do NOT install the `ollama` Python package** unless simpler than porting to `requests`. Server uses raw HTTP everywhere else — stay consistent.
- **Do NOT write a new comparison script from scratch.** The existing `experiment_vlm_analysis.py` has matching logic, caching, metrics, and report generation. Adapt, don't rebuild.
- **Do NOT change the matching algorithm** (30/70 weighted, greedy) unless evidence shows it's wrong. Algorithm was designed for this exact problem.
- **Do NOT wait for the 6000-sample dataset.** 34 samples is enough to validate the approach and identify extraction failure patterns.

## Plan

### Phase 1: Adapt `vlm/experiment_vlm_analysis.py` for Local Data

**Goal:** Make the existing comparison script runnable against `SN_6_3D_dataset` using pre-extracted VLM outputs and raw HTTP embeddings.

**Why this approach:** The script already has the correct matching algorithm (30/70 weighted cosine, greedy match). The changes are mechanical: data paths, GT format, and API transport. Adapting is ~15 lines of changes vs writing 450+ lines from scratch.

1. **Change `DATA_DIR`** from `"vlm/data/SN_6期动漫数据标注"` to `"vlm/data/SN_6_3D_dataset"`.
2. **Replace VLM inference** — `analyze_image()` currently calls `ollama.chat()` to re-extract elements. Replace with loading pre-existing `extracted_elements.json`:
   ```python
   # OLD: pred = analyze_image(str(image_path))
   # NEW:
   extraction_path = f"vlm/tmp/supervision_agent_output/{char_name}/extraction/{char_name}/extracted_elements.json"
   with open(extraction_path) as f:
       pred = json.load(f)
   pred_elements = pred.get('elements', [])
   ```
3. **Fix GT format** — `load_ground_truth()` currently returns `dict` with `elements` key that the script treats as a list. But `char_XXX.json` has `elements` as `dict{name: description}`, not a `list`. Convert:
   ```python
   # GT format: {"金色长发与黑色蝴蝶结": "角色拥有飘逸的...", ...}
   # Convert to list of {name, value} dicts for match_elements():
   gt_raw = json.load(open(json_path))
   gt_elements = [{"name": name, "value": value} for name, value in gt_raw['elements'].items()]
   ```
4. **Replace `ollama.embed()` with raw `requests.post()`** in `OllamaEmbedder.encode()`:
   ```python
   # OLD: resp = ollama.embed(model=self.model_name, input=text)
   # NEW:
   resp = requests.post(
       "http://127.0.0.1:11434/api/embeddings",
       json={"model": self.model_name, "prompt": text},
       proxies={"http": None, "https": None},  # bypass corporate proxy
       timeout=30
   )
   emb = np.array(resp.json()['embedding'], dtype=np.float32)
   ```
5. **Remove `import ollama`** — replace with `import requests` (already likely available from existing pipeline scripts).
6. **Keep everything else intact**: `match_elements()` (greedy matching, 30/70 weights), `generate_report()`, metrics computation, `OllamaEmbedder` cache.
7. **Test on char_001 first** before running full 34-sample loop. Verify: GT loaded correctly (5 elements as list), VLM loaded (8 elements), embeddings computed, matches found.

**Files:** `vlm/experiment_vlm_analysis.py` — modify ~20 lines
**Validates with:** Run on char_001 only, check console output shows "Matched: N, Unmatched pred: M, Unmatched GT: K" with reasonable similarity scores (0.6–0.9). Save to `vlm/experiment_results/experiment_results.json`.
**Rollback:** `git checkout vlm/experiment_vlm_analysis.py` — the file is not yet committed, so backup first.

### Phase 2: Run Full 34-Sample Comparison and Analyze Results

**Goal:** Run the adapted script on all 34 samples, then analyze precision/recall/F1 with per-category breakdown.

**Why this approach:** Phase 1 proves the script works on one sample. Phase 2 scales to all 34 and produces the actual evaluation.

1. **Run full comparison**: `python3 vlm/experiment_vlm_analysis.py` — processes all 34 samples. Expected runtime: ~2-5 minutes (600-700 embedding API calls at ~200ms each, plus overhead).
2. **Review aggregate metrics** in `vlm/experiment_results/experiment_results.json`:
   - Overall coverage (GT recall): what % of human-annotated elements did VLM find?
   - Overall precision: what % of VLM extractions matched a human element?
   - Avg similarity: how close are matched descriptions semantically?
3. **Per-category analysis** — extend script to group by VLM `category` field (hair, face, clothing, accessory, headwear):
   - Which categories does VLM excel at? (expect clothing/face > accessories)
   - Which categories have lowest recall? (expect merged human elements to cause "missed" on sub-elements)
   - Which categories generate most false positives? (expect accessories — VLM may hallucinate small details)
4. **Threshold sensitivity** — run at multiple thresholds (0.6, 0.65, 0.7, 0.75, 0.8) if the matching algorithm uses a hard cutoff. Currently the script uses greedy max-match without threshold, so unmatched simply means all GT candidates were claimed by other predictions. Consider adding a minimum similarity threshold to prevent low-quality matches.
5. **Spot-check 3 borderline samples manually** — one with highest unmatched count, one with lowest similarity, one where VLM count ≈ human count but matches are poor.

**Files:** `vlm/experiment_vlm_analysis.py` — may add category tracking; `vlm/experiment_results/experiment_results.json` — output; `vlm/experiment_results/experiment_report.md` — human-readable report
**Validates with:** Overall coverage > 0.7, overall precision > 0.6, avg similarity > 0.7. Per-category breakdown with no category catastrophically failing (all > 0.5).
**Rollback:** results are additive — no code changes to roll back in this phase (beyond optional category tracking).

### Phase 3: Document Extraction Failure Patterns

**Goal:** Identify systematic VLM extraction errors that could be corrected via prompt engineering or fine-tuning.

**Why this approach:** The 34-sample eval is too small for definitive conclusions about model quality, but it's exactly the right size for finding patterns. Pattern identification feeds into the next iteration (prompt improvements or fine-tuning data prep).

1. **Categorize unmatched GT elements** (VLM missed): common patterns? Are they small/detailed accessories? Elements merged into human compound names? Background elements?
2. **Categorize unmatched VLM predictions** (VLM hallucinated): common patterns? Over-splitting of clothing items? Reading details that don't exist?
3. **Check confidence vs accuracy** — all VLM confidences are "high". Add `confidence` realism note to findings.
4. **Compare with 3D review results** — do samples that "failed" 3D review (char_015, char_011, etc.) also have poor extraction quality? Or is extraction quality independent of 3D manufacturing quality? This is a sanity check.
5. **Write findings to** `vlm/experiment_results/failure_patterns.md` — structured for use in next prompt iteration.

**Files:** `vlm/experiment_results/failure_patterns.md` — new analysis document
**Validates with:** Document has ≥5 specific patterns with examples (sample_id + element name), and ≥2 actionable recommendations for prompt improvement.
**Rollback:** N/A — additive analysis.

## Dependencies & Order

- Phase 1 must complete before Phase 2 (can't run full comparison until script works on one sample)
- Phase 2 must complete before Phase 3 (need metrics to identify failure patterns)
- All phases are sequential — no parallelism possible
- Each phase is ≤30 minutes of work

## Risks & Mitigations

- **`requests` package not installed** — unlikely (existing pipeline scripts use it), but if missing: `pip install requests` or `python3 -m pip install requests`. Low risk.
- **bge-m3 API returns errors for certain texts** — very long Chinese descriptions might fail. Mitigation: add try/except around embedding calls, fall back to name-only similarity if text embedding fails. Low risk.
- **Ollama service goes down mid-run** — service has been stable for 6 weeks. Mitigation: check `systemctl status ollama` before starting. Low risk.
- **Greedy matching produces misleading matches** — pred-to-GT greedy means early predictions "steal" the best GT match, leaving later predictions with poor matches. This inflates precision. Mitigation: also report the per-match similarity distribution, not just counts. Flag any matches below 0.5 as suspicious. Medium risk.
- **GT format conversion loses information** — `dict{name: desc}` → `list[{name, value}]` flattens the structure. The compound name IS semantically meaningful. Mitigation: keep original name as the `name` field; the embedding comparison text combines `name + value`. Low risk.

## Success Criteria

- **Minimum viable**: Script runs on all 34 samples without crashing, outputs aggregate metrics (coverage, precision, avg similarity) with per-sample detail.
- **Full success**: Per-category breakdown showing clear strengths/weaknesses, ≥3 documented failure patterns with sample evidence, ≥2 actionable prompt improvement recommendations.
- **Baseline numbers to beat** (from handoff Evidence):
  - Human element count range: 4–8 per sample (total ~180 across 34)
  - VLM element count range: 4–11 per sample (total 272 across 34)
  - Expected coverage (recall): 0.65–0.85 (VLM should find most human-annotated elements, modulo granularity differences)
  - Expected precision: 0.55–0.75 (VLM over-extracts — 272 vs ~180)

## Quick Start

```bash
# Restore full context
cat /home/intern/jsy/.claude/handoffs/HANDOFF_standalone-bbd103dc_embedding-baseline-comparison_2026-07-28.md

# Key source files for Phase 1
# 1. vlm/experiment_vlm_analysis.py (EXISTING — read the whole file, 452 lines)
# 2. vlm/data/SN_6_3D_dataset/char_001/char_001.json (ground truth format)
# 3. vlm/tmp/supervision_agent_output/char_001/extraction/char_001/extracted_elements.json (VLM format)

# Backup the existing script before modifying
cp vlm/experiment_vlm_analysis.py vlm/experiment_vlm_analysis.py.bak

# Verify Ollama embedding works
curl -s --noproxy '*' http://127.0.0.1:11434/api/embeddings \
  -d '{"model":"bge-m3:latest","prompt":"金色长发与黑色蝴蝶结"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'OK: {len(d[\"embedding\"])}d')"

# Verify requests is available
python3 -c "import requests; print('requests OK')"

# First concrete action
# Edit vlm/experiment_vlm_analysis.py:
#   Line 28: DATA_DIR = "vlm/data/SN_6_3D_dataset"
#   Line 30-31: Remove MODEL_NAME (no longer needed for inference)
#   Replace analyze_image() call → load extracted_elements.json
#   Fix load_ground_truth() → convert dict elements to list
#   Replace ollama.embed() → requests.post() with proxy bypass
```
