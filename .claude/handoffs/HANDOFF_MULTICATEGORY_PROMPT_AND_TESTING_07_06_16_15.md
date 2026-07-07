# Handoff: VLM 监修多品类视角语义规则 + 小批次测试完成

**Created:** 2026-07-06 16:15
**Branch:** main (未提交)
**Session Duration:** ~55 min

---

## Summary

本次会话接续 `HANDOFF_VLM_SUPERVISION_MULTI_CATEGORY_07_06_15_20.md`，完成了 3 个品类（head_key_chain、plush、cake_roll）的视角语义 prompt 模板、泛化审核脚本、样本配置，并通过 Qwen VL API 小批次测试（每品类 2 样本，共 6 样本）全部达到 QC FAIL = 0。figurine 和 QSItFigures 因数据集暂无生成图而跳过。

---

## Work Completed

### Changes Made

- [x] 创建 head_key_chain prompt 模板（6-section 结构，back = 角色后脑勺）
- [x] 创建 plush prompt 模板（6-section 结构，back = 角色全身背面）
- [x] 创建 cake_roll prompt 模板（6-section 结构，back = 螺旋纹面，非角色背面）
- [x] 创建泛化审核脚本 `run_multicategory_supervision_review.py`（按品类自动匹配 prompt）
- [x] 创建 3 个品类样本配置 JSON（每品类 2 个样本）
- [x] 修复 Qwen 输出下划线格式问题（`wrong_color` → `wrong color`）— 脚本端 `normalize_prediction()`
- [x] 修复 Qwen `wrong invisible` 混淆问题 — prompt 中加 `⚠️ CRITICAL STATUS RULE`
- [x] 修复 Qwen 跳过 out-of-scope 规则问题 — prompt + 脚本端 `fill_missing_out_of_scope_rules()`
- [x] 更新 `process.md` 记录新增产物和测试结果

### Key Decisions

| Decision | Rationale | Alternatives Considered |
|----------|-----------|------------------------|
| 新脚本命名 `run_multicategory_supervision_review.py` | 已有 `run_supervision_review.py`（三阶段流水线架构），不能覆盖 | 重命名旧脚本（风险大） |
| 脚本端后处理 + prompt 双保险 | Qwen 输出不完全可控，prompt 约束 + 脚本兜底更可靠 | 仅靠 prompt 约束（不够可靠） |
| auto-fill 使用 `value: "N/A"` | QC 验证要求 value 非空，`""` 会触发 `missing_value` FAIL | 空字符串（QC 报错） |
| figurine/QSitFigures 跳过 | `body_and_head/` 目录仅含 backpack，无 figurine/QSitFigures 子目录 | 创建占位模板（无数据验证，意义不大） |

---

## Files Affected

### Created

- `vlm/prompts/supervision/qwen_prompt_v3_head_key_chain.txt` — 头部挂件品类 prompt 模板
- `vlm/prompts/supervision/qwen_prompt_v3_plush.txt` — 全身毛绒玩偶品类 prompt 模板
- `vlm/prompts/supervision/qwen_prompt_v3_cake_roll.txt` — 蛋糕卷挂件品类 prompt 模板
- `vlm/scripts/supervise/run_multicategory_supervision_review.py` — 多品类泛化审核脚本
- `vlm/config/supervision/head_key_chain_review_samples.json` — head_key_chain 2 样本配置
- `vlm/config/supervision/cake_roll_review_samples.json` — cake_roll 2 样本配置
- `vlm/config/supervision/plush_review_samples.json` — plush 2 样本配置

### Modified

- `vlm/docs/workflows/process.md` — 更新"待完成"清单 + 新增"多品类视角语义规则 + 小批次测试"章节（产物列表、测试结果表格、修复问题记录、品类视角差异表）

### Read (Reference)

- `vlm/tmp/v3_schema_and_backpack_view_rules_20260706/qwen_prompt_v3_final_backpack.txt` — prompt 模板范例
- `vlm/scripts/supervise/run_backpack_supervision_review.py` — backpack 审核脚本（泛化基础）
- `vlm/scripts/supervise/run_supervision_review.py` — 三阶段审核脚本（避免覆盖）
- `vlm/config/supervision/category_rules.json` — 6 品类高层规则定义
- `vlm/config/supervision/supervision_agent_output_v3.schema.json` — v3 schema
- `vlm/config/supervision/backpack_review_samples.json` — 样本配置格式参考
- `.claude/handoffs/HANDOFF_VLM_SUPERVISION_MULTI_CATEGORY_07_06_15_20.md` — 上手文档

