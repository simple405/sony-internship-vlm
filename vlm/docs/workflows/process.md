# VLM 监修当前流程（压缩版）

更新日期：2026-07-27 +08:00

本文件用于节约后续上下文成本，只保留当前有效结论、关键路径、会议纪要和下一步。历史长流程已压缩。

## 1. 当前最高优先级规则

2026-07-08 会议纪要定义 **人工标注验收/修改/计费口径**，不替代生图 prompt 或 atomic_rules 生成的完整 IP 设计标准。生图和 atomic_rules 仍需覆盖角色身份、商品形态、关键配饰、服装结构、图案拓扑等设计质量要求。

当前乙方可修改/可计费项按以下口径执行：

1. **描述修改规则**：仅允许对预识别阶段已标注出的部位、装饰物等，针对其颜色、材质、形状三方面的明显错误进行修正，其他内容不予改动。
2. **左右方位标注标准**：所有任务中的“左”“右”判断，统一以标注员自身的观察视角为准，确保全流程标准一致。
3. **成对物品或身体部位标注要求**：对于成对出现的物品或部位，例如一双鞋、两条腿、两只犄角等，若原标注框仅覆盖其中一侧，则须补全另一侧标注框并添加相应描述。若两侧在外观上无任何差异，描述内容可完全相同；若存在差异，则需分别描述。若预识别阶段将成对部位合并为一个大的标注框，例如两条腿合为一框，同样需拆分为独立单框，并逐框独立描述。
4. **计费范围说明**：凡涉及描述修改或新增标注框的操作，均纳入修改计费范畴，按统一规则核算。

Agent 输出约束：必须区分 `billable_annotation_issues` 与 `design_quality_notes`。普通缺失细节和开放式描述补充不作为当前乙方主验收目标；如需保留观察，可进入设计质量备注或人工复核，不直接影响乙方计费/验收分数。

## 1b. 监修 Agent 架构（已统一定义）

```text
输入：2D 原图 + 商品设计图（由上游生图流程提供，不属于 agent 职责）
  ↓
Step 1: 元素提取 — 从 2D 原图自动生成 atomic_rules
        脚本: vlm/scripts/supervise/run_element_extraction.py
        模型: qwen3-vl-plus（当前首选）
  ↓
Step 2: VLM 审查 — 用 atomic_rules 对比商品设计图
        脚本: vlm/scripts/supervise/run_multicategory_supervision_review.py
        Prompt: vlm/prompts/supervision/qwen_prompt_v3_{category}.txt
  ↓
输出：结构化监修报告
        billable_annotation_issues（颜色/材质/形状错误、成对补框）
        design_quality_notes（设计质量观察，不计入主指标）
```

**关键约束：** atomic_rules 由 agent 内部从 2D 原图生成，不作为外部输入。生图链路（RunningHub、IC-Light）是上游流程，不是监修 agent 的组成部分。

## 2. 核心路径

```text
项目根目录: D:\索尼实习
数据集根目录: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20
生成三件套根目录: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated
试标数据集: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/multi_view试标数据集
人工标注说明: vlm/docs/supervision/stage1_annotation_instructions.md
CSV schema: vlm/docs/supervision/human_annotation_csv_schemas.md
Agent schema: vlm/config/supervision/supervision_agent_output_v3.schema.json
API 环境变量: vlm/config/api.env
集中路径常量: vlm/scripts/_paths.py
Claude Code 看图入口: vlm/scripts/supervise/qwen_vl_image_tool.py
```

当前工作流以 `generated/` 下每个样本文件夹中的三件套为输入资产：

```text
2d_original.*        # 2D 原图 / source reference
*_product.png        # 多视角生成图，例如 *_backpack.png、*_cake_roll.png、*_plush.png
atomic_rules.json    # 预识别阶段生成的原子规则 / 标注依据
```

如果实际文件名按品类变化，以样本配置中的 `source_image`、`multiview_image`、`atomic_rules` 三个字段为准。

Claude Code 不要直接 `Read` 图片文件；需要图片理解时使用：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.qwen_vl_image_tool `
  --model qwen-vl-max `
  --json `
  --prompt "请分析这张图中可见的角色/商品特征，输出用于监修的结构化 JSON。" `
  "path\to\image.png"
