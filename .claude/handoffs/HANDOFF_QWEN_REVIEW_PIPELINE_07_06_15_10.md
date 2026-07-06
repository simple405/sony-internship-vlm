# Handoff: Qwen Supervision Review Pipeline + Backpack View Semantics 验证

**Created:** 2026-07-06 15:10 +08:00
**Branch:** main
**Session Duration:** ~1.5 小时（从上一个 handoff 继续）

---

## Summary

本会话从上一个 handoff 继续，完成了三项核心工作：(1) 将 v3 schema 从 tmp 移到 `vlm/config/supervision/` 正式位置；(2) 编写了可复用的 Qwen VL 监督审核脚本 `run_backpack_supervision_review.py`；(3) 用修正后的 prompt（含 SECTION 3 Backpack View Semantics）重跑了 2812503 和 2807649 两个 backpack 样本，**成功修复了全部 19 条 back_visible 误判**。

---

## Work Completed

### Changes Made

- [x] 更新 `build_annotation_products.py`：`INVISIBLE_STATUS_VALUES` 从 `{"correct invisible", "wrong invisible"}` 改为 `{"correct", "wrong invisible"}`
- [x] 将 v3 schema 和 example JSON 从 tmp 复制到 `vlm/config/supervision/`
- [x] 创建 `vlm/scripts/supervise/run_backpack_supervision_review.py` — 完整的 Qwen VL 审核脚本
- [x] 创建 `vlm/config/supervision/backpack_review_samples.json` — 样本配置文件
- [x] 重跑 backpack/2812503：27 条规则，11 条 back_visible 误判修复，QC 27 PASS
- [x] 重跑 backpack/2807649：21 条规则，8 条 back_visible 误判修复，QC 21 PASS
- [x] 生成对比报告 `vlm/tmp/backpack_supervision_review_v3/COMPARISON_REPORT.md`
- [x] 更新 `vlm/docs/workflows/process.md`（进度、产物路径、下一步）
- [x] 清理 dry-run 临时目录

### Key Decisions

| Decision | Rationale | Alternatives Considered |
|----------|-----------|------------------------|
| 脚本独立于 `run_supervision_review.py` | 旧脚本是 dry-run only，新脚本直接调 Qwen API，职责分离更清晰 | 在旧脚本上魔改（复杂度高，破坏性大） |
| 使用 `qwen-vl-max` 而非 `qwen-vl-plus` | 之前的预测用的就是 max，保持一致便于对比 | plus 更便宜但可能精度不够 |
| atomic_rules 中 `id` 字段在脚本里 normalize 为 `rule_id` | 源文件用 `id`，prompt 和输出用 `rule_id`，脚本做转换 | 改源文件（影响面大） |
| boolean value (`true`) 转为 Python `str(True)` → `"True"` | 与旧 prompt 中 `"True"` 格式一致 | 用 JSON `true`（与旧格式不一致） |
| 暂不修 Qwen 输出的顶层 schema 偏差 | 规则级字段完全正确，CSV 可用；顶层结构偏差不影响评测 | 加 few-shot example 或后处理（增加复杂度） |

---

## Files Affected

### Created (本会话)

- `vlm/scripts/supervise/run_backpack_supervision_review.py` - Qwen VL 监督审核脚本（~300 行）
- `vlm/config/supervision/backpack_review_samples.json` - 2 个 backpack 样本配置
- `vlm/config/supervision/supervision_agent_output_v3.schema.json` - 从 tmp 复制的 v3 schema
- `vlm/config/supervision/supervision_agent_output_v3.example.json` - 从 tmp 复制的 v3 example
- `vlm/tmp/backpack_supervision_review_v3/2812503_v3_view_semantics_20260706_135832/` - 新预测输出（9 个文件）
- `vlm/tmp/backpack_supervision_review_v3/2807649_v3_view_semantics_20260706_140006/` - 新预测输出
- `vlm/tmp/backpack_supervision_review_v3/COMPARISON_REPORT.md` - 新旧预测对比报告

### Modified

- `vlm/scripts/supervise/build_annotation_products.py` - 第 46 行：`INVISIBLE_STATUS_VALUES` 改为 `{"correct", "wrong invisible"}`
- `vlm/docs/workflows/process.md` - 更新时间戳、产物路径、下一步列表（标记已完成项）

### Read (Reference)

