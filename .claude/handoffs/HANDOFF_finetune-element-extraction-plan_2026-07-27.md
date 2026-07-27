# Handoff: overall_decision 修复 + VLM 元素提取微调 Plan

**Created:** 2026-07-27
**Branch:** main
**Session Duration:** ~1 小时

---

## Summary

本次会话承接上一份 handoff（`HANDOFF_batch-supervision-and-finetune-direction_2026-07-27.md`），完成了其中列出的第一项 immediate next step：修复 `agent_summary.json` 里 `overall_decision` 空字符串的 bug，并验证通过。随后回答了用户关于"监修审查到底检测的是什么"的问题（结论：检测的是 VLM 自动提取的 atomic_rules vs 3D 生成图，人工金标 JSON 完全没被用上）。基于这个结论，用户明确调整方向：**不再关心 3D 生图质量，转向用 6000 个人工金标 `(2D原图, elements)` 样本微调一个开源 VLM 的元素提取能力**，取代当前的 DashScope API 调用。本会话产出了一份完整的 5-phase 微调 plan（尚未批准执行，仅记录），供下一个 session 直接开始执行或细化。

---

## Work Completed

### Changes Made

- [x] 修复 `run_supervision_agent.py` 里 `overall_decision` 空字符串 bug
- [x] 用 char_001 真实数据验证修复生效
- [x] 排查清楚监修审查（Step 2）的实际输入：2D 原图 + 3D 商品图 + VLM 自动生成的 atomic_rules，人工金标 JSON 未参与
- [x] 探查本地环境：确认本机 GPU（RTX 4060 Laptop，8GB）未装 `torch`，无法本地训练
- [x] 探查现有金标数据分布：`SN_6期动漫数据标注/`（20 样本）+ `SN_6_3D_dataset/`（28 样本，含重复项如 char_027）
- [x] 复用 `.claude/plans/handoffs/HANDOFF_vlm-anime-ch-element-extraction_2026-07-23.md` 里的历史实验数据（Ollama + qwen36-vl 本地推理实验，97.3% coverage）作为对比基线参考
- [x] 产出完整微调 Plan（见下方"Plan 全文"），用户要求写入 handoff 而非直接执行

### Key Decisions

| Decision | Rationale | Alternatives Considered |
|---|---|---|
| 微调目标 schema 简化为仅 `{name, value}` | 人工金标只有这两个字段；下游 `elements_to_atomic_rules()` 也只消费 `value`（通过 `element_id`），`category`/`attributes`/`confidence` 未被消费，无监督信号不学 | 保留完整 `element_extraction.v1` schema 全字段训练 |
| 训练框架推荐 ms-swift，备选 LLaMA-Factory | 对 Qwen-VL 系列 LoRA/QLoRA 原生支持，同源生态兼容性风险最低 | 直接手写 transformers+peft 训练脚本 |
| 基座模型首选 Qwen2.5-VL-7B-Instruct | 单卡 3090 可 LoRA/QLoRA，训练快，便于先跑通整条链路再决定是否上 32B | 直接上 Qwen2.5-VL-32B-Instruct |
| 复用现有 `evaluate_element_extraction.py` 做评估 | 已经是专门针对这个 gold schema 写的语义匹配+冲突检测评估器，且能直接对比 process.md 里已有的 qwen3-vl-plus/32b/30b 基线数据 | 重新写一套评估脚本 |
| SN_6期动漫数据标注（20）+ SN_6_3D_dataset（28）设为固定 held-out 评估集 | 两者格式一致、体量小，去重后适合做训练全程不动的验证基准 | 从 6000 样本里随机切一部分做 held-out |

---

## Files Affected

### Modified

- `vlm/scripts/supervise/run_supervision_agent.py` — 第 226-238 行附近，`final_summary` 构建前先从 `qwen_prediction_v3.json` 读取 `overall_decision`，不再从 `review_result` 读（那里没有这个 key）

### Read (Reference)

