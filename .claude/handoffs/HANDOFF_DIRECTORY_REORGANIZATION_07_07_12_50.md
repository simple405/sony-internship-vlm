# Handoff: VLM 项目目录结构整理

**Created:** 2026-07-07 12:50
**Branch:** main
**Session Duration:** ~2 hours
**Previous Handoff:** `HANDOFF_MULTICATEGORY_PROMPT_AND_TESTING_07_06_16_15.md`

---

## Summary

本次会话对 VLM 监修项目进行了全面的目录结构整理。完成了 7 个阶段的清理工作：抢救 backpack prompt 到正式目录、移动旧项目到 archive、清空 119MB 临时文件、修复数据目录双重嵌套、扁平化 generated 目录结构（含创建集中路径模块 `_paths.py`）、清理散落文件、更新文档。所有改动通过 5 个 atomic commit 提交。

---

## Work Completed

### Changes Made

- [x] 将 backpack prompt 模板从 `vlm/tmp/` 移到 `vlm/prompts/supervision/qwen_prompt_v3_backpack.txt`
- [x] 更新 `run_backpack_supervision_review.py` 和 `run_multicategory_supervision_review.py` 中的 prompt 路径
- [x] 将 `vlm/reference/ip_review_project/` 移到 `vlm/archive/ip_review_project/`
- [x] 更新 `run_single_qwen_runninghub_demo.py` 中的 reference 路径
- [x] 清空 `vlm/tmp/` 全部 50 项（119 MB）
- [x] 修复 `vlm/data/raw_trials/动漫IP监修试标数据/` 双重嵌套
- [x] 清理 legacy 目录中的 `desktop.ini` 和 `__pycache__`
- [x] 扁平化 generated 目录：`generated_3d_no_rules/监修vlm数据/{body_and_head,head_only,full body}/{category}/` → `generated/{category}/`
- [x] 创建 `vlm/scripts/_paths.py` 集中路径常量模块
- [x] 更新 6 个脚本 + 4 个 JSON 配置中的旧路径引用
- [x] 删除空目录 `output/`、`.agents/`
- [x] 移动 `human_annotation_csv_schemas.md` 从 `config/supervision/` 到 `docs/supervision/`
- [x] 更新 `process.md` 和 `vlm/README.md`

### Key Decisions

| Decision | Rationale | Alternatives Considered |
|----------|-----------|------------------------|
| 扁平化 generated/ 而非重命名数据集根 | 9 个脚本 + 4 个 JSON 引用 `japanese_anime_turnaround_pilot_20`，改名风险太大 | 重命名数据集根目录 |
| 创建 `_paths.py` 集中路径常量 | 减少 30+ 处散布的硬编码路径，后续新脚本可直接 import | 在每个脚本中单独修改（维护成本高） |
| RunningHub staging 路径也迁移到 `generated/runninghub/` | 保持一致性，`generated_3d_no_rules/` 已删除 | 保留旧路径（目录已不存在） |
| 不改动 legacy 中有内容的 output/ 目录 | 91 个项目可能有参考价值 | 全部删除 |
| tmp/ 全部清空不保留 | 用户确认全部可删 | 分类保留部分 |

---

## Files Affected

### Created

- `vlm/scripts/_paths.py` — 集中路径常量模块（PROJECT_ROOT, DATASET_ROOT, GENERATED_ROOT, API_ENV_FILE 等）
- `vlm/prompts/supervision/qwen_prompt_v3_backpack.txt` — backpack 品类 prompt（从 tmp 复制）
- `vlm/docs/supervision/human_annotation_csv_schemas.md` — CSV schema 文档（从 config 移入）

### Modified

