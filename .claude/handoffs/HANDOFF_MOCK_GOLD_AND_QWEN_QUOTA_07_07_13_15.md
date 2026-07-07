# Handoff: Mock Gold 闭环 + 标注说明 + Qwen 额度恢复

**Created:** 2026-07-07 13:15
**Branch:** main
**Session Duration:** ~1 hour
**Previous Handoff:** `HANDOFF_DIRECTORY_REORGANIZATION_07_07_12_50.md`

---

## Summary

本次会话执行了上一个 handoff 的 5 个 immediate next steps：确认试标样本包稳定、写了 Stage 1 人工标注说明文档（中文）、创建了 mock gold 数据并跑通了完整的 validate → align → verified gold → summary 管线（57/57 PASS）。**重要更新：Qwen API 额度已充值完成**，之前阻塞的大批次测试（每品类 10 样本）现在可以正常推进。

---

## Work Completed

### Changes Made

- [x] 确认 `multi_view试标数据集/` 24 样本稳定（4 品类 × 4 + dataset_QSitFigures × 4 + dataset_figurine × 4）
- [x] 发现 `sample_index.csv` 中路径引用旧的 `multiview_consistency_trial_20260702_24samples_reselected` 目录（数据本身不受影响）
- [x] 创建 Stage 1 标注说明文档 `vlm/docs/supervision/stage1_annotation_instructions.md`（中文，含示例、品类特殊说明、FAQ）
- [x] 创建 trial_sample_config.json 供 mock gold 测试使用
- [x] 创建 3 个 mock CSV：`human_visual_findings.csv`（3 findings）、`annotator_gold.csv`（27 rules）、`atomic_rule_audit.csv`（27 audits）
- [x] 运行 `validate_human_annotations.py` — 57/57 行全部 PASS
- [x] 运行 `align_human_findings_to_atomic_rules.py` — 产出 4 个 candidates
- [x] 运行 `build_verified_evaluation_gold.py` — 产出 17 verified + 10 excluded
- [x] 运行 `summarize_pre_gold_assets.py` — 资产汇总正常
- [x] 更新 `vlm/docs/workflows/process.md` 反映完成状态
- [x] **Qwen API 额度已恢复**（用户确认）

### Key Decisions

| Decision | Rationale | Alternatives Considered |
|----------|-----------|------------------------|
| 标注说明用中文写 | 标注员是中国团队成员 | 英文（团队有国际成员但不适用本次） |
| mock gold 用 backpack/2812503 | 该样本已有 Qwen 预测结果，可以对照 | 其他品类（无 Qwen 结果参考） |
| mock 中 hair_color 标为 wrong_value | 模拟真实的 atomic rule 错误场景 | 全部 correct（测试不到 exclude 逻辑） |
| mock 中 9 条下半身规则标 out_of_scope | backpack 产品不覆盖下半身，符合实际 | 全部 in-scope（不符合 v3 规则） |
| 不修复 align 的 STOPWORDS 问题 | token-based 方法本身局限大，后续考虑 LLM-assisted alignment 替代 | 从 STOPWORDS 中删除 headwear/ribbon（治标不治本） |

---

## Files Affected

### Created

- `vlm/docs/supervision/stage1_annotation_instructions.md` — Stage 1 人工视觉监修标注说明（中文，含示例和品类说明）
- `vlm/tmp/mock_gold_test/trial_sample_config.json` — mock 测试用样本配置（仅 backpack/2812503）
- `vlm/tmp/mock_gold_test/human_visual_findings.csv` — 3 条 mock 视觉发现
- `vlm/tmp/mock_gold_test/annotator_gold.csv` — 27 条 mock rule-level 标注
- `vlm/tmp/mock_gold_test/atomic_rule_audit.csv` — 27 条 mock rule audit
- `vlm/tmp/mock_gold_test/validation_output/` — 校验报告（57/57 PASS）
- `vlm/tmp/mock_gold_test/alignment_output/` — 候选对齐输出（4 candidates）
- `vlm/tmp/mock_gold_test/verified_gold_output/` — verified gold（17 verified + 10 excluded）
- `vlm/tmp/mock_gold_test/pre_gold_summary/` — 资产汇总

### Modified

- `vlm/docs/workflows/process.md` — 更新日期、新增 mock gold 闭环测试结果、标记已完成项

### Read (Reference)

