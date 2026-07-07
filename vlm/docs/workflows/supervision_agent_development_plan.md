# IP 周边生成图监修 Agent 开发方案

更新日期：2026-07-02 +08:00

## 0. 当前项目理解

本方案面向当前 `D:\索尼实习` 工作区中的 Anime IP 周边生成流程。目标不是普通文本审校，而是开发一个用于 `2D 原图 -> 周边三视图生成图` 的视觉监修 Agent。

当前有效上下文：

```text
项目根目录: D:\索尼实习
主工作区: vlm/
当前流程文档: vlm/docs/workflows/process.md
头部挂件问题总结: vlm/docs/workflows/head_key_chain_context_summary.markdown
原始 2D 图: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/image
atomic_rules: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/atomic_rules
当前生成结果: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d_no_rules/监修vlm数据
分类报告: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/reports/merchandise_category_assignment
```

当前生成结果按商品形态分为：

```text
head_only/
  head_key_chain
  backpack
  cake_roll

full body/
  plush
  dataset_QSitFigures
  dataset_figurine
```

监修 Agent 的核心任务：

```text
输入:
  1. sample_id
  2. 商品类别
  3. 原始 2D 角色图
  4. 生成的周边三视图
  5. 可选 atomic_rules / manifest tags / prompt 文件

输出:
  1. 是否通过监修
  2. 问题类型
  3. 问题位置
  4. 严重等级
  5. 修改建议
  6. 是否需要人工复核
  7. 可追溯 JSON/CSV/Markdown 报告
```

重要原则：

```text
1. 原图是最高优先级依据。
2. atomic_rules 只能作为辅助信息，不能压过肉眼图像判断。
3. 监修结果必须结构化，不能只输出自然语言评价。
4. Agent 不能自动删除、覆盖、重跑生成图。
5. 高风险或低置信度样本必须进入人工复核。
```

## 1. 监修目标定义

### 1.1 通过监修的含义

一个生成图可以通过监修，不代表它和原图姿势完全一致，而是代表它满足以下条件：

```text
1. 角色身份可识别。
2. 商品类型正确。
3. 关键身份元素没有明显缺失。
4. 没有新增原图不存在的强身份元素。
5. 三视图是同一个实体，不是三个不同设计。
6. 服装、头发、配饰、武器、花纹在三视图之间保持空间连续。
7. 不存在明显结构错误、畸形、文字水印、包装、无关背景或多余角色。
```

### 1.2 不通过监修的典型情况

从当前样例和历史记录看，优先覆盖这些失败类型：

```text
identity_missing:
  原图中的马尾、辫子、长后发、帽子、发饰、角、耳朵、武器、服装主结构缺失。

identity_hallucination:
  凭空新增兽耳、猫耳、角、尾巴、帽子、蝴蝶结、花朵、武器、翅膀。

misread_accessory:
  把头发尖角、帽檐、发饰、蝴蝶结、衣服边缘误生成兽耳、角或尾巴。

hairstyle_structure_error:
  长发变短发，马尾变散发，侧辫丢失，后发束数量明显不对。

face_expression_error:
  闭眼变睁眼，眼睛颜色明显错误，表情完全不符。

product_type_error:
  head_key_chain 生成全身，plush 生成坐姿手办，figurine 生成毛绒，cake_roll 生成真实食物。

view_inconsistency:
  正面、侧面、背面不是同一个设计，颜色、背带、裙摆、发束、武器位置不连续。

pattern_topology_error:
  局部花纹被移动到背面中心，弯曲纹样被重画成十字、T 形、菱形、徽章等新符号。

layout_error:
  不是白底三视图，视图缺失，文字标签过多，水印，包装，展示台，裁切严重。

safety_or_generation_block:
  生成失败、内容安全 1501、空输出、文件损坏。
```

### 1.3 第一版不要做的事情

```text
1. 不要训练模型。
2. 不要接入自动重跑 RunningHub。
3. 不要自动覆盖现有生成结果。
4. 不要一开始做复杂网页系统。
5. 不要试图完全替代人工监修。
6. 不要把所有判断写进一个超长 prompt。
```

第一版应先做成可批量跑、可复查、可统计的离线监修工具。

## 2. 推荐总体架构

### 2.1 架构选择

建议使用 `code-driven orchestration`，不要一开始使用完全自主的多 Agent handoff。

理由：

```text
1. 当前流程是固定的: 读图 -> 分析原图 -> 分析生成图 -> 对照 -> 输出报告。
2. 视觉监修需要可复现、可统计、可中断续跑。
3. 每一步产物都要落盘，方便人工检查和后续评估。
4. Code-driven 更容易避免 Agent 自己跳步骤或重复调用高成本模型。
```

第一版编排：

```text
collect_sample_pair
  -> validate_files
  -> extract_original_features
  -> extract_generated_features
  -> compare_identity_and_product
  -> apply_category_rules
  -> decide_review_result
  -> write_json_report
  -> write_csv_summary
  -> build_human_review_sheet
```

### 2.2 Agent 和工具分层

推荐分 1 个主 Agent + 3 个视觉分析 Agent + 若干确定性工具。

```text
ReviewOrchestrator
  固定流程控制器，由 Python/TypeScript 代码实现，不交给 LLM 自由决定。

OriginalFeatureExtractorAgent
  读取原图，抽取角色身份特征。

GeneratedSheetParserAgent
  读取生成图，解析商品类型、三视图结构、可见元素。

SupervisionCompareAgent
  对比原图特征和生成图特征，输出监修发现。

DecisionAgent
  根据 findings、严重等级、品类规则、置信度给出最终结论。
```

确定性工具：

```text
resolve_sample_paths
  根据 sample_id 和 category 找到原图、生成图、atomic_rules。

validate_image_files
  检查图片是否存在、能否打开、尺寸是否合理。

load_category_rule
  加载商品类别监修规则。

load_atomic_rules
  读取 atomic_rules，仅作为辅助证据。

load_manifest_tags
  读取 manifest.csv 中 tags、crawl_label、尺寸等信息。

split_or_mark_three_views
  第一版可以不真实切图，只记录三视图区域假设；第二版再做图像裁切。

write_review_artifacts
  写 JSON、CSV、Markdown、contact sheet。
```

### 2.3 最小落地目录结构

建议新增这些文件和目录：

```text
vlm/scripts/supervise/
  __init__.py
  run_supervision_review.py
  collect_review_pairs.py
  review_schemas.py
  category_rules.py
  report_writer.py

vlm/prompts/supervision/
  original_feature_extractor_cn.txt
  generated_sheet_parser_cn.txt
  supervision_compare_cn.txt
  decision_policy_cn.txt

vlm/config/supervision/
  category_rules.json
  severity_policy.json
  output_schema.json

vlm/experiments/supervision/
  README.md
  seed_cases.jsonl
  failure_taxonomy.md

vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/reports/supervision_review/
  runs/
  latest/
```

