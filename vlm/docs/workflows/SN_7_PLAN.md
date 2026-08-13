# SN-7 设定集三视图流程

## 目标

三个已批准源目录共 10610 张设定集图片：

```text
vlm/data/safebooru_character_sheet  6217
vlm/data/safebooru_turnaround       1908
vlm/data/角色分解                    2485
```

当前机器未保留这些源目录和已生成结果。接手人取得数据后放回上述位置，再从导入步骤开始；不要恢复旧 `safebooru_2d` 实验集。

## 数据契约

统一汇总清单为 `vlm/data/sn7_data_generation/manifest.csv`，通过
`dataset_id=design_sheet_10610` 筛选本批次；图片和产物根目录为
`vlm/data/sn7_data_generation/`：

```text
image/<sample_id>.<ext>
atomic_rules/<sample_id>/atomic_rules.json
generated/<category>/<sample_id>/
reports/merchandise_category_assignment/
deliverables/<category>/<sample_id>/
```

manifest 的 `image_path` 必须相对数据集根目录。`sample_id` 使用 `cs_`、`ta_`、`cd_` 来源前缀，防止三个源之间重名。
汇总 manifest 的 `image_path` 必须相对 `vlm/data/`。因此当前 SN-7 图片以
`sn7_data_generation/image/<sample_id>.<ext>` 记录。分类字段和 atomic
执行状态直接写在该表；`atomic_rules_status=error` 时同时保留错误类型、原因和拒绝分类。

最终每个 `deliverables` 样本必须包含：

```text
2d_original.<ext>
atomic_rules.json
multiview_design.png
<sample_id>.xlsx
```

六类名称固定为 `head_key_chain`、`cake_roll`、`backpack`、`plush`、`dataset_QSitFigures`、`dataset_figurine`。前三类 XLSX 只导出 `location=head`；后三类导出全部规则。

## 执行

先创建 12 张免费预检数据：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.prepare_sn7_smoke_test
.\.venv\Scripts\python.exe -m vlm.scripts.validate_sn7_smoke_test
```

全量导入和分配：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.import_sn7_design_sheet_dataset
.\.venv\Scripts\python.exe -m vlm.scripts.data.assign_merchandise_categories
.\.venv\Scripts\python.exe -m vlm.scripts.consolidate_data_manifests --remove-merged-files
```

先对少量样本提取 atomic rules；人工确认 JSON 的 `id/location/value` 和观察者视角 left/right 后，再用 `--limit 0` 全量执行：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.extract_atomic_rules --limit 12 --workers 2
.\.venv\Scripts\python.exe -m vlm.scripts.extract_atomic_rules --limit 0 --workers 2
```

RunningHub 先 dry-run，再正式运行。编排器会按固定顺序消费六类队列；任一子任务失败即返回非零：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.orchestrate.run_runninghub_merchandise_full_batch --dry-run
.\.venv\Scripts\python.exe -m vlm.scripts.orchestrate.run_runninghub_merchandise_full_batch --workers 2
```

全部生成后打包；缺少原图、规则或三视图时默认返回非零，在
`reports/package_validation/` 写入 incomplete 报告，并保留上一版 `deliverables/`。
已有交付目录时必须显式传入 `--overwrite` 才会通过 staging 整体替换：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.package_sn7_dataset
```

## 验收

- manifest 样本 ID 唯一、路径可迁移、图片 SHA-256 与文件一致。
- atomic rules 只描述直接可见内容，每条包含 `id/location/value`，location 仅为 `head/body`。
- RunningHub 请求只有原始 2D 图和渲染后的通用提示词，不发送 atomic rules。
- 每个三视图是同一商品的正面、侧面和背面，局部花纹不换边、不镜像、不凭空补全。
- `deliverables/_reports/package_summary.json` 的 `incomplete_count` 为 0。
