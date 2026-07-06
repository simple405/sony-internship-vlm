# Human Annotation CSV Schemas

This document defines the handoff contract for human annotation data before it
is merged into verified evaluation gold.

Encoding: UTF-8 with BOM (`utf-8-sig`) for Excel compatibility.

## human_visual_findings.csv

Stage 1 free-form visual findings. Annotators compare the original 2D image
against the generated multi-view product image and record visual differences.

Required columns:

| column | required | allowed values | notes |
|--------|----------|----------------|-------|
| sample_id | yes | sample id | Must match the sample config or dataset folder. |
| category | yes | category id | Example: `backpack`, `head_key_chain`, `cake_roll`, `plush`. |
| finding_id | yes | free text id | Unique within one sample. |
| view | yes | `front`, `side`, `back`, `multiple`, `all`, `unknown` | The affected view. |
| issue_type | yes | `wrong color`, `wrong shape`, `missing`, `extra`, `wrong invisible`, `other` | Human-visible issue type. |
| feature_key | yes | free text | Human-readable feature name, not necessarily an atomic rule id. |
| expected_from_2d | no | free text | What the 2D source shows. |
| observed_in_multiview | no | free text | What the generated product shows. |
| severity | no | `critical`, `major`, `minor`, `unknown` | Defaults to `unknown` if left blank. |
| source_2d_evidence | no | free text | Optional evidence/region note. |
| multiview_evidence | no | free text | Optional evidence/region note. |
| reason | no | free text | Optional explanation. |
| annotator_id | no | free text | Human annotator id. |
| annotation_batch | no | free text | Batch/date/version id. |

## annotator_gold.csv

Stage 1 rule-level v3 supervision table filled by annotators after visual
comparison. It uses the same core columns as Qwen flattened predictions.

Required columns:

```text
sample_id
rule_id
value
front_visible
front_status
side_visible
side_status
back_visible
back_status
result
```

Optional columns:

```text
category
issue_type
confidence
reason
evidence
annotator_id
annotation_batch
```

Allowed values:

```text
*_visible: visible, invisible
*_status when visible: correct, wrong color, wrong shape, extra
*_status when invisible: correct, wrong invisible
result: correct, wrong
```

`result` must be `wrong` if any view status is an error status
(`wrong color`, `wrong shape`, `extra`, `wrong invisible`), otherwise `correct`.

## atomic_rule_audit.csv

Stage 2 audit of whether each atomic rule correctly describes the original 2D
image. This file decides which rules may enter verified Qwen evaluation gold.

Required columns:

| column | required | allowed values | notes |
|--------|----------|----------------|-------|
| sample_id | yes | sample id | Must match sample config or dataset folder. |
| category | yes | category id | Same category naming as sample configs. |
| rule_id | yes | atomic rule id | Must exist in the sample's atomic rules. |
| rule_key | no | free text | Optional normalized feature key. |
| atomic_value | yes | free text | Value from atomic_rules.json. |
| rule_validity | yes | `correct`, `wrong_value`, `missing_from_2d`, `ambiguous`, `out_of_scope`, `duplicate` | Only `correct` enters verified gold by default. |
| corrected_value | conditional | free text | Required when `rule_validity=wrong_value`. |
| reason | conditional | free text | Required for every non-`correct` validity. |
| annotator_id | no | free text | Human annotator id. |
| annotation_batch | no | free text | Batch/date/version id. |

## verified_evaluation_gold.csv

Stage 3 generated output. It is built from `annotator_gold.csv` filtered by
`atomic_rule_audit.csv`.

Core columns:

```text
sample_id
category
rule_id
value
front_visible
front_status
side_visible
side_status
back_visible
back_status
result
issue_type
confidence
reason
audit_rule_validity
audit_reason
```

Rules excluded from verified gold are written to `excluded_gold_rows.csv` with
an `exclude_reason` column.
