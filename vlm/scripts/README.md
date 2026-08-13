# Script Entry Points

从仓库根目录使用 `.\.venv\Scripts\python.exe -m <module>` 执行。

## SN-7

| 顺序 | 任务 | 模块 |
|---|---|---|
| 1 | 导入三个设定集源目录 | `vlm.scripts.import_sn7_design_sheet_dataset` |
| 1a | 合并历史/现有清单并同步 atomic 状态 | `vlm.scripts.consolidate_data_manifests` |
| 2 | 准备/校验 12 张 smoke test | `vlm.scripts.prepare_sn7_smoke_test` / `vlm.scripts.validate_sn7_smoke_test` |
| 3 | 生成或刷新六类分配 | `vlm.scripts.data.assign_merchandise_categories` |
| 4 | Qwen 提取 atomic rules | `vlm.scripts.extract_atomic_rules` |
| 4a | Qwen 自然中文翻译与 XLSX 同步 | `vlm.scripts.translate_atomic_rules_xlsx` |
| 5 | RunningHub 六类批处理 | `vlm.scripts.orchestrate.run_runninghub_merchandise_full_batch` |
| 5a | 小批量直接生成 | `vlm.scripts.generate.generate_sn7_multiview` |
| 6 | 生成四件套交付目录 | `vlm.scripts.package_sn7_dataset` |
| 维护 | 补写 XLSX / 下拉验证 | `vlm.scripts.utils.sync_generated_annotation_xlsx` / `vlm.scripts.utils.sync_annotation_workbook_validations` |

## SN-6

| 顺序 | 任务 | 模块 |
|---|---|---|
| 1 | 仅使用原图生成正视图 | `vlm.scripts.generate.generate_paired_front_view` |
| 2 | Qwen 按 paired JSON 监修 | `vlm.scripts.supervise.run_paired_front_view_review` |
| 3 | 汇总监修结果 | `vlm.scripts.supervise.sync_paired_front_view_review` |
| 4 | 生成人工 gold 工作包 | `vlm.scripts.supervise.prepare_paired_front_view_human_gold` |
| 维护 | 颜色系 verdict 后处理 | `vlm.scripts.supervise.postprocess_color_family_verdicts` |

## 共用模块

- `_paths.py`：工作区路径和 `api.env` 加载。
- `_validation.py`：样本 ID、manifest 路径和 Qwen 端点校验。
- `_dataset_manifest.py`：统一 `vlm/data/sn7_data_generation/manifest.csv` 的筛选、路径解析和原子更新。
- `_http.py`：官方 API 直连 Session，不继承父进程的代理环境变量。
- `generate/runninghub_client.py`：RunningHub 上传、提交、轮询和受限下载。
- `generate/prompt_renderer.py`：一个生成模板渲染六类商品和正面/三视图模式。
- `utils/atomic_rule_xlsx.py`：标准监修 XLSX 导出，优先读取 Qwen 自然中文缓存。

## 交接安全规则

- 任何会发布到 `vlm/data` 的脚本都必须使用 staging + archive 流程，不能直接删除或覆盖已有人工包、交付包和生成图。
- `prepare_paired_front_view_human_gold` 默认使用非破坏式发布；重新生成前先确认旧包已经归档。
- SN-7 RunningHub 恢复生成前先确认 `atomic_rules/<sample_id>/error.json`：有 extraction error 的样本必须跳过，不能消费同目录的旧 `atomic_rules.json`。
- `vlm/data/sn7_data_generation/manifest.csv` 是本机唯一总清单；逻辑批次 ID 仍为 `design_sheet_10610`。atomic 或分类状态变化后运行 `vlm.scripts.consolidate_data_manifests` 同步。
- 已生成图片由 canonical output guard 保护；重试失败样本必须显式使用 `--retry-failed`。
- 运行 live API 前确认 `vlm/config/api.env` 只包含本机凭据，禁止把密钥写进命令行、日志或 handoff。
