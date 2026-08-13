# SN-6 JSON-Conditioned Generation A/B 实验工作流

Date: 2026-08-11

## 实验问题

验证人工标注 JSON 是否能提升“大变形商品类别”的生成保真度：

- v1：只给原图生图
- v2：给原图 + 人工 JSON 生图
- 统一用人工 JSON 作为检查清单 review 生成图

核心问题不是“图好不好看”，而是：

> 生成图是否仍符合人工 JSON 中的角色身份元素。

## 推荐实验目录

统一放到 `vlm/tmp/sn6_json_conditioned_ab_v1/`，不要污染正式 `vlm/data/`。

```text
vlm/tmp/sn6_json_conditioned_ab_v1/
  selection_manifest.csv
  generation_image_only/
  generation_json_conditioned/
  metadata_image_only/
  metadata_json_conditioned/
  review_image_only/
  review_json_conditioned/
  comparison/
    sample_comparison.csv
    rule_comparison.csv
    summary.json
    README.md
```

## Step 0：确定样本与类别

### Input

- 源 paired 数据：
  - `vlm/data/1-动漫标注结果导出_paired_samples/manifest.csv`
  - 每个样本的原图
  - 每个样本的人工 JSON
- 目标类别：
  - `head_key_chain`
  - `cake_roll`
  - `backpack`
  - `plush`
  - `dataset_QSitFigures`
  - 可选对照：`dataset_figurine`

### Process

优先选“大变形”类别：

1. `head_key_chain`：头部保真压力最大。
2. `cake_roll`：形态变化最大。
3. `backpack`：角色元素要转成包体结构。
4. `dataset_QSitFigures`：Q 版比例变化。
5. `plush`：材质转换明显。
6. `dataset_figurine`：作为全身手办对照组。

建议规模：

- smoke：每类 5 张，5 类共 25 张，A/B 共 50 张生成。
- pilot：每类 20 张，5 类共 100 张，A/B 共 200 张生成。

### Output

`selection_manifest.csv`

最小字段：

```csv
category,sample_id
head_key_chain,1-1027228695
cake_roll,1-147300128
...
```

若需要固定证据，可额外保留：

```csv
category,sample_id,image_path,gold_json,source_sha256,gold_sha256,rule_count,image_bytes
```

### 现有命令

五类默认选择：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.prepare_five_category_supervision_manifest `
  --samples-per-category 20 `
  --output vlm/tmp/sn6_json_conditioned_ab_v1/selection_manifest.csv
```

如果要包含 `dataset_figurine`，需要手工追加或写一个 six-category selector。

## Step 1：v1 生图，原图 only

### Input

- `selection_manifest.csv`
- paired samples root：
  - `vlm/data/1-动漫标注结果导出_paired_samples/`
- 生图 prompt：
  - `vlm/prompts/generation/runninghub/merchandise_generation_cn.txt`
- RunningHub API key：
  - `vlm/config/api.env`

### Process

对每个 `(category, sample_id)`：

```text
original image + category prompt -> RunningHub -> generated front-view image
```

不读取、不发送人工 JSON。

### Output

```text
vlm/tmp/sn6_json_conditioned_ab_v1/generation_image_only/<category>/<sample_id>/
  <sample_id>_original.<ext>
  <sample_id>_<category>_front_view.png
  <sample_id>.json

vlm/tmp/sn6_json_conditioned_ab_v1/metadata_image_only/
  batch_summary.json
  failed_queue.json
  <category>/<sample_id>/
    prompt.txt
    request_preview.json
    status.json
```

### Command

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.generate.generate_paired_front_view `
  --input-root vlm/data/1-动漫标注结果导出_paired_samples `
  --sample-manifest vlm/tmp/sn6_json_conditioned_ab_v1/selection_manifest.csv `
  --output-root vlm/tmp/sn6_json_conditioned_ab_v1/generation_image_only `
  --metadata-root vlm/tmp/sn6_json_conditioned_ab_v1/metadata_image_only `
  --workers 1
```

## Step 2：v2 生图，原图 + 人工 JSON

### Input

和 Step 1 相同，额外使用每个 sample 的人工 JSON。

### Process

对每个 `(category, sample_id)`：

```text
original image + category prompt + compact JSON element list
  -> RunningHub
  -> generated front-view image
```

脚本通过 `--include-silver-json` 把 JSON 元素压缩进 prompt。

### Output

```text
vlm/tmp/sn6_json_conditioned_ab_v1/generation_json_conditioned/<category>/<sample_id>/
  <sample_id>_original.<ext>
  <sample_id>_<category>_front_view.png
  <sample_id>.json