- `vlm/scripts/supervise/validate_human_annotations.py` — 校验逻辑和 CSV schema 定义
- `vlm/scripts/supervise/align_human_findings_to_atomic_rules.py` — token-based 对齐算法
- `vlm/scripts/supervise/build_verified_evaluation_gold.py` — verified gold 构建逻辑
- `vlm/scripts/supervise/summarize_pre_gold_assets.py` — 资产汇总脚本
- `vlm/scripts/supervise/create_human_annotation_templates.py` — 模板生成脚本
- `vlm/docs/supervision/human_annotation_csv_schemas.md` — CSV schema 定义文档
- `vlm/data/.../multi_view试标数据集/backpack/2812503/atomic_rules.json` — 27 条 atomic rules
- `vlm/data/.../multi_view试标数据集/backpack/2812503/qwen_supervision_result.csv` — Qwen 预测结果
- `vlm/config/supervision/backpack_review_samples.json` — Qwen 审核样本配置

---

## Technical Context

### Mock Gold 闭环测试结果

```text
validate     → 57/57 PASS ✅
align        → 4 candidates (2 broader_or_narrower, 1 related, 1 no_match) ✅
verified gold → 17 verified + 10 excluded ✅
  - 17 correct rules → verified gold
  - 1 wrong_value (hair_color) → excluded (rule_validity_wrong_value)
  - 9 out_of_scope (skirt/legwear/footwear/bag) → excluded
pre-gold summary → 资产汇总正常 ✅
```

### 已知限制：align 的 STOPWORDS 问题

`align_human_findings_to_atomic_rules.py` 的 STOPWORDS 集合包含 `"headwear"` 和 `"ribbon"`，当标注员在 `element_name` 中写 `headwear_ribbon` 时，这两个 token 都会被过滤掉，导致文本相似度为 0，产出 `no_match_candidate`。这是 token-based 方法的根本局限。

对齐分数整体偏低（最高 0.33），因为人工 finding 用自然语言描述而 atomic rule 用 terse ID。后续可考虑 LLM-assisted semantic alignment 作为补充或替代。

### sample_index.csv 路径过期

`multi_view试标数据集/sample_index.csv` 中的绝对路径仍引用旧的 `multiview_consistency_trial_20260702_24samples_reselected` 目录。数据本身已正确放在 `multi_view试标数据集/` 下，但 CSV 中的路径需要更新。

---

## Things to Know

### Gotchas & Pitfalls

- **不要用 Read 工具读取图片文件** — DashScope 400 错误。使用 `qwen_vl_image_tool.py`。
- **CSV 写入必须用 Python csv 模块** — 手写 CSV 容易因自由文本中的逗号导致列数不匹配，validator 会报 `AttributeError: 'list' object has no attribute 'strip'`。
- **`assign_merchandise_categories.py` 不要随意运行** — 可能重写 `sample_lists/*.txt`。
- **atomic_rules.json 中 rule ID 字段叫 `"id"` 不是 `"rule_id"`** — 各脚本的 `load_atomic_rules()` 已处理两种命名。

### Assumptions Made

- Qwen 审核样本配置（`*_review_samples.json`）引用 `generated/` 下的数据，与 `multi_view试标数据集/` 是不同的样本集
- `multi_view试标数据集/` 是给标注员用的试标包，`generated/` 是给 Qwen 批量审核用的数据集

### Known Issues

- `sample_index.csv` 路径过期（不影响数据，但可能误导后续脚本）
- align 的 STOPWORDS 和 token-based 方法对齐效果有限
- 之前 session 遗留的 9 个未提交文件仍未提交

---

## Current State

### What's Working

- ✅ 人工标注管线全链路（validate → align → verified gold → summary）
- ✅ 4 品类 Qwen prompt + 审核脚本（小批次 QC FAIL = 0）
- ✅ Stage 1 标注说明文档（中文）
- ✅ 目录结构整理完成
- ✅ mock gold 闭环验证通过

### What's Not Working

- ❌ Qwen 大批次测试未运行（**额度已恢复，可以开始**）
- ❌ `compare_predictions.py` 未开发（等 verified gold + Qwen 大批次结果）
- ❌ figurine / QSItFigures 无数据集和 prompt（等 RunningHub 补图）

### Git Status

```text
未提交修改（来自多个 session，共 10 个文件）:
 M .claude/handoffs/HANDOFF_MULTICATEGORY_PROMPT_AND_TESTING_07_06_16_15.md
 M .gitignore
 M vlm/__init__.py
 M vlm/docs/workflows/process.md          ← 本次 session 更新
 M vlm/requirements.txt
 M vlm/scripts/__init__.py
 M vlm/scripts/crawl_safebooru.py
 M vlm/scripts/data/__init__.py
 M vlm/scripts/generate/__init__.py
 M vlm/scripts/orchestrate/__init__.py

未跟踪文件:
 ?? .claude/handoffs/HANDOFF_DIRECTORY_REORGANIZATION_07_07_12_50.md
 ?? vlm/docs/supervision/stage1_annotation_instructions.md   ← 本次 session 新建
 ?? vlm/docs/workflows/head_key_chain_context_summary.markdown
 ?? vlm/docs/workflows/supervision_agent_development_plan.md
 ?? vlm/experiments/supervision/
```

