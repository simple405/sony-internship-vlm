# 2-SN_7期动漫标注-02试做_rev 试标质量审查

审查日期：2026-08-04
数据目录：`vlm/data/2-SN_7期动漫标注-02试做_rev`
标注说明：`vlm/data/multi_view试标数据集_rev/动漫IP多品类商品设计监修标注说明v2_已修改.pdf`

## 结论

本批试标不建议进入正式生产/评测链路，判定为 **blocked / 需返工**。

主要原因：

1. **结构不合规**：3 个 Excel 均缺少说明中提到的 `result` 汇总列。
2. **字段值不合规**：`front_visible/side_visible/back_visible` 按说明只能填 `visible` 或 `invisible`，但表内填成 `visible (可见)` / `invisible (不可见)`；`status` 也大量填成 `correct (正确)` / `correct invisible (合理不可见)`。这会让严格解析器直接失败。
3. **规则覆盖严重缺失**：按 `atomic_rules.json` 共有 67 条规则，Excel 只标了 40 条，缺失 27 条，缺失率约 40.3%。
4. **两个样本漏标成片**：`2807649` 漏 14/21 条，`3084017` 漏 13/24 条。漏项主要是 body / clothing / lower-body 规则；即使商品形态只表达头部或背包，说明也要求“商品范围外”的规则保留为 `invisible + correct invisible`，不能直接删行。
5. **语义判断仍有偏松/不确定项**：部分 visible/status 需要复核，尤其是 2807649 的 back 视角头发可见性、3084017 的 eye_marking 是否真的保真，以及产品结构新增元素是否应记为 extra 或商品结构豁免。

## 结构统计

| sample_id | atomic_rules.json 规则数 | Excel 标注行数 | 缺失规则数 | `result`列 | 严格字段值违规数 |
|---|---:|---:|---:|---|---:|
| 2180426 | 22 | 22 | 0 | 缺失 | 131 |
| 2807649 | 21 | 7 | 14 | 缺失 | 42 |
| 3084017 | 24 | 11 | 13 | 缺失 | 66 |
| 合计 | 67 | 40 | 27 | 3/3 缺失 | 239 |

> 严格字段值违规数按说明原文校验：visible 只能是 `visible/invisible`，status 只能是 `correct/wrong color/wrong shape/wrong_prosition/extra/correct invisible/wrong invisible`。当前双语括号写法不符合机器字段规范。

## 分样本问题

### 2180426

质量相对最好：22 条 atomic rules 全覆盖；能识别 `handheld_item` / `fan` / `handheld_item_color` 在三视角缺失，标为 `wrong invisible`，方向基本对。

问题：

- 缺 `result` 列。
- 所有 visible/status 使用双语括号值，不符合规范。
- `inner_clothing_color=black` 的注释写“不确定原图衣领交叉处黑色部分为阴影还是内搭”，但 front_status 直接判 `wrong color`。如果标准不可确认，建议标注规范增加 uncertain/review 机制，或至少纳入人工复核队列。

### 2807649

质量不合格。Excel 只标了头部 7 条，漏掉 14 条：

`skin_tone, top_type, top_color, top_style, top_pattern, bottom_type, bottom_color, legwear_type, legwear_color, shoe_color, shoe_accent_color, has_choker, choker_color, choker_shape`

其中 `top_color/top_pattern/top_style`、`has_choker/choker_color/choker_shape` 在背包正面是可见或部分可见的，不应缺行。`bottom/legwear/shoe` 如果因背包商品形态不表达，应按说明填 `invisible + correct invisible`，也不应删除。

需复核：

- `hair_color` 的 back 视角被标为 visible/correct，但背面主要是橙色边缘/顶部结构，不一定能判定为角色头发；当前 note 也写了“不确定书包上方橙色是否是头发”。建议转 review，不要直接 correct。
- 背面蓝橙蝴蝶结/背包结构若属于商品结构，应在规则里注明 product fixture 豁免；否则可能构成 unsupported extra。

### 3084017

质量不合格。Excel 只标了头部 11 条，漏掉 13 条：

`clothing_type, clothing_color, sleeve_length, has_sash, sash_color, sash_pattern, has_harness, harness_color, harness_arrangement, has_tights, tights_color, footwear_type, footwear_color`

该商品是头部/圆柱抱枕/挂件形态，body 规则大多可判为商品范围外，但按说明仍应保留行并填 `invisible + correct invisible`，不能删掉。

需复核：

- `eye_marking_color=red` 被标 correct，但生成图正面更像淡腮红/阴影，原图眼下红色标记保真度不够明确，应进入 review。
- 头顶挂链、背面紫色旋涡、圆柱化结构如果是商品类型要求，应在任务 contract 中写明；如果不是，则这些新增视觉元素要考虑 extra/设计偏离。

## 返工要求

1. 模板改回机器可读字段：
   - `visible` 字段只允许 `visible` / `invisible`。
   - `status` 字段只允许 `correct` / `wrong color` / `wrong shape` / `wrong_prosition` / `extra` / `correct invisible` / `wrong invisible`。
   - 中文解释不要写进枚举值，可放注释或单独中文列。
2. 补上 `result` 列：整条 rule 只要任一视角有 `wrong color/wrong shape/wrong_prosition/extra/wrong invisible`，`result=wrong`；全为 correct/correct invisible 则 `result=correct`；不确定进入 `review` 或 note 明确人工复核。
3. 每个 sample 必须覆盖 `atomic_rules.json` 的全部 rule。商品范围外也必须保留规则行，填 `invisible + correct invisible`。
4. 对不确定项不要硬判 correct：如 2180426 内搭、2807649 back 头发、3084017 眼纹。
5. 增加 QC 脚本：交付前自动检查列名、枚举、rule 覆盖、sample_id 一致性、result 推导一致性。

## 最终评级

- 结构合规：差
- 规则覆盖：差（67 条仅 40 条）
- 视角 visible/status 理解：中等，局部理解了 v2，但执行不稳定
- 视觉语义准确性：中等偏低，需要二审
- 可进入生产：否

建议让乙方按上述 5 点返工后再验收。当前最多只能作为沟通样例，不能作为合格试标样本。