- `.claude/handoffs/HANDOFF_V3_SCHEMA_AND_SKILLS_07_06_13_45.md` - 上一个 handoff（本次工作起点）
- `vlm/scripts/orchestrate/run_single_qwen_runninghub_demo.py` - Qwen API 调用模式参考
- `vlm/scripts/supervise/vlm_client.py` - dry-run VLM 客户端（确认不直接可用）
- `vlm/scripts/supervise/run_supervision_review.py` - 旧 dry-run 审核脚本
- `vlm/tmp/qwen_v3_prediction_backpack_2812503_*/request_payload_redacted.json` - 旧预测的 API 调用结构
- `vlm/config/supervision/category_rules.json` - 品类规则定义
- `vlm/data/.../atomic_rules/2812503/2812503_atomic_rules.json` - atomic rules 源文件（字段名为 `id`）

---

## Technical Context

### Architecture/Design Notes

**Qwen VL 审核管线（本次建立的）**：
```
sample_config.json + prompt_template.txt + source_image + multiview_image
  → run_backpack_supervision_review.py
    → qwen_vl_chat(api_key, messages=[system, user{text+2 images}])
      → extract_json_object(raw_text)
        → flatten_rules() → CSV
        → run_qc() → QC report CSV
```

**脚本核心设计**：
- 支持 `--dry-run` 模式（只构建 prompt，不调 API）
- 支持批量样本（通过 JSON 配置文件）
- 输出完整 provenance：prompt、redacted request、raw response、JSON、CSV、QC、summary
- `INVISIBLE_STATUS_VALUES` 已更新为 v3 约定

**Qwen API 调用细节**：
- Endpoint: `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- Model: `qwen-vl-max`
- 图片：base64 data URL，通过 `image_url` content block 传入
- `response_format: {"type": "json_object"}` 确保 JSON 输出
- `temperature: 0.0`，`max_tokens: 8000`
- API key 从 `vlm/config/api.env` 加载

**Qwen 输出 schema 偏差（已发现未修）**：

| 字段 | 期望（v3 schema） | Qwen 实际输出 |
|------|-------------------|-------------|
| `aggregate_counts` | `{total_rules, correct_rules, wrong_rules, unsure_rules}` | `{total_rules, correct, wrong, invisible}` |
| `evidence` | 结构化数组 `[{view, source_region, ...}]` | 纯字符串 |
| `inputs` | `{images: [{role, path}], atomic_rules_path}` | `{source_image, generated_design}` |
| 规则级 12 字段 | ✅ | ✅ 完全匹配 |

### Dependencies

- `requests` — Qwen API 调用
- `vlm/config/api.env` — API 密钥（QWEN_API_KEY, QWEN_BASE_URL 等）
- Python 3.10+

### Configuration Changes

- `vlm/config/supervision/` 新增 4 个文件（schema, example, backpack_review_samples, 已有的 category_rules + severity_policy）

---

## Things to Know

### Gotchas & Pitfalls

- **atomic_rules 源文件用 `id` 不是 `rule_id`**：脚本已做 normalize，但如果直接读 JSON 要注意
- **boolean values**：atomic rules 中 `has_bangs`, `headwear_ribbon`, `has_bag` 的 value 是 JSON `true`/`false`，脚本转为 Python `str()` → `"True"`/`"False"`
- **dry-run 目录和真实运行目录不同**：因为 timestamp 不同，glob 时要用 `[0]` 取最新或用精确路径
- **Qwen 调用耗时**：2812503 约 94 秒，2807649 约 74 秒，timeout 设 300 秒够用
- **Qwen 的 "全部判 correct" 倾向**：两个样本 48 条规则全部 `result=correct`，可能是真没问题也可能是过宽松，需更多样本或人工标注验证

### Assumptions Made

- `headwear_ribbon` 在背包背面 visible（蝴蝶结延伸到背板上沿）— Qwen 新预测也这样判断，与人工编写的视角语义一致
- 两个样本的 `result=correct` 可能确实正确（商品图质量高），但需要更多样本确认

### Known Issues

- **Qwen 顶层 JSON 结构不完全符合 v3 schema**：aggregate_counts 字段名、evidence 类型、inputs 结构都不同。规则级字段正确，CSV 不受影响，但 JSON 对接需要注意
- **只有 backpack 品类有视角语义规则**：其他 5 个品类（head_key_chain, cake_roll, plush, dataset_QSitFigures, dataset_figurine）还没写
- **Working tree 大量未提交变更**：12 个 modified 文件 + 约 25 个 untracked 文件，建议尽快 `/atomic-commit`

---

## Current State

### What's Working

- ✅ v3 schema 固化在 `vlm/config/supervision/`
- ✅ `INVISIBLE_STATUS_VALUES` 已更新
- ✅ `run_backpack_supervision_review.py` 脚本（dry-run + 真实 API 调用）
- ✅ Backpack view semantics 在 prompt 中生效（19 条误判全部修复）
- ✅ `process.md` 已更新到最新进度
- ✅ 对比报告已生成

### What's Not Working

- ⏳ 其他品类视角语义规则未写
- ⏳ Qwen 输出的顶层 schema 偏差未修
- ⏳ 评测脚本未建（blocked on 人工标注）
- ⏳ 未扩大测试样本量

### Tests

- [x] Dry-run：两个样本 prompt 构建正确，atomic rules normalize 正确
- [x] Qwen API 调用：2812503（27 rules, 94s）和 2807649（21 rules, 74s）均成功
- [x] QC 验证：48 条规则全部 PASS
- [x] 新旧对比：2812503 修正 11 条、2807649 修正 8 条 back_visible 误判，front/side 无变化
- [ ] 人工标注对比：blocked on 标注返回

---

## Next Steps

### Immediate (Start Here)

1. **为其他品类写视角语义规则**：
   - 需要看每个品类的 atomic_rules（rule_id 列表），了解哪些规则涉及哪些视角
   - 品类列表：head_key_chain, cake_roll, plush, dataset_QSitFigures, dataset_figurine
   - 每个品类的 front/side/back 含义不同，需要分别定义
   - atomic rules 在 `vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/atomic_rules/{sample_id}/`

2. **扩展测试到全品类 5-10 个样本**：
   - 把其他品类的样本加入 `backpack_review_samples.json`（或新建 `review_samples.json`）
   - 需要找到各品类的 source_image + multiview_image + atomic_rules 路径
   - multiview images 在 `vlm/data/safebooru_2d/.../generated_3d_no_rules/监修vlm数据/` 下按品类分目录

3. **`/atomic-commit` 整理 working tree**：
   - 当前有 12 modified + ~25 untracked 文件
   - 建议分批提交：schema 固化、新脚本、预测结果、文档更新

### Subsequent

- 修 Qwen 顶层 schema 偏差（在 prompt 中加 few-shot example 或内联 JSON Schema）
- 创建评测脚本（对比 Qwen CSV vs 人工 gold CSV）
- 等人工标注回来后跑完整评测

### Blocked On

- 人工标注尚未返回（依赖外部标注员）
- `headwear_ribbon` 在背包背面是否真的 visible（需看实际商品图确认）

---

## Related Resources

### Documentation

- 项目进度文档：`vlm/docs/workflows/process.md`（2026-07-06 14:30 更新）
- 对比报告：`vlm/tmp/backpack_supervision_review_v3/COMPARISON_REPORT.md`
- 上一个 handoff：`.claude/handoffs/HANDOFF_V3_SCHEMA_AND_SKILLS_07_06_13_45.md`

### Commands to Run

```bash
# Dry-run 验证新样本配置
python -m vlm.scripts.supervise.run_backpack_supervision_review \
  --sample-config vlm/config/supervision/backpack_review_samples.json \
  --dry-run

