# Handoff: VLM 监修 Agent 差距分析

**Date:** 2026-07-24
**Status:** IN PROGRESS
**Bead(s):** none
**Epic:** Anime IP merchandise supervision VLM pipeline
**Chain:** `standalone-07527e3e` seq `1`
**Parent:** none — first in chain

---

## The Goal

用户想了解当前项目距离"最终要完成的 VLM 检修（监修）Agent"还有多远。会话聚焦于梳理所有 handoff 文档和项目规划文件中关于监修 Agent 的描述，找到"当前实际完成状态"与"最终目标"之间的差距。

---

## Where We Are

### 发现的文档结构

- **`vlm/docs/workflows/supervision_agent_development_plan.md`**（2026-07-08）— 监修 Agent 开发规则压缩版，定义了三层架构和输出契约，但不是执行路线图
- **`vlm/docs/workflows/process.md`**（2026-07-14）— 当前 VLM 监修流程，包含人工标注 + 评估工作流的四段式描述
- **近期 5 个 handoff**（2026-07-22 ~ 07-24）全部聚焦于基础设施：RunningHub 生图、IC-Light 推理、代码重构、元素提取优化、批量评估
- **早期 handoff**（2026-07-06 ~ 07-08）涉及 v3 schema 固化、多品类 prompt 编写、mock gold 管线

### 最终 Agent 的目标定义（来自 development plan）

- **输入**：2D 原图 + 多视角生成图 + atomic_rules.json
- **输出**：三层 lane 分离的 JSON
  - `billable_annotation_issues` — wrong color / wrong material / wrong shape / paired box completion
  - `design_quality_notes` — IP 保真风险、身份元素缺失/幻觉、商品类型错误、三视图不一致
  - `human_review_required` — 规则冲突、低置信度、高设计风险时的自动标记
- **主指标**：acceptance_precision / acceptance_recall / acceptance_f1 / billable_issue_recall

### 已完成的组件（16 个独立脚本）

| 组件 | 脚本 | 状态 |
|------|------|------|
| 元素提取（2D → elements） | `run_element_extraction.py` | ✅ qwen3-vl-plus 基线 98.2% coverage |
| 多品类 Qwen VL 审核 | `run_multicategory_supervision_review.py` | ✅ backpack/钥匙扣/蛋糕卷/毛绒 4 品类 |
| 本地 ComfyUI 结果审核 | `review_local_comfyui_output.py` | ✅ 6-gate + 5-element + identity 评分 |
| RunningHub 批量审核 | `batch_review_runninghub.py` | ✅ 20/20 样本完成 |
| 人工标注校验 | `validate_human_annotations.py` | ✅ |
| 人工标注 → atomic_rules 对齐 | `align_human_findings_to_atomic_rules.py` | ✅ token-based 匹配 |
| Verified gold 构建 | `build_verified_evaluation_gold.py` | ✅ |
| 预测 vs gold 对比 | `compare_predictions.py` | ✅ Lane A/B 分离逻辑已实现 |
| V3 schema | `supervision_agent_output_v3.schema.json` | ✅ wrong material 已加入 |
| 人工标注说明 | `stage1_annotation_instructions.md` | ✅ 中文 |
| 标注模板创建 | `create_human_annotation_templates.py` | ✅ |
| xlsx → csv 转换 | `convert_annotation_xlsx_to_csv.py` | ✅ |
| 颜色族后处理 | `postprocess_color_family_verdicts.py` | ✅ |
| 标注产物构建 | `build_annotation_products.py` | ✅ |
| 预 gold 资产汇总 | `summarize_pre_gold_assets.py` | ✅ |
| 语义相似度评分 | `embedding_scorer.py` | ✅ |

---

## What We Tried (Chronological)

### 1. 扫描所有 handoff 文档寻找监修 Agent 描述

