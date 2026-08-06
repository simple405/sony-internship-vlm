# Phase B: Paired Front-View Reviewer Baseline — Design

Date: 2026-08-06
Status: Approved (small-batch implementation authorized by user; final review pending after pilot run)

## 1. Goal

Implement a Qwen-VL reviewer baseline that judges each generated PVC front-view
image (`vlm/data/front_view_generation_v1/<sample_id>/<sample_id>_q_front_view.png`)
against its paired gold JSON (`<sample_id>.json`), producing a structured,
per-element verdict without leaking the original 2D source image into the
default review request.

This is Phase B of the pipeline described in `vlm/docs/workflows/process.md`.
Phase A (generation) is complete; Phase C (human gold annotation) and Phase D
(training) are out of scope here.

## 2. Non-goals

- No training or fine-tuning.
- No review of the full 6901-sample corpus — this baseline runs only against
  the existing 20-sample pilot in `front_view_generation_v1/`.
- No original-image input in the default review request (it stays reserved
  for future dispute-review tooling, per `process.md` section 2.2).
- No changes to the Phase A generator or its output format.

## 3. Architecture

New, independent script: `vlm/scripts/supervise/run_paired_front_view_review.py`.

It is **not** a mode/branch of `run_multicategory_supervision_review.py`,
because the input shape (single generated image + gold JSON with
`element/description/bbox`), and output schema (`rule_index/result/
evidence_bbox/...` per `process.md` section 3) are both different from the v3
multicategory schema (`front_status/side_status/back_status` triplets driven
by `atomic_rules` configs). The new script reuses only generic helpers by
copying the same small, dependency-free patterns already used in the sibling
script (image→data-URI encoding, DashScope chat call, tolerant JSON
extraction) rather than importing from it, to keep the two schemas fully
decoupled.

### Components

1. **Sample discovery** — scan `vlm/data/front_view_generation_v1/` for
   sample directories containing all three deliverable files
   (`<id>_original.<ext>`, `<id>_q_front_view.png`, `<id>.json`). Skip
   `_metadata/` and any incomplete directory. Support `--sample-id` (repeatable)
   and `--limit` like the generator script, for consistency.
2. **Prompt loader** — reads the frozen prompt template file (see §4) and the
   sample's gold JSON (list of `{element, description, bbox}`), and builds the
   final request text: template + a rendered list of gold elements (numbered,
   matching `rule_index`).
3. **Qwen VL client** — single-image chat call (`qwen-vl-max` by default,
   overridable via `QWEN_VISION_MODEL`/`--model`), `response_format:
   {"type": "json_object"}`, credentials from `vlm/config/api.env` via the
   existing `load_env_file`/`require_key` pattern.
4. **Parser + validator** — reuses the `extract_json_object`-style tolerant
   JSON parsing, then validates the returned `rules` array against the gold
   element count/order (must contain exactly one entry per gold element, in
   the same order — enforced the same way `lock_rule_ids_to_input` enforces
   rule identity in the sibling script), validates `result` is one of the five
   allowed enum values, and records violations as QC rows rather than failing
   the whole sample.
5. **Output writer** — per-sample verdict JSON + flattened CSV/JSONL for
   spreadsheet review, plus a batch-level summary (verdict distribution,
   fail/review queue, parse-failure list).

### Data flow

```
<sample_id>_q_front_view.png ─┐
                               ├─> build_messages() ─> Qwen VL chat ─> raw text
<sample_id>.json (gold) ──────┘                                         │
                                                                          v
                                                          extract_json_object()
                                                                          │
                                                                          v
                                                    validate + QC (rule_index align)
                                                                          │
                                                                          v
                        vlm/tmp/paired_front_view_review_v1/<sample_id>/{prediction.json, qc.csv}
                        vlm/tmp/paired_front_view_review_v1/batch_summary.json
```

Output goes to `vlm/tmp/` (scratch, gitignored), not `vlm/data/`, because this
is a baseline experiment, not a durable dataset artifact — consistent with the
project convention "`vlm/tmp/` for scratch outputs, `vlm/data/` for durable
datasets."

## 4. Prompt: location and freezing

- File: `vlm/prompts/supervision/paired_front_view_review_v1_cn.txt`.
- Placed alongside the existing `qwen_prompt_v3_*.txt` files but named
  `_v1` to make clear it is an independent contract, not a v3 variant.
- At run time, the script snapshots the exact prompt text used into
  `_metadata`-style output per sample: `<output_root>/<sample_id>/review_prompt.txt`
  plus `review_prompt_sha256` recorded in the per-sample prediction JSON's
  `metadata` block. This mirrors the Phase A generator's prompt-snapshot
  pattern so any batch run can be traced back to an exact prompt version.
- Future prompt changes create a new `_v2` file; `_v1` is never overwritten,
  so historical review runs stay reproducible.

## 5. Output contract (per sample)

Top-level JSON (`prediction.json`):

