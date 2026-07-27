# Plan: 用人工金标数据微调 VLM 元素提取能力

**Created:** 2026-07-27
**Status:** Draft — 待批准

---

## 目标

用 6000 个人工标注的 `(2D 角色原图, elements gold)` 样本，微调一个开源 VLM，使其在"元素提取"任务上达到或超过当前 API 方案（qwen3-vl-plus，98.2% coverage）的准确率，最终替换 `run_element_extraction.py` 里的 DashScope API 调用，降低成本、去掉云端依赖。

**范围边界**：只做元素提取（Step 1），不动监修审查（Step 2）。之前讨论的"3D 生图质量"问题不在本 plan 范围内。

---

## 已确认的关键信息

- **6000 样本状态**：已就位，格式待整理（用户正在处理）。
- **算力**：之前用过的远程服务器，A100-SXM4-80GB + RTX 3090，此前跑过 Ollama 推理实验（`qwen36-vl`，35.5GB Q8）。**注意**：Ollama 只能做推理，不能做 LoRA 训练；训练需要直接用 HF 权重 + `transformers`/`peft` 或训练框架（ms-swift / LLaMA-Factory），跳过 Ollama。
- **本地机器 GPU 不可用于训练**：RTX 4060 Laptop 只有 8GB 显存，且未装 `torch`——本地只能做数据准备/评估脚本开发，不能跑微调。
- **现有金标数据**（本地已有，作为验证/对比基准）：
  - `vlm/data/SN_6期动漫数据标注/`：20 个样本，`{sample_id, source_image, elements:[{name, value}]}`
  - `vlm/data/SN_6_3D_dataset/`：28 个样本，同结构（例如 `char_027.json` 已确认格式一致）
  - 两者可能有 ID 重叠（如 char_001~020），需要在 Phase 0 核实并去重，作为统一的 held-out 评估集，不能混进训练集。