vlm/tmp/sn6_json_conditioned_ab_v1/metadata_json_conditioned/
  batch_summary.json
  failed_queue.json
  <category>/<sample_id>/
    prompt.txt
    request_preview.json
    status.json
```

### Command

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.generate.generate_paired_front_view `
  --input-root vlm/data/1-动漫标注结果导出_paired_samples `
  --sample-manifest vlm/tmp/sn6_json_conditioned_ab_v1/selection_manifest.csv `
  --output-root vlm/tmp/sn6_json_conditioned_ab_v1/generation_json_conditioned `
  --metadata-root vlm/tmp/sn6_json_conditioned_ab_v1/metadata_json_conditioned `
  --include-silver-json `
  --silver-elements-limit 12 `
  --workers 1
```

## Step 3：生成结果完整性校验

### Input

- Step 1 output root
- Step 2 output root
- 两边的 `batch_summary.json`
- `selection_manifest.csv`

### Process

检查：

- 每个 manifest job 是否两边都有输出
- 原图是否复制成功
- JSON 是否复制成功
- 生成图是否可读
- prompt hash 是否存在
- failed_queue 是否为空
- A/B 两边样本顺序是否一致

### Output

```text
vlm/tmp/sn6_json_conditioned_ab_v1/comparison/generation_integrity.json
```

建议字段：

```json
{
  "selected": 100,
  "image_only_succeeded": 100,
  "json_conditioned_succeeded": 100,
  "paired_ab_count": 100,
  "missing_in_image_only": [],
  "missing_in_json_conditioned": [],
  "bad_images": []
}
```

## Step 4：review v1 生成图是否符合 JSON

### Input

- v1 generation root：
  - `generation_image_only/`
- 人工 JSON：
  - 每个生成目录内复制的 `<sample_id>.json`
- review prompt：
  - `vlm/prompts/supervision/paired_front_view_review_v2_cn.txt`
- Qwen API key：
  - `vlm/config/api.env`

### Process

统一评估：

```text
generated front-view image + human JSON -> Qwen review_v2
```

注意：这里不输入原图。目标是测“生成图是否符合 JSON checklist”。

### Output

```text
vlm/tmp/sn6_json_conditioned_ab_v1/review_image_only/
  batch_summary.json
  review_result_summary.csv
  _sample_aux/review_v2/<category>/<sample_id>/
    review_prompt.txt
    request_preview.json

vlm/tmp/sn6_json_conditioned_ab_v1/generation_image_only/<category>/<sample_id>/_review/review_v2_ab_image_only/
  prediction.json
  qc.csv
  status.json
```

### Command

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.run_paired_front_view_review `
  --input-root vlm/tmp/sn6_json_conditioned_ab_v1/generation_image_only `
  --sample-manifest vlm/tmp/sn6_json_conditioned_ab_v1/selection_manifest.csv `
  --output-root vlm/tmp/sn6_json_conditioned_ab_v1/review_image_only `
  --sample-review-root-name review_v2_ab_image_only `
  --workers 1
```

## Step 5：review v2 生成图是否符合 JSON

### Input

- v2 generation root：
  - `generation_json_conditioned/`
- 人工 JSON
- 同一个 review prompt
- Qwen API key

### Process

同 Step 4。

### Output

```text
vlm/tmp/sn6_json_conditioned_ab_v1/review_json_conditioned/
  batch_summary.json
  review_result_summary.csv
  _sample_aux/review_v2/<category>/<sample_id>/
    review_prompt.txt
    request_preview.json

vlm/tmp/sn6_json_conditioned_ab_v1/generation_json_conditioned/<category>/<sample_id>/_review/review_v2_ab_json_conditioned/
  prediction.json
  qc.csv
  status.json
```

### Command

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.run_paired_front_view_review `
  --input-root vlm/tmp/sn6_json_conditioned_ab_v1/generation_json_conditioned `
  --sample-manifest vlm/tmp/sn6_json_conditioned_ab_v1/selection_manifest.csv `
  --output-root vlm/tmp/sn6_json_conditioned_ab_v1/review_json_conditioned `
  --sample-review-root-name review_v2_ab_json_conditioned `
  --workers 1