- 假设：handoff 文档中应该存在"最终要完成的 VLM 检修 Agent"的描述
- 方法：读取 4 个最新 handoff + 2 个参考文档，全局 grep 关键词
- 读取了 `HANDOFF_runninghub-eval-refactor_2026-07-24.md`（215 行）— Where We're Going 的 6 项全是评估调整、失败样本处理、品类扩展、代码提交、修复和 IC-Light 归档
- 读取了 `HANDOFF_runninghub-batch-complete_consolidated_2026-07-24.md`（363 行）— Where We're Going 的 7 项全是生图评估、char_008 修复、IC-Light 推理、API 重构、env 统一
- 读取了 `HANDOFF_V3_SCHEMA_AND_SKILLS_07_06_13_45.md`（188 行）— 提到 `supervision_agent_development_plan.md`（"~2000 行详细计划"）但该文档已被压缩为当前版本
- 读取了 `HANDOFF_VLM_SUPERVISION_MULTI_CATEGORY_07_06_15_20.md`（60 行）— 多品类语义规则配置
- 全局 grep 了 `/home/intern/jsy/.claude/handoffs/` 和 `vlm/plans/handoffs/` 中所有"检修""监修 agent""supervision agent""最终""终极"关键词
- 结果：**没有任何 handoff 将"构建最终监修 Agent"列为下一步最高优先级**。近期 handoff 的 Where We're Going 全部聚焦于 RunningHub 生图质量评估（19/20）、IC-Light 推理对比、API 代码重构、品类扩展。最早期的 handoff 涉及 v3 schema 固化和多品类 prompt 编写——这些是最终 Agent 的零件，但从未被组装

### 2. 定位最终目标的唯一定义文档

- `supervision_agent_development_plan.md`（186 行）标题为"IP 周边监修 Agent 开发规则（压缩版）"
- 它明确标注"本文件是后续开发的短上下文锚点。历史长版方案已压缩"——说明曾经有更详细的方案（被早期 handoff 引用为 ~2000 行），但当前只保留了压缩后的规则/原则
- 文档核心内容：
  - 2026-07-08 会议纪要的验收口径（仅允许修改 color/material/shape，左右方位以观察者为准，成对部位补框/拆框）
  - 分层原则：generation layer ≠ annotation acceptance layer ≠ supervision agent layer
  - 输出契约：`{ billable_annotation_issues, design_quality_notes, human_review_required }`
  - 指标边界：主指标只统计 acceptance_precision/recall/f1，设计质量问题不纳入主指标
- 文档缺少的内容：Agent 入口定义（类/函数签名）、集成架构（脚本间数据流）、分阶段里程碑、从"当前工具箱"到"端到端 Agent"的迁移步骤

### 3. 分析当前脚本生态 vs 最终目标

- 列出 `vlm/scripts/supervise/` 下 16 个 Python 文件（不含 `__init__.py`），逐一确认功能边界
- 列出 `vlm/prompts/supervision/` 下 5 个 prompt 文件 → 发现 PVC 手办品类 prompt 缺失
- 用 `grep "def main\|class.*Agent\|def run_agent"` 扫描了所有脚本的入口点——每个脚本都有独立的 `main()` 和 argparse CLI，没有共享的 Agent 基类
- 检查了 `review_local_comfyui_output.py` 的核心函数：`build_review_prompt()`, `call_local_ollama()`, `extract_json()`, `normalize_review()` — 这些是离"Agent 核心循环"最近的逻辑，但被硬编码为本地 ComfyUI 结果的审核，不是通用品类审核
- 检查了 `compare_predictions.py` 的 Lane 分离逻辑：`ACCEPTANCE_ISSUE_TYPES = {wrong color, wrong material, wrong shape, paired box completion}`，Lane A/B 分离已代码化但依赖外部 CSV 输入
- 结论：当前有完整的**工具箱**（16 个独立 Python 脚本 + 5 个 prompt 模板 + v3 schema），但没有 `SupervisionAgent` 类或 `run_supervision_agent.py` 把它们串成端到端流水线

