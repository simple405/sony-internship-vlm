# SN-6 Paired Front-View 监修流程

## 目标与边界

源数据为 `vlm/data/1-动漫标注结果导出_paired_samples/`，包含约 6901 个原图与人工 JSON 配对。流程严格分两阶段：

1. 生图只读取原始图片和通用商品提示词，不解析、不发送 paired JSON。
2. 监修只把生成的正视图和 paired JSON 文本交给 Qwen；原始 2D 图不进入默认监修请求。

这个隔离是评估有效性的核心契约，不能为了改善生成结果把 gold JSON 拼进生图提示词。

## 生图

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.generate.generate_paired_front_view --dry-run --limit 20
.\.venv\Scripts\python.exe -m vlm.scripts.generate.generate_paired_front_view --limit 20 --workers 2
```

输出位于 `vlm/data/front_view_generation_v1/`。每个成功样本目录只保留：

```text
<sample_id>_original.<ext>
<sample_id>_q_front_view.png
<sample_id>.json
```

请求预览、prompt 快照和状态写入 `_metadata/<sample_id>/`。已有有效结果会 resume，不重复计费；prompt 发生漂移时拒绝复用旧结果。任一样本失败时命令返回非零，并更新 `failed_queue.json`。

## Qwen 监修

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.run_paired_front_view_review --dry-run --limit 20
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.run_paired_front_view_review --limit 20
```

canonical 结果写入 `vlm/tmp/paired_front_view_review_v1/`。逐条 verdict 为 `pass`、`partial`、`fail`、`not_evaluable` 或 `review`；模型必须在生成图上重新给出 evidence bbox，不能复用原图 bbox。微小细节优先放大检查，相邻色系按角色识别容差处理。解析或样本失败会使命令返回非零。

将人看的 `qc.csv` 放回样本目录，并把机器产物集中到一个可替换的汇总目录：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.sync_paired_front_view_review
```

集中目录为 `vlm/data/front_view_generation_v1/_review/paired_front_view_review_v1/`，包含 `qc_all.csv`、`prediction_summary.csv`、`predictions.jsonl`、`request_audit.csv`、可选 `batch_summary.json` 和 `sync_summary.json`。脚本先校验输入，再用 staging 目录整体替换，避免半写入和陈旧 summary。

## 人工 gold

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.prepare_paired_front_view_human_gold
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.prepare_paired_front_view_human_gold --validate
```

工作包位于 `vlm/tmp/paired_front_view_human_gold_v1/`。当前 20 张 pilot 已生成，人工字段仍需填写和校验。`model_*` 列只用于预标注参考，不能直接作为训练 gold。至少积累 500-1000 条人工确认 verdict，并按角色隔离 train/holdout 后，才评估 SFT/LoRA。

工作包已存在时，生成命令会拒绝覆盖，防止清空已填写的人工列。只有确认已备份人工修改后，才可显式使用 `--overwrite` 重建。`--validate` 在仍有 pending 行时返回非零，只有全部人工项完成且 schema 合法时才返回成功。

## 当前基线

- 20/20 正视图生成成功，失败队列为空。
- 最新 Qwen 样本结论：`pass=12`、`fail=8`、`review=0`，解析失败 0。
- rule-level：`pass=75`、`partial=45`、`fail=9`。
- 人工包：20 个样本、129 条 rule 中仍有 127 条 pending；当前 extra CSV 1 条且已填写。最终人工 gold 尚未完成。