```

## Step 6：A/B 对比汇总

### Input

- `review_image_only/batch_summary.json`
- `review_json_conditioned/batch_summary.json`
- v1 per-sample `qc.csv`
- v2 per-sample `qc.csv`
- `selection_manifest.csv`

### Process

按 sample 和 rule 两层对齐：

Sample-level：

```text
category
sample_id
v1_overall_decision
v2_overall_decision
v1_pass
v1_partial
v1_fail
v1_review
v1_not_evaluable
v1_out_of_scope
v2_pass
v2_partial
v2_fail
v2_review
v2_not_evaluable
v2_out_of_scope
delta_acceptable_rate
```

Rule-level：

```text
category
sample_id
rule_index
element
location
v1_result
v2_result
changed
change_type
v1_reason
v2_reason
```

核心指标：

```text
scoped_rules = pass + partial + fail + review + not_evaluable
strict_pass_rate = pass / scoped_rules
acceptable_rate = (pass + partial) / scoped_rules
fail_rate = fail / scoped_rules
review_rate = review / scoped_rules
json_help_delta = v2_acceptable_rate - v1_acceptable_rate
```

### Output

```text
vlm/tmp/sn6_json_conditioned_ab_v1/comparison/
  sample_comparison.csv
  rule_comparison.csv
  summary.json
  README.md
```

`summary.json` 建议字段：

```json
{
  "sample_count": 100,
  "categories": {
    "head_key_chain": {
      "sample_count": 20,
      "v1_acceptable_rate": 0.82,
      "v2_acceptable_rate": 0.91,
      "json_help_delta": 0.09,
      "v1_fail_rules": 12,
      "v2_fail_rules": 4
    }
  },
  "top_improved_samples": [],
  "regressed_samples": [],
  "needs_human_review": []
}
```

## Step 7：人工抽查

### Input

- `sample_comparison.csv`
- `rule_comparison.csv`
- A/B 生成图
- 原图
- 人工 JSON

### Process

优先抽查：

1. v1 fail -> v2 pass/partial：验证 JSON 是否真有帮助。
2. v1 pass -> v2 fail/review：找 JSON-conditioned 反向退化。
3. v1/v2 都 fail：找商品类别本身不适合的元素。
4. v2 partial 多的样本：判断是合理简化还是仍需优化 prompt。

人工标注建议字段：

```csv
category,sample_id,rule_index,human_verdict,human_reason,error_bucket
```

`error_bucket`：

```text
generation_missing
generation_wrong_color
generation_wrong_structure
json_label_ambiguous
review_too_strict
review_too_loose
reasonable_merchandise_conversion
```

### Output

```text
vlm/tmp/sn6_json_conditioned_ab_v1/comparison/human_spotcheck.csv
```

## Step 8：判断是否进入训练监修 VLM

### Input

- A/B review 汇总
- 人工抽查结果
- v1/v2 生成图
- 人工 JSON

### Process

只有满足这些条件，才把 v2 纳入训练数据：

1. v2 相对 v1 的 `acceptable_rate` 明显提升。
2. v2 没有大量引入 extra 或风格污染。
3. 人工抽查确认 review 口径基本可信。
4. 训练集和 eval set 分开，v2 不能当最终 unbiased test。

### Output

训练候选 bucket：

```text
train_candidates/
  high_conf_positive.jsonl
  weak_positive_partial.jsonl
  hard_negative_or_regression.jsonl
  human_dev.jsonl
```

每条 JSONL 建议 schema：

```json
{
  "sample_id": "1-xxx",
  "category": "head_key_chain",
  "arm": "json_conditioned",
  "source_image": "...original.png",
  "generated_image": "...front_view.png",
  "gold_json": "...json",
  "review_qc": "...qc.csv",
  "overall_decision": "pass",
  "rule_counts": {
    "pass": 5,
    "partial": 1,
    "fail": 0,
    "review": 0,
    "out_of_scope": 3
  },
  "usable_for": ["json_based_supervision_train", "image_only_tolerance_train"],
  "not_usable_for": ["final_unbiased_eval"]
}
```

## 最小可交付结果

一次完整 pilot 至少交付：

```text
1. selection_manifest.csv
2. v1 generation batch_summary.json
3. v2 generation batch_summary.json
4. v1 review batch_summary.json
5. v2 review batch_summary.json
6. sample_comparison.csv
7. rule_comparison.csv
8. summary.json
9. human_spotcheck.csv
10. README.md / markdown report
```

## 判定标准

可以推进训练监修 VLM：

```text
v2 acceptable_rate - v1 acceptable_rate >= 5%
且 v2 fail_rate 明显下降
且人工抽查确认 v2 改善不是 review 幻觉
```

不能推进训练，只能继续调生图 prompt：

```text
v2 和 v1 差距很小
或 v2 增加大量 extra/错误结构
或 review 和人工判断冲突明显
```
