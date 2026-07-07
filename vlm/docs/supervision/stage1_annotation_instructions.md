# Stage 1 人工视觉监修标注说明

**版本**: v1.0 | **日期**: 2026-07-07

---

## 任务概述

你的工作是对比 **2D 原图**（角色设计图）和 **3D 多视角生成图**（商品渲染图），找出两者之间的视觉差异。

**重要**：第一轮请完全基于你自己的视觉观察。不要参考 atomic_rules.json 或其他自动化产出作为标准答案。你的发现是独立的、有价值的。

---

## 工作流程

```text
2D 原图（角色设计参考）  ←对比→  多视角生成图（商品渲染结果）
         ↓                            ↓
         └────── 找出差异 ──────┘
                    ↓
         填写 human_visual_findings.csv
```

---

## 你拿到什么

每个样本文件夹包含：

| 文件 | 说明 |
|------|------|
| `2d_original.jpg` | 2D 角色设计原图（你的参考标准） |
| `multiview_design.png` | 3D 多视角生成图（你要检查的对象） |
| `atomic_rules.json` | ⚠️ **暂不参考** — 等 Stage 2 再看 |

---

## 你要做什么

### 第一步：整体观察

1. 打开 2D 原图，观察角色的整体外观：头发、眼睛、服装、配饰等
2. 打开多视角生成图，通常包含正面（front）、侧面（side）、背面（back）三个视角
3. 逐一检查每个视角中的元素是否与 2D 原图一致

### 第二步：记录发现

每发现一个差异或问题，在 `human_visual_findings.csv` 中新增一行。

**找什么？**

- **颜色错误**：头发颜色不对、眼睛颜色不对、服装颜色不对
- **形状错误**：发型形状不对、服装款式不对
- **缺失元素**：2D 图中有的元素在生成图中缺失（比如蝴蝶结不见了）
- **多余元素**：生成图中出现了 2D 图中没有的元素
- **可见性问题**：应该在某个视角可见的元素不可见，或反过来

### 第三步：填写 CSV

---

## CSV 字段说明

### 必填字段（每个发现都要填）

| 字段 | 说明 | 示例 |
|------|------|------|
| `sample_id` | 样本编号（文件夹名） | `2812503` |
| `category` | 商品品类 | `backpack` |
| `finding_id` | 你给这个发现编的 ID，同一个样本内不重复 | `F001` |
| `view` | 受影响的视角 | `front` / `side` / `back` / `multiple` / `all` |
| `issue_type` | 问题类型 | `wrong color` / `wrong shape` / `missing` / `extra` / `wrong invisible` / `other` |

### 推荐填写（帮助后续分析）

| 字段 | 说明 | 示例 |
|------|------|------|
| `element_name` | 出问题的元素名称 | `hair_color` / `headwear_ribbon` |
| `attribute` | 出问题的属性 | `color` / `shape` / `existence` |
| `feature_key` | 你对这个发现起的特征名 | `hair color mismatch` |
| `expected_from_2d` | 2D 图中看到的是什么 | `brown hair` |
| `observed_in_multiview` | 生成图中看到的是什么 | `dark brown / almost black hair` |
| `severity` | 严重程度 | `critical` / `major` / `minor` |
| `reason` | 你的解释 | `side view hair color significantly darker than 2D reference` |

### 可选字段

| 字段 | 说明 |
|------|------|
| `human_rule_name` | 你自己定义的规则描述 |
| `bbox_2d` | 2D 图上问题区域的坐标框 |
| `bbox_multiview` | 生成图上问题区域的坐标框 |
| `visible` | 元素是否可见：`visible` / `invisible` / `unknown` |
| `status` | v3 状态值（如 `correct`、`wrong color` 等） |
| `match_status` | `correct` / `wrong` / `unsure` |
| `expected_value` | 期望值 |
| `observed_value` | 观察到的值 |
| `source_2d_evidence` | 2D 图中的证据说明 |
| `multiview_evidence` | 生成图中的证据说明 |
| `annotator_id` | 你的工号 |
| `annotation_batch` | 批次号/日期 |

