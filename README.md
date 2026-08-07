# Anime IP Merchandise VLM

本仓库只维护两条生产流程：

1. **SN-7**：设定集导入 -> Qwen 提取 atomic rules -> 六类商品三视图生成 -> 四件套打包。
2. **SN-6**：人工金标配对数据 -> PVC 手办等二创商品正视图生成 -> Qwen 监修 -> 人工 gold 复核。

## 快速开始

环境固定为 Python 3.11：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r vlm\requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

复制 `vlm/config/api.env.example` 为本地 `vlm/config/api.env` 并填写密钥。`api.env`、数据集、生成结果和临时输出均被 Git 忽略，不应提交。

## 入口

- 项目结构与数据目录：`vlm/README.md`
- 可执行脚本：`vlm/scripts/README.md`
- SN-7：`vlm/docs/workflows/SN_7_PLAN.md`
- SN-6：`vlm/docs/workflows/process.md`
- 交接状态：`vlm/docs/HANDOFF.md`

所有命令都从仓库根目录执行。CI 会在 Windows + Python 3.11 上编译脚本并运行测试。
