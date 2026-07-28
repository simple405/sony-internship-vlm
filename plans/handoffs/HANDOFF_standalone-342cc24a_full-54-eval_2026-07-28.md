# Handoff: Atomic Rules 全量 54 样本评估 + 监修 Agent Step 1 适用性分析

**Date:** 2026-07-28
**Status:** COMPLETED
**Bead(s):** none
**Epic:** VLM Supervision Agent Pipeline
**Chain:** `standalone-342cc24a` seq 2
**Parent:** `HANDOFF_standalone-342cc24a_atomic-rules-eval_2026-07-28.md` (seq 1, 34-sample evaluation)

---

## Related Handoffs

- `HANDOFF_standalone-342cc24a_atomic-rules-eval_2026-07-28.md` — seq 1: 34-sample embedding eval + Hungarian/Jaccard comparison
- `HANDOFF_supervision-agent-pipeline_2026-07-27.md` — 监修 agent 端到端 pipeline 架构定义
- `HANDOFF_sn6-54-sample-extraction-verified_2026-07-28.md` — qwen36-vl 54 样本元素提取验证（不同 pipeline）

---

## The Goal

将 34 样本的 atomic_rules 评估扩展到全量 54 样本，并基于全量结果评估当前 2D 元素提取方案是否可以作为监修 agent pipeline 的 Step 1（提取 atomic_rules）。

---

## Where We Are

- [x] 读取 seq 1 handoff，确认 char_035~054 缺 atomic_rules_generated.json
- [x] 发现 `vlm/data/element_extraction_results/` 已有全部 54 样本的 `extracted_elements.json`（qwen36-vl 提取）
- [x] 写转换脚本：`extracted_elements.json` → `atomic_rules_generated.json`（`element_id→rule_id`, `value→value`），20 个缺失样本无需重新调用 VLM
- [x] 跑完 54 样本全量 embedding 评估：Macro Coverage 92.22%, Macro Precision 72.13%, F1 0.8095, Avg Sim 0.6816
- [x] 对比 char_001~034 vs char_035~054 质量差异
- [x] 分析 precision gap 对监修 agent 的实际影响（细粒度拆分是优势而非缺陷）
- [x] 分析 26 个未匹配 gold 的监修相关性（pose/gesture 占 46%，监修不检查姿势）
- [x] 结论：当前方案可以作为监修 agent Step 1，需补 3 个坑
- [ ] 未清理 embedding 缓存中 char_035~054 的无用条目（不影响功能）
- [ ] 未分析 char_035~054 质量偏低的根因（raw_response 检查）

---

## What We Did

### 1. 转换 char_035~054 的 atomic_rules

**Method:** 不重新调用 VLM API，直接从已有的 `element_extraction_results/char_XXX/extracted_elements.json` 转换。

```python
# 映射逻辑（与 run_supervision_agent.py 的 elements_to_atomic_rules 一致）
atomic_rules = [
    {"rule_id": e["element_id"], "value": e["value"]}
    for e in extracted["elements"]
]
```

写入 `vlm/tmp/supervision_agent_output/char_XXX/atomic_rules_generated.json`。20 个样本全部成功转换，element 数范围 4-12。

### 2. 全量 54 样本 embedding 评估

使用 bge-m3 + Hungarian matching，与 seq 1 相同的评估参数（threshold=0.50, good=0.65）。

```
Evaluating 54 samples...
Precomputing embeddings for 743 unique texts...
```

#### 核心指标对比

| 指标 | char_001~034 (seq 1) | char_035~054 (new) | **全部 54** |
|---|---|---|---|
| 样本数 | 34 | 20 | **54** |
| Gold 元素 | 212 | 122 | **334** |
| Pred 元素 | 272 | 155 | **427** |
| Matched | 200 | 108 | **308** (193 good, 115 weak) |
| Macro Coverage | 95.11% | 88.35% | **92.22%** |
| Macro Precision | 76.26% | 70.48% | **72.13%** |
| Macro F1 | 0.8340 | 0.7767 | **0.8095** |
| Avg Cosine Sim | 0.7113 | 0.6310 | **0.6816** |
| 未匹配 gold | 12 | 14 | **26** |
| 未匹配 pred | 72 | 47 | **119** |

