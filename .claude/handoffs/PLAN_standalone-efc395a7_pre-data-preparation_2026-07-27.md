# Plan: 监修 Agent 无标准数据前的准备与优化工作

**Date:** 2026-07-27
**Status:** PLANNED
**Bead(s):** none
**Epic:** VLM 监修 Agent
**Chain:** `standalone-efc395a7` seq `1`
**Context:** See `HANDOFF_standalone-efc395a7_pre-data-preparation_2026-07-27.md` for session data, test results, and prior approaches.

---

## Problem Statement

监修 VLM agent 的端到端 pipeline (`run_supervision_agent.py`) 已在 Windows 上完成开发并通过 20 样本批量验证，但 Linux 服务器上从未运行过。用户暂时无法获得大体量标准格式数据（含 2D 原图 + 商品设计图 + 人工标注 gold），需要在等待数据期间推进不依赖新数据的工作。当前 Linux 服务器上有 SN_6_3D_dataset（34 个角色，其中 20 个含 front_view 产品图）、完整的 prompt 体系（6 品类）、和已实现的评估框架，但 pipeline 从未在 Linux 上验证、元素提取从未在 SN_6_3D 上批量运行、已知 bug 未修复。

## Key Findings

1. **`run_supervision_agent.py` 是最高优先级但未在 Linux 验证** — 上次在 Windows 批量跑完 20 样本，Linux 上 `vlm/tmp/supervision_agent_output/` 目录不存在 → 驱动 Phase 1
2. **34 个角色中仅 20 个有 front_view** — char_021~034 只能跑元素提取（Step 1），不能跑完整端到端，但刚好可扩大元素提取评估样本量 → 驱动 Phase 2
3. **元素提取评估框架已就绪但从未在 SN_6_3D 上运行** — `evaluate_element_extraction.py` 需要 gold JSON（`char_XXX.json` 已存在），可立即建立 20~34 样本 baseline → 驱动 Phase 2
4. **known bug: `overall_decision` 为空字符串** — 根因和修复方案已在 prior handoff 中记录，修复简单（从 `qwen_prediction_v3.json` 读取而非从 `review_result` 读取）→ 驱动 Phase 3
5. **元素提取 prompt 有已知盲区** — 所有模型共同漏掉"胡须"（面部毛发）和"袜子"（腿部叠层），prompt 不含这些维度的提取指令 → 驱动 Phase 4
6. **本地 vLLM 部署方案已有候选模型** — qwen3-vl-30b-a3b-instruct（MoE, 3B 激活, int4 ~22GB VRAM）+ guided_json 可解决 DashScope JSON 崩溃问题 → 驱动 Phase 5

## Anti-Goals (What NOT To Do)

- **不要重新设计 pipeline 架构** — `run_supervision_agent.py` 的架构已经过 dry-run 和 20 样本真实 API 验证，只需在 Linux 上跑通，不需要重构
- **不要修改 side/back 的 invisible+correct 策略** — 这是上游输入决定的（单张 front_view），不是 agent 的问题；等上游提供多视角图后再改
- **不要用 thinking 模式模型做元素提取** — 已有证据表明 thinking 对结构化提取有害（94.6% vs 98.2% coverage）
- **不要在没有 GPU 的情况下尝试本地部署** — qwen3-vl-32b 需要 ~22GB VRAM，先确认资源再动手

## Plan

### Phase 1: Linux 上跑通端到端 Pipeline

**Goal:** 在 Linux 服务器上验证 `run_supervision_agent.py` 的完整 API 调用链路正常，产出至少 1 个样本的完整监修报告。

**Why this approach:** Pipeline 代码已验证过逻辑正确性（dry-run + Windows 20 样本），Linux 验证的关键是 API 连通性和路径兼容性。从单样本开始可快速定位环境问题（api.env 缺失、Python 依赖、路径分隔符等）。