```

## 3. 当前有效产物

配置和 schema：

```text
vlm/config/supervision/supervision_agent_output_v3.schema.json
vlm/config/supervision/supervision_agent_output_v3.example.json
vlm/config/supervision/backpack_review_samples.json
vlm/config/supervision/head_key_chain_review_samples.json
vlm/config/supervision/cake_roll_review_samples.json
vlm/config/supervision/plush_review_samples.json
```

活跃 prompt：

```text
vlm/prompts/supervision/qwen_prompt_v3_backpack.txt
vlm/prompts/supervision/qwen_prompt_v3_head_key_chain.txt
vlm/prompts/supervision/qwen_prompt_v3_plush.txt
vlm/prompts/supervision/qwen_prompt_v3_cake_roll.txt
vlm/prompts/supervision/element_extraction_from_2d.txt
vlm/prompts/generation/runninghub/runninghub_g2_figurine_front_view_user_cn.txt  # 冻结的前视图提示词
```

核心脚本：

```text
vlm/scripts/supervise/run_backpack_supervision_review.py
vlm/scripts/supervise/run_multicategory_supervision_review.py
vlm/scripts/supervise/validate_human_annotations.py
vlm/scripts/supervise/create_human_annotation_templates.py
vlm/scripts/supervise/convert_annotation_xlsx_to_csv.py
vlm/scripts/supervise/align_human_findings_to_atomic_rules.py
vlm/scripts/supervise/build_verified_evaluation_gold.py
vlm/scripts/supervise/summarize_pre_gold_assets.py
vlm/scripts/supervise/run_element_extraction.py
vlm/scripts/supervise/evaluate_element_extraction.py
vlm/scripts/generate/runninghub_client.py         # RunningHub API 公共模块
vlm/scripts/generate/batch_front_view.py           # 前视图 PVC 手办批量生成（4 并发，支持 resume）
vlm/scripts/generate/smoke_test_front_view.py      # 单样本冒烟测试
```

## 4. 已知当前状态

```text
- v3 标注系统不新增 excluded；商品范围外身体部位仍按 invisible + correct 处理。
- atomic_rules 不是天然 gold：需要先审核 rule 本身，再评估生成质量和 Qwen review 质量。
- Qwen baseline 已能输出 v3 rule-level JSON。
- backpack 的 back view 是背包背板，不是角色背面；该语义已写入 prompt。
- head_key_chain / plush / cake_roll 已有品类视角语义 prompt。
- wrong material 已加入 schema、prompt 和本地校验常量。
- paired box completion 已作为人工标注验收问题类型保留。
- RunningHub 前视图 PVC 手办批量生成已完成：19/20 成功（1568×672），char_008 被内容审核拦截（errorCode 1501）。
- runninghub_client.py 已抽取为公共 API 模块，消除 ~150 行重复代码。
```

## 4b. 元素提取模型对比（2026-07-14）

评估集：20 样本 / 111 gold elements，使用 `evaluate_element_extraction.py` + DashScope text-embedding-v3。

| 模型 | Coverage | Conflicts | Unsupported Extra | 状态 |
|------|----------|-----------|-------------------|------|
| qwen3-vl-plus（基线） | 98.2% | 10 | 25 | 稳定，当前 API 首选 |
| qwen3-vl-32b-instruct | 98.2% | 14 | 21 | 稳定，coverage 持平 |
| qwen3-vl-30b-a3b-thinking | 94.6% | 21 | 26 | thinking 模式对结构化提取无益 |
| qwen3-vl-30b-a3b-instruct | N/A | N/A | N/A | DashScope 45% JSON 崩溃 |

关键结论：

```text
- qwen3-vl-plus 为闭源模型，无公开权重，不可本地部署。
- qwen3-vl-32b-instruct 开源可部署，coverage 与 plus 持平，int4 量化约需 22GB VRAM。
- qwen3-vl-30b-a3b-instruct 架构最优（MoE，总参数 30B，推理激活仅 3B），
  DashScope 的 JSON 崩溃是平台侧问题，本地用 vLLM guided_json 可解决；
  本地部署 ≤30B 场景的首选候选。
- qwen3-vl-7b DashScope 无托管（404），可作为本地保守方案。
- thinking 模式对结构化提取任务有害，不要使用 -thinking 后缀的模型。
- 所有模型共同漏掉 char_013 的"胡须"和"袜子"——提示词无面部毛发/腿部叠层规则，
  待新数据确认后再考虑修改（避免过拟合20样本评估集）。
```

脚本与数据路径：

```text
提取脚本:  vlm/scripts/supervise/run_element_extraction.py
评估脚本:  vlm/scripts/supervise/evaluate_element_extraction.py
提示词:    vlm/prompts/supervision/element_extraction_from_2d.txt
Gold 数据: vlm/data/SN_6期动漫数据标注/
结果目录:  vlm/data/element_extraction_results/          ← qwen3-vl-plus 基线
           vlm/data/element_extraction_results_32b/      ← qwen3-vl-32b-instruct
           vlm/data/element_extraction_results_30b_thinking/ ← qwen3-vl-30b-a3b-thinking
