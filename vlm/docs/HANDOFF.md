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
- gitleaks 本机 pre-commit hook 首次安装仍受 `proxy.golang.org` 网络影响；GitHub Actions 已拆分为独立 `gitleaks` workflow，最新 push/PR 均通过。

## 已知残余风险

- 当前测试使用 mock，不会在 CI 中调用 RunningHub/DashScope；正式 API 的 schema 或限流变化仍需通过小批量 smoke test 发现。
- SN-7 源数据不在本机，因此导入后的 10610 样本全量验收尚未执行。
- SN-6 人工 gold 未完成，现有 Qwen verdict 不能作为训练真值。
---

CKPT-1  ·  Codex  ·  2026-08-07 15:27 Asia/Shanghai

## SUMMARY
本轮完成 GitHub 交付收尾：把当前交接提交推到原工作分支，并新增 `sn7-data-generation` 远端分支，方便在网页端单独查看 SN-7 数据生成链路。GitHub Actions 的 `test` 失败已定位并修复：补齐 SN-7 脚本的 pydocstyle docstring，把 gitleaks 从 Python test workflow 中拆成独立 workflow，并修复新 workflow 的文件尾换行。最新提交为 `428aa63`，`test` 与 `gitleaks` 的 push/PR run 均已通过。

## PROGRESS
### GITHUB-CI — Branches and Actions
  ✅ `work/sn6-supervision-agent-training` 已推送到 `428aa63`
  ✅ `sn7-data-generation` 已创建并推送到同一提交 `428aa63`
  ✅ `test` workflow 最新 push/PR 均为 success
  ✅ `gitleaks` workflow 最新 push/PR 均为 success
  ☐ 后续如需 PR 合并，由接手人在 GitHub 网页端检查 PR #1 后合并

### WORKFLOW-READINESS — SN-7 / SN-6 retained flows
  ✅ 本地 `pre-commit` 稳定部分、`compileall`、`pytest` 已通过，pytest 为 78 passed
  ✅ SN-6 本地 paired 数据、20 个 front-view 生成样本、20 个 Qwen 监修结果仍保留在 ignored data/tmp 目录
  ⏳ SN-7 源目录与 `design_sheet_10610` 不在本机，真实导入与 API smoke test 尚未执行
  ☐ 取得 SN-7 源目录后，从 `prepare_sn7_smoke_test` / `validate_sn7_smoke_test` 和 12 张 smoke test 开始

## NEXT ACTION
取得 SN-7 三个源目录后放回 `vlm/data/safebooru_character_sheet/`、`vlm/data/safebooru_turnaround/`、`vlm/data/角色分解/`，然后从仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.prepare_sn7_smoke_test
.\.venv\Scripts\python.exe -m vlm.scripts.validate_sn7_smoke_test
.\.venv\Scripts\python.exe -m vlm.scripts.import_sn7_design_sheet_dataset
```

再按 `vlm/docs/workflows/SN_7_PLAN.md` 做 12 张 Qwen/RunningHub 小批量真实 smoke test。

## SYSTEM STATE
当前检出分支为 `work/sn6-supervision-agent-training`。远端分支为 `main`、`work/sn6-supervision-agent-training`、`sn7-data-generation`。没有长期运行的本地服务。真实 API 凭据只在本地 `vlm/config/api.env`，该文件被 Git 忽略，不应写入 handoff 或提交。

## FILES CHANGED
- `.github/workflows/test.yml` — CI test workflow 跳过 pre-commit gitleaks hook，避免 Go 安装链路影响 Python 测试。
- `.github/workflows/gitleaks.yml` — 新增独立 gitleaks 扫描 workflow。
- `vlm/scripts/extract_atomic_rules.py` — 给公开函数补 docstring，修复 pydocstyle。
- `vlm/scripts/generate/generate_sn7_multiview.py` — 给公开函数补 docstring，修复 pydocstyle。
- `vlm/docs/HANDOFF.md` — 追加本 checkpoint，并更新 gitleaks CI 状态。
