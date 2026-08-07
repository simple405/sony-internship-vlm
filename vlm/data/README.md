# Data Layout

`vlm/data/` 只保留两条交付流程所需的本地数据。该目录被 Git 忽略，交接时必须通过受控存储单独传输。

## SN-6

- `1-动漫标注结果导出_paired_samples/`：人工金标配对源数据。
- `front_view_generation_v1/`：由配对源数据生成的 20 个正视图样本。
- Qwen 监修和人工 gold 工作包位于 `vlm/tmp/`，不在本目录。

## SN-7

SN-7 三个源目录和 `design_sheet_10610` 当前不在本机。取得源数据后，按 `vlm/docs/workflows/SN_7_PLAN.md` 导入，不要恢复旧 Safebooru 实验集。

不要在此目录新增临时实验、日志或历史归档。