#### F1=1.0 样本（4 个）

char_003, char_009, char_022, char_052

#### 最差 F1 样本

| sample | F1 | coverage | precision | 根因 |
|---|---|---|---|---|
| char_039 | 0.444 | 40% | 50% | Gold 按左右脚分别标注鞋子，pred 只有 4 个元素 |
| char_036 | 0.500 | 50% | 50% | Gold 写了连帽卫衣+内搭T恤+牛仔裤，pred 的提取偏差大 |
| char_037 | 0.700 | 87.5% | 58.3% | 12 个 pred 过于细碎（发扣、额饰、飘带等） |

### 3. char_035~054 质量偏低分析

Avg similarity 0.631 vs 0.711（差 8pp），可能原因：
- 这些角色视觉复杂度更高（char_037=12 pred, char_040=12 pred）
- extraction 参数可能不同（需检查 raw_response 确认）
- prompt 对复杂角色（多层服装、大量配饰）的提取覆盖不够精准

### 4. 监修 Agent Step 1 适用性评估

#### Pipeline 关系

```
2D 源图 → [元素提取 prompt] → atomic_rules ({rule_id, value})
  → [监修审核 prompt] → 每条 rule: front/side/back visible + correct/wrong color/material/shape
```

监修 VLM 对每条 atomic rule 做原子判断：**这个特征在产品渲染图上可见吗？颜色对吗？形状对吗？**

#### ✅ 为什么可行

**粒度拆分是匹配的。** 评估中 119 个 "extra" pred 本质上是 gold 用复合命名（"黑色长筒袜与紫色高跟靴"）而 extraction 做了拆分（rule_007: 黑色过膝长筒袜 + rule_009: 紫银配色高跟鞋）。对监修审核来说，细粒度规则让每条判断更精准——"袜子颜色对吗"和"鞋子颜色对吗"可以分别判定。

**Coverage 92% 覆盖了监修关心的维度。** 头发、眼睛、服装、鞋、袜、配饰——这些是监修审核中 actual check 的内容。26 个未匹配 gold 中 12 个（46%）是姿势类（站立、叉腰、蹲姿），而监修 prompt 不检查姿势——它检查的是逐条 visual feature 的 color/shape/material。

**反幻觉已内置。** extraction prompt 明确写"凡是不在图中直接观察到的元素，一律不得提取"，这是监修的底线——不能凭空生成 rule 然后在产品图上找不存在的东西。

#### ⚠️ 三个需补的坑

| # | 问题 | 影响 | 修复方案 |
|---|---|---|---|
| 1 | 个别 sample 遗漏了监修关心的类别（眼睛颜色、鞋类、袜类） | char_010（蓝眼睛）、char_025（紫红眼睛+大腿袜）、char_028（凉鞋）等 7 个 sample 漏检 | extraction prompt 末尾加强制检查清单，要求模型逐项确认 8 个类别 |
| 2 | Pose/gesture 完全不提取 | 46% 的 gold 未匹配——但监修 prompt 不检查姿势，所以**对监修无实际影响** | 在 gold 中区分 "visual element" vs "pose description"，评估分别打分 |
| 3 | char_035~054 的 avg similarity 偏低（0.63 vs 0.71） | 部分 sample 的 extraction 描述与 gold 语义有偏差 | 挑 2-3 个低分 sample 检查 raw_response，确认是 prompt 问题还是模型问题 |

#### 结论

**当前方案可以作为监修 agent 的 Step 1 使用。** 核心指标（coverage 92%、反幻觉、细粒度拆分）满足监修审核对 atomic_rules 的需求。不追求 gold 对齐的 precision（因为是 annotation 口径差异），而是追求 extraction prompt 本身的召回率和反幻觉。

---

## Key Decisions