- `vlm/scripts/supervise/run_backpack_supervision_review.py` — 更新 BACKPACK_PROMPT_TEMPLATE 路径（第 33 行）
- `vlm/scripts/supervise/run_multicategory_supervision_review.py` — 更新 CATEGORY_PROMPT_TEMPLATES["backpack"]（第 48 行）
- `vlm/scripts/orchestrate/run_single_qwen_runninghub_demo.py` — 更新 reference prompt 和 env 路径（第 34-35 行）
- `vlm/scripts/supervise/collect_review_pairs.py` — 更新 DEFAULT_GENERATED_ROOT（第 26 行）+ 简化 generated_category_dir()（第 92-96 行）
- `vlm/scripts/data/assign_merchandise_categories.py` — 更新 generated_root（第 111 行）
- `vlm/scripts/generate/generate_head_keychain_with_runninghub_g2.py` — 更新 DEFAULT_DIRECT_OUTPUT_DIR（第 27-32 行）
- `vlm/scripts/orchestrate/run_runninghub_merchandise_full_batch.py` — 更新 output_dir（第 159, 246 行）
- `vlm/scripts/supervise/review_schemas.py` — 更新注释中的路径引用（第 27-29 行）
- `vlm/config/supervision/backpack_review_samples.json` — 批量替换路径（20 处）
- `vlm/config/supervision/head_key_chain_review_samples.json` — 批量替换路径（20 处）
- `vlm/config/supervision/cake_roll_review_samples.json` — 批量替换路径（20 处）
- `vlm/config/supervision/plush_review_samples.json` — 批量替换路径（20 处）
- `vlm/docs/workflows/process.md` — 更新核心路径、已有产物、下一步等章节
- `vlm/README.md` — 重写目录结构描述

### Moved (Data, not git-tracked)

- `vlm/data/.../generated_3d_no_rules/监修vlm数据/body_and_head/backpack/` → `vlm/data/.../generated/backpack/`
- `vlm/data/.../generated_3d_no_rules/监修vlm数据/head_only/head_key_chain/` → `vlm/data/.../generated/head_key_chain/`
- `vlm/data/.../generated_3d_no_rules/监修vlm数据/head_only/cake_roll/` → `vlm/data/.../generated/cake_roll/`
- `vlm/data/.../generated_3d_no_rules/监修vlm数据/full body/plush/` → `vlm/data/.../generated/plush/`
- `vlm/data/.../generated_3d_no_rules/监修vlm数据/full body/dataset_QSitFigures/` → `vlm/data/.../generated/dataset_QSitFigures/`
- `vlm/data/.../generated_3d_no_rules/监修vlm数据/full body/dataset_figurine/` → `vlm/data/.../generated/dataset_figurine/`
- `vlm/reference/ip_review_project/` → `vlm/archive/ip_review_project/`

### Deleted (Data, not git-tracked)

- `vlm/tmp/` 下全部 50 项（47 子目录 + 4 松散文件，119 MB）
- `vlm/data/.../generated_3d_no_rules/` 整个旧目录（内容已迁出）
- `vlm/data/.../generated_3d_no_rules/监修vlm数据/_debug/`（debug 输出）
- `vlm/data/legacy/ip_review_project/data/desktop.ini`
- `vlm/data/legacy/ip_review_project/__pycache__/`
- `output/`（根目录空目录）
- `.agents/`（根目录空目录）
- 4 处 `__pycache__/` 目录

---

## Technical Context

### 路径映射表（旧→新）

| 旧路径片段 | 新路径片段 |
|-----------|-----------|
| `generated_3d_no_rules/监修vlm数据/body_and_head/backpack/` | `generated/backpack/` |
| `generated_3d_no_rules/监修vlm数据/head_only/head_key_chain/` | `generated/head_key_chain/` |
| `generated_3d_no_rules/监修vlm数据/head_only/cake_roll/` | `generated/cake_roll/` |
| `generated_3d_no_rules/监修vlm数据/full body/plush/` | `generated/plush/` |
| `generated_3d_no_rules/runninghub/<category>/` | `generated/runninghub/<category>/` |
| `vlm/reference/ip_review_project/` | `vlm/archive/ip_review_project/` |
| `vlm/tmp/.../qwen_prompt_v3_final_backpack.txt` | `vlm/prompts/supervision/qwen_prompt_v3_backpack.txt` |
| `vlm/config/supervision/human_annotation_csv_schemas.md` | `vlm/docs/supervision/human_annotation_csv_schemas.md` |

### _paths.py 模块

