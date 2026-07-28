# Handoff: VLM Evaluation — Compound GT Matching + Server Re-run

**Created:** 2026-07-28 17:05 CST  
**Branch:** main  
**Last Commit:** `be364c6` — eval: compound-aware GT matching + prompt P0 fixes

---

## 概要

完成了本机的全部编辑工作：修复了 element extraction prompt（6项P0问题）、重写了评估脚本（compound-aware GT matching + relaxed precision），并修正了5个数据集JSON格式问题。所有改动已 push 到 `origin/main`。下一步在服务器上 `git pull` 并重跑实验。

---

## Work Completed

### Changes Made

- [x] Prompt P0修复：内搭提取规则（完全遮挡不提取）
- [x] Prompt P0修复：精度规则末尾加"如有疑问，省略该元素"
- [x] Prompt P0修复：新增姿势/手势提取规则（标志性姿势才提取）
- [x] Prompt P0修复：鞋靴/袜类约束（仅设计特征明显时提取）
- [x] Prompt P0修复：手持道具/武器约束（标志性才提取）
- [x] Prompt P0修复：末尾自查 checklist（输出JSON前逐项核对）
- [x] 评估脚本重写：compound GT splitting (`与/及/和` 分割)
- [x] 评估脚本重写：many-to-one matching（多个pred覆盖同一GT）
- [x] 评估脚本重写：relaxed precision（贡献部分分的落选pred）
- [x] 评估脚本重写：MIN_SIMILARITY=0.6（过滤~31%级联假匹配）
- [x] 数据集修复：char_041 删除重复 `source_id` 字段
- [x] 数据集修复：char_057/058/059/062 `source_image` 后缀 `.json` → `.png`
- [x] 数据集修复：char_024 merge conflict 解决（采用 remote 版本）

### Key Decisions

| Decision | Rationale | Alternatives Considered |
|---|---|---|
| compound GT splitting（语义分割复合元素名） | "金色长发与黑色蝴蝶结"一条GT对应两个视觉元素，直接匹配导致cascading false matches | 不分割直接匹配 |
| MIN_SIMILARITY=0.6 | 实验发现 0.5 时有~31%的假匹配；0.7 会漏掉合法近义词 | 0.5（过松），0.7（过严） |
| relaxed precision | 贪心匹配会让"good but losing"的pred计入假阳性，inflating FP | 纯greedy precision |
| sim(parts)<0.75 才分割 | 防止"金色头发"这类颜色+名词被错误分割 | 固定分割所有带连词的元素 |

---

## Files Affected

### Modified

- `vlm/prompts/supervision/element_extraction_from_2d.txt` — 6项P0修复（见 commit be364c6 diff）
  - 第10行：内搭遮挡规则
  - 第13行：精度规则末尾加省略建议
  - 第27行：姿势/手势新规则
  - 第33-34行：鞋靴/道具严格约束
  - 第48-49行：输出前自查checklist

- `vlm/scripts/supervise/evaluate_extraction_compound.py`（原 `vlm/experiment_vlm_analysis.py`，已移入标准包位置）— 完整重写（compound-aware matching）
  - 新函数：`split_compound_name()`, `expand_gt_for_matching()`
  - `match_elements()` 返回4-tuple，包含 `coverage_info`
  - 结果字段新增：`relaxed_precision`, `coverage_info`, `virtual_matches`
  - 配置：`MIN_SIMILARITY=0.6`, `RELAXED_PRECISION_THRESHOLD=0.6`

- `vlm/data/SN_6_3D_dataset/char_041/char_041.json` — 删除 `source_id` 字段
- `vlm/data/SN_6_3D_dataset/char_025/char_025.json` — 细节修正（与024一起处理）
- `vlm/data/SN_6_3D_dataset/char_057~062/*.json` — source_image 后缀修正

---

## Technical Context

### Compound GT Matching 逻辑

```python
# 1. expand_gt_for_matching: "A与B" → virtual candidates [A, B]
# 2. greedy match: pred → nearest candidate (sim >= 0.6)
# 3. coverage_scores[gt_idx] = matched_sub_parts / total_sub_parts (fractional)
# 4. relaxed_precision: unmatched preds with any GT sim >= 0.6 get partial credit
```

### 评估指标含义

- `coverage`：GT覆盖率（含复合元素的部分覆盖得分）
- `precision`：贪心匹配精准率
- `relaxed_precision`：放宽精准率（贡献部分分给"good but losing"的pred）
- `virtual_matches`：通过子元素匹配命中的GT数量（compound splitting效果指标）

### Dataset Schema（标准格式）

```json
{
  "sample_id": "char_NNN",
  "source_image": "char_NNN.png",
  "elements": ["...", "..."]
}
```