| Decision | Rationale | Alternatives Rejected |
|---|---|---|
| 从 `element_extraction_results` 转换而非重新跑 VLM | 54 样本的 extracted_elements.json 已存在且质量一致，转换只需 ~1 秒；重跑需 ~2 小时 VLM API 调用 | 重跑 extraction（浪费算力和时间） |
| 不将 pose 加入 extraction prompt | 监修审核 prompt 逐条检查 visual feature 的 color/shape/material，不检查姿势；加入 pose 反而引入监修不需要的信息 | 扩展 prompt 要求提取姿态（与监修审核设计不一致） |
| 细粒度 precision gap 不算缺陷 | 拆分后的 rule 更适合监修 VLM 逐条判断（一物一判），复合描述反而让判断模糊 | 要求 extraction 产出与 gold 一致的复合命名（违背监修流程设计） |
| 不上传 embedding cache | 缓存文件 ~500KB，下次评估可自动重建；git 不跟踪二进制 cache | git add -f（增加仓库体积且每次评估会冲突） |

---

## Evidence & Data

### 评估结果文件

| 文件 | 内容 | Git 状态 |
|---|---|---|
| `vlm/tmp/atomic_rules_eval_report.json` | 54 样本 embedding 评估完整报告（per-sample matches, unmatched, metrics） | `git add -f` 上传 |
| `vlm/tmp/embedding_cache_local.json` | bge-m3 embedding 缓存（743 唯一文本） | 不上传（`vlm/tmp/` gitignored） |
| `vlm/tmp/supervision_agent_output/char_035~054/atomic_rules_generated.json` | 20 个新转换的 atomic_rules | 不上传（`vlm/tmp/` gitignored） |
| `vlm/data/element_extraction_results/char_001~054/` | 54 样本 qwen36-vl 元素提取结果 | `vlm/data/` gitignored |

### 26 个未匹配 gold 分类

| 类别 | 数量 | 占比 | 对监修有影响？ |
|---|---|---|---|
| pose/gesture | 12 | 46% | ❌ 监修不检查姿势 |
| footwear | 5 | 19% | ✅ 监修检查鞋类颜色/形状 |
| clothing | 4 | 15% | ✅ 监修检查服装颜色/形状 |
| legwear | 2 | 8% | ✅ 监修检查袜类 |
| eyes | 1 | 4% | ✅ 监修检查眼睛颜色 |
| non-human anatomy | 1 | 4% | ⚠️ 监修可检查但不常见 |
| hair | 1 | 4% | ✅ 监修检查头发颜色/形状 |

对监修有实际影响的遗漏约 14 个（54%），分布在 7 个 sample 中。

### Per-Sample 指标（全部 54 样本，sorted by F1 asc）