```python
from vlm.scripts._paths import (
    PROJECT_ROOT,    # D:\索尼实习
    VLM_ROOT,        # vlm/
    DATASET_ROOT,    # vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20
    GENERATED_ROOT,  # {DATASET_ROOT}/generated
    ATOMIC_RULES_ROOT, IMAGE_ROOT, MULTI_VIEW_ROOT,
    API_ENV_FILE,    # vlm/config/api.env
    SUPERVISION_PROMPTS_DIR, GENERATION_PROMPTS_DIR,
    TMP_DIR, ARCHIVE_DIR, DOCS_DIR, EXPERIMENTS_DIR,
)
```

### 整理后的目录结构

```
vlm/
├── scripts/
│   ├── _paths.py              # 🆕 集中路径常量
│   ├── crawl_safebooru.py
│   ├── data/                  # assign_merchandise_categories.py
│   ├── generate/              # generate_head_keychain_with_runninghub_g2.py
│   ├── orchestrate/           # 批量运行脚本
│   └── supervise/             # 18 个审核/标注/评估脚本
├── config/
│   ├── api.env
│   └── supervision/           # JSON configs + schema（csv_schemas.md 已移走）
├── prompts/
│   ├── supervision/           # 7 个 prompt（+backpack）🆕
│   ├── generation/runninghub/ # 7 个 RunningHub prompt
│   └── references/
├── data/                      # gitignored
│   ├── legacy/                # 清理后
│   ├── raw_trials/            # 双重嵌套已修复
│   └── safebooru_2d/.../
│       ├── generated/         # 🆕 扁平化品类目录
│       ├── atomic_rules/
│       ├── image/
│       └── multi_view试标数据集/
├── docs/
│   ├── supervision/           # 🆕 csv_schemas.md
│   ├── workflows/
│   └── source_pdfs/
├── experiments/
├── tmp/                       # 已清空
└── archive/                   # gitignored
    ├── 2026-06-29_cleanup/
    └── ip_review_project/     # 🆕 从 reference/ 移入
```

---

## Things to Know

### Gotchas & Pitfalls

- **不要用 Read 工具读取图片文件** — DashScope 400 错误。使用 `qwen_vl_image_tool.py`。
- **`assign_merchandise_categories.py` 不要随意运行** — 可能重写 `sample_lists/*.txt`。
- **RunningHub staging 路径已更新** — 从 `generated_3d_no_rules/runninghub/` 改为 `generated/runninghub/`。首次运行 RunningHub 脚本时会自动创建新目录。
- **`_paths.py` 已创建但旧脚本尚未全部迁移** — 只有路径发生了变化的脚本被更新，大部分脚本仍然使用硬编码的 `Path("vlm/data/...")` 而非 `from _paths import ...`。可以逐步迁移。
- **git 有未提交的修改** — `.gitignore`, `__init__.py` 文件, `crawl_safebooru.py`, 以及 handoff 文件有来自前几个 session 的未提交修改。这些不是本次 session 产生的。

### Assumptions Made

- `generated_3d_no_rules/` 已完全删除，所有 RunningHub 脚本会自动创建新的 `generated/runninghub/` 目录
- `_debug/` 目录中的内容是旧 debug 输出，可以安全删除
- legacy 目录中有内容的 output/（91 项）保留不删

### Known Issues

- 旧脚本尚未使用 `_paths.py` — 只是定义了常量，现有脚本仍用硬编码路径。这是一个渐进式改进。
- `.gitignore` 可能需要更新以匹配新的 `generated/` 路径（当前 `generated_3d_no_rules` 可能仍在 gitignore 规则中）

---

## Current State

### What's Working

- ✅ 所有 7 个品类 prompt 模板统一在 `vlm/prompts/supervision/`
- ✅ generated 目录扁平化，路径引用全部更新
- ✅ 4 个 JSON 样本配置路径已更新
- ✅ 6 个脚本路径引用已更新
- ✅ `_paths.py` 集中路径模块已创建
- ✅ tmp/ 已清空
- ✅ 旧项目已归档
- ✅ 文档已更新
- ✅ grep 验证无残留旧路径引用

### What's Not Working

- ❌ figurine / QSItFigures — 无数据集，无 prompt 模板（等 RunningHub 补图）
- ❌ `_paths.py` 尚未被所有脚本采用（渐进式改进）