注意：

```text
1. 不要修改当前 RunningHub 生成脚本。
2. 不要把监修报告写进 generated_3d_no_rules 结果目录。
3. 所有监修结果写到 reports/supervision_review。
4. 第一版只读数据，不产生新的生成图。
```

## 3. 数据输入规范

### 3.1 样本对定义

每个监修任务最小单位是一个 `ReviewPair`。

```json
{
  "sample_id": "2027251",
  "category": "head_key_chain",
  "source_image_path": "vlm/data/.../image/2027251_xxx.jpg",
  "generated_image_path": "vlm/data/.../generated_3d_no_rules/监修vlm数据/head_only/head_key_chain/2027251/Image.png",
  "atomic_rules_path": "vlm/data/.../atomic_rules/2027251/2027251_atomic_rules.json",
  "manifest_row": {
    "tags": "...",
    "crawl_label": "..."
  }
}
```

### 3.2 输入收集规则

执行顺序：

```text
1. 读取用户传入的 category。
2. 根据 category 判断生成结果根目录:
   - head_key_chain/backpack/cake_roll -> head_only
   - plush/dataset_QSitFigures/dataset_figurine -> full body
3. 读取该类别下所有 sample_id 子目录。
4. 在每个子目录内寻找生成图。
5. 在 source image 目录中寻找同 sample_id 前缀的原图。
6. 在 atomic_rules 目录或生成子目录中寻找 atomic_rules。
7. 组装 ReviewPair。
8. 如果缺文件，写入 skipped 列表，而不是报错终止全批次。
```

生成图文件优先级：

```text
1. 明确命名的结果图:
   <sample_id>_head_keychain.png
   <sample_id>_backpack.png
   <sample_id>_cake_roll.png
   <sample_id>_plush.png
   <sample_id>_SitFigures.png
   <sample_id>_figurine.png
   <sample_id>_pvc_figurine.png

2. 当前监修vlm数据目录中的通用文件:
   Image.png

3. 排除:
   *_original.*
   *_atomic_rules.json
   .part
   debug 文件
```

### 3.3 第一批种子样本

先不要全量 1115 个样本。第一批做 20-40 个种子样本。

必须包含：

```text
head_key_chain:
  2027251  长发/高位束发被简化，是典型不通过样例。
  2028680  发饰误判成兽耳风险。
  2028681  闭眼/后发束风险。
  2028690  帽子和侧辫缺失风险。
  2166018  角/兽耳误判风险。

dataset_figurine:
  3206142  已确认可用，可作为通过样例。
  2726312  内容安全/风控相关样本，作为特殊状态样例。

plush:
  2436714  内容安全 1501 样本，作为 blocked 样例。
```

再从每个品类随机补充：

```text
head_key_chain: 5 个
backpack: 5 个
cake_roll: 5 个
plush: 5 个
dataset_QSitFigures: 5 个
dataset_figurine: 5 个
```

种子样本文件：

```text
vlm/experiments/supervision/seed_cases.jsonl
```

字段：

```json
{
  "sample_id": "2027251",
  "category": "head_key_chain",
  "expected_decision": "reject",
  "expected_findings": ["hairstyle_structure_error", "identity_missing"],
  "notes": "原图长发和高位束发在生成图中被明显简化。"
}
```

## 4. 监修维度和评分

### 4.1 监修维度

第一版固定 8 个维度：

```text
1. identity_fidelity
   角色身份保真。

2. product_type_correctness
   商品类型是否正确。

3. three_view_consistency
   三视图是否是同一个实体。

4. spatial_logic
   空间结构是否合理。

5. pattern_topology
   花纹、色块、服装拓扑是否连续。

6. hallucination_control
   是否新增原图没有的身份元素。

7. omission_control
   是否缺失原图关键元素。

8. output_cleanliness
   白底、无文字水印、无包装、无多余角色、无遮挡裁切。
```

### 4.2 严重等级

```text
critical:
  角色完全不像、商品类型完全错误、三视图严重混乱、生成图不可用。

high:
  关键身份元素缺失或幻觉，例如马尾丢失、帽子丢失、凭空新增兽耳、武器消失。

medium:
  局部颜色、花纹、配饰、表情有明显错误，但角色仍可识别。

low:
  轻微比例、材质、风格、细节偏差，不影响主要身份和商品形态。

info:
  不确定，需要人工确认，不直接扣重分。
```

### 4.3 总分规则

初始 100 分，按 findings 扣分：

```text
critical: -45
high: -25
medium: -12
low: -4
info: 0
```

加权规则：

```text
1. product_type_error 最低降到 40 分。
2. identity_hallucination 如果新增强身份元素，最低降到 65 分。
3. identity_missing 如果缺失核心身份元素，最低降到 70 分。
4. 三视图不是同一个设计，最低降到 60 分。
5. 图片打不开、没有生成图，直接 0 分。
```

决策规则：

```text
approved:
  score >= 85
  且没有 high/critical
  且商品类型正确

needs_revision:
  60 <= score < 85
  或存在 medium 问题
  且没有 critical

human_review_required:
  存在 high 问题但 Agent 置信度不足
  或原图信息复杂/遮挡导致无法可靠判断
  或 atomic_rules 与视觉判断冲突

rejected:
  score < 60
  或存在 critical
  或商品类型错误
  或关键身份元素严重丢失/严重幻觉
```

## 5. 品类规则细化

### 5.1 head_key_chain

必须满足：

```text
1. 只包含头部挂件，不画完整身体。
2. 有挂扣或钥匙链结构。
3. 正面、侧面、背面为同一头部挂件。
4. 保留头部身份元素:
   - 发型轮廓
   - 刘海
   - 侧发
   - 后发
   - 马尾
   - 辫子
   - 发髻
   - 发色分布
   - 头饰/帽子/角/耳朵
   - 眼睛开闭状态
5. 原图没有兽耳/猫耳时，禁止生成兽耳/猫耳。
6. 不要把发饰、帽檐、头发尖角误判成兽耳或角。
```

重点失败：

```text
2027251 类型问题:
  原图长发/高位束发/后发结构明显，生成图变成短发圆头。

2028680 类型问题:
  黄色头部发饰被误生成动物耳。

2028681 类型问题:
  闭眼变睁眼，多束后发被简化。

2028690 类型问题:
  黑色帽子和侧辫缺失。
```

### 5.2 backpack

必须满足：

```text
1. 商品是双肩背包，不是玩偶、手办、挂件。
2. 有明确包体、背带、侧面厚度、背面结构。
3. 三视图是同一个背包。
4. 角色身份元素以背包外观、图案、头部装饰、配色方式体现。
5. 不能凭空新增原图没有的耳朵、角、尾巴、蝴蝶结。
```

重点失败：

```text
1. 只画角色，不像背包。
2. 正面像玩偶，背面像普通书包，侧面结构断裂。
3. 背带数量或位置在三视图中不一致。
4. 把角色头发尖角设计成兽耳包。
```