---

## Things to Know

### Gotchas & Pitfalls

- `vlm/data/` 在 `.gitignore` 中，数据文件需要 `git add -f` 才能追踪
- 服务器上 `NO_PROXY="*"` 环境变量必须加，否则Ollama请求会走代理失败
- `char_035~054` 的元素提取结果是旧prompt生成的（未含P0修复），**需要重跑**
- `char_001~034` 的提取结果也是旧prompt，但优先级较低（可后续处理）

### Known Issues

- `stash@{1}` 仍存在（char_025/041旧修改，已被新commit覆盖，可安全删除）：
  ```bash
  git stash drop stash@{1}
  ```
- `stash@{0}` 也可清理（char_024旧修改，已解决）：
  ```bash
  git stash drop stash@{0}
  ```
- 本机 git status 显示大量 `D` (deleted) 文件——这些是本地清理的临时实验文件，**不需要 commit 这些删除**

---

## Current State

### What's Working

- 本机代码编辑完成，commit `be364c6` 已 push 到 GitHub
- 评估脚本逻辑完整（未在服务器运行验证）
- Prompt 修复完整（未用新prompt重跑提取验证）

### What's Not Working / Not Yet Done

- 服务器尚未 `git pull`
- char_035~054 的元素提取结果是旧prompt生成的（需重跑）
- 新评估脚本尚未在54样本上运行（compound matching效果未知）
- char_036/039 的 avg similarity 0.63 vs 整体0.71 的root cause未分析

---

## Next Steps

### Immediate（从这里开始）

1. **本机清理 stash**（可选，不影响服务器工作）：
   ```bash
   cd d:/索尼实习
   git stash drop stash@{0}
   git stash drop stash@{0}  # 删掉原stash@{1}，现在变成{0}了
   ```

2. **服务器：pull 最新代码**
   ```bash
   cd /home/intern/jsy
   git pull origin main
   # 验证
   tail -10 vlm/prompts/supervision/element_extraction_from_2d.txt  # 应该看到checklist
   head -5 vlm/scripts/supervise/evaluate_extraction_compound.py  # 应该看到compound matching docstring
   ```

3. **服务器：重跑 char_035~054 元素提取**（新prompt，约160分钟）
   ```bash
   NO_PROXY="*" /usr/bin/python3 -m vlm.scripts.supervise.run_element_extraction \
     --data-root vlm/data/SN_6_3D_dataset \
     --char-range 035-054 \
     --output-root vlm/tmp/supervision_agent_output
   # （先确认 CLI flags 与实际脚本一致）
   ```

4. **服务器：重跑54样本评估**
   ```bash
   PYTHONUNBUFFERED=1 python3 -m vlm.scripts.supervise.evaluate_extraction_compound
   ```

5. **对比指标**：主要关注
   - `footwear_precision`：旧版 28.6%，新prompt应该 >60%
   - `virtual_matches`：compound splitting命中数（新指标，期望>0）
   - `relaxed_precision` vs `precision`：差值越大说明有越多"good but losing"的pred

### Subsequent

- 分析 char_036/039 raw_response，定位 avg similarity 0.63 的root cause
- 考虑将 pose/gesture 元素从 visual elements GT 中分离，单独评估（P1）
- 如果提取结果改善显著，考虑将 char_001~034 也用新prompt重跑（P2）

---

## Related Resources

### Key Files

- `vlm/prompts/supervision/element_extraction_from_2d.txt` — 提取prompt
- `vlm/scripts/supervise/evaluate_extraction_compound.py` — 评估脚本（compound-aware matching）
- `vlm/data/SN_6_3D_dataset/` — 64样本JSON dataset
- `vlm/docs/workflows/process.md` — 项目流程文档

### Commands

```bash
# 查看评估脚本配置
grep -n "MIN_SIMILARITY\|RELAXED" vlm/scripts/supervise/evaluate_extraction_compound.py

# 查看prompt末尾checklist
tail -15 vlm/prompts/supervision/element_extraction_from_2d.txt

# 查看元素提取CLI用法
/usr/bin/python3 -m vlm.scripts.supervise.run_element_extraction --help
```

---

## Open Questions

- [ ] `run_element_extraction` 的 `--char-range` flag 格式是否为 `035-054`？需确认服务器上实际参数
- [ ] 服务器上 `vlm/data/SN_6_3D_dataset` 是否已经有 char_055~064 的数据？（本机有64个sample，服务器可能只有54个）
- [ ] compound splitting 的 0.75 相似度阈值是否合适？（需在运行后通过 `virtual_matches` 指标评估）

---

_Handoff generated 2026-07-28. Start new session with this document as initial context._
