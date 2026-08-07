# VLM Workspace

## 目录

- `scripts/`：两条保留流程及共用 API、校验和 XLSX 工具。
- `prompts/`：三个通用提示词文件；商品差异由代码上下文渲染。
- `docs/workflows/`：SN-7 与 SN-6 的运行契约。
- `config/api.env.example`：允许的本地 API 配置项。
- `data/1-动漫标注结果导出_paired_samples/`：SN-6 配对人工金标源数据。
- `data/front_view_generation_v1/`：SN-6 已生成的 20 样本 pilot。
- `data/design_sheet_10610/`：SN-7 数据根目录；当前机器尚未放入源设定集。
- `tmp/paired_front_view_review_v1/`：SN-6 Qwen 监修结果。
- `tmp/paired_front_view_human_gold_v1/`：SN-6 人工复核包。

`data/` 和 `tmp/` 是本地资产，不进入 Git。交接或迁移时必须单独复制，并核对 `vlm/docs/HANDOFF.md` 中的目录清单。

## 安全边界

- RunningHub 凭据只发送到官方 HTTPS 主机；结果下载限制为 64 MiB，并拒绝本地/私网地址和重定向。
- Qwen 凭据只发送到 `https://dashscope.aliyuncs.com`。
- API 密钥不支持命令行参数，避免进入 shell 历史或进程列表。
- manifest 路径必须是数据根目录内的相对路径，样本 ID 不能包含路径分隔符。
- 批处理任一样本失败时进程返回非零，供 CI/调度器可靠识别。
