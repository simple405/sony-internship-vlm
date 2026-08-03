CKPT-9  ·  Codex  ·  2026-08-03 15:14 +08:00

## SUMMARY
The SN-7 workflow has moved from the approved 12-image smoke test to the 10,610-image production dataset. The three approved source directories were imported into `vlm/data/design_sheet_10610` with globally unique source-prefixed IDs and exact six-category balancing. Qwen atomic-rule extraction and RunningHub multiview generation have both started. At this checkpoint Qwen has produced `4853` successful `atomic_rules.json` files, and RunningHub has attempted `3675` sample tasks, with `639` clean generated packages and most failures caused by RunningHub enterprise balance exhaustion.

## PROGRESS
### SN7-IMPORT — Production Dataset Prepared
  ✅ Imported `10610 / 10610` source images, with `0` rejected images and `551` duplicate raw-ID groups retained through `cs_`, `ta_`, and `cd_` prefixes.
  ✅ Wrote `manifest.csv`, `metadata.jsonl`, import reports, balanced assignment CSV, and six sample-list queues under `vlm/data/design_sheet_10610/`.
  ✅ Balanced queues: `head_key_chain=1769`, `cake_roll=1769`, and all four remaining categories `=1768`.

### SN7-QWEN — Full Atomic Rule Extraction
  ✅ Prompt and extraction normalization require every Qwen rule to return exactly `id`, `location` (`head|body`), and `value`.
  ✅ Input and credentials audited before the paid API run.
  ⏳ Qwen extraction checkpoint: `4865` sample directories, `4853 / 10610` successful `atomic_rules.json` files, `4854` raw responses, and `6` error files.
  ☐ When Qwen completes, verify all emitted rules have a legal `location` value before generation.

### SN7-RUNNINGHUB — Multiview Generation
  ✅ Smoke test verified all six category prompts and final package layout.
  ⏳ Follow-mode generation checkpoint: `3675` attempted sample task directories, `639` clean successes, and `3030` `generation_error.json` files.
  ⏳ Error breakdown: `3028` balance-insufficient (`errorCode 812`), `1` content audit rejection, and `1` image-download connection failure.
  ☐ RunningHub requests must contain only the original 2D image and category prompt. `atomic_rules.json` is local provenance and packaging input only; it is never submitted to RunningHub.

## GENERATION TASK REQUIREMENTS
This production generation task is for the full SN-7 design-sheet dataset, not the older `safebooru_2d` expansion line. Use only the three approved source pools:

```text
vlm/data/safebooru_character_sheet   6217 images
vlm/data/safebooru_turnaround        1908 images
vlm/data/角色分解                     2485 images
```

The imported dataset root is:

```text
vlm/data/design_sheet_10610
```

All `10610` images must be preserved. Duplicate raw image IDs across source directories are not dropped; they are disambiguated with source prefixes such as `cs_`, `ta_`, and `cd_`. `.gif` files are converted from the first frame to `.png`; unreadable images must be recorded in `reports/rejected_images.csv`.

Six merchandise categories must stay balanced:

```text
head_key_chain       1769
cake_roll            1769
backpack             1768
plush                1768
dataset_QSitFigures  1768
dataset_figurine     1768
```

For every sample, Qwen must read the original 2D image and emit local atomic rules only. Each rule must be a JSON object with exactly the useful visual claim fields:

```json
{"id": "hair_color", "location": "head", "value": "orange"}
```

`location` must be either `head` or `body`. For all `*_position` rules, left/right is from the annotator/viewer perspective, not the character's own perspective. Qwen output is stored under `atomic_rules/<sample_id>/`; failures write `error.json`.

RunningHub generation must use image-to-image with only:

```text
original 2D image + frozen category prompt
```

Do not send `atomic_rules.json` to RunningHub. Atomic rules are only for local provenance, filtering, and `.xlsx` packaging. RunningHub settings for this run are `resolution=1k`, `aspectRatio=21:9`, `workers=6`, `poll_interval=8`, and `timeout=1200`. The follow-mode runner should consume newly available atomic rules and must skip samples that already have output or error records.

Expected generated output is:

```text
generated/<category>/<sample_id>/
  <sample_id>_original.<ext>
  <sample_id>_atomic_rules.json
  <sample_id>_<category_suffix>.png
  <sample_id>.xlsx
```

