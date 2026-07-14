# IP 周边监修 Agent 开发规则（压缩版）

更新日期：2026-07-08 +08:00

本文件是后续开发的短上下文锚点。历史长版方案已压缩，当前优先保留 2026-07-08 会议纪要、分层原则、输出契约和下一步。

## 1. 最高优先级：2026-07-08 标注验收口径

以下内容定义的是 **乙方人工标注的验收、修改、计费口径**，不是生图 prompt 或 atomic_rules 生成的完整设计标准。

### 1.1 描述修改规则

仅允许对预识别阶段已标注出的部位、装饰物等，针对其 **颜色、材质、形状** 三方面的明显错误进行修正，其他内容不予改动。

执行含义：

```text
允许进入乙方可修改/可计费项：
- wrong color
- wrong material
- wrong shape

不作为当前乙方主验收失败项：
- 未被预识别标出的普通细节缺失
- 开放式细节补充
- 与颜色/材质/形状无关的描述扩写
```

### 1.2 左右方位标注标准

所有任务中的“左”“右”判断，统一以标注员自身的观察视角为准，确保全流程标准一致。

Agent 输出左右方位时也使用观察者视角，不使用角色自身左右。

### 1.3 成对物品或身体部位标注要求

对于成对出现的物品或部位，例如一双鞋、两条腿、两只犄角等：

```text
1. 若原标注框仅覆盖其中一侧，须补全另一侧标注框并添加相应描述。
2. 若两侧在外观上无任何差异，描述内容可完全相同。
3. 若两侧存在差异，则需分别描述。
4. 若预识别阶段将成对部位合并为一个大的标注框，例如两条腿合为一框，须拆分为独立单框，并逐框独立描述。
```

Agent/CSV 中使用：`paired box completion`。

### 1.4 计费范围说明

凡涉及描述修改或新增标注框的操作，均纳入修改计费范畴，按统一规则核算。

Agent 报告必须区分：

```text
description_correction: 颜色/材质/形状描述修改
paired_box_completion: 成对部位补框或拆框
```

## 2. 分层原则：验收标准不等于生图标准

```text
generation/design layer:
  生图和 atomic_rules 仍应保留 IP 关键身份特征，包括发型、配饰、服装结构、图案、道具、商品品类约束。
  不能因为乙方人工修改范围较窄，就降低生图或 atomic_rules 的特征覆盖要求。

annotation acceptance layer:
  用于判断乙方标注员当前应该改什么、哪些操作计入修改量。
  本层采用 2026-07-08 会议纪要的收窄口径。

supervision agent layer:
  Agent 可以保留设计质量发现，但输出必须分 lane。
```

建议输出分层：

```json
{
  "billable_annotation_issues": [],
  "design_quality_notes": [],
  "human_review_required": false
}
```

解释：

```text
billable_annotation_issues:
  当前乙方可修改/可计费问题，只放 wrong color / wrong material / wrong shape / paired box completion。

design_quality_notes:
  生图或 IP 保真风险，例如关键配饰缺失、身份幻觉、商品类型错误、三视图不一致。
  这些可以影响内部设计质量判断，但不要直接混入乙方当前计费口径。

human_review_required:
  规则冲突、低置信度、预识别缺失但设计风险较高时进入人工复核。
```

## 3. 当前数据和路径

```text
项目根目录: D:\索尼实习
主工作区: vlm/
生成三件套根目录: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated
当前流程文档: vlm/docs/workflows/process.md
人工标注说明: vlm/docs/supervision/stage1_annotation_instructions.md
CSV schema: vlm/docs/supervision/human_annotation_csv_schemas.md
Agent 输出 schema: vlm/config/supervision/supervision_agent_output_v3.schema.json
API 环境变量: vlm/config/api.env
Claude Code 看图入口: vlm/scripts/supervise/qwen_vl_image_tool.py
```

重要约束：Claude Code 不直接 Read 图片文件；需要看图时用 `qwen_vl_image_tool.py` 返回文本/JSON。

当前算法输入仍使用 `generated/` 下每个样本文件夹里的三件套：

```text
source_image / 2d_original
multiview_image / generated product image
atomic_rules.json
```

三件套是输入资产，不因金标颗粒度变低而删除或弱化。

## 4. 颗粒度变化后的算法/评估调整

当前乙方 gold 只有会议纪要颗粒度时，算法拆成两条 lane：

```text
annotation_acceptance lane:
  使用乙方 gold 评估。
  只输出/统计 billable_annotation_issues。
  支持 wrong color / wrong material / wrong shape / paired box completion。

design_quality lane:
  继续保留 agent 对 IP 保真、生图质量、商品结构的观察。
  输出到 design_quality_notes 或 human_review_required。
  不用乙方 gold 计算主 precision / recall / F1，避免把 gold 未覆盖的问题误算成 false positive。
```

主指标：

```text
acceptance_precision
acceptance_recall
acceptance_f1
billable_issue_recall
```

暂不作为主指标：

```text
identity_missing recall
identity_hallucination recall
product_type_error recall
three_view_consistency accuracy
open-ended missing/extra detail recall
```

若后续要评估完整监修能力，需要另建少量甲方专家 gold，不要用当前乙方 gold 直接替代。

## 5. 当前实现状态

已保留/同步：

```text
- v3 schema 支持 wrong material。
- human_visual_findings.csv 支持 paired box completion。
- 活跃 Qwen prompt 支持 wrong color / wrong material / wrong shape / extra。
- 本地校验脚本已接受 wrong material。
- 当前乙方验收口径已写入 process.md 与 stage1_annotation_instructions.md。
```

相关脚本：

```text
vlm/scripts/supervise/validate_human_annotations.py
vlm/scripts/supervise/build_annotation_products.py
vlm/scripts/supervise/run_backpack_supervision_review.py
vlm/scripts/supervise/run_multicategory_supervision_review.py
vlm/scripts/supervise/create_human_annotation_templates.py
vlm/scripts/supervise/convert_annotation_xlsx_to_csv.py
vlm/scripts/supervise/align_human_findings_to_atomic_rules.py
vlm/scripts/supervise/build_verified_evaluation_gold.py
```

## 6. 后续开发规则

1. 不把乙方验收范围当成生图/atomic_rules 的上限。
2. 所有 agent 结果先分 lane，再决定是否计费、是否进入设计质量风险、是否人工复核。
3. `missing` / `extra` 保留为历史兼容或诊断值；默认不要作为当前乙方主验收失败项。
4. 成对部位漏框/合框是会议纪要明确要求，必须保留为可计费问题。
5. 左右方向一律以标注员观察视角输出。
6. 不自动覆盖生成图，不自动重跑 RunningHub，不删除用户数据。

## 7. 推荐下一步

```text
1. 若乙方回传 xlsx/csv，先用 validate_human_annotations.py 校验。
2. 检查是否存在新列名或新状态值；只做最小 alias/枚举补充。
3. 将人工结果拆分为：billable_annotation_issues / design_quality_notes / human_review_required。
4. 再决定是否更新 compare_predictions.py 或 gold 构建逻辑。
```