---

## 填写示例

以下是一个 backpack 品类的示例：

### 示例 1：头发颜色错误

```text
sample_id:           2812503
category:            backpack
finding_id:          F001
view:                front
issue_type:          wrong color
element_name:        hair_color
attribute:           color
feature_key:         front hair color
expected_from_2d:    brown
observed_in_multiview: dark brown
severity:            major
reason:              front view hair appears darker than the 2D reference brown
```

### 示例 2：蝴蝶结缺失

```text
sample_id:           2812503
category:            backpack
finding_id:          F002
view:                side
issue_type:          missing
element_name:        headwear_ribbon
attribute:           existence
feature_key:         beret ribbon missing on side
expected_from_2d:    ribbon present on beret
observed_in_multiview: no ribbon visible on side view
severity:            critical
reason:              the beret should have a visible ribbon on the side view
```

### 示例 3：背包背面图案正确

```text
sample_id:           2812503
category:            backpack
finding_id:          F003
view:                back
issue_type:          other
element_name:        back_pattern
attribute:           pattern
feature_key:         back panel pattern
expected_from_2d:    white zigzag pattern
observed_in_multiview: white zigzag pattern
severity:            minor
match_status:        correct
reason:              back panel pattern matches 2D reference
```

> **注意**：不需要记录"一切正常"的发现。只记录你注意到的差异和问题。但如果某个元素你不确定，可以记录并标注 `match_status=unsure`。

---

## 品类特殊说明

### backpack（背包）

- ⚠️ **背面视角（back）是背包的背板，不是角色的背面**
- 背包产品只看背包本身，不看角色的下半身（裙子、裤子、鞋子等）
- 角色头发、帽子等如果在背包正面/侧面可见，需要检查
- 背包背板上的图案、拉链、口袋需要检查

### head_key_chain（头部钥匙扣）

- ⚠️ **背面视角是角色的后脑勺**
- 只看头部和头发相关元素，颈部以下全部不检查
- 发饰、蝴蝶结、耳朵装饰等需要检查

### cake_roll（蛋糕卷）

- ⚠️ **背面视角是蛋糕卷的螺旋纹面，不是角色背面**
- 角色身体/服装全部不适用
- 只检查蛋糕卷上印制的角色图案

### plush（毛绒玩偶）

- ⚠️ **背面视角是角色的全身背面**
- 这是全身产品，所有元素都需要检查
- 正面、侧面、背面的所有特征都要对比

---

## 提交格式

- 文件编码：UTF-8（Excel 打开后另存为 CSV UTF-8 即可）
- 文件名：`human_visual_findings.csv`
- 每个样本一个 CSV 文件，放在对应样本文件夹中

**也可以把所有样本的发现合并到一个 CSV 中**，通过 `sample_id` 区分。

---

## 常见问题

### Q: 我不确定这是不是问题，要不要记？
A: 记。标注 `match_status=unsure`，`severity=minor`。

### Q: 2D 图中某个元素在生成图的某个视角看不到，这算问题吗？
A: 不一定。如果那个视角本来就不应该看到（比如正面看不到后脑勺），那不算问题。如果应该看到但看不到（比如正面的蝴蝶结消失了），那算 `missing`。

### Q: 颜色有一点点偏差算问题吗？
A: 如果是明显的色差（比如棕色变成黑色），算。如果只是轻微色差（光线造成的），可以记为 `minor`。

### Q: 生成图比 2D 图多了细节（比如纹理），这算问题吗？
A: 如果多出的细节不矛盾，一般不算问题。但如果多出了 2D 中完全不存在的元素（比如多了一个口袋），记为 `extra`。

---

## 时间估算

每个样本预计需要 3-5 分钟。4 品类 × 4 样本 = 16 个样本，预计总时间 1-2 小时。