- `.claude/handoffs/HANDOFF_batch-supervision-and-finetune-direction_2026-07-27.md` — 上一份 handoff，本次工作的起点
- `vlm/scripts/supervise/run_multicategory_supervision_review.py` — 确认 `run_one_sample()` 的输入构成（source_image + multiview_image + atomic_rules，均非人工金标）
- `vlm/scripts/supervise/run_element_extraction.py` — 确认 `run_sample()` 未读取 gold JSON 内容，只用 `sample_id`/`source_image` 填 prompt 模板
- `vlm/docs/workflows/process.md` — 项目当前状态压缩文档，含元素提取模型对比表（qwen3-vl-plus 98.2% coverage 基线）
- `vlm/scripts/supervise/evaluate_element_extraction.py` — 现有评估脚本全文，确认其打分逻辑不强制要求 `category` 等字段，可直接用于评估微调后模型
- `vlm/prompts/supervision/element_extraction_from_2d.txt` — 当前元素提取 prompt 模板
- `.claude/plans/handoffs/HANDOFF_vlm-anime-ch-element-extraction_2026-07-23.md` — 历史 Ollama 本地推理实验记录（qwen36-vl，97.3% coverage，A100+3090 服务器）
- `vlm/data/SN_6_3D_dataset/char_027/char_027.json` — 发现金标本身含重复 element 的实例（噪声证据）
- `vlm/requirements.txt` — 确认当前无训练类依赖（无 torch/transformers/peft）

---

## Technical Context

### 关于"监修审查检测的是什么"（用户提问的结论）

`run_supervision_agent.py` 的三步流程：
1. Step 1（元素提取）：VLM 看 2D 原图，自己生成 `atomic_rules_generated.json`——**不读人工金标 JSON**
2. Step 2（监修审查）：VLM 用 Step 1 生成的 atomic_rules 去对比 3D 商品图（`--product`），判断每条规则是否成立
3. 人工金标 `char_XXX.json` 在整条链路里完全没被使用

这个发现直接促成了用户的方向调整：与其继续评估 3D 生图质量（跟人工标注质量无关），不如直接拿人工金标去训练/微调元素提取这一步的模型能力。

### Fine-tuning Plan 全文

> 完整 plan 已在 plan 模式下写好，用户要求存档而非立即执行。以下为全文，供下一 session 直接续接。

---

#### 目标

用 6000 个人工标注的 `(2D 角色原图, elements gold)` 样本，微调一个开源 VLM，使其在"元素提取"任务上达到或超过当前 API 方案（qwen3-vl-plus，98.2% coverage）的准确率，最终替换 `run_element_extraction.py` 里的 DashScope API 调用，降低成本、去掉云端依赖。

**范围边界**：只做元素提取（Step 1），不动监修审查（Step 2）。3D 生图质量问题不在本 plan 范围内。

#### 已确认的关键信息

- **6000 样本状态**：已就位，格式待整理（用户正在处理）。
- **算力**：之前用过的远程服务器，A100-SXM4-80GB + RTX 3090，此前跑过 Ollama 推理实验（`qwen36-vl`，35.5GB Q8）。**注意**：Ollama 只能做推理，不能做 LoRA 训练；训练需要直接用 HF 权重 + `transformers`/`peft` 或训练框架（ms-swift / LLaMA-Factory），跳过 Ollama。
- **本地机器 GPU 不可用于训练**：RTX 4060 Laptop 只有 8GB 显存，且未装 `torch`——本地只能做数据准备/评估脚本开发，不能跑微调。
- **现有金标数据**（本地已有，作为验证/对比基准）：
  - `vlm/data/SN_6期动漫数据标注/`：20 个样本，`{sample_id, source_image, elements:[{name, value}]}`
  - `vlm/data/SN_6_3D_dataset/`：28 个样本，同结构（`char_027.json` 已确认格式一致，但发现一例完全重复的 element）
  - 两者可能有 ID 重叠（如 char_001~020），需要在 Phase 0 核实并去重，作为统一的 held-out 评估集，不能混进训练集。