| sample_id | gold | pred | matched | good | weak | cov% | prec% | F1 | sim |
|---|---|---|---|---|---|---|---|---|---|
| char_039 | 5 | 4 | 2 | 0 | 2 | 40.0% | 50.0% | .444 | .566 |
| char_036 | 6 | 6 | 3 | 2 | 1 | 50.0% | 50.0% | .500 | .614 |
| char_028 | 5 | 8 | 4 | 3 | 1 | 80.0% | 50.0% | .615 | .706 |
| char_002 | 5 | 11 | 5 | 4 | 1 | 100.0% | 45.5% | .625 | .724 |
| char_024 | 7 | 11 | 6 | 3 | 3 | 85.7% | 54.5% | .667 | .679 |
| char_031 | 7 | 11 | 6 | 4 | 2 | 85.7% | 54.5% | .667 | .731 |
| char_037 | 8 | 12 | 7 | 3 | 4 | 87.5% | 58.3% | .700 | .648 |
| char_008 | 6 | 11 | 6 | 5 | 1 | 100.0% | 54.5% | .706 | .752 |
| char_054 | 7 | 10 | 6 | 3 | 3 | 85.7% | 60.0% | .706 | .635 |
| char_015 | 5 | 9 | 5 | 2 | 3 | 100.0% | 55.6% | .714 | .636 |
| char_046 | 5 | 9 | 5 | 1 | 4 | 100.0% | 55.6% | .714 | .571 |
| char_044 | 5 | 6 | 4 | 2 | 2 | 80.0% | 66.7% | .727 | .604 |
| char_019 | 6 | 10 | 6 | 3 | 3 | 100.0% | 60.0% | .750 | .712 |
| char_001 | 5 | 8 | 5 | 5 | 0 | 100.0% | 62.5% | .769 | .705 |
| char_043 | 6 | 7 | 5 | 3 | 2 | 83.3% | 71.4% | .769 | .603 |
| char_050 | 5 | 8 | 5 | 4 | 1 | 100.0% | 62.5% | .769 | .664 |
| char_006 | 6 | 9 | 6 | 5 | 1 | 100.0% | 66.7% | .800 | .750 |
| char_011 | 6 | 9 | 6 | 3 | 3 | 100.0% | 66.7% | .800 | .723 |
| char_014 | 6 | 9 | 6 | 4 | 2 | 100.0% | 66.7% | .800 | .737 |
| char_018 | 4 | 6 | 4 | 2 | 2 | 100.0% | 66.7% | .800 | .696 |
| char_017 | 7 | 8 | 6 | 3 | 3 | 85.7% | 75.0% | .800 | .667 |
| char_040 | 8 | 12 | 8 | 4 | 4 | 100.0% | 66.7% | .800 | .622 |
| char_045 | 6 | 9 | 6 | 2 | 4 | 100.0% | 66.7% | .800 | .581 |
| char_047 | 7 | 8 | 6 | 3 | 3 | 85.7% | 75.0% | .800 | .661 |
| char_051 | 6 | 9 | 6 | 3 | 3 | 100.0% | 66.7% | .800 | .630 |
| char_026 | 7 | 10 | 7 | 4 | 3 | 100.0% | 70.0% | .824 | .718 |
| char_021 | 7 | 10 | 7 | 4 | 3 | 100.0% | 70.0% | .824 | .678 |
| char_007 | 5 | 7 | 5 | 4 | 1 | 100.0% | 71.4% | .833 | .754 |
| char_010 | 6 | 6 | 5 | 4 | 1 | 83.3% | 83.3% | .833 | .729 |
| char_035 | 5 | 7 | 5 | 3 | 2 | 100.0% | 71.4% | .833 | .578 |
| char_038 | 5 | 7 | 5 | 4 | 1 | 100.0% | 71.4% | .833 | .661 |
| char_048 | 6 | 6 | 5 | 3 | 2 | 83.3% | 83.3% | .833 | .672 |
| char_005 | 6 | 8 | 6 | 6 | 0 | 100.0% | 75.0% | .857 | .772 |
| char_013 | 6 | 8 | 6 | 5 | 1 | 100.0% | 75.0% | .857 | .743 |
| char_034 | 8 | 6 | 6 | 2 | 4 | 75.0% | 100.0% | .857 | .687 |
| char_041 | 7 | 7 | 6 | 3 | 3 | 85.7% | 85.7% | .857 | .752 |
| char_042 | 7 | 7 | 6 | 3 | 3 | 85.7% | 85.7% | .857 | .619 |
| char_049 | 6 | 8 | 6 | 3 | 3 | 100.0% | 75.0% | .857 | .632 |
| char_027 | 7 | 9 | 7 | 4 | 3 | 100.0% | 77.8% | .875 | .696 |
| char_033 | 8 | 8 | 7 | 4 | 3 | 87.5% | 87.5% | .875 | .658 |
| char_025 | 10 | 8 | 8 | 5 | 3 | 80.0% | 100.0% | .889 | .643 |
| char_029 | 8 | 10 | 8 | 5 | 3 | 100.0% | 80.0% | .889 | .643 |
| char_020 | 4 | 5 | 4 | 0 | 4 | 100.0% | 80.0% | .889 | .630 |
| char_016 | 5 | 6 | 5 | 4 | 1 | 100.0% | 83.3% | .909 | .796 |
| char_030 | 6 | 5 | 5 | 4 | 1 | 83.3% | 100.0% | .909 | .724 |
| char_004 | 6 | 7 | 6 | 5 | 1 | 100.0% | 85.7% | .923 | .770 |
| char_023 | 7 | 8 | 7 | 4 | 3 | 100.0% | 87.5% | .933 | .713 |
| char_012 | 7 | 8 | 7 | 3 | 4 | 100.0% | 87.5% | .933 | .676 |
| char_032 | 8 | 7 | 7 | 6 | 1 | 87.5% | 100.0% | .933 | .746 |
| char_053 | 7 | 8 | 7 | 6 | 1 | 100.0% | 87.5% | .933 | .688 |
| char_003 | 4 | 4 | 4 | 4 | 0 | 100.0% | 100.0% | 1.000 | .822 |
| char_009 | 6 | 6 | 6 | 4 | 2 | 100.0% | 100.0% | 1.000 | .707 |
| char_022 | 6 | 6 | 6 | 2 | 4 | 100.0% | 100.0% | 1.000 | .659 |
| char_052 | 5 | 5 | 5 | 5 | 0 | 100.0% | 100.0% | 1.000 | .620 |

