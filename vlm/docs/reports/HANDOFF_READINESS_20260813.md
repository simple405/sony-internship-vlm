# SN-7 Handoff Readiness Report · 2026-08-13

本报告记录当前物理目录 `vlm/data/sn7_data_generation`（逻辑批次 ID `design_sheet_10610`）的可交接状态。命令均从仓库根目录 `D:\索尼实习` 执行。

## 当前结论

- 代码验证通过：`147 passed`。
- SN-7 atomic rules 目录和 manifest 对齐：1000/1000 目录存在，无缺失、无额外目录。
- Qwen 当前全量覆盖提取未全部成功：`success=830`、`errors=170`。
- RunningHub 恢复队列现在会把 `atomic_rules/<sample_id>/error.json` 视为终止态；即使同目录还有旧 `atomic_rules.json`，也不会被误提交。
- RunningHub CN 节点对当前模型区域下线；恢复 live 生成前必须切到全球站/国际站入口。

## 已运行验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 147 passed in 1.60s

.\.venv\Scripts\python.exe -m pytest tests/test_runninghub_orchestrator.py tests/test_sn7_workflow.py -q
# 30 passed

.\.venv\Scripts\python.exe -m compileall -q vlm tests
# exit code 0

git diff --check
# exit code 0；仅 Git CRLF warning，无 whitespace error
```

凭据扫描只命中测试里的占位值：`unused`、`secret`、`mykey`；未发现真实 API key 写入仓库文本文件。

## SN-7 数据状态

Atomic extraction 摘要：

```json
{
  "status": "error",
  "requested": 1000,
  "success": 830,
  "skipped": 0,
  "errors": 170,
  "pilot_limit": 0
}
```

审计报告：

- `vlm/data/sn7_data_generation/reports/atomic_rules_completion_audit_20260813_corrected.json`

关键计数：

- `samples_with_atomic_rules_json`: 1000
- `current_prompt_atomic_count`: 830
- `stale_prompt_atomic_count`: 170
- `samples_with_error_json`: 170
- `complete_samples_no_fatal_count`: 378
- `bad_samples_count`: 622

说明：170 个 extraction error 样本目录里仍有旧 `atomic_rules.json`，属于历史残留，不能当作当前成功产物。

## RunningHub 恢复队列快照

按当前修复后的分类逻辑统计：

```json
{
  "head_key_chain": {"existing": 159, "generation_errors": 3, "ready": 0, "atomic_errors": 0, "waiting": 0},
  "cake_roll": {"existing": 159, "generation_errors": 3, "ready": 0, "atomic_errors": 0, "waiting": 0},
  "backpack": {"existing": 6, "generation_errors": 128, "ready": 0, "atomic_errors": 28, "waiting": 0},
  "plush": {"existing": 0, "generation_errors": 136, "ready": 0, "atomic_errors": 26, "waiting": 0},
  "dataset_QSitFigures": {"existing": 0, "generation_errors": 139, "ready": 0, "atomic_errors": 22, "waiting": 0},
  "dataset_figurine": {"existing": 0, "generation_errors": 129, "ready": 0, "atomic_errors": 32, "waiting": 0}
}
```

当前没有 ready 样本；不切全球站、不显式处理失败样本时，RunningHub 不应继续提交。

## 交接操作规则

1. 不要删除 `atomic_rules/<sample_id>/error.json` 来绕过失败；需要人工确认输入或重跑 Qwen 后再清理。
2. 恢复 RunningHub live 前先切全球站/国际站入口，并做 dry-run 或 endpoint 校验。
3. 已生成图片由 canonical output guard 保护；不加 `--retry-failed` 时 `generation_error.json` 是终止态。
4. 需要重试 RunningHub 失败样本时显式加 `--retry-failed`，并确认不会继续命中 CN 节点下线。
5. 本地 `vlm/data`、`vlm/tmp` 不进 Git，迁移时必须单独复制。

## 推荐下一步

如果目标是继续完成 SN-7 交付：

```powershell
# 1. 先确认没有旧 Qwen extraction 进程
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
  Where-Object { $_.CommandLine -like '*vlm.scripts.extract_atomic_rules*' } |
  Select-Object ProcessId,CreationDate,CommandLine | Format-List

# 2. 切 RunningHub 全球站/国际站配置后，先 dry-run
.\.venv\Scripts\python.exe -m vlm.scripts.orchestrate.run_runninghub_merchandise_full_batch --follow-atomic-rules --workers 6 --dry-run

# 3. 若要重试已有 RunningHub 失败样本，再显式 retry
.\.venv\Scripts\python.exe -m vlm.scripts.orchestrate.run_runninghub_merchandise_full_batch --follow-atomic-rules --workers 6 --retry-failed
```
