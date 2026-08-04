# Workspace cleanup ? 2026-08-04

Goal: make `D:\????` easier to maintain and hand off by removing root-level scratch clutter, documenting script entry points, and preserving one-off work without presenting it as active code.

## Decisions

- Maintained scripts live under `vlm/scripts/` only.
- Root `tmp/` and `output/` are not active work areas. Future scratch should go under ignored `vlm/tmp/` or a dated archive.
- Durable handoff/report markdown belongs under `vlm/docs/`.
- One-off scripts are archived, not deleted, so historical reproduction is still possible.
- Xlsx export no longer flips left/right position values. Current atomic_rules values are expected to already use annotator/viewer coordinates.

## Moved artifacts

| From | To | Reason |
|---|---|---|
| `output/vlm_audit/trial_label_quality_report_20260804.md` | `vlm/docs/supervision/reports/trial_label_quality_report_20260804.md` | Durable audit report; should be visible to handoff. |
| `tmp/` | `vlm/archive/cleanup_20260804/root_tmp/` | One-off scripts, PDF render cache, contact sheets, and generated inventory. |
| `output/` remainder | `vlm/archive/cleanup_20260804/root_output_remainder/` | Empty/leftover root output container after report migration. |

## Archived script triage

| Archived script | Keep active replacement / rationale |
|---|---|
| `batch_convert_atomic_rules.py` | Superseded by `vlm/scripts/build_safebooru_trial_dataset.py` and `vlm/scripts/utils/tag_and_export_atomic_rules.py`. |
| `smoke_test_atomic_rules.py` | Prototype converter; covered by maintained xlsx export tests and workflow scripts. |
| `correct_atomic_rule_positions.py` | Superseded by `vlm/scripts/fix_atomic_rule_positions_with_qwen.py`. |
| `vision_fix_position_values.py` | Superseded by `vlm/scripts/fix_atomic_rule_positions_with_qwen.py`. |
| `format_trial_annotation_workbooks.py` | One-off styling pass; maintained dropdown sync is `vlm/scripts/utils/sync_annotation_workbook_validations.py`. |
| `sync_trial_workbook_values.py` | One-off workbook value sync; generated package sync is `vlm/scripts/utils/sync_generated_annotation_xlsx.py`. |
| `update_pdf_wrong_prosition.py` | One-off PDF regeneration provenance; final/report artifacts live under `vlm/data`/`vlm/docs`. |

## Current docs to read first

1. `handoff/LATEST.md` ? latest operational checkpoint.
2. `vlm/docs/workflows/process.md` ? compressed current process.
3. `vlm/scripts/README.md` ? maintained script entry points.
4. `vlm/docs/supervision/reports/trial_label_quality_report_20260804.md` ? latest trial-label QC report.