### 5.3 cake_roll

必须满足：

```text
1. 商品是圆润蛋糕卷毛绒挂件，不是真实食物。
2. 正面显示角色脸部。
3. 侧面显示连续圆柱外侧和厚度。
4. 背面才允许显示卷纹结构。
5. 侧面不能出现蛋糕切面、螺旋卷纹或夹心层。
6. 不要生成完整身体、四肢、衣服身体、鞋子。
```

重点失败：

```text
1. 生成真实蛋糕卷。
2. 每个视角都是不同的圆形图案。
3. 侧面出现不该出现的切面。
4. 角色身份只剩颜色，不可识别。
```

### 5.4 plush

必须满足：

```text
1. 商品是全身站姿毛绒玩偶。
2. 不是 QSitFigures，不是坐姿手办，不是 PVC 手办。
3. 三视图都是同一个全身站姿毛绒。
4. 双脚落地，身体直立。
5. 可以 Q 化，但不能坐下、蹲下、跪坐、盘腿。
6. 不要出现椅子、底座、展示台、包装、文字。
```

重点失败：

```text
1. 生成坐姿。
2. 腿脚结构缺失。
3. 服装和发型过度简化。
4. 三视图身体比例明显不一致。
```

### 5.5 dataset_QSitFigures

必须满足：

```text
1. 商品是 Q 版坐姿小手办。
2. 坐姿应稳定、可商品化。
3. 角色身份元素不能因为坐姿 Q 化而丢失。
4. 不要生成站姿 PVC、毛绒玩偶、钥匙链或背包。
```

重点失败：

```text
1. 仍然是站姿。
2. 坐姿导致服装结构完全乱掉。
3. 道具、武器、尾巴、翅膀与身体关系不合理。
```

### 5.6 dataset_figurine

必须满足：

```text
1. 商品是 PVC 收藏手办。
2. 白底横向三视图。
3. 正面、侧面、背面是同一个全身手办。
4. 中性站姿，双脚落地，身体直立。
5. 可以轻微 Q 化，但不能变成毛绒、坐姿、钥匙链、背包、蛋糕卷。
6. 服装结构、武器、道具、发型、配色、花纹都要和原图对得上。
```

重点规则：

```text
1. 局部花纹不能被移动到背面中心。
2. 侧边、斜侧、局部边缘的花纹必须保持在对应衣片位置。
3. 弯曲纹样不能被重画成十字、T 形、菱形、徽章。
4. 单角度原图无法确认背面时，不要凭空补大面积背部符号。
5. 背面可延续主色、金边、接缝和自然绕过去的一小段装饰。
```

参考通过样例：

```text
3206142:
  不要求姿势完全一样，但紫发、头饰、服装色块、武器、裙摆局部红色花纹和三视图连续性需要稳定。
```

## 6. 输出 Schema 设计

### 6.1 ReviewResult

第一版建议固定 JSON 结构：

```json
{
  "sample_id": "2027251",
  "category": "head_key_chain",
  "decision": "rejected",
  "score": 52,
  "risk_level": "high",
  "confidence": 0.82,
  "requires_human_review": false,
  "summary_cn": "生成图商品形态基本成立，但原图长发和高位束发结构被明显简化，角色身份保真不足。",
  "findings": [],
  "positive_points": [],
  "source_evidence": {},
  "generated_evidence": {},
  "metadata": {}
}
```

### 6.2 Finding

```json
{
  "finding_id": "F001",
  "type": "hairstyle_structure_error",
  "dimension": "identity_fidelity",
  "severity": "high",
  "confidence": 0.86,
  "source_region": "原图右侧/背面视角头发区域",
  "generated_region": "生成图背面头部区域",
  "problem_cn": "原图存在明显长后发和高位束发，生成图背面被简化为短发圆头。",
  "expected_cn": "应保留长后发轮廓、高位束发位置和后方发束体量。",
  "suggestion_cn": "重新生成时应强调后发长度、束发位置和背面发束结构，避免简化为普通短发头套。",
  "evidence_cn": "原图可见长发延伸到背部以下，生成图背面只显示齐颈短发。"
}
```

### 6.3 FeatureExtraction

原图抽取结构：

```json
{
  "sample_id": "2027251",
  "visible_views": ["front", "side", "back"],
  "character_count": 1,
  "identity_features": {
    "hair": {
      "color": "light brown",
      "length": "long",
      "structure": ["high side ponytail", "long back hair", "bangs"],
      "risk_notes": ["must not be simplified into short bob"]
    },
    "eyes": {
      "color": "green",
      "state": "open"
    },
    "head_accessories": ["pink hair ornament"],
    "outfit": ["maid-like blouse", "purple skirt"],
    "props": []
  },
  "uncertain_features": []
}
```

生成图解析结构：

```json
{
  "sample_id": "2027251",
  "detected_product_type": "head_key_chain",
  "views": ["front", "side", "back"],
  "product_structure": {
    "has_keychain": true,
    "is_head_only": true,
    "has_full_body": false
  },
  "visible_identity_features": {
    "hair": {
      "color": "light brown",
      "length": "short",
      "structure": ["short bob", "small side bun"]
    },
    "eyes": {
      "color": "green",
      "state": "open"
    },
    "head_accessories": ["pink hair ornament"]
  },
  "view_consistency": {
    "is_same_object": true,
    "issues": []
  }
}
```

## 7. Prompt 设计

### 7.1 原图特征抽取 Prompt

文件：

```text
vlm/prompts/supervision/original_feature_extractor_cn.txt
```

职责：

```text
你是动漫角色视觉特征抽取器。
你只分析输入的原始 2D 角色图，不评价生成图。
请抽取后续 IP 周边监修必须保留的角色身份特征。
不要猜测被遮挡或不可见的细节。
如果不确定，放入 uncertain_features。
输出必须为 JSON。
```

必须抽取：

```text
1. 角色数量和主体角色。
2. 可见视角: 正面、侧面、背面、设定图、多表情、多角色拼图。
3. 发型: 长短、刘海、侧发、后发、马尾、辫子、双马尾、发髻、呆毛。
4. 发色和颜色分布。
5. 眼睛颜色、开闭状态、表情。
6. 头部元素: 帽子、发饰、角、兽耳、普通耳朵、蝴蝶结、皇冠。
7. 服装结构: 上衣、裙摆、披风、袖口、腰带、鞋靴。
8. 局部花纹和色块位置。
9. 武器、道具、翅膀、尾巴。
10. 必须禁止误判的元素。
```

### 7.2 生成图解析 Prompt

文件：

```text
vlm/prompts/supervision/generated_sheet_parser_cn.txt
```

职责：

```text
你是周边商品三视图解析器。
你只分析生成图，不看原图。
请判断商品类型、三视图完整性、可见身份元素、结构一致性和明显画面问题。
输出必须为 JSON。
```

