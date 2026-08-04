# VLM Script Entry Points

This directory is the maintained script surface for the workspace. Run commands from the repository root (`D:\????`) so package imports and relative data paths resolve consistently.

## Production / Current SN-7 Flow

| Task | Script | Notes |
|---|---|---|
| Import SN-7 source image pools | `python -m vlm.scripts.import_sn7_design_sheet_dataset` | Builds `vlm/data/design_sheet_10610` from the approved source pools. |
| Prepare SN-7 smoke test | `python -m vlm.scripts.prepare_sn7_smoke_test` | Deterministic 12-image smoke-test input. |
| Validate SN-7 smoke test | `python -m vlm.scripts.validate_sn7_smoke_test` | Manifest and asset preflight before paid API work. |
| Full RunningHub batch | `python -m vlm.scripts.orchestrate.run_runninghub_merchandise_full_batch` | Main six-category production runner; supports follow-mode atomic-rules consumption. |
| Sync generated xlsx packages | `python -m vlm.scripts.utils.sync_generated_annotation_xlsx` | Reuses the shared xlsx writer for completed generated samples. |
| Add/fix xlsx dropdowns | `python -m vlm.scripts.utils.sync_annotation_workbook_validations` | In-place validation dropdown sync without changing cell values. |

## Supervision / Evaluation

| Task | Script | Notes |
|---|---|---|
| End-to-end supervision agent | `python -m vlm.scripts.supervise.run_supervision_agent` | 2D source + product image -> element extraction -> review report. |
| Element extraction | `python -m vlm.scripts.supervise.run_element_extraction` | Qwen VL source-2D extraction. |
| Multi-category review | `python -m vlm.scripts.supervise.run_multicategory_supervision_review` | Qwen review against atomic rules and product image. |
| Validate human annotations | `python -m vlm.scripts.supervise.validate_human_annotations` | CSV/xlsx-derived schema, enum, coverage, and result consistency checks. |
| Build annotation products | `python -m vlm.scripts.supervise.build_annotation_products` | Standard supervision annotation deliverables from filled Excel. |
| Convert xlsx to CSV | `python -m vlm.scripts.supervise.convert_annotation_xlsx_to_csv` | Converts annotation workbooks into schema-aware CSV files. |
| Align human findings | `python -m vlm.scripts.supervise.align_human_findings_to_atomic_rules` | Candidate matching between visual findings and atomic rules. |
| Build verified gold | `python -m vlm.scripts.supervise.build_verified_evaluation_gold` | Produces verified evaluation gold after review. |
| Compare predictions | `python -m vlm.scripts.supervise.compare_predictions` | Metrics over predictions and gold. |
| Position-rule audit/fix | `python -m vlm.scripts.fix_atomic_rule_positions_with_qwen` | Reusable audited replacement for older root `tmp/*position*` scripts. |

## Shared Helpers

| Module | Purpose |
|---|---|
| `vlm.scripts._paths` | Centralized path constants and API env loading. |
| `vlm.scripts.generate.runninghub_client` | Shared RunningHub API client helpers. |
| `vlm.scripts.utils.atomic_rule_xlsx` | Annotation xlsx dropdown constants and export helpers. It does **not** flip left/right; atomic rules are expected to already use annotator/view coordinates. |
| `vlm.scripts.utils.tag_and_export_atomic_rules` | Legacy/reusable atomic-rules tagging plus xlsx export. |

## Retired / Low-Reuse Scripts

One-off scripts previously under repository-root `tmp/` were archived to `vlm/archive/cleanup_20260804/root_tmp/` and should not be used as entry points. Keep the maintained scripts above unless a historical reproduction needs the archived code.
