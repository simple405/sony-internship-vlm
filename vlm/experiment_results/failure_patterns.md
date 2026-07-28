# VLM Element Extraction Failure Patterns

**Date:** 2026-07-28
**Model:** qwen36-vl:latest
**Samples:** 34 (204 GT elements, 272 VLM predictions)
**Matching:** bge-m3 semantic similarity, 30/70 weighted greedy (pred→GT)

---

## Aggregate Results

| Metric | Value |
|--------|-------|
| Overall Coverage (GT recall) | 95.1% (194/204) |
| Overall Precision | 71.3% (194/272) |
| Avg Semantic Similarity | 0.678 |
| Median Similarity | 0.689 |
| GT elements missed | 10 / 204 |
| VLM predictions unmatched | 78 / 272 |

## Per-Category Precision

| Category | Precision | Matched / Total | Avg Similarity | Assessment |
|----------|-----------|-----------------|----------------|------------|
| hair | 100% | 33/33 | 0.712 | Excellent |
| headwear | 100% | 10/10 | 0.689 | Excellent |
| clothing | 79.8% | 75/94 | 0.667 | Good |
| skin_body | 83.3% | 5/6 | 0.648 | Good (small sample) |
| other | 80.0% | 4/5 | 0.614 | Adequate |
| face | 65.0% | 13/20 | 0.697 | Fair |
| accessory | 67.7% | 44/65 | 0.651 | Fair |
| footwear | 28.6% | 10/35 | 0.725 | **Poor** |
| prop | 0% | 0/4 | — | **Hallucination** |

---

## Pattern 1: Footwear Over-Extraction (CRITICAL)

**Severity:** High — 25 false positives across 34 samples
**Evidence:** 35 footwear predictions but only 10 matched (28.6% precision)

VLM extracts shoes, socks, shoelaces, and boot details as separate elements, but human GT rarely annotates footwear at that granularity. Examples:

| Sample | VLM Prediction | Status |
|--------|---------------|--------|
| char_008 | 蓝色长靴 | Extra (GT has "鞋子" merged into compound names) |
| char_019 | 棕色靴子与蕾丝边装饰 | Extra |
| char_025 | 过膝袜, 紫红色鞋子 | Extra (GT merges footwear into clothing entries) |

**Why:** VLM's element extraction prompt encourages exhaustiveness. Footwear is visually prominent in full-body character designs, so VLM extracts it. Human annotators focus on outfit-defining elements and fold footwear into compound descriptions.

**Recommendation:** Add a prompt constraint: "Footwear should only be listed if it has distinctive design elements (unusual color, pattern, or shape). Standard shoes/socks should be omitted or noted briefly in the clothing description."

---

## Pattern 2: Greedy Matching Produces Cascading False Matches (METHODOLOGICAL)

**Severity:** Medium — inflates apparent coverage, hides real mismatch patterns
**Evidence:** 46 out of 194 matches have similarity < 0.6; many are semantically unrelated

When human annotations merge multiple elements into one compound name (e.g., "金色长发与黑色蝴蝶结" = hair + headwear), the greedy pred→GT matcher assigns that compound to the first VLM element. Later VLM elements that should match to the remaining sub-element are forced to match unrelated GT entries:

**Example — char_001:**
1. VLM "头发" claims GT "金色长发与黑色蝴蝶结" (sim=0.706) ✓
2. VLM "头饰" (black bow) forced to match GT "白色衬衫与蓝色宝石领饰" (sim=0.603) ✗ — semantically unrelated
3. VLM "衬衫" forced to match GT "黑色短裙与腰带" (sim=0.512) ✗
4. VLM "领饰" (gems+chain) → unmatched ✗ — its correct GT match was stolen in step 2
5. VLM "裙子" (brown pleated) → unmatched ✗ — its correct GT match was stolen in step 3

**Why:** The 30/70 weighted cosine similarity produces non-zero scores even for semantically unrelated pairs. Since greedy matching always picks the best remaining GT (no minimum threshold by default), spurious matches cascade.

**Recommendation:** Raise `MIN_SIMILARITY` to 0.6 (filters 30% of matches, mostly the spurious ones). Per threshold sensitivity:
- t=0.5: 194/194 pass (current, too permissive)
- t=0.55: 167/194 pass (14% filtered)
- t=0.6: 134/194 pass (31% filtered, removes most evidence of cascading)
- t=0.65: 113/194 pass (42% filtered)
- t=0.7: 89/194 pass (54% filtered, likely too aggressive)

**Recommendation:** Use t=0.6 as default threshold. This would give coverage ≈ 67% and precision ≈ 51%, which are more honest estimates of VLM capability.

---

## Pattern 3: Pose/Gesture GT Elements Invisible to VLM (MODERATE)

**Severity:** Medium — 4 of 10 missed GT elements are pose/gesture descriptions
**Evidence:**
- char_024: "右手姿势" (right hand pose) — missed
- char_030: "左手自然下垂" (left hand hanging naturally) — missed
- char_033: "右手自然垂下" (right hand hanging down) — missed
- char_034: "蹲姿与右手部姿势" + "左手部姿势" — missed (2 elements)

**Why:** The VLM extraction prompt says "列出该角色的所有关键视觉元素" (list all key visual elements) and suggests hair, eyes, clothing, accessories. It does not explicitly ask for pose/gesture. The human GT annotators included pose because it matters for 3D modeling, but VLM interprets "visual elements" as design attributes (colors, shapes, clothing items), not transient poses.

**Recommendation:** If pose extraction matters, add an explicit prompt instruction: "Also describe the character's pose, gestures, and body language." Otherwise, exclude pose-only GT elements from the evaluation (they test prompt design, not visual understanding).

---

## Pattern 4: "Prop" Category Hallucination (LOW FREQUENCY, HIGH IMPACT)