必须解析：

```text
1. 检测到的商品类型。
2. 是否白底三视图。
3. 是否有正面、侧面、背面。
4. 是否同一个实体。
5. 是否有文字、水印、包装、底座、多余角色。
6. 商品结构是否符合类别。
7. 可见发型、头饰、眼睛、服装、武器、花纹。
8. 三视图之间的连续性问题。
```

### 7.3 对照监修 Prompt

文件：

```text
vlm/prompts/supervision/supervision_compare_cn.txt
```

职责：

```text
你是 IP 周边视觉监修员。
你会收到:
1. 原图特征 JSON
2. 生成图解析 JSON
3. 商品类别规则
4. 原图
5. 生成图

请判断生成图是否能通过 IP 公司监修。
原图是最高优先级依据，atomic_rules 仅作辅助。
你必须区分:
1. 确定问题
2. 潜在风险
3. 可接受的 Q 化或商品化变化
4. 无法判断，需要人工复核
输出必须符合 ReviewResult JSON。
```

关键约束：

```text
1. 不要因为姿势不同就直接判失败，除非商品类别要求特定姿势。
2. 不要要求生成图完全复刻原图，但关键身份元素必须保留。
3. 不要凭空推断原图不可见的背面细节。
4. 对单角度原图，背面不确定处应标记为 uncertain，而不是错误。
5. 如果生成图新增强身份元素，优先判为 hallucination。
6. 如果生成图缺失强身份元素，优先判为 omission。
```

### 7.4 决策 Prompt

文件：

```text
vlm/prompts/supervision/decision_policy_cn.txt
```

职责：

```text
根据 findings、品类规则、严重等级和置信度给出最终 decision。
不得引入新的视觉判断，只能基于已有 findings 做决策。
```

决策必须稳定，建议尽量用代码规则完成。DecisionAgent 只用于解释边界情况。

## 8. 开发步骤细化

### 8.0 执行分工和人工确认门

本节用于指导后续真实开发时如何分配工作。原则是：Codex 负责把流程、文件、脚本、报告和可复现检查搭起来；人工负责给出主观监修标准、确认样本标签、判断输出是否符合业务预期。

角色标记：

```text
[Codex 可完成]
  可以由 Codex 直接创建、修改、运行或验证的工程任务。

[需要人工帮助]
  必须由人类提供业务判断、视觉监修结论、模型/API 选择、成本授权或敏感数据确认。

[人工确认后 Codex 执行]
  Codex 可以实现，但需要先由人工确认方向、阈值、样例或是否允许调用外部 API。

[Codex 不应执行]
  即使技术上能做，也不应让 Codex 自动执行的动作。
```

总原则：

```text
1. Codex 可以写监修管线，但不能替人工定义“IP 公司最终通过标准”。
2. Codex 可以根据已有样例起草规则，但人工必须确认规则是否符合真实监修口径。
3. Codex 可以批量跑 dry-run 和离线报告，但真实 VLM API 调用需要人工确认模型、成本和数据外发风险。
4. Codex 可以生成 Agent 判断结果，但第一阶段所有 high/rejected/approved 样本都应抽样人工复核。
5. Codex 不应自动删除、覆盖、重跑或替换任何生成图。
```

#### 8.0.1 开发阶段分工总表

| 阶段 | 目标 | Codex 可完成 | 需要人工帮助 | 产物 | 进入下一阶段条件 |
| --- | --- | --- | --- | --- | --- |
| 0. 环境盘点 | 确认现有目录、数据、脚本、生成结果 | 扫描目录、读取 README/process、列出现有资产和缺口 | 确认当前主数据目录是否就是 `监修vlm数据` | 缺口清单 | 人工确认开发目标没有偏差 |
| 1. 失败类型整理 | 把人工经验变成 taxonomy | 根据历史文档起草 `failure_taxonomy.md` | 确认每类问题是否真的影响监修通过 | `failure_taxonomy.md` | 每个高风险问题都有定义和样例 |
| 2. 种子集建立 | 建立第一批可评测样本 | 生成 seed case 模板、自动检查路径是否存在 | 给每个样本标注 expected_decision 和 expected_findings | `seed_cases.json` 或 `seed_cases.jsonl` | 至少 30 个样本且覆盖 6 类商品 |
| 3. 品类规则配置 | 把 prompt 中的硬约束机器化 | 起草 `category_rules.json` 和 `severity_policy.json` | 确认各类别的通过/拒绝阈值 | 规则 JSON | 规则能解释 2027251 和 3206142 |
| 4. Prompt 起草 | 建立监修用 VLM prompt | 写原图抽取、生成图解析、对照监修 prompt | 确认语言、判断口径、禁止事项是否正确 | `vlm/prompts/supervision/*.txt` | prompt 不再混杂生成任务和监修任务 |
| 5. 样本配对脚本 | 自动找到原图和生成图 | 写 `collect_review_pairs.py`，跑 dry-run | 确认多结果图时的优先级 | `review_pairs.jsonl`、`skipped_pairs.jsonl` | 2027251、3206142 能正确配对 |
| 6. Schema 和报告骨架 | 固定输出格式 | 写 `review_schemas.py`、`report_writer.py` | 确认 CSV 字段是否满足人工复核 | `review_summary.csv`、`findings.csv` 模板 | Excel 可读，字段足够复核 |
| 7. VLM Client 骨架 | 预留真实模型接入点 | 写 `vlm_client.py` dry-run provider | 选择真实 VLM provider、模型、API key、预算 | dry-run JSON 输出 | 不接 API 也能完整跑通流程 |
| 8. 单样本监修 | 对一个样本输出 result.json | 写 `run_supervision_review.py --sample-id` | 人工检查输出是否符合视觉事实 | 单样本 `result.json` | 2027251 输出具体失败点 |
| 9. 种子集批跑 | 批量跑 20-40 个样本 | 实现 `--pairs --limit --resume`，生成报告 | 人工复核所有 high/rejected 和部分 approved | seed run 报告 | 结构化输出成功率稳定 |
| 10. 人工反馈分析 | 统计误报和漏报 | 写 `analyze_human_feedback.py` | 填写 human_decision 和 human_notes | 误报/漏报统计 | 明确下一轮要改规则还是 prompt |
| 11. 小批量扩展 | 每类别先跑 20 个 | 批量执行、汇总、生成 contact sheet | 抽查每个类别结果 | 类别小批报告 | 没有系统性错判 |
| 12. 全量监修 | 跑完整数据集 | 按类别批跑、断点续跑、汇总总报告 | 最终监修结论和发布/重跑决策 | 全量报告 | 人工确认可作为后续生产依据 |

#### 8.0.2 人工确认门

每个确认门没有通过时，Codex 只应继续做离线整理、报告和工具检查，不应推进到下一阶段。