```json
{
  "schema_version": "paired_front_view_review.v1",
  "sample_id": "1-1020644465",
  "inputs": {
    "generated_image": "vlm/data/front_view_generation_v1/1-1020644465/1-1020644465_q_front_view.png",
    "gold_json": "vlm/data/front_view_generation_v1/1-1020644465/1-1020644465.json",
    "source_image_used": false
  },
  "rules": [
    {
      "rule_index": 1,
      "element": "金色长发与黑色蝴蝶结",
      "result": "pass | partial | fail | not_evaluable | review",
      "image_grounded": true,
      "description_correct": true,
      "issue_types": [],
      "observed_description": "...",
      "evidence_bbox": [x1, y1, x2, y2],
      "confidence": 0.91,
      "reason": "..."
    }
  ],
  "extra_elements": [
    {
      "element": "红色蝴蝶发夹",
      "observed_description": "...",
      "evidence_bbox": [x1, y1, x2, y2],
      "confidence": 0.82,
      "issue_types": ["extra"],
      "reason": "..."
    }
  ],
  "aggregate_counts": {"pass": 0, "partial": 0, "fail": 0, "not_evaluable": 0, "review": 0},
  "overall_decision": "pass | fail | review",
  "metadata": {"model": "qwen-vl-max", "review_prompt_sha256": "...", "elapsed_seconds": 0.0}
}
```

Rules:

- `evidence_bbox` is always in the **generated image's pixel coordinate
  system** (fixed 1915×821 for this pilot), matching the gold JSON's own
  `[x1, y1, x2, y2]` bbox style so both can be visualized with the same
  drawing code. This must never be confused with the gold bbox, which is in
  the original 2D source image's coordinate system — the two are not
  comparable and the script does not attempt to reconcile them.
- `rule_index` is 1-based and must match the gold element's position in its
  JSON array; the script overwrites whatever the model returns to enforce
  this (mirrors `lock_rule_ids_to_input`).
- `extra_elements` entries are for salient generated content with no
  corresponding gold element — never merged into an existing `rule_index`.
- `overall_decision`: `fail` if any rule is `fail`; else `review` if any rule
  is `review` or overall confidence is low; else `pass`.

## 6. Dry-run / request-preview validation (pilot-only, before real calls)

Before spending API budget, `--dry-run` on all 20 pilot samples must produce,
per sample, a redacted request preview (`request_preview.json`) analogous to
the generator's, asserting and recording:

- Exactly one image is referenced in the request payload, and it is the
  `_q_front_view.png` path — never the `_original.<ext>` path.
- The gold JSON's element list was read (to build the numbered prompt) but
  the file path of the *original* image never appears anywhere in the
  serialized preview.
- `prompt_chars` and `gold_element_count` are recorded for a quick sanity
  check that the prompt scales with element count as expected.

This reuses the same audit approach Phase A used (20/20 dry-run before the
real pilot) — inspecting the serialized preview for absence of forbidden
paths/content, not just structural fields.

## 7. Baseline run and summary

After dry-run validation passes for all 20 samples, run the real batch
(`--limit 20`, no `--dry-run`) and produce `batch_summary.json`:

```json
{
  "schema_version": "paired_front_view_review_batch.v1",
  "sample_count": 20,
  "verdict_distribution": {"pass": 0, "partial": 0, "fail": 0, "not_evaluable": 0, "review": 0},
  "overall_decision_distribution": {"pass": 0, "fail": 0, "review": 0},
  "fail_or_review_sample_ids": ["..."],
  "parse_failures": ["..."]
}
```

`parse_failures` lists sample IDs where the model response could not be
parsed into valid JSON even after tolerant extraction, or failed rule-count/
order validation — these go into the human review queue same as `fail`/
`review` verdicts, per `process.md`'s "低置信度、描述含糊或证据不足进入 review"
rule.

The script explicitly refuses `--limit` values that would exceed the 20
pilot samples currently on disk unless `--sample-id` is passed explicitly,
as a guard against accidentally scaling to the full 6901-sample corpus.

## 8. Testing

Following `vlm/tests/test_generate_paired_front_view.py`'s style: unit tests
for sample discovery (only complete 3-file dirs are picked up), prompt
rendering (gold element list numbering matches `rule_index`), request-preview
leak checks (original image path never appears, exactly one image
referenced), and the rule-alignment validator (rejects/repairs mismatched
counts or out-of-order `rule_index`). API calls are mocked/stubbed; no test
hits the real Qwen endpoint.

## 9. Rollout plan (small-batch first)

1. Write prompt template + script + tests.
2. Run `--dry-run` on all 20 pilot samples; manually inspect 2-3 previews.
3. Run the real baseline on a **small subset first (3-5 samples)** for the
   user to review output quality and schema shape before committing to the
   full 20-sample pilot run.
4. After user feedback, run the remaining pilot samples and produce the
   batch summary.