### 4. 对话内输出差距分析（用户明确要求）

- 用户说"你直接输出内容给我，而不是文档"，确认只做对话内分析
- 输出了结构化的 8 项 Gap 清单，按优先级排列
- 给出了拼图示意图（ASCII art）展示最终 Agent 的组件关系

---

## Code Analysis

### `review_local_comfyui_output.py` — 当前最接近"Agent 核心循环"的脚本

```
核心流程:
1. annotation JSON → build_review_prompt(annotation) → prompt string (6-gate + 5-element + identity)
2. [source.png, generated.png] → call_local_ollama(prompt, images) → raw text
3. extract_json(text) → raw dict
4. normalize_review(raw, annotation, threshold) → standardized review

关键函数签名:
- build_review_prompt(annotation: dict) → str
- call_local_ollama(prompt: str, images: list[Path], base_url: str, model: str, timeout: int) → str
- extract_json(text: str) → dict[str, Any]
- normalize_review(raw: dict, annotation: dict, identity_threshold: float = 0.85) → dict

关键常量:
- Ollama model: "qwen36-vl:latest", base URL: "http://127.0.0.1:11434"
- identity_threshold: 0.85, timeout: 300s
- 输出: 6-gate (front_view/back_view/side_view/white_bg/no_watermark/no_red_frame)
       + 5-element (correct/wrong_color/wrong_material/wrong_shape/extra/missing)
       + identity_match (0-1) + visual_quality (0-1)
```

此脚本的问题是：(1) 硬编码为本地 ComfyUI 路径，不是通用品类审核；(2) 不输出分 lane 的 design_quality_notes；(3) 不支持作为库被其他脚本调用（argparse 入口，非函数 API）

### `compare_predictions.py` — Lane A/B 分离的核心逻辑

```python
ACCEPTANCE_ISSUE_TYPES = {
    "wrong color", "wrong material", "wrong shape", "paired box completion",
}

def load_predictions(sample_dir: Path) -> List[Dict[str, Any]]:
    """加载 Qwen 预测结果"""
    pred_csv = sample_dir / "qwen_prediction_flattened_v3.csv"
    ...
```

- Lane A (annotation_acceptance): 只统计 ACCEPTANCE_ISSUE_TYPES 中的问题
- Lane B (design_quality): 保留但不纳入主指标
- 已经实现了 event-level 匹配逻辑和 precision/recall/f1 计算
- 但依赖外部 CSV 输入（`qwen_prediction_flattened_v3.csv` + `verified_evaluation_gold.csv`），没有自动触发上游脚本

### `run_multicategory_supervision_review.py` — 多品类审核的统一入口（860 行）

- 支持多品类配置（backpack/head_key_chain/cake_roll/plush）
- 通过品类级别的 config JSON 和 prompt 文件区分不同品类
- 输出：每条 rule 的 view_status + verdict + confidence + reason + evidence
- 缺少 PVC figurine 品类配置和 prompt

### 脚本间数据流（当前手动状态）

```
run_element_extraction.py                     # → atomic_rules.json (手动传递)
  → run_multicategory_supervision_review.py   # → qwen_prediction_flattened_v3.csv (手动传递)
    → compare_predictions.py                  # → acceptance F1 分数
```

三个步骤之间没有任何自动衔接——没有统一的 config 文件、没有 pipeline runner、没有共享的 sample manifest。

---

## Key Decisions

- **本次会话定位为"差距发现"而非"执行"**：用户明确只要求查看和分析，不需要创建新文档。差距分析以对话内容输出，不写入文件
- **差距分析的 8 个缺口按依赖关系排序**：从阻断性的"没有统一入口"开始，到品类级别的"PVC 视角语义规则缺失"结束
- **不把现有 handoff 中的"下一步"当成最终目标**：近期 handoff 的 Where We're Going 全是基础设施优化（调整 identity 阈值、处理 char_011/020、扩展品类、commit 代码），这些都是有价值的，但都不是"构建最终监修 Agent"