```text
H0 目标确认门
  人工确认本项目目标是“IP 周边生成图监修”，不是通用图像评分或文本审核。

H1 标准确认门
  人工确认 failure taxonomy 和各品类规则符合真实监修口径。

H2 样本标签确认门
  人工确认 seed_cases 中 expected_decision 和 expected_findings。

H3 模型/API 确认门
  人工确认是否允许把原图和生成图发给某个外部 VLM API。
  人工确认模型名称、API key 来源、预算、单批数量。

H4 首轮结果确认门
  人工检查 2027251、3206142 等关键样本的 result.json。
  如果 2027251 没抓住发型/束发缺失，不能进入批量。
  如果 3206142 被严重误拒，不能进入批量。

H5 种子集评估确认门
  人工复核 seed run 输出，确认 high_risk_recall 和误报可接受。

H6 全量执行确认门
  人工确认小批量结果稳定后，才允许全量跑真实 VLM。
```

#### 8.0.3 Codex 可直接完成的任务

这些任务属于工程搭建、离线数据处理和格式化输出，Codex 可以直接执行：

```text
1. 创建目录:
   - vlm/scripts/supervise/
   - vlm/prompts/supervision/
   - vlm/config/supervision/
   - vlm/experiments/supervision/

2. 创建配置和模板:
   - category_rules.json
   - severity_policy.json
   - seed_cases 模板
   - failure_taxonomy.md 初稿

3. 创建脚本:
   - collect_review_pairs.py
   - review_schemas.py
   - report_writer.py
   - run_supervision_review.py dry-run 版本
   - analyze_human_feedback.py

4. 运行不调用外部 API 的检查:
   - 路径配对
   - 图片能否打开
   - JSON/CSV 能否写出
   - dry-run result.json 能否生成
   - 报告汇总是否完整

5. 输出开发状态报告:
   - 已完成文件
   - 缺失文件
   - 失败样本
   - skipped 样本
   - 下一步人工确认点
```

#### 8.0.4 需要人工帮助的任务

这些任务包含主观视觉判断、业务标准和外部资源授权，必须人工参与：

```text
1. 判断某张生成图是否真实通过 IP 监修。
2. 确认某个问题属于 high、medium 还是可接受 Q 化。
3. 给 seed_cases 填写最终 expected_decision。
4. 判断某个原图不可见的背面细节是否允许生成模型自行补全。
5. 选择真实 VLM 模型和 API provider。
6. 授权是否可以把图片发送给外部 API。
7. 确认单次和全量调用预算。
8. 复核第一轮 rejected、human_review_required、approved 样本。
9. 决定是否根据监修结果重跑 RunningHub。
10. 决定哪些样本进入最终交付或展示。
```

#### 8.0.5 人工确认后 Codex 可以执行的任务

这些任务技术上可以自动化，但需要人工先确认方向：

```text
1. 接入真实 VLM API。
   需要人工确认 provider、模型、API key、预算、图片外发许可。

2. 批量调用真实 VLM。
   需要人工确认 sample 数量、workers、是否限制类别。

3. 修改 prompt 判断口径。
   需要人工确认上一轮误报/漏报分析。

4. 调整 severity_policy 阈值。
   需要人工确认是宁可多拦截还是减少误报。

5. 生成 rerun_prompt_hint。
   需要人工确认这些 hint 只作为建议，不自动重跑。

6. 生成可视化 contact sheet。
   需要人工确认图片数量、是否包含 rejected 样本、是否适合分享。
```

#### 8.0.6 Codex 不应执行的任务

这些任务会影响数据安全、成本、现有结果或最终业务判断，除非用户明确要求，否则不执行：

```text
1. 不自动删除任何原图、生成图、atomic_rules、报告或 sample_lists。
2. 不自动覆盖已有生成结果。
3. 不自动运行 RunningHub 重生成。
4. 不自动运行 assign_merchandise_categories.py 刷新 sample_lists。
5. 不把人工未确认的 Agent 判断当作最终监修结论。
6. 不擅自把图片上传到新的第三方服务。
7. 不在没有预算确认时跑全量真实 VLM。
8. 不把失败样本从数据集中移除。
9. 不修改现有生成 prompt 来“顺手优化”，除非进入 prompt 迭代阶段并获得确认。
```

#### 8.0.7 推荐的实际推进顺序

如果后续要让 Codex 继续开发，建议按下面顺序逐步推进，每一步结束都停下来给人工看结果：

```text
第 A 轮: 离线骨架
  Codex:
    1. 建目录。
    2. 写 category_rules.json 初稿。
    3. 写 seed_cases 模板。
    4. 写 collect_review_pairs.py。
    5. 对 2027251 和 3206142 跑路径配对。
  人工:
    1. 确认路径配对是否正确。
    2. 确认 seed_cases 中关键样本标签。

第 B 轮: dry-run 监修报告
  Codex:
    1. 写 review_schemas.py。
    2. 写 report_writer.py。
    3. 写 run_supervision_review.py dry-run。
    4. 输出 review_summary.csv 和 result.json。
  人工:
    1. 确认报告字段够不够人工复核。
    2. 确认决策字段和 finding 字段是否符合工作习惯。

第 C 轮: 真实 VLM 单样本
  人工:
    1. 确认模型和 API。
    2. 确认允许上传测试图片。
  Codex:
    1. 接入真实 VLM provider。
    2. 只跑 2027251 和 3206142。
    3. 保存 raw response、parsed JSON、result.json。
  人工:
    1. 检查 2027251 是否抓住关键失败。
    2. 检查 3206142 是否被合理通过或轻微建议。

第 D 轮: 种子集小批
  Codex:
    1. 跑 seed_cases 20-40 个。
    2. 生成 findings.csv、human_review_queue.csv、review_report.md。
  人工:
    1. 填 human_decision。
    2. 标注 missed_findings 和 false_positive_findings。

第 E 轮: 误报漏报修正
  Codex:
    1. 统计误报/漏报。
    2. 提出 prompt/rule 修改建议。
    3. 在人工确认后修改 prompt/rule。
  人工:
    1. 决定优先提高召回还是降低误报。

第 F 轮: 分类别扩展
  Codex:
    1. 每类别跑 20 个。
    2. 输出类别报告。
  人工:
    1. 确认没有某一类别系统性错判。

第 G 轮: 全量运行
  人工:
    1. 确认预算和执行窗口。
  Codex:
    1. 按类别全量跑。
    2. 断点续跑。
    3. 输出最终总报告。
```

### 第 1 步：冻结需求文档

操作：

```text
1. 阅读:
   - vlm/docs/workflows/process.md
   - vlm/docs/workflows/head_key_chain_context_summary.markdown
   - vlm/prompts/generation/runninghub/*.txt

2. 在 vlm/experiments/supervision/failure_taxonomy.md 中整理失败类型。

3. 把失败类型分成:
   - 商品类型错误
   - 角色身份缺失
   - 角色身份幻觉
   - 三视图不一致
   - 花纹拓扑错误
   - 输出格式错误
   - 生成/文件错误

4. 给每类失败写 2-3 个例子。

5. 明确第一版范围:
   - 只做离线监修
   - 只读现有生成图
   - 只输出报告
   - 不自动重跑
```

