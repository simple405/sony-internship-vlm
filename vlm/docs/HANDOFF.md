# Project Handoff

更新日期：2026-08-07

## 交付范围

仓库只保留 SN-7 设定集 atomic-rules/三视图流程，以及 SN-6 paired 正视图/Qwen 监修/人工 gold 流程。其他爬虫、元素抽取、旧多品类监督、训练实验、归档和提示词已移除。

## 本地资产

- SN-6 源：`vlm/data/1-动漫标注结果导出_paired_samples/`。
- SN-6 20 张生成结果：`vlm/data/front_view_generation_v1/`。
- SN-6 Qwen 监修：`vlm/tmp/paired_front_view_review_v1/`。
- SN-6 人工 gold 工作包：`vlm/tmp/paired_front_view_human_gold_v1/`。
- SN-7 源目录与 `design_sheet_10610` 当前不在本机，需要从数据负责人处单独迁移。

这些目录被 Git 忽略，克隆仓库不会获得数据。交接时应使用受控存储传输，并在传输后核对目录大小、样本数和 manifest/hash 报告。

本机已核验 paired manifest 共 6901 行且 ID 唯一，图片/JSON 路径均存在。20 个生成样本全部满足原图、正视图、paired JSON 三文件契约，图片可验证且 JSON 可解析。Qwen 监修 20 份均可解析，当前为 12 pass / 8 fail。

人工 gold 尚未完成：`human_gold_rules.csv` 共 129 行，其中 127 行 pending；`human_gold_extras.csv` 当前 1 行且已填写。重新生成工作包默认会被拒绝，防止覆盖人工修改。

## 凭据

实际密钥仅在本地 `vlm/config/api.env`。仓库包含 `api.env.example`，不包含密钥。本机 Windows ACL 已关闭继承，仅保留当前用户、SYSTEM 和 Administrators。ACL 不随 Git 或普通文件复制迁移；接手人在新机器创建 `api.env` 后必须重新收紧权限。更换负责人时应撤销旧密钥并签发新密钥，不要直接传递现有值。

## 运行环境

- Python 3.11（本机验证版本 3.11.9）。
- 运行依赖锁定在 `vlm/requirements.txt`。
- 开发依赖锁定在 `vlm/requirements-dev.txt`。
- GitHub Actions 在 Windows/Python 3.11 执行 compileall 和 pytest。

## 接手后的第一步

1. 创建虚拟环境并运行全量测试。
2. 根据 `api.env.example` 配置新密钥，先执行 dry-run。
3. 完成 SN-6 人工 gold 的 pending 行并运行 `--validate`。
4. 取得 SN-7 三个源目录后，按 `workflows/SN_7_PLAN.md` 从 12 张 smoke test 开始。

## 验证状态

- Python 3.11.9，Pillow 12.3.0。
- `compileall` 和 78 项 pytest 全部通过；pydocstyle、YAML/JSON/冲突/大文件/文件卫生钩子已在本机执行通过。
- gitleaks 本机首次安装因 `proxy.golang.org` 连接超时未完成；CI 已配置运行完整 pre-commit，需要在联网的交付环境确认该项通过。

## 已知残余风险

- 当前测试使用 mock，不会在 CI 中调用 RunningHub/DashScope；正式 API 的 schema 或限流变化仍需通过小批量 smoke test 发现。
- SN-7 源数据不在本机，因此导入后的 10610 样本全量验收尚未执行。
- SN-6 人工 gold 未完成，现有 Qwen verdict 不能作为训练真值。
