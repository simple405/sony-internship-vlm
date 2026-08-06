# 当前主线：Paired Front-View 监修 Agent

更新日期：2026-08-06

本文是当前唯一主流程。旧的元素抽取、SN-7 批处理和历史会议方案只作为归档参考，不与本流程混用。

## 1. 目标

对 `vlm/data/1-动漫标注结果导出_paired_samples/` 下的角色样本：

1. 只用 2D 原图和固定提示词生成 Q 版 3D PVC 手办正面正式图。
2. 用 paired JSON 作为监修规格，判断生成图是否符合对应元素描述。
3. 输出逐元素问题、整体结论和人工复核队列。

当前数据规模：`6901` 个有效图文配对，另有 `3` 张孤立图片不进入主流程。

## 2. 严格的数据边界

### 2.1 生图阶段

```text
输入：source_image + 固定 front-view prompt
输出：<sample_id>_q_front_view.png + prompt 快照 + 请求状态
```

生图阶段禁止读取或拼接该样本 JSON。否则 JSON 会泄漏到生成条件，后续监修评估失去独立性。

当前可复用提示词：

```text
vlm/prompts/generation/runninghub/runninghub_g2_figurine_front_view_user_cn.txt
```

生成结果写入独立目录，不覆盖 paired 原始目录：

```text
vlm/data/front_view_generation_v1/<sample_id>/
  <sample_id>_original.<ext>
  <sample_id>_q_front_view.png
  <sample_id>.json

vlm/data/front_view_generation_v1/_metadata/<sample_id>/
  prompt.txt
  request_preview.json
  status.json
```

样本交付目录严格只保留三件套；元数据不进入样本目录。原图和 gold JSON
在生成完成后按字节复制，JSON 不会被解析或发送到 RunningHub。

### 2.2 监修阶段

```text
输入：generated_front_view + paired JSON
可选审计输入：source_image（仅用于争议复核，不作为默认判定条件）
输出：per-rule verdict + overall decision
```

原 JSON 中的 `bbox` 是 2D 原图坐标，不能直接套到生成图。Agent 必须在生成图上重新给出 evidence bbox，或者明确 `not_evaluable`。

## 3. 监修输出契约

每条 JSON 元素输出以下最小字段：

```json
{
  "rule_index": 1,
  "element": "蓝色眼睛",
  "result": "pass | partial | fail | not_evaluable | review",
  "image_grounded": true,
  "description_correct": true,
  "issue_types": [],
  "observed_description": "生成图中可见蓝色眼睛。",
  "evidence_bbox": [100, 80, 240, 160],
  "confidence": 0.91,
  "reason": "颜色和位置与规格一致。"
}
```

规则：

- 复合描述允许 `partial`，不能把只实现一半的元素直接算全错。
- 正面不可见的背面/侧面细节使用 `not_evaluable`，不直接判缺失。
- 颜色、形状、结构和代表性配饰错误进入 `design_quality_notes`；若业务验收范围明确，再映射到 `billable_annotation_issues`。
- 低置信度、JSON 描述本身含糊或图像证据不足进入 `review`。
- 额外生成的显著元素单独记录为 `extra_elements`，不能偷偷并入某条 gold。

## 4. 开发阶段

### Phase A：独立生图批处理

基于 `runninghub_client.py` 写新的 paired 批处理脚本，支持：

- `--input-root`、`--output-root`、`--sample-id`、`--limit`；
- resume，已有成功结果不重复计费；
- 固定 prompt 快照、任务状态、失败重试队列；
- 明确记录请求只包含一张原图和固定 prompt。

先做 `20` 张分层 pilot，不直接跑 6901 张。

状态（2026-08-06）：已完成。新脚本为：

```text
vlm/scripts/generate/generate_paired_front_view.py
```

先执行 dry-run：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.generate.generate_paired_front_view --dry-run --limit 20
```

验证 preview 后执行真实 pilot：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.generate.generate_paired_front_view --limit 20 --workers 2
```

pilot 结果为 `20/20` 成功、失败队列为空，输出位于
`vlm/data/front_view_generation_v1/`。请求审计确认每份 payload 只有一张原图和冻结 prompt，
不含 paired JSON 路径或内容；paired 输入目录仍为 `6901` 个标准双文件样本目录。
现有 20 个完成样本均已迁移为严格三件套，原图与 gold JSON 的 SHA-256 和 paired 输入一致。

### Phase B：规格对图 baseline

已完成。paired reviewer 直接读取 JSON，不重新抽取规则；默认请求只带生成的正面图，
不带原图。2026-08-06 已在原 `paired_front_view_review_v1` 上直接覆盖更新：
prompt 增加微小细节局部检查指令和 `micro_detail_hints`，并加入相邻色系容差后处理
（如粉红/玫红/紫红/红紫不按硬错色处理）。20 张 pilot 最新结构化 verdict：
样本级 `pass=12`、`fail=8`、`review=0`、解析失败 `0`；
rule-level 为 `pass=75`、`partial=45`、`fail=9`、`not_evaluable=0`、`review=0`。
结果的 canonical 版本位于 `vlm/tmp/paired_front_view_review_v1/`；为方便逐样本复核，
同一批结果已镜像到每个样本目录的
`vlm/data/front_view_generation_v1/<sample_id>/_review/paired_front_view_review_v1/`。
镜像只包含 reviewer 产物，不改变顶层三件套。

### Phase C：人工 gold

已生成完整 20 张人工标注包，但尚未填写最终 gold。标注包位于
`vlm/tmp/paired_front_view_human_gold_v1/`，包含 20 个样本、129 条 rule 行和
19 条 extra 候选；其中 12 个样本含自动 reviewer 的 `fail/partial` 结果，另外 8 个
pass 样本用于校准 false negative。Qwen 结果只放在 `model_*` 列，人工字段保持空白，
禁止直接拿自动结果训练。

### Phase D：训练或蒸馏

只有在至少积累 `500–1000` 条人工确认 verdict 后，才评估 LoRA/SFT。先比较 prompt baseline 与训练模型，再决定是否训练；不能把模型自己的预标注当 gold。

## 5. 指标

主指标：

- rule-level macro/micro F1；
- `fail` recall，优先避免漏报关键错误；
- `partial` 识别率；
- `not_evaluable` precision；
- extra hallucination precision；
- overall fail/review recall。

评估按角色分组拆分，避免同一角色或近重复图同时进入 train 和 holdout。

## 6. 当前资产

```text
原始配对：vlm/data/1-动漫标注结果导出_paired_samples/
生成提示词：vlm/prompts/generation/runninghub/runninghub_g2_figurine_front_view_user_cn.txt
RunningHub 客户端：vlm/scripts/generate/runninghub_client.py
旧多品类 reviewer：vlm/scripts/supervise/run_multicategory_supervision_review.py
API 配置：vlm/config/api.env
实验归档：vlm/archive/experiments/2026-08-05_2026-08-06_element_extraction_frontview/
```

旧的 `smoke_test_q_front_view_from_paired.py` 会把 JSON 拼入 prompt，已归档，禁止作为新主线脚本复用。

## 7. 下一步

进入 Phase C：填写 `vlm/tmp/paired_front_view_human_gold_v1/human_gold_rules.csv` 和
`human_gold_extras.csv`，然后运行同一脚本的 `--validate` 检查是否仍有 pending 行。
人工确认达到足够规模后，再设计 Phase D 的训练/蒸馏集与 holdout；当前禁止启动训练。