- **现有评估脚本**：`vlm/scripts/supervise/evaluate_element_extraction.py`——已经是专门针对这个 gold schema 写的语义匹配+冲突检测评估器，直接可以复用来评估微调后的模型，与 process.md 里 qwen3-vl-plus/32b/30b 的对比表数据可比。
- **关键发现——训练目标 schema 可以简化**：
  - 完整的 `element_extraction.v1` 输出包含 `element_id/name/value/category/attributes/confidence` 等字段，但人工金标只有 `name` + `value`。
  - 下游 `run_supervision_agent.py` 的 `elements_to_atomic_rules()`（[run_supervision_agent.py:83-99](vlm/scripts/supervise/run_supervision_agent.py#L83-L99)）只用了 `element_id` 和 `value`，`category`/`attributes`/`confidence` 根本没被消费。
  - 因此微调目标可以直接对齐 gold 的 `{name, value}` 结构，不需要教模型编造 `category`/`attributes`/`confidence`——省数据标注工作量，也避免模型学到没有监督信号的字段。
  - `evaluate_element_extraction.py` 的打分逻辑基于 name+value 文本关键词匹配，不强制要求 `category` 字段存在，兼容这个简化 schema。

---

## Phase 0 — 数据盘点与清洗（本地可做）

1. 确认 6000 样本的实际存放位置和格式（等用户整理完成后核对）。
2. 扩展/复用 `validate_human_annotations.py` 的思路，写一个校验脚本，检查每个样本：
   - 图片文件存在
   - JSON 含 `sample_id`/`source_image`/`elements[name,value]`
   - `sample_id` 与文件夹名一致
   - 无重复 element（已在 `char_027.json` 发现一例完全重复的 `"银色长靴与银色护胫"`，说明金标本身有噪声，需要批量检测同类问题）
3. 核实 `SN_6期动漫数据标注`（20）与 `SN_6_3D_dataset`（28）之间的 sample_id 重叠情况，合并去重后作为固定 held-out 评估集（不进训练集，保证评估干净）。
4. 输出：一份清洗后的样本清单（manifest jsonl：`sample_id, image_path, json_path, element_count, status`）。

## Phase 1 — 构建 SFT 训练数据（本地可做）

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

## Phase 2 — 训练框架与基座模型选型（远程服务器上验证，预计 1 天）

- **推荐**：ms-swift（ModelScope Swift）——对 Qwen-VL 系列 LoRA/QLoRA 支持最原生，同源生态，兼容性风险最低。
- **备选**：LLaMA-Factory——社区更大，Qwen2.5-VL 支持也成熟。
- **基座模型候选**：
  - 首选 `Qwen2.5-VL-7B-Instruct`：单张 3090（24GB）就能 LoRA/QLoRA，训练快、便于快速迭代验证整条链路。
  - 若 7B 结果明显低于 98.2% coverage 基线，再上 `Qwen2.5-VL-32B-Instruct`（用 A100 80GB，int4/LoRA）。
- 需要确认远程服务器**训练用的这台机器**能否联网下载 HF 权重（之前那台跑 Ollama 推理的服务器是**无法访问 HuggingFace/PyPI 的**，如果训练用同一台，需要提前把模型权重从本地传上去，类似目前卡住的 SSH 传输问题）。

## Phase 3 — LoRA 微调（远程服务器）

1. 用 ms-swift 标准 Qwen2.5-VL LoRA 配方跑训练（rank 16-64，cosine LR，2-3 epoch 起步）。
2. 训练中定期人工抽查生成结果，防止 JSON 格式跑偏。
3. 训练完成后合并 LoRA 权重，导出可推理的模型目录。

## Phase 4 — 评估（复用现有脚本，决策关卡）

1. 用微调后模型对 held-out 评估集跑推理，产出 `extracted_elements.json`（沿用现有 `element_extraction.v1` 输出结构，`category`/`attributes`/`confidence` 留空即可）。
2. 直接跑 `evaluate_element_extraction.py`，得到 coverage / conflict / unsupported extra，和 process.md 里现有的 API 基线对比表放在一起看。
3. **决策关卡**：
   - 效果接近或超过 qwen3-vl-plus API 基线 → 进入 Phase 5 集成。
   - 效果不够 → 先看是否数据质量问题（回到 Phase 0 清洗）或模型规模问题（换 32B），再迭代，暂不集成。

## Phase 5 — 接入现有 pipeline（仅在 Phase 4 通过后做）

1. 在 `run_element_extraction.py` 里加一个可选的本地推理后端（起 vLLM/transformers 服务，走 HTTP 或本地调用），用 `--model-backend {api,local}` 切换，`build_prompt`/`normalize_elements` 等现有逻辑不变。
2. 更新 `vlm/docs/workflows/process.md` 记录新结论和使用方式。

---

## 风险与阻塞点

- **6000 样本的具体落地路径未定**：Phase 0 依赖用户整理完成，这是当前最大不确定性。
- **训练服务器联网情况未知**：如果和之前 Ollama 推理服务器是同一台且无法访问 HuggingFace，需要提前规划权重传输（可能撞上现有的 SSH 端口未知的传输阻塞，见另一份 handoff）。
- **GPU 是否空闲**：A100 上此前有 `qwen36-vl`（~37GB）常驻做推理服务，训练时要确认显存冲突，可能需要临时停掉推理服务或只用 3090。
- **金标数据本身有噪声**（如 `char_027` 重复 element），6000 个样本大概率存在同类问题，Phase 0 的清洗质量直接影响训练效果，不能省略。

---

## 待确认的开放问题

- [ ] 6000 样本目前具体存放在哪里，整理后交付的目录结构是什么？
- [ ] 远程训练服务器是否能联网下载 Qwen2.5-VL 权重？如果不能，权重怎么传上去？
- [ ] 训练时 A100 的 `qwen36-vl` 推理服务是否需要保留在线，还是可以临时下线腾显存？
- [ ] ms-swift 还是 LLaMA-Factory——是否有既有偏好（比如已经在其他项目用过其中一个）？