### Git Commits (本次会话)

```
3d37e76 docs: update process.md and README.md to reflect directory reorganization
257016d chore: clean up scattered files and empty directories
3672d31 refactor: flatten generated data directory and create centralized _paths.py
2eaa287 refactor: move reference/ip_review_project to archive/
b00c3fd refactor: move backpack prompt template to formal prompts/ directory
```

### Uncommitted Changes (来自前几个 session)

```
M .claude/handoffs/HANDOFF_MULTICATEGORY_PROMPT_AND_TESTING_07_06_16_15.md
M .gitignore
M vlm/__init__.py
M vlm/requirements.txt
M vlm/scripts/__init__.py
M vlm/scripts/crawl_safebooru.py
M vlm/scripts/data/__init__.py
M vlm/scripts/generate/__init__.py
M vlm/scripts/orchestrate/__init__.py
```

---

## Next Steps

### Immediate (Start Here)

根据上一次 handoff 的优先级调整，主线是**在人工 gold 回来前把标注闭环跑通**：

1. **冻结试标样本包**：确认 `multi_view试标数据集/` 的样本不再被替换
2. **明确给 labor 的 Stage 1 标注任务**：写说明文档，第一轮只看 2D + 生成图，不当 atomic_rules 为 gold
3. **准备 human_visual_findings.csv 导入/校验链路**：确认 `validate_human_annotations.py` 支持实际格式
4. **用 mock gold 跑通闭环**：手写 2-3 条假 finding → 导入 → 校验 → 汇总 → 报告
5. **准备 Stage 2 atomic_rule_audit.csv 字段设计**

### Subsequent

- 逐步将更多脚本迁移到使用 `_paths.py` 中的常量
- 更新 `.gitignore` 以匹配新的 `generated/` 路径模式
- 提交之前 session 遗留的未提交修改

### Blocked On

- 人工 Stage 1 visual findings 尚未回来
- 人工 Stage 2 atomic_rules audit 尚未回来
- figurine/QSitFigures 数据需要 RunningHub 补图

---

## Related Resources

### Commands to Run

```bash
# 验证无残留旧路径
grep -r "generated_3d_no_rules" vlm/scripts/ vlm/config/
grep -r "监修vlm数据" vlm/scripts/ vlm/config/
grep -r "vlm/reference" vlm/scripts/

# 查看新目录结构
ls vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated/
ls vlm/prompts/supervision/

# dry-run 验证审核脚本（需要 API key 但不会实际调用 API）
.venv/Scripts/python.exe -m vlm.scripts.supervise.run_multicategory_supervision_review --sample-config vlm/config/supervision/backpack_review_samples.json --dry-run
```

### 关键文档

- `vlm/docs/workflows/process.md` — 当前工作流状态（已更新）
- `vlm/README.md` — 目录结构说明（已更新）
- `vlm/scripts/_paths.py` — 集中路径常量
- `CLAUDE.md` — 项目约定

---

## Open Questions

- [ ] `_paths.py` 是否应该被所有脚本采用？还是仅在新脚本中使用？
- [ ] `.gitignore` 中是否有 `generated_3d_no_rules` 相关规则需要更新为 `generated/`？
- [ ] RunningHub staging 数据（`generated/runninghub/`）和 supervision curated 数据（`generated/<category>/`）是否需要进一步区分？
- [ ] 之前 session 遗留的 9 个未提交文件何时提交？

---

## Session Notes

- 本次会话是一个纯整理/重构 session，没有新增业务逻辑
- 用户明确选择了最彻底的整理方案（全部清空 tmp、做结构整理、移动旧项目）
- Phase 5（数据重组）是最高风险阶段，涉及 3.7GB 数据移动 + 13 个文件更新，通过 grep 验证确认无残留引用
- 所有改动通过 5 个 atomic commit 提交，每个 commit 对应一个独立阶段
- 会话开始时还做了一致性检查（handoff vs process.md），发现了 4 个不一致并在 Phase 7 文档更新中修复

---

_This handoff was generated at context window capacity. Start a new session and use this document as your initial context._