- **现有评估脚本**：`vlm/scripts/supervise/evaluate_element_extraction.py`——已经是专门针对这个 gold schema 写的语义匹配+冲突检测评估器，直接可以复用来评估微调后的模型，与 process.md 里 qwen3-vl-plus/32b/30b 的对比表数据可比。
- **关键发现——训练目标 schema 可以简化**：
  - 完整的 `element_extraction.v1` 输出包含 `element_id/name/value/category/attributes/confidence` 等字段，但人工金标只有 `name` + `value`。
  - 下游 `run_supervision_agent.py` 的 `elements_to_atomic_rules()`（`run_supervision_agent.py:83-99`）只用了 `element_id` 和 `value`，`category`/`attributes`/`confidence` 根本没被消费。
  - 因此微调目标可以直接对齐 gold 的 `{name, value}` 结构，不需要教模型编造 `category`/`attributes`/`confidence`——省数据标注工作量，也避免模型学到没有监督信号的字段。
  - `evaluate_element_extraction.py` 的打分逻辑基于 name+value 文本关键词匹配，不强制要求 `category` 字段存在，兼容这个简化 schema。

#### Phase 0 — 数据盘点与清洗（本地可做）

1. 确认 6000 样本的实际存放位置和格式（等用户整理完成后核对）。
2. 扩展/复用 `validate_human_annotations.py` 的思路，写一个校验脚本，检查每个样本：
   - 图片文件存在
   - JSON 含 `sample_id`/`source_image`/`elements[name,value]`
   - `sample_id` 与文件夹名一致
   - 无重复 element（已在 `char_027.json` 发现一例完全重复的 `"银色长靴与银色护胫"`，说明金标本身有噪声，需要批量检测同类问题）
3. 核实 `SN_6期动漫数据标注`（20）与 `SN_6_3D_dataset`（28）之间的 sample_id 重叠情况，合并去重后作为固定 held-out 评估集（不进训练集，保证评估干净）。
4. 输出：一份清洗后的样本清单（manifest jsonl：`sample_id, image_path, json_path, element_count, status`）。

#### Phase 1 — 构建 SFT 训练数据（本地可做）

1. 新脚本：`vlm/scripts/finetune/build_sft_dataset.py`
2. 对每个有效样本，生成对话式训练记录：
   - 图片：2D 原图
   - system/user prompt：复用 `element_extraction_from_2d.txt` 的表述，但把输出 schema 简化为仅要求 `element_id + name + value`（去掉 category/attributes/confidence 的强制要求）
   - assistant 目标：按 gold 的 `elements` 直接生成 `element_id`（`{sample_id}_e001` 顺序编号）
3. 切分：
   - Train：6000 里去掉验证集后的剩余部分
   - Val（早停用）：从 6000 里随机切 ~200-300 个
   - Test：Phase 0 产出的固定 held-out 集（现有 ~28-48 个去重样本），继续用现成的 `evaluate_element_extraction.py` 打分，直接对比历史基线
4. 输出格式：先定为通用 jsonl（图片路径 + messages 数组），Phase 2 选定训练框架后再确认具体字段名对齐。

#### Phase 2 — 训练框架与基座模型选型（远程服务器上验证，预计 1 天）

- **推荐**：ms-swift（ModelScope Swift）——对 Qwen-VL 系列 LoRA/QLoRA 支持最原生，同源生态，兼容性风险最低。
- **备选**：LLaMA-Factory——社区更大，Qwen2.5-VL 支持也成熟。
- **基座模型候选**：
  - 首选 `Qwen2.5-VL-7B-Instruct`：单张 3090（24GB）就能 LoRA/QLoRA，训练快、便于快速迭代验证整条链路。
  - 若 7B 结果明显低于 98.2% coverage 基线，再上 `Qwen2.5-VL-32B-Instruct`（用 A100 80GB，int4/LoRA）。