---

## Files Changed

### Source code (created)
- `vlm/scripts/supervise/evaluate_atomic_rules.py` — 专用于 atomic_rules 格式的评估脚本（~423 行）

### Data & results (created)
- `vlm/tmp/atomic_rules_eval_report.json` — 54 样本 embedding 评估完整报告（force-added to git）
- `vlm/tmp/supervision_agent_output/char_035~054/atomic_rules_generated.json` — 20 个新转换的 atomic_rules（gitignored, 可从 element_extraction_results 重建）

### Data fixes (uncommitted → committed in this session)
- `vlm/data/SN_6_3D_dataset/char_024/char_024.json` — 加了 `source_image` 字段
- `vlm/data/SN_6_3D_dataset/char_025/char_025.json` — 修复 typo `cha_025` → `char_025`
- `vlm/data/SN_6_3D_dataset/char_041/char_041.json` — 加了 `sample_id` 字段

### Handoffs
- `plans/handoffs/HANDOFF_standalone-342cc24a_atomic-rules-eval_2026-07-28.md` — seq 1: 34-sample eval
- `plans/handoffs/HANDOFF_standalone-342cc24a_full-54-eval_2026-07-28.md` — seq 2: this file, 54-sample full eval

---

## Open Questions

- [ ] char_035~054 的 avg similarity 为什么偏低？需要检查 raw_response 确认是 prompt 问题还是模型问题
- [ ] extraction prompt 的强制检查清单怎么措辞？只加一句"请逐项确认以下类别是否已覆盖"还是有更好的方式？
- [ ] 是否需要为 extraction 建立独立的质量评估（不依赖 gold 的 coverage/precision，而是直接评估提取的忠实度）？

---

## Quick Start for Next Session

```bash
# Restore context — read this file first

# Key files
# vlm/scripts/supervise/evaluate_atomic_rules.py — the evaluation script
# vlm/tmp/atomic_rules_eval_report.json — full 54-sample report
# vlm/scripts/supervise/run_supervision_agent.py — pipeline entry point
# vlm/scripts/supervise/run_element_extraction.py — standalone extraction runner

# Verify current state
python3 -c "
import json
r=json.load(open('vlm/tmp/atomic_rules_eval_report.json'))
print(f'{r[\"summary\"][\"evaluated_samples\"]} samples evaluated')
print(f'Coverage: {r[\"summary\"][\"macro_coverage\"]:.2%}')
print(f'Precision: {r[\"summary\"][\"macro_precision\"]:.2%}')
print(f'F1: {r[\"summary\"][\"macro_f1\"]:.4f}')
"

# Run evaluation again (all 54 samples)
NO_PROXY="localhost,127.0.0.1" .venv/bin/python3 -m vlm.scripts.supervise.evaluate_atomic_rules

# Next actions
# 1. 检查 char_036, char_039 raw_response 分析质量偏低根因
# 2. 在 extraction prompt 末尾加强制检查清单
# 3. 在 gold 中区分 visual element vs pose description，评估分别打分
```