### Test Outputs (vlm/tmp/)

```
vlm/tmp/multicategory_supervision_review_v3/
├── head_key_chain/
│   ├── 1784345_v3_20260706_154702/  ← 最终结果：31 PASS, 0 FAIL
│   ├── 1906753_v3_20260706_154845/  ← 最终结果：20 PASS, 0 FAIL
│   └── (早期迭代目录)
├── cake_roll/
│   ├── 2175989_v3_20260706_160406/  ← 最终结果：19 PASS, 0 FAIL
│   ├── 2175991_v3_20260706_160526/  ← 最终结果：21 PASS, 0 FAIL
│   └── (早期迭代目录)
└── plush/
    ├── 2028681_v3_20260706_155054/  ← 最终结果：26 PASS, 0 FAIL
    ├── 2028685_v3_20260706_155221/  ← 最终结果：29 PASS, 0 FAIL
    └── (早期迭代目录)
```

---

## Technical Context

### 多品类审核脚本架构

`run_multicategory_supervision_review.py` 核心流程：

1. 加载样本配置 JSON（含 sample_id, category, source_image, multiview_image, atomic_rules）
2. 根据 `CATEGORY_PROMPT_TEMPLATES` 映射自动匹配品类 prompt 模板
3. 构建 prompt（模板 + 原子规则）→ 编码图片 → 调用 Qwen VL API
4. **后处理管道**（3 步）：
   - `extract_json_object()` — 解析 JSON（容忍 code fences）
   - `normalize_prediction()` — 修正 `wrong_color` → `wrong color` 等下划线问题 + 重算 result
   - `fill_missing_out_of_scope_rules()` — 对 head_only 品类自动填充缺失的身体规则
5. QC 验证 + 输出 CSV/JSONL/JSON

### 品类视角语义核心差异

| 品类 | BACK 视角含义 | 身体规则范围 | OUT-OF-SCOPE 列表 |
|------|--------------|-------------|-------------------|
| backpack | 背包背板+肩带 | 下半身 out | skirt/legwear/footwear |
| head_key_chain | 角色后脑勺 | 颈部以下全部 out | top/skirt/legwear/footwear + 通用原则 |
| cake_roll | 螺旋纹面 | 全部身体/服装 out | top/skirt/legwear/footwear + 通用原则 |
| plush | 角色全身背面 | 全部 in-scope | 仅 has_bag/bag_color |

### 数据集目录

```
vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d_no_rules/监修vlm数据/
├── head_only/
│   ├── head_key_chain/  (20+ 样本)
│   └── cake_roll/       (20+ 样本)
├── full body/
│   └── plush/           (20+ 样本)
├── body_and_head/
│   └── backpack/        (130+ 样本) ← 仅此品类，无 figurine/QSitFigures
└── _debug/
```

### 配置

- 脚本: `python -m vlm.scripts.supervise.run_multicategory_supervision_review --sample-config <path> [--dry-run]`
- 输出根目录: `vlm/tmp/multicategory_supervision_review_v3/`（按 category 子目录）
- API: `vlm/config/api.env` 中的 `QWEN_API_KEY`

---

## Things to Know

### Gotchas & Pitfalls

- **Qwen 输出格式不稳定**：status 值有时用下划线 `wrong_color` 而非空格 `wrong color`。已通过 `normalize_prediction()` 修正。
- **Qwen 会跳过 out-of-scope 规则**：即使 prompt 要求输出所有 rule_id，模型仍可能跳过身体规则。`fill_missing_out_of_scope_rules()` 通过 `BODY_RULE_KEYWORDS` 列表自动识别并填充。
- **Qwen 会多输出额外规则**：模型有时输出不在请求中的 rule_id（QC 标记为 WARN），暂未限制。
- **auto-fill value 必须非空**：设为 `"N/A"` 而非 `""`，否则 QC 报 `missing_value`。
- **不要用 Read 工具读取图片** — 同上一次 handoff 记录。
- **`assign_merchandise_categories.py` 不要随意运行** — 同上一次。

### Assumptions Made

- head_key_chain 和 plush 的 back view 是角色背面（与 backpack/cake_roll 不同）— 已验证
- `BODY_RULE_KEYWORDS` 列表覆盖了常见身体/服装规则前缀 — 可能需要随新样本扩展
- figurine/QSitFigures 需要等 RunningHub 补图后才有数据