- 需要确认远程服务器**训练用的这台机器**能否联网下载 HF 权重（之前那台跑 Ollama 推理的服务器是**无法访问 HuggingFace/PyPI 的**，如果训练用同一台，需要提前把模型权重从本地传上去，类似目前卡住的 SSH 传输问题）。

#### Phase 3 — LoRA 微调（远程服务器）

1. 用 ms-swift 标准 Qwen2.5-VL LoRA 配方跑训练（rank 16-64，cosine LR，2-3 epoch 起步）。
2. 训练中定期人工抽查生成结果，防止 JSON 格式跑偏。
3. 训练完成后合并 LoRA 权重，导出可推理的模型目录。

#### Phase 4 — 评估（复用现有脚本，决策关卡）

1. 用微调后模型对 held-out 评估集跑推理，产出 `extracted_elements.json`（沿用现有 `element_extraction.v1` 输出结构，`category`/`attributes`/`confidence` 留空即可）。
2. 直接跑 `evaluate_element_extraction.py`，得到 coverage / conflict / unsupported extra，和 process.md 里现有的 API 基线对比表放在一起看。
3. **决策关卡**：
   - 效果接近或超过 qwen3-vl-plus API 基线 → 进入 Phase 5 集成。
   - 效果不够 → 先看是否数据质量问题（回到 Phase 0 清洗）或模型规模问题（换 32B），再迭代，暂不集成。

#### Phase 5 — 接入现有 pipeline（仅在 Phase 4 通过后做）

1. 在 `run_element_extraction.py` 里加一个可选的本地推理后端（起 vLLM/transformers 服务，走 HTTP 或本地调用），用 `--model-backend {api,local}` 切换，`build_prompt`/`normalize_elements` 等现有逻辑不变。
2. 更新 `vlm/docs/workflows/process.md` 记录新结论和使用方式。

#### 风险与阻塞点

- **6000 样本的具体落地路径未定**：Phase 0 依赖用户整理完成，这是当前最大不确定性。
- **训练服务器联网情况未知**：如果和之前 Ollama 推理服务器是同一台且无法访问 HuggingFace，需要提前规划权重传输（可能撞上现有的 SSH 端口未知的传输阻塞，见 `HANDOFF_batch-supervision-and-finetune-direction_2026-07-27.md`）。
- **GPU 是否空闲**：A100 上此前有 `qwen36-vl`（~37GB）常驻做推理服务，训练时要确认显存冲突，可能需要临时停掉推理服务或只用 3090。
- **金标数据本身有噪声**（如 `char_027` 重复 element），6000 个样本大概率存在同类问题，Phase 0 的清洗质量直接影响训练效果，不能省略。

---

## Things to Know

### Gotchas & Pitfalls

- Ollama 只能推理不能训练——之前远程服务器上跑通的 `qwen36-vl` 推理服务不能直接拿来做 LoRA，训练必须走 HF 权重 + transformers/peft 或专门训练框架
- 本机（RTX 4060 Laptop, 8GB）没装 torch，本地环境目前只能做数据准备和脚本开发，不能做任何模型推理/训练验证
- 金标数据存在噪声：`char_027.json` 里 `"银色长靴与银色护胫"` 这个 element 完全重复了两次，6000 样本里大概率有更多同类问题

### Assumptions Made

- 假设 6000 样本整理后的格式会与现有 `SN_6期动漫数据标注`/`SN_6_3D_dataset` 一致（`{sample_id, source_image, elements:[{name,value}]}`），需要用户交付后核实
- 假设远程训练服务器可以复用之前跑 Ollama 的那台（A100+3090），但联网能力未验证

---

## Current State

### What's Working

- `overall_decision` 字段修复已验证（char_001 数据核实过）
- 现有 `evaluate_element_extraction.py` 评估脚本可直接复用于微调后模型评估，无需重写

### What's Not Working / Not Started