- 验证 `vlm/config/api.env` 存在且 `QWEN_API_KEY` 有效
- 检查 Python 依赖：`dashscope`、`requests` 等是否安装
- 用 char_001 跑 `--dry-run` 先确认参数链路无语法错误
- 跑 char_001 真实 API 调用（`--timeout 120`，与 Windows 上次参数一致）
- 检查输出：`agent_summary.json` 是否生成、`qwen_prediction_v3.json` 格式是否完整
- 如果 API 调用失败，检查网络、key 有效性、模型名称（Linux 上可能需用 `qwen3-vl-plus` 而非 `qwen3.7-plus`）
- char_001 通过后，批量跑 char_002~020（顺序执行，总耗时约 30-40 分钟）

**Files:** `vlm/scripts/supervise/run_supervision_agent.py`（运行）、`vlm/config/api.env`（检查）
**Validates with:** `cat vlm/tmp/supervision_agent_output/char_001/agent_summary.json` 输出 `"status": "ok"` 且 `element_count > 0`
**Rollback:** 如果 API 一直失败，检查是否需要切换模型名（qwen3-vl-plus vs qwen3.7-plus），或检查 DashScope API 配额

### Phase 2: 元素提取 Baseline 建立

**Goal:** 在 SN_6_3D_dataset 全部 34 个样本上跑元素提取，用现有 gold JSON 评估 coverage/conflicts，建立 Linux 环境下的 baseline 指标。

**Why this approach:** 元素提取是 pipeline 的第一步，其质量决定监修审查的上限。现有的 34 个 `char_XXX.json` 可以作为 gold 立即使用（格式与 `SN_6期动漫数据标注` 一致），不需要等待新数据。结果可与 process.md 中记录的 98.2% baseline 对比。

- 确认 `run_element_extraction.py` 的 `--gold-root` 参数接受 `SN_6_3D_dataset` 的目录结构
- 对全部 34 个样本跑元素提取：`python3 -m vlm.scripts.supervise.run_element_extraction --model qwen3-vl-plus --gold-root vlm/data/SN_6_3D_dataset --output-root vlm/data/element_extraction_results_sn6 --workers 6`
- 跑评估：`python3 -m vlm.scripts.supervise.evaluate_element_extraction --pred-root vlm/data/element_extraction_results_sn6 --gold-root vlm/data/SN_6_3D_dataset --report-path vlm/data/element_extraction_results_sn6/evaluation_report.json`
- 对比 34 样本 vs 之前 20 样本的 coverage/conflicts 差异
- 如果 char_013 的"胡须"和"袜子"仍被漏掉，确认这是 prompt 盲区而非样本特例
- 记录 embedding scorer 对每种元素类型的匹配率，找出系统性弱项

**Files:** `vlm/scripts/supervise/run_element_extraction.py`（运行）、`vlm/scripts/supervise/evaluate_element_extraction.py`（运行）
**Validates with:** `evaluation_report.json` 中 coverage ≥ 90%、conflicts ≤ 20
**Rollback:** 如果提取质量显著低于之前的 98.2%，检查模型名是否正确、prompt template 是否加载成功

### Phase 3: Bug 修复 + 批量容错增强

**Goal:** 修复 `overall_decision` 空字符串 bug，为 `run_element_extraction.py` 添加断点续跑能力，增强 JSON 解析容错。

**Why this approach:** 这两个问题已经在 prior handoff 中明确定位。修复简单且直接提升可用性。断点续跑对 34+ 样本的批量运行至关重要——API 调用中途失败不应要求从头开始。

- **Bug 修复：** 在 `run_supervision_agent.py:234` 之前，从 `qwen_prediction_v3.json` 读取 `overall_decision`：
  ```python
  pred_path = Path(review_result["output_dir"]) / "qwen_prediction_v3.json"
  pred = json.loads(pred_path.read_text(encoding="utf-8"))
  overall_decision = pred.get("overall_decision", "")
  ```