验收：

```text
1. failure_taxonomy.md 存在。
2. 每个问题类型都有定义、严重等级建议、样例。
3. 能解释 2027251 为什么不通过。
4. 能解释 3206142 为什么可作为通过样例。
```

### 第 2 步：建立种子评测集

操作：

```text
1. 新建 vlm/experiments/supervision/seed_cases.jsonl。

2. 手工写入历史明确样本:
   - 2027251
   - 2028680
   - 2028681
   - 2028685
   - 2028690
   - 2166018
   - 3206142
   - 2436714
   - 2726312

3. 每行记录:
   - sample_id
   - category
   - expected_decision
   - expected_findings
   - reviewer_note

4. 从每个品类随机补充 5 个样本。

5. 不要把大图片复制到 experiments，只记录路径。
```

验收：

```text
1. 至少 30 个样本。
2. 至少覆盖 6 个商品类别。
3. 至少包含 5 个明确失败样本。
4. 至少包含 1 个明确通过样本。
```

### 第 3 步：实现样本路径收集器

文件：

```text
vlm/scripts/supervise/collect_review_pairs.py
```

功能：

```text
1. 输入 category 或 seed_cases.jsonl。
2. 找到原图路径。
3. 找到生成图路径。
4. 找到 atomic_rules 路径。
5. 找到 manifest 行。
6. 输出 review_pairs.jsonl。
```

命令设计：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\supervise\collect_review_pairs.py `
  --dataset-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20 `
  --generated-root '.\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\generated_3d_no_rules\监修vlm数据' `
  --category head_key_chain `
  --output .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\reports\supervision_review\latest\review_pairs.jsonl
```

实现细节：

```text
1. 使用 pathlib.Path。
2. 图片后缀支持 .png/.jpg/.jpeg/.webp。
3. sample_id 从目录名或文件名前缀读取。
4. 原图查找逻辑复用现有生成脚本思路:
   - image/<sample_id>*
   - generated 子目录内 *_original.*
5. 生成图查找必须排除:
   - *_original.*
   - *_atomic_rules.json
   - .part
6. 如果多个生成图同时存在，记录 candidates，并选择优先级最高的。
7. 缺失文件不抛异常终止，写 skipped_pairs.jsonl。
```

验收：

```text
1. 对 head_key_chain 能收集到 2027251。
2. 对 dataset_figurine 能收集到 3206142。
3. 缺图样本进入 skipped_pairs.jsonl。
4. 输出 JSONL 每行都能被 json.loads 解析。
```

### 第 4 步：定义 Schema

文件：

```text
vlm/scripts/supervise/review_schemas.py
```

内容：

```text
1. ReviewPair
2. OriginalFeatureExtraction
3. GeneratedSheetParsing
4. Finding
5. ReviewResult
6. RunSummary
```

如果项目继续用 Python：

```text
优先用 dataclasses + typing.TypedDict。
暂时不要引入 pydantic，除非后续确实需要强校验。
```

如果后续接 OpenAI Agents SDK TypeScript：

```text
用 Zod 定义同构 schema。
Python 侧和 TypeScript 侧字段名保持一致。
```

验收：

```text
1. 所有输出字段有固定命名。
2. decision、severity、finding type 使用枚举。
3. 不允许 Agent 输出任意自由字段。
4. schema 中包含 version 字段，方便后续升级。
```

### 第 5 步：编写品类规则文件

文件：

```text
vlm/config/supervision/category_rules.json
```

结构：

```json
{
  "head_key_chain": {
    "required_product_traits": ["head_only", "keychain_or_hook", "front_side_back_views"],
    "forbidden_traits": ["full_body", "extra_character", "animal_ears_if_absent_in_source"],
    "identity_priority": ["hair_structure", "head_accessories", "eye_state", "ears_or_horns_if_present"],
    "critical_failures": ["not_head_keychain", "different_character"],
    "high_failures": ["missing_core_hair_structure", "hallucinated_animal_ears"]
  }
}
```

操作：

```text
1. 先写 6 个 category。
2. 每个 category 至少包含:
   - required_product_traits
   - forbidden_traits
   - identity_priority
   - view_requirements
   - critical_failures
   - high_failures
3. 规则文字使用中文说明，字段名用英文。
4. 不要在规则里写某个样本专属细节。
```

验收：

```text
1. category_rules.json 能被 Python json.load。
2. 6 个 category 都有规则。
3. 规则能覆盖 prompt 文件中的硬约束。
```

### 第 6 步：编写三个 Prompt 文件

文件：

```text
vlm/prompts/supervision/original_feature_extractor_cn.txt
vlm/prompts/supervision/generated_sheet_parser_cn.txt
vlm/prompts/supervision/supervision_compare_cn.txt
```

操作：

```text
1. 从本方案第 7 节复制职责和约束。
2. 每个 prompt 只做一件事。
3. prompt 中明确:
   - 输入是什么
   - 不能做什么
   - 输出 JSON 字段
   - 不确定时如何处理
4. 不要把全部品类规则塞进 prompt，运行时按 category 注入对应规则。
```

验收：

```text
1. 每个 prompt 文件小于 250 行。
2. 每个 prompt 都要求 JSON 输出。
3. 对照 prompt 明确“原图最高优先级，atomic_rules 仅辅助”。
```

### 第 7 步：实现 VLM 调用适配层

文件：

```text
vlm/scripts/supervise/vlm_client.py
```

职责：

```text
1. 封装多模态模型调用。
2. 支持传入一张或两张图片。
3. 支持 prompt + JSON 输出。
4. 支持 dry-run。
5. 支持失败重试。
6. 记录原始响应到 debug 目录。
```

接口设计：

```python
def run_vlm_json(
    *,
    prompt: str,
    image_paths: list[Path],
    expected_schema_name: str,
    output_path: Path,
    debug_dir: Path,
    dry_run: bool = False,
) -> dict:
    ...
```

实现注意：

```text
1. 第一版可以先留 provider 抽象:
   - openai
   - dashscope
   - local
2. 不要把 API key 写入文件。
3. 原始响应和解析后 JSON 分开保存。
4. JSON 解析失败时:
   - 保存 raw 文本
   - 重试一次
   - 仍失败则返回 status=json_parse_failed