---

## Evidence & Data

### 当前监修 prompt 覆盖情况

| 品类 | Prompt 文件 | 监修审核脚本 | 生图链路 |
|------|------------|-------------|---------|
| Backpack | `qwen_prompt_v3_backpack.txt` | `run_backpack_supervision_review.py` | RunningHub 全品类编排 |
| Head Key Chain | `qwen_prompt_v3_head_key_chain.txt` | `run_multicategory_supervision_review.py` | RunningHub G-2 |
| Cake Roll | `qwen_prompt_v3_cake_roll.txt` | `run_multicategory_supervision_review.py` | — |
| Plush | `qwen_prompt_v3_plush.txt` | `run_multicategory_supervision_review.py` | — |
| **PVC Figurine** | **缺失** | 仅有 `review_local_comfyui_output.py`（通用 6-gate 逻辑） | RunningHub 20 张已生成 |

### Gap 清单（8 项）

1. **没有统一 Agent 入口** — 16 个脚本各自独立，无 `SupervisionAgent` 类或 `run_supervision_agent.py`
2. **PVC 手办监修 prompt 缺失** — 4 个品类有品类视角 prompt，但已批量生成的 PVC 手办没有
3. **元素提取未接入审核流水线** — `run_element_extraction.py` → atomic_rules 需手动传递给审核脚本
4. **`design_quality_notes` lane 未实现** — `compare_predictions.py` 有 Lane B 预留但审核脚本不产生相应输出
5. **`human_review_required` 决策逻辑不存在** — 无自动 triage 代码
6. **端到端评测指标未跑通** — `compare_predictions.py` 有计算逻辑但无自动化流程和真实数据
7. **atomic_rules 质量审核未集成** — Stage 2 的 rule audit 没有独立脚本接入 Agent 流程
8. **PVC figurine 品类视角语义规则缺失** — 无文档定义 PVC 手办的 front/side/back 语义

### 参考文档路径

```
监修 Agent 开发规则: vlm/docs/workflows/supervision_agent_development_plan.md
当前流程文档:       vlm/docs/workflows/process.md
V3 schema:          vlm/config/supervision/supervision_agent_output_v3.schema.json
元素提取结果:        vlm/data/element_extraction_results/ (qwen3-vl-plus 基线)
                    vlm/data/element_extraction_results_32b/ (qwen3-vl-32b)
RunningHub 批量:    vlm/data/smoke_test/batch_review_summary.json
```

---

## Files Changed

本会话为纯分析会话，无文件修改。

### Read (Reference)

- `.claude/handoffs/HANDOFF_runninghub-eval-refactor_2026-07-24.md` — 最新 handoff（RunningHub 评估 + IC-Light + 重构）
- `.claude/handoffs/HANDOFF_runninghub-batch-complete_consolidated_2026-07-24.md` — RunningHub 20 张批量完成
- `.claude/handoffs/HANDOFF_V3_SCHEMA_AND_SKILLS_07_06_13_45.md` — v3 schema + skills 安装
- `.claude/handoffs/HANDOFF_VLM_SUPERVISION_MULTI_CATEGORY_07_06_15_20.md` — 多品类视角语义
- `.claude/handoffs/HANDOFF_MOCK_GOLD_AND_QWEN_QUOTA_07_07_13_15.md` — mock gold 闭环
- `vlm/docs/workflows/supervision_agent_development_plan.md` — 监修 Agent 开发规则
- `vlm/docs/workflows/process.md` — 当前流程文档
- `vlm/scripts/supervise/` 目录 — 全部 16 个脚本列表
- `vlm/prompts/supervision/` 目录 — 全部 5 个 prompt 文件列表
- `vlm/scripts/supervise/review_local_comfyui_output.py` — 通用审核脚本（前 60 行）
- `vlm/scripts/supervise/compare_predictions.py` — Lane A/B 对比逻辑（前 30 行）