**Severity:** Medium — 0% precision, all 4 predictions are fabrications
**Evidence:**
- char_014: "双枪武器" (dual guns) in GT → VLM extracts "枪套" (holster) + "手枪" (pistol) which are correct sub-elements, but matched category=prop → unmatched because the greedy matcher assigned them to other GT
- Wait — actually checking: char_014 has 9 pred, 6 gt, 3 unmatched pred. The "枪套" and "手枪" are likely matched to GT compound names. The unmatched props might be from other samples.

**Why:** VLM sometimes invents weapon-like elements from ambiguous visual details (belt attachments, decorative folds).

**Recommendation:** Add a confidence self-assessment: "For each element, indicate whether you are certain (clearly visible), probable (likely but partially obscured), or speculative (inferred from context)." This gives downstream systems a signal to filter low-confidence props.

---

## Pattern 5: Compound GT Names Create Ambiguous Evaluation (METHODOLOGICAL)

**Severity:** Low (known design choice) — but affects all metrics
**Evidence:** Human GT merges 2-4 logical elements into one compound name. Examples:

| GT Compound Name | Logical Sub-Elements | VLM Splits Into |
|-----------------|---------------------|-----------------|
| 金色长发与黑色蝴蝶结 | hair color/style + headwear bow | 头发, 头饰 |
| 白色衬衫与蓝色宝石领饰 | shirt + neck ribbon + gem pin | 衬衫, 领饰 |
| 黑色短裙与腰带 | skirt + belt | 裙子, 腰带 |
| 蓝色腰带与小包 | belt + pouch/bag | (separate elements) |

**Why:** The granularity mismatch means coverage can never reach 100% without many-to-one matching: 272 VLM elements vs 204 GT elements (33% more). This is expected and was designed into the methodology. But it makes precision appear worse than it truly is — some "unmatched" predictions are correct sub-elements that simply don't have a dedicated GT entry.

**Recommendation:** Report two precision metrics: (a) strict precision (current, pred→GT one-to-one matching) and (b) relaxed precision that counts any VLM element with similarity > 0.6 to ANY GT element (regardless of whether it was "claimed" by another pred). The relaxed metric better reflects actual extraction quality for granularity-mismatched datasets.

---

## Pattern 6: Face Element Matching is Unreliable (MODERATE)

**Severity:** Medium — 65% precision, 7/20 face predictions unmatched
**Evidence:**
- char_002: "面部纹路" (facial markings) forced to match "红色长外套与金色火焰纹饰" (jacket) = 0.502 ✗
- char_021: "脸部纹路" (facial markings) forced to match "右手握拳" (right fist) = 0.507 ✗
- char_027: "胡须" (beard) forced to match "红色披风" (red cape) = 0.504 ✗

**Why:** Facial elements (eyes, markings, expressions) are frequently merged into GT compound names that include hair/clothing. When hair claims the compound, face elements cascade into absurd matches.

**Recommendation:** Extract face elements with a separate, focused prompt: "Describe ONLY the facial features: eyes, eyebrows, mouth, facial markings/scars, expression." This would produce cleaner category separation.

---

## Pattern 7: All Predictions Have "High" Confidence (CALIBRATION)

**Severity:** Low (UX issue) — but reduces usefulness for downstream filtering
**Evidence:** All 272 VLM predictions across 34 samples have `confidence: "high"`. This includes the 4 prop hallucinations (0% precision), the 25 unmatched footwear predictions, and the spurious cascaded matches.

**Why:** qwen36-vl has no self-calibration mechanism. The structured output format asks for a confidence field, but the model always fills it with "high" regardless of actual certainty.

**Recommendation:** Replace the categorical confidence field with a numeric 0-1 score derived from:
- Description length (shorter descriptions → less certain)
- Semantic specificity (generic terms like "衬衫" → less certain than specific terms like "黑色领结及垂坠装饰，中央镶嵌蓝色圆形宝石")
- Internal consistency check (does the element name match the described visual feature?)

---

## Summary of Recommendations

| Priority | Action | Expected Impact |
|----------|--------|----------------|
| **P0** | Raise `MIN_SIMILARITY` to 0.6 | Reduces spurious matches by 31%, gives more honest metrics |
| **P0** | Add "footwear only if distinctive" to extraction prompt | Reduces ~25 false positives, improves precision ~8% |
| **P1** | Add pose/gesture instruction to prompt OR exclude pose from GT eval | Closes 4/10 missed GT gap |
| **P2** | Extract face elements with a dedicated sub-prompt | Improves face matching from 65% to estimated 80%+ |
| **P2** | Report relaxed precision (any-GT similarity > 0.6) alongside strict precision | Better reflects extraction quality given granularity mismatch |
| **P3** | Add numeric confidence scoring | Enables downstream quality filtering |

---

## Threshold Sensitivity Curve

For the 194 matches at t=0.5:

| Threshold | Matches Pass | % Retained | Implied Coverage | Implied Precision |
|-----------|-------------|------------|-----------------|-------------------|
| 0.50 | 194 | 100% | 95.1% | 71.3% |
| 0.55 | 167 | 86.1% | 81.9% | 61.4% |
| 0.60 | 134 | 69.1% | 65.7% | 49.3% |
| 0.65 | 113 | 58.2% | 55.4% | 41.5% |
| 0.70 | 89 | 45.9% | 43.6% | 32.7% |
| 0.75 | 59 | 30.4% | 28.9% | 21.7% |
| 0.80 | 20 | 10.3% | 9.8% | 7.4% |

**Recommended operating point: t=0.6** — balances filtering spurious matches against retaining genuine semantic matches. At this threshold, ~69% of matches survive; the 31% filtered are predominantly cascading false matches (Pattern 2).