```

## 5. 人工标注 + 评估工作流

当前三段式流程：

```text
generated 三件套: 2D 原图 + multi_view 生成图 + atomic_rules
  -> Stage 1: 人工标注验收发现
       只记录会议纪要允许的可修改/可计费项：颜色、材质、形状错误，成对补框/拆框。
  -> Stage 2: atomic_rules 正误审核
       判断每条 rule 是否真实描述 2D 图。
  -> Stage 3: 候选语义对齐 + 人工复核
       将人工发现与 atomic_rules 建立可复核桥梁。
  -> Stage 4: 低颗粒度验收评估
       只用 acceptance gold 评估 billable_annotation_issues。
       design_quality_notes 单独保留，不纳入当前主 precision / recall / F1。
```

颗粒度变化后的指标边界：

```text
主指标：
  acceptance_precision
  acceptance_recall
  acceptance_f1
  billable_issue_recall

主指标只统计：
  wrong color
  wrong material
  wrong shape
  paired box completion

不进入主指标：
  未预识别普通细节缺失
  开放式描述补充
  身份元素缺失/幻觉
  商品类型错误
  三视图不一致

这些设计质量问题可进入 design_quality_notes 或 human_review_required，后续需要甲方专家 gold 才能评估。
```

标准样本文件夹目标结构：

```text
{category}/{sample_id}/
├── 2d_original.jpg
├── multiview_design.png
├── atomic_rules.json
├── qwen_supervision_result.csv
├── qwen_supervision_result_summary.json
├── human_visual_findings.csv
├── atomic_rule_audit.csv
├── human_to_atomic_rule_mapping_candidates.csv
├── mapping_review_queue.csv
└── verified_evaluation_gold.csv
```

## 6. 下一步

### 6a. 监修 Agent 端到端串联（最高优先级）

两个核心步骤的脚本均已就绪，缺少统一入口：

```text
目标：单命令完成 2D 原图 + 商品设计图 → 监修报告全流程

待完成：
  1. 写 vlm/scripts/supervise/run_supervision_agent.py
     - 接收 --source（2D 原图）和 --product（商品设计图）两个参数
     - 内部调用 run_element_extraction → 生成 atomic_rules
     - 再调用 run_multicategory_supervision_review → 输出监修报告
     - 输出：billable_annotation_issues + design_quality_notes JSON

  2. 用现有 20 个样本端到端跑一次，验证两步串联无断点

  3. 扩充 evaluation gold（新数据批次 40-50 张到手后）验证 agent 精度
     - 主指标：acceptance_precision / acceptance_recall / acceptance_f1 / billable_issue_recall
```

### 6b. 生图链路（上游，与监修 agent 无关）

RunningHub 批量生图已完成 19/20，生图链路属于监修 agent 的上游输入来源，不是 agent 本身的功能。相关后续工作（batch_review、char_008 重试、IC-Light 对比）独立推进，不阻塞监修 agent 开发。完整计划见 `.claude/handoffs/PLAN_runninghub-batch-complete_consolidated_2026-07-24.md`。

### 6b. 新元素提取批次（40-50 张图 + 人工标注，预计 2026-07-15 到手）

新数据形式：源图 + 人工标注 element 名称与描述（作为 gold）。

```text
1. 将新图片和人工标注整理到 vlm/data/SN_新批次/ 目录，
   每张图一个子文件夹，gold JSON 与现有 vlm/data/SN_6期动漫数据标注/ 格式一致：
   {"elements": [{"name": "...", "value": "..."}, ...]}

2. 在新图上跑元素提取（--workers 根据 DashScope QPS 限制调整，默认 6）：
   python -m vlm.scripts.supervise.run_element_extraction \
     --model qwen3-vl-plus \
     --output-root vlm/data/element_extraction_results_new_batch \
     --gold-root vlm/data/SN_新批次

3. 跑评估，与 6期 baseline 对比：
   python -m vlm.scripts.supervise.evaluate_element_extraction \
     --pred-root vlm/data/element_extraction_results_new_batch \
     --gold-root vlm/data/SN_新批次 \
     --report-path vlm/data/element_extraction_results_new_batch/evaluation_report.json

4. 若新 gold 中"胡须"/"袜子"类细节在多个样本出现且仍被漏掉，
   再考虑修改 vlm/prompts/supervision/element_extraction_from_2d.txt。
```

### 6b. 监修验收工作流（如有 .xlsx/.csv 人工验收标注文件）

```text
1. 拿到 .xlsx 或 .csv。
2. 用 convert_annotation_xlsx_to_csv.py 转标准 CSV（如需要）。
3. 用 validate_human_annotations.py 校验列名、状态值、sample_id、rule_id。
4. 若发现新列名或新状态值，只做最小 alias/枚举补充。
5. 用 align_human_findings_to_atomic_rules.py 做候选对齐。
6. 用 build_verified_evaluation_gold.py 生成 verified gold。
7. 后续再开发/运行 compare_predictions.py 做三方对比。
```

RunningHub 补图不是当前主线；如恢复生成，遵守“不覆盖已有图、跳过 blocked 样本、先查进程”的旧规则。