The final deliverable must be packaged as:

```text
multi_view试标数据集_new/<category>/<sample_id>/
  2d_original.<ext>
  atomic_rules.json
  multiview_design.png
  <sample_id>.xlsx
```

For `head_key_chain`, `cake_roll`, and `backpack`, the `.xlsx` should include only `location=head` rules. For `plush`, `dataset_QSitFigures`, and `dataset_figurine`, the `.xlsx` should include all rules. Do not mechanically flip left/right during packaging; the JSON value is already expected to be in annotator-view coordinates.

## NEXT ACTION
Monitor both production outputs before restarting any paid job:

```powershell
$root = 'D:\索尼实习\vlm\data\design_sheet_10610\atomic_rules'
(Get-ChildItem -LiteralPath $root -Recurse -Filter atomic_rules.json -File).Count
(Get-ChildItem -LiteralPath $root -Recurse -Filter error.json -File -ErrorAction SilentlyContinue).Count
```

Check RunningHub task status and account balance before resuming, because most pending failures are balance-insufficient errors:

```powershell
$root = 'D:\索尼实习\vlm\data\design_sheet_10610\generated'
(Get-ChildItem -LiteralPath $root -Recurse -Filter generation_error.json -File).Count
```

The follow-mode command used for the production run was:

```powershell
.\.venv\Scripts\python.exe vlm/scripts/orchestrate/run_runninghub_merchandise_full_batch.py --dataset-dir vlm/data/design_sheet_10610 --assignment-dir vlm/data/design_sheet_10610/reports/merchandise_category_assignment --workers 6 --poll-interval 8 --timeout 1200 --resolution 1k --aspect-ratio 21:9 --follow-atomic-rules --atomic-poll-interval 30
```

After all generated images complete, run in-place packaging and generated-artifact synchronization:

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.build_safebooru_trial_dataset --root vlm/data/design_sheet_10610 --manifest vlm/data/design_sheet_10610/manifest.csv --atomic-root vlm/data/design_sheet_10610/atomic_rules --generated-root vlm/data/design_sheet_10610/generated --package-root vlm/data/design_sheet_10610/multi_view试标数据集_new --assignment-csv vlm/data/design_sheet_10610/reports/merchandise_category_assignment/merchandise_category_assignments.csv --skip-qwen-location --overwrite --sync-generated
```

## SYSTEM STATE
Qwen background processes were active earlier with command arguments `extract_atomic_rules_safebooru ... --workers 6`; current log files are `vlm/tmp/sn7_full_qwen/qwen_atomic_workers6.out.log` and `.err.log`. Re-check processes before starting or restarting any paid job.

The old concurrency-2 Qwen process was stopped and replaced safely; existing atomic JSON files are skipped on restart. The RunningHub follow process hit enterprise balance exhaustion for most pending tasks; check account balance before restarting. Its launcher logs are under `vlm/tmp/sn7_runninghub_follow/`, and its per-category logs are under `vlm/tmp/runninghub_full_generation/20260803_115342/`. Required credential names are `QWEN_API_KEY` and `RUNNINGHUB_API_KEY`; do not store their values.

## FILES CHANGED
- `vlm/scripts/import_sn7_design_sheet_dataset.py` — new resumable import, manifest/report, and balanced queue builder for the three SN-7 sources.
- `vlm/prompts/supervision/atomic_rules_from_safebooru.txt` — requires Qwen output `location=head|body` for every rule.
- `vlm/scripts/extract_atomic_rules_safebooru.py` — rejects atomic rules without a legal Qwen-provided location.
- `vlm/scripts/orchestrate/run_runninghub_merchandise_full_batch.py` — supports resumable `--follow-atomic-rules` consumption so RunningHub can trail Qwen without duplicate submissions in one run.
- `tests/test_runninghub_orchestrator.py` — covers follow-queue state partitioning.
- `vlm/scripts/build_safebooru_trial_dataset.py` — packages compact reference-style JSON and can sync generated snapshots/XLSX in place via `--sync-generated`.
- `tests/test_safebooru_trial_workflow.py` — covers the normalized location field.
- `handoff/LATEST.md` — current session checkpoint and detailed generation requirements.

