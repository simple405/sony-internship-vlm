# VLM Element Extraction Experiment Report v2

**Prompt**: v2_optimized
**Algorithm**: hungarian (threshold=0.5)
**Name/Desc Weight**: 0.3/0.7
**Model**: qwen36-vl:latest
**Embedding**: bge-m3:latest
**Date**: 2026-07-23 18:19:15
**Samples**: 1
**Total Time**: 37.9s

## Aggregate Metrics

| Metric | Value |
|--------|-------|
| Avg Combined Similarity (name+desc) | 0.7144 ± 0.0 |
| **Avg Description Similarity** | **0.7263** |
| Min / Max Similarity | 0.7144 / 0.7144 |
| Avg Coverage (GT recall) | 0.8333 |
| Avg Precision | 1.0 |
| Overall Coverage | 0.8333 |
| Overall Precision | 1.0 |
| Total GT / Pred / Matched | 6 / 5 / 5 |
| Good / Weak Matches | 3 / 2 |
| Good Match Ratio | 0.6 |
| Unmatched Pred / GT | 0 / 1 |

## Per-Sample Summary

| Sample | GT | Pred | Matched | Good | Weak | Combined | Desc Sim | Cov | Prec | Time(s) |
|--------|-----|------|---------|------|------|----------|----------|-----|------|---------|
| char_014 | 6 | 5 | 5 | 3 | 2 | 0.7144 | 0.7263 | 0.8333 | 1.0 | 37.9 |

## Per-Sample Details

### char_014

- GT: 6, Pred: 5, Matched: 5, Combined Sim: 0.7144, **Desc Sim: 0.7263**
- Coverage: 0.8333, Precision: 1.0

| # | Quality | Pred Name | GT Name | Similarity |
|---|---------|-----------|---------|------------|
| 1 | ✅ | 银白色短发与黑色眼罩 | 白色短发 | 0.7368 |
| 2 | ⚠️ | 深灰色立领外套与红色滚边 | 黑红配色服装 | 0.6474 |
| 3 | ⚠️ | 浅灰色纽扣马甲 | 黑色眼罩 | 0.5643 |
| 4 | ✅ | 黑色重型双枪 | 双枪武器 | 0.818 |
| 5 | ✅ | 银色机械义肢手套 | 机械义肢 | 0.8057 |

**Missed GT:**
- **红色右眼**: 右眼为醒目的红色，瞳孔细节清晰，眼神锐利，是角色的重要特征。

---
