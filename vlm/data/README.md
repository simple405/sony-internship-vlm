# Data Layout

`vlm/data/` 只保留两条交付流程所需的本地数据。该目录被 Git 忽略，交接时必须通过受控存储单独传输。

`sn7_data_generation/manifest.csv` 是所有本地批次的唯一汇总清单。用 `dataset_id` 区分批次；
SN-7 的分类、atomic 执行状态和错误原因都同步在这里，子数据集目录不再保留重复 CSV。

## SN-6

- `1-动漫标注结果导出_paired_samples/`：人工金标配对源数据。
- `front_view_generation_v1/`：由配对源数据生成的 20 个正视图样本。
- Qwen 监修和人工 gold 工作包位于 `vlm/tmp/`，不在本目录。

## SN-7

- `sn7_data_generation/`：当前 1000 张 SN-7 工作集及 atomic/generated/deliverables 产物。
- `safebooru_character_sheet/`、`safebooru_turnaround/`：本机保留的来源目录。
- atomic 状态当前以 `sn7_data_generation/manifest.csv` 为准；失败样本必须保留 `error.json`，不能使用同目录 stale rules。

不要在此目录新增临时实验、日志或历史归档。