### Known Issues

- Qwen 对某些样本可能过于宽松（全部判 correct），需要更多样本验证
- 模型多输出的额外规则（WARN）可能干扰 aggregate_counts 统计
- 每次 API 调用耗时 70-125 秒，大批量时需考虑并发或缓存

---

## Current State

### Priority Update (2026-07-07)

后续讨论确认：当前手头的数据只有**未经人工金标验证的 `atomic_rules`** 和 **RunningHub 生成的 `multiview` 三视图**。因此 `atomic_rules` 不能直接作为 gold，也不能让人工第一轮只按 `atomic_rules` 逐条核对。当前优先级应从“继续扩大 Qwen API 测试”调整为“等待人工 Stage 1 gold 期间，先把标注导入、校验、mock gold 和评估闭环准备好”。

新的数据口径：

1. **Stage 1: human visual findings / generation quality gold**
   - 输入：`2d_original.*` + `multiview_design.*`
   - 不把 `atomic_rules.json` 当标准答案
   - labor 需要自由找视觉问题、画框、记录 issue
   - 目标：判断生成三视图是否忠于原始 2D 角色，以及错在哪里

2. **Stage 2: atomic_rules audit / rule quality gold**
   - 输入：`2d_original.*` + `atomic_rules.json`
   - 逐条审核 atomic rule 是否真实描述原图
   - 目标：把 rule extraction error 和 generation error 拆开

3. **Stage 3: verified evaluation gold**
   - 输入：Stage 1 findings + Stage 2 rule audit + atomic_rules
   - 只把人工确认正确/可对齐的内容用于后续 Qwen 预测对比

在人工 gold 回来前，Qwen 只保留小样本 baseline / dry-run / schema 稳定性检查，不建议继续大规模烧 API 额度。

### What's Working

- ✅ head_key_chain prompt + 脚本 + 2 样本测试通过（QC FAIL = 0）
- ✅ cake_roll prompt + 脚本 + 2 样本测试通过（QC FAIL = 0）
- ✅ plush prompt + 脚本 + 2 样本测试通过（QC FAIL = 0）
- ✅ backpack prompt + 脚本（上次会话已完成）
- ✅ 后处理管道（normalize + auto-fill）稳定运行
- ✅ v3 schema + category_rules.json（6 品类高层规则已定义）

### What's Not Working

- ❌ figurine (dataset_figurine) — 无数据集，无 prompt 模板，无测试
- ❌ dataset_QSitFigures — 无数据集，无 prompt 模板，无测试

### Tests

- [x] dry-run: 3 品类 × 2 样本 = 6 次 dry-run 全部成功
- [x] API test: 3 品类 × 2 样本 = 6 次 API 调用全部成功，QC FAIL = 0
- [ ] 扩大测试: 每品类 5-10 个样本（待执行）

---

## Next Steps

### Immediate (Start Here)

1. **冻结当前人工试标样本包**：把 `multi_view试标数据集` 作为当前 Stage 1 gold seed，确认样本列表、`2d_original.*`、`multiview_design.*`、`atomic_rules.json` 不再被替换。记录生成方式为 RunningHub / 原图 + prompt，避免人工标注回来后文件对不上。
2. **明确给 labor 的 Stage 1 标注任务**：第一轮只看 `2d_original.*` + `multiview_design.*`，不要把 `atomic_rules.json` 当标准答案。labor 需要自由找问题、画框，并按固定字段记录一行一个 visual finding。
3. **准备 `human_visual_findings.csv` 导入/校验链路**：支持 xlsx/csv 导入，校验 `sample_id`、`category`、`issue_type`、`view`、`severity`、bbox 格式、重复行、空样本等问题。
4. **用 mock gold 跑通闭环**：手写 2-3 条假的 human findings，验证导入 -> 校验 -> 汇总 -> 报告骨架可运行。不要等真实人工标注回来后才发现格式读不了。
5. **准备 Stage 2 `atomic_rules` 审核表**：设计 `atomic_rule_audit.csv` 字段，包括 `sample_id`、`rule_id`、`rule_value`、`rule_validity`、`corrected_value`、`reason`、`bbox_original`。第二轮再让 labor 审核 rules。

### Subsequent