- **断点续跑：** 在 `run_element_extraction.py` 的批量循环中，检查每个样本的 `extracted_elements.json` 是否已存在且 status=="ok"，是则跳过（类似 `batch_front_view.py` 的 resume 逻辑）
- **JSON 容错：** 在 `run_sample()` 的 JSON 解析处包装 `json.JSONDecodeError`，失败时记录 raw response 到 `{output_dir}/{sample_id}_raw_failure.txt` 并标记 status="json_error"，不中断整个批量
- **汇总脚本：** 写一个简单的 `summarize_batch_results.py`，扫描 `element_extraction_results_sn6/` 下所有 `extracted_elements.json`，输出成功/失败/跳过的计数和 coverage 分布

**Files:** `vlm/scripts/supervise/run_supervision_agent.py`（bug 修复）、`vlm/scripts/supervise/run_element_extraction.py`（resume + 容错）、新建 `vlm/scripts/supervise/summarize_batch_results.py`（汇总）
**Validates with:** `agent_summary.json` 的 `overall_decision` 非空；中断后重新运行 batch 能跳过已完成样本；故意传入畸形 JSON 能触发容错并记录 raw response
**Rollback:** 单文件修改，revert 单个 commit 即可

### Phase 4: 元素提取 Prompt 优化

**Goal:** 针对已知盲区（面部毛发、腿部叠层/袜子）改进 `element_extraction_from_2d.txt`，在 34 样本上做 A/B 对比验证改进效果。

**Why this approach:** 所有模型共享同一个盲区——说明是 prompt 的结构性缺失，不是模型能力问题。"胡须"和"袜子"在 34 样本中的出现频率未知，但 prompt 修复成本低，即使只在少数样本上有效也是净收益。

- 读取当前 `element_extraction_from_2d.txt`（96 行），理解现有的提取维度和指令结构
- 添加面部毛发维度指令（胡须、眉毛、睫毛等）——不要求模型强行提取不存在的特征，而是增加"如有面部毛发则必须描述"的规则
- 添加腿部/脚部叠层指令（袜子、绑腿、鞋套等下身服饰叠层）
- 备份原 prompt → 修改 → 在 34 样本上重新跑元素提取 → 对比 coverage
- 如果新增维度的 coverage 提升但其他维度下降（overfitting），回退到原 prompt 并只做最小增量
- 不做过拟合优化——避免针对 34 样本特化导致泛化能力下降

**Files:** `vlm/prompts/supervision/element_extraction_from_2d.txt`（修改）、备份到 `vlm/prompts/supervision/element_extraction_from_2d_v1_backup.txt`（保留原版）
**Validates with:** 新 prompt 的 coverage ≥ 旧 prompt，且 char_013 的"胡须"/"袜子"至少一项被提取到
**Rollback:** 从 backup 文件恢复原 prompt

### Phase 5: 本地 vLLM 部署探索（可选/低优先级）

**Goal:** 如 GPU 资源可用，搭建 qwen3-vl-30b-a3b-instruct 的本地 vLLM 服务，测试 guided_json 模式下的结构化输出稳定性。

**Why this approach:** 本地部署可绕过 DashScope 的 JSON 崩溃问题（30b-a3b 在 DashScope 上有 45% 崩溃率），并为后续 fine-tuning 准备好推理环境。但需要 GPU 资源确认后才能开始。

- 确认服务器 GPU 资源：`nvidia-smi` 检查可用 VRAM（需要 ≥24GB 用于 int4 量化）
- 安装 vLLM：`pip install vllm`（如未安装）
- 启动服务：`python3 -m vllm.entrypoints.openai.api_server --model Qwen/Qwen3-VL-30B-A3B-Instruct --dtype auto --max-model-len 32768 --guided-decoding-backend outlines`
- 写测试脚本 `vlm/scripts/supervise/test_vllm_guided_json.py`：用 `guided_json` 约束输出 element_extraction.v1 schema，对比自由输出 vs guided 输出的 JSON 合规率
- 对比本地推理 vs DashScope 的延迟、成本、JSON 合规率

