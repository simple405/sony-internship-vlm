# SN-6 Smoke V2 60-Sample Review Summary

Date: 2026-08-10

## Scope

This smoke batch expands SN-6 silver-label supervision to 60 generated samples:
10 samples per merchandise category.

Categories:

- `head_key_chain`
- `cake_roll`
- `backpack`
- `plush`
- `dataset_QSitFigures`
- `dataset_figurine`

The source paired JSON is treated as `vendor_silver`, not human gold. Review
results should therefore be used as pseudo labels or triage signals, not as
human-verified accuracy claims.

## Generation

RunningHub front-view generation completed for all selected samples.

| Metric | Count |
| --- | ---: |
| Selected samples | 60 |
| Generated successfully | 60 |
| Failed generation | 0 |
| Valid generated images | 60 |

## Qwen Review

Qwen `review_v2` completed for all 60 generated samples.

### Sample-Level Decisions

| Decision | Count |
| --- | ---: |
| `pass` | 60 |
| `fail` | 0 |
| `review` | 0 |

### Rule-Level Verdicts

| Verdict | Count |
| --- | ---: |
| `pass` | 267 |
| `partial` | 10 |
| `fail` | 0 |
| `review` | 0 |
| `not_evaluable` | 0 |
| `out_of_scope` | 128 |

`out_of_scope` is expected for body rules in head-only categories:
`head_key_chain`, `cake_roll`, and `backpack`.

## Partial Samples

The batch has no `fail`, `review`, or `not_evaluable` rules. The only issue
signals are 10 `partial` rules across 7 samples:

| Category | Sample ID | Partial Rules |
| --- | --- | ---: |
| `head_key_chain` | `1-1738734758` | 1 |
| `head_key_chain` | `1-1118500219` | 1 |
| `cake_roll` | `1-147300128` | 1 |
| `backpack` | `38889-423663422` | 2 |
| `plush` | `1-1981488321` | 1 |
| `dataset_QSitFigures` | `1-140879813` | 1 |
| `dataset_figurine` | `1-1473170314` | 3 |

## Local Artifact Paths

The full image and review artifacts are intentionally ignored by git.

- Selection manifest: `vlm/tmp/sn6_runninghub_smoke_v2/selection_manifest.csv`
- Review summary: `vlm/tmp/sn6_runninghub_smoke_v2/review_v2/batch_summary.json`
- Per-sample summary CSV: `vlm/tmp/sn6_runninghub_smoke_v2/review_v2/review_result_summary.csv`
- Per-sample review artifacts: `vlm/data/front_view_generation_v2/<category>/<sample_id>/_review/review_v2/`

## Next Step

Manually inspect the 7 partial samples before using this batch for pseudo-label
training buckets. Recommended split:

- `high_conf_pass`: sample-level pass with all scoped rules pass.
- `weak_pass`: sample-level pass with one or more partial rules.
- `uncertain`: any future review/not_evaluable or low-confidence edge case.
- `fail`: any future fail rule or failed sample-level decision.