- 准备 human finding -> atomic rule 的候选对齐逻辑：只生成候选，不自动当 gold。真实标注回来后再人工复核。
- 抽查现有 multi_view 失败类型，整理 failure taxonomy，例如新增兽耳/角、发型简化、颜色漂移、三视图不一致、背面乱补、商品类型跑偏、图案位置错误。
- Qwen baseline 保持小样本运行即可，用于检查输出 schema 稳定性、是否漏规则、是否乱判背面、是否能识别三视图不一致。不要在没有 gold 的情况下继续扩大 API 调用。
- 等人工 Stage 1 / Stage 2 标注回来后：导入 -> 自动质检 -> 构建 verified evaluation gold -> Qwen predictions 对比。
- 有 verified gold 后，再决定是否扩大 backpack/head_key_chain/cake_roll/plush 到 5-10 个样本或更多，并分析 Qwen 判断错误模式，迭代 prompt。
- 等 RunningHub 补 figurine/QSitFigures 数据后，再创建 prompt 模板 + 样本配置 + 小批次测试。

### Blocked On

- 人工 Stage 1 visual findings 尚未回来：无法做真实 generation quality 评估。
- 人工 Stage 2 atomic_rules audit 尚未回来：`atomic_rules` 不能作为 gold。
- figurine/QSitFigures 数据：需 RunningHub 补图（参考 `runninghub_blocked_samples.csv` 跳过风控样本）。

---

## Related Resources

### Commands to Run

```bash
# 运行 head_key_chain 审核（真实 API 调用）
.venv/Scripts/python.exe -m vlm.scripts.supervise.run_multicategory_supervision_review \
  --sample-config vlm/config/supervision/head_key_chain_review_samples.json

# 运行 cake_roll 审核
.venv/Scripts/python.exe -m vlm.scripts.supervise.run_multicategory_supervision_review \
  --sample-config vlm/config/supervision/cake_roll_review_samples.json

# 运行 plush 审核
.venv/Scripts/python.exe -m vlm.scripts.supervise.run_multicategory_supervision_review \
  --sample-config vlm/config/supervision/plush_review_samples.json

# dry-run 模式（不调 API，验证配置）
.venv/Scripts/python.exe -m vlm.scripts.supervise.run_multicategory_supervision_review \
  --sample-config vlm/config/supervision/head_key_chain_review_samples.json --dry-run

# 查看各品类可用样本
ls "vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d_no_rules/监修vlm数据/head_only/head_key_chain/"
ls "vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d_no_rules/监修vlm数据/head_only/cake_roll/"
ls "vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d_no_rules/监修vlm数据/full body/plush/"
```

---

## Open Questions

- [ ] Stage 1 labor 返回的 bbox 格式是什么？是否需要补 alias/转换器？
- [ ] human_visual_findings.csv 是否需要支持一个 issue 多个 bbox？
- [ ] Stage 2 atomic_rules audit 是否由同一批 labor 完成，还是需要单独说明规则审核口径？
- [ ] Qwen 对 5-10 个样本是否仍保持稳定？该问题等 gold 或 mock gold 闭环跑通后再扩大验证。
- [ ] Qwen 是否对某些品类过于宽松（全判 correct 而忽略真实错误）？需要人工 gold 回来后判断。
- [ ] `BODY_RULE_KEYWORDS` 列表是否足够覆盖？新样本可能出现未匹配的规则前缀
- [ ] figurine/QSitFigures 何时能有生成数据？
- [ ] 是否需要在 prompt 中限制 Qwen 只输出请求的 rule_id（减少 WARN 噪音）？

---

## Session Notes

- 本次会话共进行了 3 轮 API 测试迭代（每轮 3 品类 × 2 样本 = 6 次调用），总计约 18 次 API 调用
- 第 1 轮发现 3 个问题：下划线格式、wrong invisible 混淆、out-of-scope 规则缺失
- 第 2 轮修复 prompt + 添加 normalize，head_key_chain 和 plush 通过，cake_roll 仍有 7 FAIL（missing_value）
- 第 3 轮修复 auto-fill value="N/A"，全部 6 样本 QC FAIL = 0
- 总 API 耗时约 6 样本 × ~90 秒 ≈ 9 分钟/轮
- 早期迭代目录保留在 `vlm/tmp/multicategory_supervision_review_v3/` 下供对比分析

---

_This handoff was generated at context window capacity. Start a new session and use this document as your initial context._
