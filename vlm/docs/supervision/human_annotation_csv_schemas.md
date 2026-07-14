# Human Annotation CSV Schemas（压缩版）

Encoding: UTF-8 with BOM (`utf-8-sig`) for Excel compatibility.

本文件定义人工标注数据进入 verified evaluation gold 前的最小契约。2026-07-08 后，Stage 1 是 **annotation-acceptance findings**，不是开放式视觉细节补充。

## 1. 2026-07-08 Stage 1 范围

```text
只记录：
- 预识别部位/装饰物的 wrong color
- 预识别部位/装饰物的 wrong material
- 预识别部位/装饰物的 wrong shape
- 成对物品或身体部位的 paired box completion / split

不作为当前乙方主验收失败项：
- 普通 missing / extra 细节
- 开放式描述补充
- 与颜色/材质/形状无关的扩写
```

本范围不替代生图或 atomic_rules 的完整 IP 设计标准。

## 2. human_visual_findings.csv

Stage 1 人工验收发现。最小列：

```text
sample_id
category
finding_id
view
issue_type
element_name
attribute
expected_from_2d
observed_in_multiview
severity
reason
```

允许值：

```text
view:
  front, side, back, multiple, all, unknown

issue_type:
  wrong color, wrong material, wrong shape, paired box completion, missing, extra, wrong invisible, other
  注：missing / extra / wrong invisible 为历史兼容或诊断值；当前主验收口径优先使用前三类和 paired box completion。

attribute:
  color, material, shape, paired_box, existence, other

severity:
  critical, major, minor, unknown

match_status:
  correct, wrong, unsure
```

可选列：

```text
human_rule_name
feature_key
bbox_2d
bbox_multiview
visible
status
match_status
expected_value
observed_value
source_2d_evidence
multiview_evidence
annotator_id
annotation_batch
```

## 3. annotator_gold.csv

Stage 1 rule-level v3 表。核心列：

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
evidence
annotator_id
annotation_batch
```

允许值：

```text
*_visible:
  visible, invisible

*_status when visible:
  correct, wrong color, wrong material, wrong shape, extra

*_status when invisible:
  correct, wrong invisible

result:
  correct, wrong
```

`result` 规则：任一 view status 属于 `wrong color`、`wrong material`、`wrong shape`、`extra`、`wrong invisible` 时，`result=wrong`；否则 `result=correct`。

## 4. atomic_rule_audit.csv

Stage 2 审核 atomic rule 是否正确描述 2D 图。核心列：

```text
sample_id
category
rule_id
rule_key
atomic_value
rule_validity
corrected_value
reason
annotator_id
annotation_batch
```

允许值：

```text
rule_validity:
  correct, wrong_value, missing_from_2d, ambiguous, out_of_scope, duplicate
```

规则：`wrong_value` 必须填 `corrected_value`；非 `correct` 建议填写 `reason`。

## 5. verified_evaluation_gold.csv

Stage 3 生成输出，由 `annotator_gold.csv` 根据 `atomic_rule_audit.csv` 过滤得到。核心列：

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

被排除的 rows 写入 `excluded_gold_rows.csv`，带 `exclude_reason`。

## 6. human_to_atomic_rule_mapping_candidates.csv

Stage 3 候选映射表，不是 gold，不能直接改写人工标注。

核心列：

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

允许值：

```text
candidate_match_type:
  exact_match_candidate
  semantic_equivalent_candidate
  broader_or_narrower_candidate
  related_candidate
  low_confidence_candidate
  no_match_candidate
```

只有人工复核接受后的映射才能进入后续评估。