- 6000 样本微调 plan 仅完成设计，Phase 0（数据盘点清洗）尚未开始
- 20 个已跑批次样本（char_001~020）的 `agent_summary.json` 仍是修复前生成的，未回填 `overall_decision`（用户尚未决定是否要回填，讨论到一半转向了新方向）

### Tests

- [x] `overall_decision` 修复：用 char_001 真实数据验证通过
- [ ] Phase 0 数据校验脚本：未写
- [ ] 微调训练：未开始（等 Phase 0-2 就位）

---

## Next Steps

### Immediate (Start Here)

1. **等用户交付 6000 样本**，确认实际存放路径和目录结构，与 Phase 0 假设的格式核对
2. 编写 Phase 0 数据校验脚本（复用 `validate_human_annotations.py` 思路），跑一遍摸底噪声情况（如 char_027 那种重复 element）
3. 确认 `SN_6期动漫数据标注`（20）与 `SN_6_3D_dataset`（28）的 sample_id 重叠情况，产出去重后的固定 held-out 评估集

### Subsequent

- Phase 1：写 `vlm/scripts/finetune/build_sft_dataset.py`，把清洗后的样本转成训练格式
- Phase 2：确认远程服务器联网情况，选定 ms-swift 或 LLaMA-Factory，下载 Qwen2.5-VL-7B-Instruct 权重
- 之前 20 样本批量结果的 `overall_decision` 回填（低优先级，未决定是否需要）

### Blocked On

- 6000 样本整理进度（用户处理中）
- 远程训练服务器能否联网下载 HF 权重（未验证，之前推理服务器确认无法访问 HuggingFace）
- SSH 端口未知导致的数据传输阻塞（见上一份 handoff，可能影响权重/数据上传服务器）

---

## Related Resources

### Documentation

- `.claude/handoffs/HANDOFF_batch-supervision-and-finetune-direction_2026-07-27.md` — 上一份 handoff，本次工作起点
- `.claude/plans/handoffs/HANDOFF_vlm-anime-ch-element-extraction_2026-07-23.md` — 历史 Ollama 本地推理实验（97.3% coverage 参考基线）
- `vlm/docs/workflows/process.md` — 项目当前状态压缩文档

### Commands to Run

```bash
# 查看现有金标数据结构
cat "vlm/data/SN_6期动漫数据标注/char_001/char_001.json"
cat vlm/data/SN_6_3D_dataset/char_027/char_027.json

# 现有评估脚本用法（Phase 4 会直接复用）
python -m vlm.scripts.supervise.evaluate_element_extraction \
  --gold-root vlm/data/SN_6期动漫数据标注 \
  --pred-root vlm/data/element_extraction_results \
  --report-path vlm/data/element_extraction_results/evaluation_report.json
```

### Search Queries

- `elements_to_atomic_rules` — 找 element→atomic_rule 字段映射逻辑（`run_supervision_agent.py`）
- `evaluate_element_extraction` — 找现有评估脚本及其打分算法

---

## Open Questions

- [ ] 6000 样本目前具体存放在哪里，整理后交付的目录结构是什么？
- [ ] 远程训练服务器是否能联网下载 Qwen2.5-VL 权重？如果不能，权重怎么传上去？
- [ ] 训练时 A100 的 `qwen36-vl` 推理服务是否需要保留在线，还是可以临时下线腾显存？
- [ ] ms-swift 还是 LLaMA-Factory——是否有既有偏好（比如已经在其他项目用过其中一个）？
- [ ] 之前 20 个批量样本的 `overall_decision` 是否需要回填？（讨论中途转向，未决定）

---

## Session Notes

用户明确表态：不再需要评估/关注 3D 生图质量问题，注意力全部转向用人工金标训练模型的元素提取与描述准确性。后续 session 如果又看到"3D 生图质量""RunningHub 补图"相关的旧 next steps（来自更早的 handoff），除非用户重新提起，否则应视为暂缓/非当前优先级。

---

_Session closed: 2026-07-27_