---

## User Feedback & Preferences

- **"查看一下当前的handoff文档，里面有没有我最终要完成的vlm检修agent的相关描述"** — 用户关心的是最终目标在文档中的体现程度
- **"你直接输出内容给我，而不是文档"** — 偏好对话内完成分析，不要额外创建文件（本次 handoff 本身除外）
- 用户对当前进展有清晰的全局意识——知道有生成链路、评估链路、人工标注管线，但在追问"这些拼起来离最终 Agent 还差什么"

---

## Where We're Going

### 最高优先级
1. **定义 Agent 的统一入口** — 设计 `SupervisionAgent` 类或 `run_supervision_agent.py`，明确输入（2D 原图 + 生成图 + atomic_rules）→ 输出（三层 lane JSON）的数据流
2. **编写 PVC 手办监修 prompt** — 参考现有 4 个品类的 prompt 结构，为 PVC figurine 编写包含视角语义的 `qwen_prompt_v3_figurine.txt`
3. **串联元素提取 → 审核流水线** — 让 `run_element_extraction.py` 的输出自动成为审核脚本的输入

### 次要
4. **实现 design_quality_notes lane** — 在审核 prompt 中增加身份元素/商品类型/三视图一致性的判断指令
5. **实现 human_review_required 决策** — 基于置信度阈值 + 规则冲突检测的自动 triage
6. **跑通端到端评测** — 在真实数据上计算 acceptance_precision/recall/f1

---

## Risks & Blockers

- **QWEN_API_KEY 仍是占位符** — `vlm/config/api.env` 中 `QWEN_API_KEY=your_qwen_api_key_here`，所有 VL 评估依赖本地 Ollama `qwen36-vl:latest`，无法使用 DashScope 云端模型
- **企业代理拦截 localhost** — Ollama 调用前必须 unset 代理变量，这是已知但烦人的环境问题
- **Python 3.8** — 不支持 PEP 604 联合类型语法，所有新代码需 `Optional[X]` + `from __future__ import annotations`

---

## Open Questions

- [ ] PVC 手办监修是否需要三视图（front/side/back），还是当前仅有前视图即可？
- [ ] 是否需要先完成 PVC 手办的监修 prompt 和端到端评测，再扩展到其他品类？
- [ ] 人工标注的乙方团队何时回传真实验收数据（用于计算 acceptance F1）？
- [ ] 元素提取的 40-50 张新批次（预计 2026-07-15 到手）是否已经到达？

---

## Quick Start for Next Session

```bash
# ── 理解最终目标 ──
cat /home/intern/jsy/vlm/docs/workflows/supervision_agent_development_plan.md

# ── 理解当前流程 ──
cat /home/intern/jsy/vlm/docs/workflows/process.md

# ── 理解差距 ──
cat /home/intern/jsy/.claude/handoffs/HANDOFF_vlm-supervision-agent-gap-analysis_2026-07-24.md

# ── 查看现有监修脚本全貌 ──
ls -la /home/intern/jsy/vlm/scripts/supervise/

# ── 查看现有监修 prompt ──
ls /home/intern/jsy/vlm/prompts/supervision/

# ── 查看 V3 schema ──
cat /home/intern/jsy/vlm/config/supervision/supervision_agent_output_v3.schema.json | python3 -m json.tool | head -80

# ── 查看 RunningHub 批量评估结果 ──
cat /home/intern/jsy/vlm/data/smoke_test/batch_review_summary.json | python3 -m json.tool | head -50

# ── 查看元素提取基线结果 ──
cat /home/intern/jsy/vlm/data/element_extraction_results/evaluation_report.json 2>/dev/null | python3 -m json.tool | head -50

# Next action
# 从 Gap 1 开始：设计并实现统一的 SupervisionAgent 入口，串联元素提取 → 品类审核 → 分层输出
```