---

## Next Steps

### Immediate (Start Here)

**Qwen 大批次测试**（额度已恢复，这是最高优先级）：

1. 运行 head_key_chain 10 样本审核：
   ```bash
   .venv/Scripts/python.exe -m vlm.scripts.supervise.run_multicategory_supervision_review \
     --sample-config vlm/config/supervision/head_key_chain_review_samples.json
   ```
2. 运行 cake_roll 10 样本审核：
   ```bash
   .venv/Scripts/python.exe -m vlm.scripts.supervise.run_multicategory_supervision_review \
     --sample-config vlm/config/supervision/cake_roll_review_samples.json
   ```
3. 运行 plush 10 样本审核：
   ```bash
   .venv/Scripts/python.exe -m vlm.scripts.supervise.run_multicategory_supervision_review \
     --sample-config vlm/config/supervision/plush_review_samples.json
   ```
4. 运行 backpack 10 样本审核：
   ```bash
   .venv/Scripts/python.exe -m vlm.scripts.supervise.run_backpack_supervision_review \
     --sample-config vlm/config/supervision/backpack_review_samples.json
   ```
5. 汇总 4 品类结果，分析 QC PASS/FAIL 分布和 wrong 分布

### Subsequent

- 将 Qwen 预测结果合并到样本文件夹（参考 backpack/2812503 的示例格式）
- 提交之前多个 session 积累的 10 个未提交文件
- 修复 `sample_index.csv` 中的过期路径
- 考虑改进 align 的对齐方法（LLM-assisted 替代 token-based）

### Blocked On

- 人工 Stage 1 visual findings 尚未回来
- 人工 Stage 2 atomic_rules audit 尚未回来
- figurine/QSitFigures 数据需要 RunningHub 补图

---

## Related Resources

### Commands to Run

```bash
# 验证无残留旧路径（目录整理 session 的验证）
grep -r "generated_3d_no_rules" vlm/scripts/ vlm/config/
grep -r "监修vlm数据" vlm/scripts/ vlm/config/

# mock gold 闭环验证（可重跑）
.venv/Scripts/python.exe -m vlm.scripts.supervise.validate_human_annotations \
  --visual-findings vlm/tmp/mock_gold_test/human_visual_findings.csv \
  --annotator-gold vlm/tmp/mock_gold_test/annotator_gold.csv \
  --atomic-rule-audit vlm/tmp/mock_gold_test/atomic_rule_audit.csv \
  --sample-config vlm/tmp/mock_gold_test/trial_sample_config.json \
  --output-dir vlm/tmp/mock_gold_test/validation_output

# Qwen 大批次 dry-run（验证脚本能启动但不实际调 API）
.venv/Scripts/python.exe -m vlm.scripts.supervise.run_multicategory_supervision_review \
  --sample-config vlm/config/supervision/head_key_chain_review_samples.json --dry-run
```

### 关键文档

- `vlm/docs/workflows/process.md` — 当前工作流状态（已更新）
- `vlm/docs/supervision/stage1_annotation_instructions.md` — 标注员说明文档（本次新建）
- `vlm/docs/supervision/human_annotation_csv_schemas.md` — CSV schema 定义
- `vlm/scripts/_paths.py` — 集中路径常量
- `CLAUDE.md` — 项目约定

---

## Open Questions

- [ ] Qwen 大批次测试（4 品类 × 10 样本）的结果如何？QC FAIL 率？wrong 分布？
- [ ] 标注员什么时候能回来 Stage 1 和 Stage 2 的数据？
- [ ] `_paths.py` 是否应该被所有脚本采用？还是仅在新脚本中使用？
- [ ] `sample_index.csv` 的过期路径是否需要修复？
- [ ] align 的 token-based 方法是否够用？还是需要 LLM-assisted alignment？

---

## Session Notes

- 本次会话是一个"执行上一个 handoff 的 next steps"的 session
- 5 个 immediate next steps 全部完成
- 最重要的新信息是 **Qwen API 额度已恢复**，下一个 session 应该立即开始大批次测试
- mock gold 闭环验证了管线的正确性，但也暴露了 align 的 token-based 方法的局限
- 标注说明文档是中文的，假设标注员是中国团队成员
- CSV 写入有一个坑：手写 CSV 容易因自由文本逗号导致列数不匹配，建议一律用 Python csv 模块

---

_This handoff was generated for context switching. Start a new session and use this document as your initial context._
