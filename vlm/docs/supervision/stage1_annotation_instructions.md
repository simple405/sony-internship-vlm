# Stage 1 人工标注验收说明（压缩版）

版本：v1.2 | 日期：2026-07-08

本文件只约束乙方人工标注的验收、修改和计费范围，不代表生图或 atomic_rules 只能覆盖这些内容。生图和 atomic_rules 仍应保留角色身份、关键配饰、服装结构、商品形态等完整设计要求。

## 1. 当前执行标准

### 描述修改范围

- 仅允许对预识别阶段已标注出的部位、装饰物等进行修正。
- 修正维度只限于 **颜色、材质、形状** 三方面的明显错误。
- 不主动补充预识别阶段未标出的普通细节，不扩写描述，不追加与颜色/材质/形状无关的信息。

### 左右方位

- 所有“左”“右”判断，统一以标注员自身观察视角为准。
- Agent 输出左右方位时也必须使用观察者视角，不切换成角色自身左右。

### 成对物品或身体部位

- 一双鞋、两条腿、两只犄角等成对部位，如果原标注框只覆盖一侧，须补全另一侧标注框并添加对应描述。
- 两侧外观无差异时，描述内容可完全相同。
- 两侧外观存在差异时，需要分别描述。
- 如果预识别阶段把成对部位合并为一个大框，例如两条腿合为一框，须拆分为独立单框，并逐框独立描述。

### 计费范围

- 凡涉及描述修改或新增标注框的操作，均纳入修改计费范畴。
- Agent 报告中应区分 `description_correction` 与 `paired_box_completion`。

## 2. 工作流程

标注输入来自 `generated/` 下每个样本文件夹里的三件套：

```text
2D 原图 / source image
多视角生成图 / multiview product image
atomic_rules.json / 预识别规则
```

```text
2D 原图 + 3D 多视角生成图
  -> 检查预识别阶段已标注内容
  -> 只记录颜色/材质/形状明显错误
  -> 检查成对部位是否漏框或合框
  -> 填写 human_visual_findings.csv
```

## 3. 需要记录的问题类型

```text
wrong color:
  头发、眼睛、服装、装饰物等颜色明显不对。

wrong material:
  金属、布料、皮革、毛绒、透明件等材质明显不对。

wrong shape:
  发型轮廓、装饰物形状、部件外形明显不对。

paired box completion:
  成对物品或身体部位只框一侧，或两侧被合并成一个大框，需要补框或拆框。
```

当前不主动处理：

```text
- 预识别阶段没有标出的普通细节
- 开放式描述补充
- 与颜色/材质/形状无关的扩写
- 普通 missing/extra 细节，除非属于成对补框/拆框场景
```

## 4. CSV 最小字段

`human_visual_findings.csv` 至少包含：

```text
sample_id
category
finding_id
view                 # front / side / back / multiple / all / unknown
issue_type           # wrong color / wrong material / wrong shape / paired box completion / other
element_name
attribute            # color / material / shape / paired_box
expected_from_2d
observed_in_multiview
severity             # critical / major / minor / unknown
reason
```

可选字段仍可保留 bbox、annotator_id、annotation_batch、match_status 等，详见 `human_annotation_csv_schemas.md`。

## 5. 示例

### 颜色错误

```text
sample_id: 2812503
category: backpack
finding_id: F001
view: front
issue_type: wrong color
element_name: hair_color
attribute: color
expected_from_2d: brown
observed_in_multiview: dark brown / almost black
severity: major
reason: pre-recognized hair color is visibly darker than the 2D reference
```

### 材质错误

```text
sample_id: 2812503
category: backpack
finding_id: F002
view: front
issue_type: wrong material
element_name: shoulder_strap
attribute: material
expected_from_2d: fabric strap
observed_in_multiview: glossy metal-like strap
severity: major
reason: pre-recognized strap material is inconsistent with the 2D reference
```

### 成对部位补框

```text
sample_id: 2812503
category: plush
finding_id: F003
view: front
issue_type: paired box completion
element_name: left_horn_and_right_horn
attribute: paired_box
expected_from_2d: two horns should be labeled separately
observed_in_multiview: only one horn has a box
severity: major
reason: paired parts require both sides to be boxed and described independently
```

## 6. 品类视角提醒

```text
backpack:
  back 是背包背板，不是角色背面。

head_key_chain:
  back 是角色后脑勺；只看头部，颈部以下不检查。

cake_roll:
  back 是蛋糕卷螺旋纹面，不是角色背面；身体/服装不适用。

plush:
  back 是角色全身背面；全身产品均在范围内。
```

## 7. 常见判断

```text
颜色轻微偏差:
  光照或渲染导致的轻微偏差可记 minor 或不记；明显色差才记 wrong color。

看起来少了某个未预识别细节:
  不作为当前乙方可修改/可计费项，可备注到 design_quality_notes 或 human_review_required。

生成图多了纹理:
  如果没有导致预识别部位的颜色/材质/形状明显错误，不作为当前描述修改项。
```