5. 所有异常转成结构化错误，不让批处理直接崩。
```

验收：

```text
1. dry-run 能生成占位 JSON。
2. 真实调用失败时不会中断整个批次。
3. debug 目录能看到 raw_response。
```

### 第 8 步：实现单样本监修流程

文件：

```text
vlm/scripts/supervise/run_supervision_review.py
```

单样本流程：

```text
1. 读取 ReviewPair。
2. validate_image_files。
3. 调 OriginalFeatureExtractorAgent。
4. 调 GeneratedSheetParserAgent。
5. 加载 category_rules。
6. 调 SupervisionCompareAgent。
7. 用代码应用 severity_policy。
8. 得到 ReviewResult。
9. 写:
   - result.json
   - original_features.json
   - generated_parse.json
   - raw responses
```

命令设计：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\supervise\run_supervision_review.py `
  --pair-json .\vlm\data\...\reports\supervision_review\latest\review_pairs.jsonl `
  --sample-id 2027251 `
  --output-dir .\vlm\data\...\reports\supervision_review\runs\20260702_001 `
  --dry-run
```

验收：

```text
1. 能跑 2027251 dry-run。
2. 输出目录结构固定。
3. result.json 字段完整。
4. 找不到 sample_id 时给出明确错误。
```

### 第 9 步：实现批量监修

批量流程：

```text
1. 读取 review_pairs.jsonl。
2. 按 sample_id 去重。
3. 跳过已有 result.json，除非 --force。
4. 每个样本单独 try/except。
5. 每完成一个样本立即写结果。
6. 最后生成 run_summary.json。
```

命令设计：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\supervise\run_supervision_review.py `
  --pairs .\vlm\data\...\reports\supervision_review\latest\review_pairs.jsonl `
  --output-dir .\vlm\data\...\reports\supervision_review\runs\20260702_seed `
  --workers 1 `
  --limit 30
```

第一版建议：

```text
workers=1
```

原因：

```text
1. VLM 调用成本高。
2. 输出需要先人工检查质量。
3. 并发会让 debug 日志难读。
```

验收：

```text
1. --limit 3 能只跑 3 个样本。
2. 中断后重跑能跳过已完成样本。
3. 每个失败样本有 error.json。
4. run_summary.json 包含成功、失败、跳过数量。
```

### 第 10 步：实现报告生成

文件：

```text
vlm/scripts/supervise/report_writer.py
```

输出：

```text
reports/supervision_review/runs/<run_id>/
  results/
    <category>/<sample_id>/result.json
  tables/
    review_summary.csv
    findings.csv
    human_review_queue.csv
  markdown/
    review_report.md
  contact_sheets/
    rejected_top.jpg
    human_review_top.jpg
```

CSV 字段：

```text
review_summary.csv:
  sample_id
  category
  decision
  score
  risk_level
  confidence
  requires_human_review
  finding_count
  high_count
  critical_count
  source_image_path
  generated_image_path
  result_json_path

findings.csv:
  sample_id
  category
  finding_id
  type
  dimension
  severity
  confidence
  source_region
  generated_region
  problem_cn
  suggestion_cn
```

Markdown 报告结构：

```text
# 监修报告

## 本次运行概览
## 按类别统计
## 按决策统计
## 高风险问题 Top
## 需要人工复核样本
## 典型不通过样本
## 典型通过样本
## 错误和跳过样本
```

验收：

```text
1. CSV 可用 Excel 打开。
2. Markdown 中能直接点击或复制路径找到图片。
3. high/critical 样本不会被埋在长报告里。
```

### 第 11 步：建立人工复核闭环

第一版不做网页，先用 CSV + Markdown。

文件：

```text
human_review_queue.csv
```

字段：

```text
sample_id
category
decision
score
primary_issue
agent_summary
source_image_path
generated_image_path
human_decision
human_notes
correct_findings
missed_findings
false_positive_findings
```

人工复核操作：

```text
1. 打开 human_review_queue.csv。
2. 逐行看 source_image_path 和 generated_image_path。
3. 填写 human_decision:
   - approved
   - needs_revision
   - rejected
   - unclear
4. 填写 human_notes。
5. 如果 Agent 错了，填写 missed_findings 或 false_positive_findings。
```

后处理脚本：

```text
vlm/scripts/supervise/analyze_human_feedback.py
```

职责：

```text
1. 读取人工标注 CSV。
2. 统计 Agent 与人工一致率。
3. 统计漏报类型。
4. 统计误报类型。
5. 生成下一轮 prompt/rule 修改建议。
```

验收：

```text
1. 能算 approved/rejected 一致率。
2. 能列出漏报最多的 finding type。
3. 能列出误报最多的 finding type。
```

### 第 12 步：建立评测指标

第一版指标：

```text
schema_success_rate:
  VLM 输出能被 JSON 解析并符合 schema 的比例。

decision_accuracy:
  Agent decision 与人工 decision 一致比例。

high_risk_recall:
  人工认为 rejected/human_review 的样本中，Agent 成功拦出的比例。

false_reject_rate:
  人工认为 approved 的样本中，Agent 判 rejected 的比例。

finding_type_recall:
  特定问题类型的召回，例如 hairstyle_structure_error。

average_latency_seconds:
  单样本平均耗时。

average_cost:
  单样本平均调用成本，如果 provider 可返回用量。
```

优先级：

```text
1. high_risk_recall
2. schema_success_rate
3. decision_accuracy
4. finding_type_recall
5. false_reject_rate
6. latency/cost
```

原因：

```text
监修系统第一目标是不要放过明显不通过样本。
早期误报可以接受，因为可以进入人工复核。
漏报关键身份错误比多拦截几个样本更危险。
```

### 第 13 步：第一轮实验

输入：

```text
seed_cases.jsonl
limit: 30
workers: 1
dry_run: false
```

操作：

```text
1. 收集 ReviewPair。
2. 跑 30 个样本。
3. 生成 review_summary.csv。
4. 人工检查所有 rejected/human_review。
5. 人工抽查 approved 至少 10 个。
6. 记录误报和漏报。
```

重点检查：

```text
1. 2027251 是否能抓到发型结构简化。
2. 3206142 是否不会被误拒。
3. Agent 是否能区分“姿势改变可接受”和“商品类型错误”。
4. Agent 是否频繁凭空指责原图不可见的背面细节。
5. 输出是否足够具体，不要只有“细节不一致”。
```

验收：

```text
1. schema_success_rate >= 90%。
2. 明确历史失败样本召回 >= 80%。
3. 每个 rejected 样本至少有一个具体 finding。
4. 每个 finding 都有 problem_cn 和 suggestion_cn。
```

### 第 14 步：错误分析和规则迭代

错误分桶：

```text
1. 漏报身份缺失。
2. 漏报身份幻觉。
3. 误报可接受 Q 化。
4. 误报原图不可见背面。
5. 商品类型误判。
6. 三视图一致性误判。
7. 花纹拓扑误判。
8. JSON 格式失败。
```

每个错误都记录：

```text
sample_id
category
agent_decision
human_decision
agent_finding
human_note
suspected_cause
fix_type
```

fix_type 枚举：

```text
prompt_update
category_rule_update
schema_update
preprocessing_update
manual_label_needed
model_limitation
```

迭代顺序：

```text
1. 先修 schema 和解析失败。
2. 再修 category_rules。
3. 再修 prompt。
4. 最后才考虑换模型或复杂视觉预处理。
```

### 第 15 步：扩展到全量批处理

全量前提：

```text
1. 种子集跑通。
2. 人工复核闭环跑通。
3. 结果 CSV 可用。
4. 明确失败样本召回稳定。
```

全量策略：

```text
1. 每个类别先跑 20 个。
2. 检查报告。
3. 每个类别再跑 100 个。
4. 最后跑全量。
5. 每批都保存独立 run_id。
```

推荐命名：

```text
runs/
  20260702_seed_30/
  20260703_head_key_chain_20/
  20260703_all_categories_100/
  20260704_full_review/