**Files:** `vlm/scripts/supervise/test_vllm_guided_json.py`（新建）
**Validates with:** guided_json 模式下 JSON 合规率 ≥ 95%（vs DashScope 30b-a3b 的 55%）
**Rollback:** 不影响现有流程，关闭 vLLM 服务即可回到 DashScope API

## Dependencies & Order

- Phase 1 必须在 Phase 2 之前完成（需要先验证 API 连通性）
- Phase 2 可以和 Phase 3 部分并行（bug 修复独立于元素提取运行）
- Phase 3 的断点续跑功能应在 Phase 4 开始前完成（Phase 4 需要重新批量跑元素提取，断点续跑可节省时间）
- Phase 4 依赖 Phase 2 的 baseline 数据做 A/B 对比
- Phase 5 完全独立，可与其他 phase 并行，但需要 GPU 资源确认

## Risks & Mitigations

- **API 不可用**（中等概率）：Linux 服务器上 `QWEN_API_KEY` 未配置或过期 → 优先检查 `api.env`，如缺失则询问用户获取新 key
- **Python 依赖缺失**（低概率）：`dashscope` 等包未安装 → `pip install dashscope openai requests`
- **prompt 修改后 coverage 下降**（低概率）：新指令与现有指令冲突 → 保留 backup，快速回退
- **GPU 不可用**（中等概率）：服务器无 GPU 或 VRAM 不足 → Phase 5 自动跳过，不影响其他 phase
- **char_021~034 的元素描述质量不如 char_001~020**（未知概率）：gold 数据本身可能有问题 → 如果某样本 coverage 异常低，人工抽查该样本的 gold JSON

## Success Criteria

| Criteria | Minimum Viable | Full Success |
|----------|---------------|--------------|
| Phase 1: 端到端跑通 | char_001 单样本输出 `"status": "ok"` | char_001~020 全部成功，产出 20 份 agent_summary.json |
| Phase 2: 元素提取 baseline | 34 样本 coverage ≥ 85% | coverage ≥ 95%，与 98.2% baseline 持平 |
| Phase 3: Bug 修复 | `overall_decision` 非空 | 断点续跑 + JSON 容错全部就绪 |
| Phase 4: Prompt 优化 | 至少覆盖"胡须"或"袜子"其中一个盲区 | 两个盲区均被修复，overall coverage 不下降 |
| Phase 5: 本地部署 | vLLM 成功启动，guided_json 测试通过 | JSON 合规率 ≥ 95%，延迟可接受 |

## Quick Start

```bash
# Restore full context
cat .claude/handoffs/HANDOFF_standalone-efc395a7_pre-data-preparation_2026-07-27.md

# Key source files for Phase 1
# 1. vlm/scripts/supervise/run_supervision_agent.py
# 2. vlm/docs/workflows/process.md
# 3. vlm/scripts/supervise/run_element_extraction.py
# 4. vlm/scripts/supervise/run_multicategory_supervision_review.py
# 5. vlm/config/api.env

# Verify starting state
ls vlm/config/api.env && echo "api.env exists" || echo "MISSING: api.env"
python3 -c "import dashscope; print('dashscope OK')" 2>&1
python3 -c "import sys; sys.path.insert(0,'.'); from vlm.scripts.supervise.run_supervision_agent import *; print('imports OK')" 2>&1

# First concrete action
python3 -m vlm.scripts.supervise.run_supervision_agent \
  --source vlm/data/SN_6_3D_dataset/char_001/char_001.png \
  --product vlm/data/SN_6_3D_dataset/char_001/char_001_front_view.png \
  --category dataset_figurine \
  --sample-id char_001 \
  --dry-run
```
