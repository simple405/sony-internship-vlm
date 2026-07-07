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
| human_rule_name | no | free text | Annotator's own rule/element phrasing. |
| element_name | no | free text | The visual element, e.g. hair, eye, headwear ribbon. |
| attribute | no | free text | Attribute under review, e.g. color, shape, length, existence. |
| view | yes | `front`, `side`, `back`, `multiple`, `all`, `unknown` | The affected view. |
| bbox_2d | no | `x,y,w,h` or tool-native box string | Evidence box on original 2D image. |
| bbox_multiview | no | `x,y,w,h` or tool-native box string | Evidence box on generated multi-view image. |
| visible | no | `visible`, `invisible`, `unknown` | Optional v3-like visibility for the annotator's own finding. |
| status | no | v3 status values or `unknown` | Optional v3-like status for the annotator's own finding. |
| match_status | no | `correct`, `wrong`, `unsure` | Whether this human finding matches the 2D expectation. |
| issue_type | yes | `wrong color`, `wrong shape`, `missing`, `extra`, `wrong invisible`, `other` | Human-visible issue type. |
| feature_key | no | free text | Human-readable feature name, not necessarily an atomic rule id. At least one of `feature_key`, `human_rule_name`, or `element_name` should be filled. |
| expected_value | no | free text | Short normalized expected value if available. |
| observed_value | no | free text | Short normalized observed value if available. |
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

## human_to_atomic_rule_mapping_candidates.csv

Generated candidate mapping table. This is not gold and must not directly
rewrite human annotations.

Core columns:

```text
sample_id
category
human_finding_id
human_rule_name
human_element_name
human_attribute
human_value
atomic_rule_id
atomic_rule_value
candidate_match_type
mapping_score
mapping_reason
needs_review
warnings
```

Candidate match types:

```text
exact_match_candidate
semantic_equivalent_candidate
broader_or_narrower_candidate
related_candidate
low_confidence_candidate
no_match_candidate
```

Only reviewed and accepted mappings should be used in downstream evaluation.