# 真实 API 调用
python -m vlm.scripts.supervise.run_backpack_supervision_review \
  --sample-config vlm/config/supervision/backpack_review_samples.json \
  --env-file vlm/config/api.env \
  --model qwen-vl-max

# 查找各品类的 multiview 图片
ls "vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d_no_rules/监修vlm数据/"

# 查找 atomic rules
ls "vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/atomic_rules/"

# 原子提交
/atomic-commit
```

### Search Queries

- `grep -r "back_visible" vlm/tmp/backpack_supervision_review_v3/` — 查看新预测的 back_visible 值
- `ls vlm/data/.../atomic_rules/` — 列出所有有 atomic rules 的样本
- `ls vlm/data/.../generated_3d_no_rules/监修vlm数据/` — 按品类查看 multiview 图片

---

## Open Questions

- [ ] 其他 5 个品类的视角语义怎么写？每个品类的 front/side/back 含义需要分别定义
- [ ] Qwen "全部判 correct" 是过宽松还是商品确实没问题？需要更多样本或人工标注验证
- [ ] Qwen 顶层 schema 偏差用什么方式修（few-shot vs 后处理 vs 不管）？
- [ ] `headwear_ribbon` 在背包背面是否真的可见？

---

## Session Notes

- 本会话从上一个 handoff 的 "Immediate Next Steps" 开始，3 个步骤全部完成
- Qwen API 调用稳定：两次调用分别 94s 和 74s，无超时或错误
- Working tree 累积了大量未提交变更（从项目开始到现在共 4 次 commit，但大量新文件未 track），强烈建议尽快提交
- 用户确认当前阶段是"前置任务"——人工标注真值还没拿到，我们在做 Qwen baseline 侧的准备工作
- 下一步用户希望合并"扩大测试"和"其他品类视角语义"——先写规则再全品类一起跑

---

_This handoff was generated at 2026-07-06 15:10 +08:00. Start a new session and use this document as your initial context._