```

全量命令模板：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\supervise\collect_review_pairs.py `
  --dataset-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20 `
  --generated-root '.\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\generated_3d_no_rules\监修vlm数据' `
  --all-categories `
  --output .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\reports\supervision_review\latest\review_pairs.jsonl

.\.venv\Scripts\python.exe .\vlm\scripts\supervise\run_supervision_review.py `
  --pairs .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\reports\supervision_review\latest\review_pairs.jsonl `
  --output-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\reports\supervision_review\runs\20260704_full_review `
  --workers 1
```

## 9. 后续可升级方向

### 9.1 图像区域定位

第一版 finding 只写自然语言区域，例如：

```text
生成图背面头发区域
原图右侧角色后发区域
```

第二版可以增加：

```text
1. 自动切分三视图。
2. 给 front/side/back 各自截图。
3. finding 中保存 approximate bbox。
4. 报告中画红框。
```

### 9.2 自动三视图切割

对 21:9 横图可先用简单规则：

```text
left third: front
middle third: side
right third: back
```

但要注意：

```text
1. 有些图可能排版不是严格三等分。
2. 有些图有文字标签或边框。
3. 自动切割只能辅助，不要作为唯一依据。
```

### 9.3 与 RunningHub 生成闭环连接

等监修稳定后，才考虑：

```text
1. 对 rejected 样本生成 rerun_prompt_hint。
2. 把失败类型汇总给 prompt 迭代。
3. 为每个 category 生成负面约束补丁。
4. 仍然不自动重跑，先由人工确认。
```

### 9.4 监修面板

后续可做前端：

```text
1. 左侧原图。
2. 右侧生成图。
3. 中间/侧栏 findings。
4. 人工选择 approved/needs_revision/rejected。
5. 一键导出 CSV。
```

但第一版不要做，先保证监修判断质量。

## 10. 避免以往问题的开发约束

### 10.1 避免路径混乱

约束：

```text
1. 所有命令从 D:\索尼实习 运行。
2. 所有默认路径相对项目根目录。
3. reports 写入 reports/supervision_review。
4. 不把监修结果写入 generated_3d_no_rules。
5. 不使用旧 runninghub 目录假设，优先支持当前 监修vlm数据 目录。
```

### 10.2 避免覆盖现有数据

约束：

```text
1. 所有输出带 run_id。
2. 默认跳过已有 result.json。
3. 只有传 --force 才覆盖某次监修结果。
4. 不修改 sample_lists。
5. 不运行 assign_merchandise_categories.py，除非明确需要刷新分类。
```

### 10.3 避免 Agent 胡判

约束：

```text
1. 原图不可见的背面细节，不判错误，只标 uncertain。
2. atomic_rules 与图像冲突时，以图像为准。
3. 低置信度进入 human_review_required。
4. 每个 high/critical finding 必须写证据。
5. 不允许只说“细节不一致”，必须指出具体元素。
```

### 10.4 避免提示词越写越乱

约束：

```text
1. 原图抽取、生成图解析、对照监修分开 prompt。
2. 品类规则放 JSON，不全部塞进 prompt。
3. 每次 prompt 修改记录版本和原因。
4. prompt 不写单个样本的专属规则。
5. 用 seed_cases 验证 prompt 是否改善。
```

### 10.5 避免只看单图不看对照

约束：

```text
1. product_type 可以只看生成图。
2. identity_fidelity 必须看原图和生成图。
3. hallucination 必须确认原图没有该元素。
4. omission 必须确认原图有该元素。
5. 只看生成图不能判定身份缺失。
```

## 11. 推荐开发顺序总览

```text
阶段 1: 文档和规则
  1. failure_taxonomy.md
  2. seed_cases.jsonl
  3. category_rules.json
  4. prompt 初稿

阶段 2: 离线数据管线
  5. collect_review_pairs.py
  6. review_schemas.py
  7. report_writer.py

阶段 3: VLM 监修 MVP
  8. vlm_client.py
  9. run_supervision_review.py 单样本
  10. run_supervision_review.py 批量

阶段 4: 评测闭环
  11. review_summary.csv
  12. human_review_queue.csv
  13. analyze_human_feedback.py

阶段 5: 扩展
  14. 每类别 20 样本
  15. 每类别 100 样本
  16. 全量监修
```

## 12. 第一版完成标准

第一版可以认为完成，当满足：

```text
1. 能从当前 监修vlm数据 目录收集样本对。
2. 能对单样本输出结构化 result.json。
3. 能批量跑 seed_cases.jsonl。
4. 能生成 review_summary.csv 和 findings.csv。
5. 能把 high/critical 样本放入 human_review_queue.csv。
6. 能抓出 2027251 的长发/束发结构缺失问题。
7. 不会误把 3206142 这类可用样本直接判为严重失败。
8. 所有结果可追溯到原图路径、生成图路径、prompt 版本、规则版本。
```

## 13. 第二版完成标准

第二版可以认为完成，当满足：

```text
1. 每个品类至少有 50 个人工复核样本。
2. high_risk_recall >= 85%。
3. schema_success_rate >= 95%。
4. 人工复核 CSV 能反哺错误分析。
5. 可以输出每个品类的主要失败类型排行。
6. 可以稳定区分:
   - 可接受 Q 化
   - 身份元素缺失
   - 身份元素幻觉
   - 商品类型错误
   - 三视图不一致
```

## 14. 最小实施清单

如果只做最小可用版本，按这个清单执行：

```text
1. 新建 vlm/experiments/supervision/seed_cases.jsonl。
2. 新建 vlm/config/supervision/category_rules.json。
3. 新建 vlm/prompts/supervision 三个 prompt。
4. 写 collect_review_pairs.py。
5. 写 run_supervision_review.py。
6. 写 report_writer.py。
7. 跑 2027251 和 3206142。
8. 检查 result.json 是否符合预期。
9. 跑 30 个 seed cases。
10. 人工复核 high/rejected 样本。
```

第一版最关键的判断不是“Agent 看起来很聪明”，而是：

```text
它能不能稳定地把明显不该通过 IP 监修的图拦出来，并且说清楚为什么。
```
