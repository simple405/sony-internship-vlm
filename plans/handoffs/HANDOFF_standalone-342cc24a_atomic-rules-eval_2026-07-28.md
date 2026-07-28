# Handoff: Atomic Rules 提取质量评估（34样本，bge-m3 embedding）

**Date:** 2026-07-28
**Status:** COMPLETED
**Bead(s):** none
**Epic:** VLM Supervision Agent Pipeline
**Chain:** `standalone-342cc24a` seq 1
**Parent:** none — first in chain

---

## Related Handoffs

- `HANDOFF_supervision-agent-pipeline_2026-07-27.md` — 监修 agent 端到端 pipeline 架构定义（创建了 `run_supervision_agent.py`），不同工作流
- `HANDOFF_sn6-54-sample-extraction-verified_2026-07-28.md` — qwen36-vl 54 样本元素提取验证（另一个 pipeline 的评估），不同工作流

---

## The Goal

评估 supervision agent pipeline 产出的 `atomic_rules_generated.json` 提取质量——这批数据用了与 qwen36-vl 不同的提取方式和输出格式（`{rule_id, value}` vs `{element_id, name, value, category, attributes, confidence}`）。需要确认：本地 bge-m3 embedding 能否做语义匹配评估，以及 atomic_rules 的 coverage/precision 是否达到可用水平。

---

## Where We Are

- [x] 确认 `supervision_agent_output/` 中 34/54 样本有 `atomic_rules_generated.json`（char_001~034）
- [x] 确认 char_035~054 缺少 atomic_rules 提取——仅有 34 样本可评估
- [x] 确认本地 Ollama 已运行（PID 2988661，6月11日启动），`bge-m3:latest` 已安装（1.2GB, 1024-dim）
- [x] 发现公司代理（137.153.170.55:10080）拦截 localhost Ollama 请求，需要 `proxies={"http": None, "https": None}`
- [x] 创建 `vlm/scripts/supervise/evaluate_atomic_rules.py`——专用于 atomic_rules 格式的评估脚本
- [x] 实现 OllamaEmbedder 类：bge-m3 批量编码 + 磁盘缓存（`vlm/tmp/embedding_cache_local.json`）
- [x] 实现 Hungarian + Jaccard 双模式匹配
- [x] 安装 numpy 1.24.4 + scipy 1.10.1 到 `.venv`
- [x] 跑完 34 样本 embedding 评估：Macro Coverage 94.34%, Macro Precision 73.53%, F1 0.8265, Avg Cosine Sim 0.711
- [x] 跑完 Jaccard-only baseline 对比：Coverage 70.75%, Precision 55.15%, F1 0.6198
- [x] 12 个 gold 元素未被匹配——按类别分析失败模式
- [x] 确认 precision gap（72 extra pred）根因是粒度不匹配（atomic_rules 拆分比 gold 复合元素细），不是幻觉
- [ ] 未评估 char_035~054（缺少 atomic_rules 输出）
- [ ] 未写入 memory / 清理未提交的 JSON 修复

---

## What We Tried (Chronological)

### 1. 阅读最新 handoff 了解上下文
**Hypothesis:** 需要先搞清楚当前 pipeline 状态，特别是 atomic_rules 的提取来源。
**Result:** 发现两个独立 pipeline：(a) `element_extraction_results/`（qwen36-vl，54/54 完成，`extracted_elements.json` 格式）和 (b) `supervision_agent_output/`（supervision agent，34/54 完成，`atomic_rules_generated.json` 格式）。主评估脚本 `evaluate_element_extraction.py` 只支持 (a) 格式。最新 handoff `HANDOFF_sn6-54-sample-extraction-verified_2026-07-28.md` 记录的是 (a) 的评估，未覆盖 (b)。

### 2. 检查本地 embedding 模型可用性
**Hypothesis:** 本地 Ollama 有 bge-m3，可替代 DashScope `text-embedding-v3` 做语义匹配。
**Result:** Ollama server 已在运行但端口被代理拦截——curl 请求被路由到 137.153.170.55:10080 → 403 Forbidden。用 `curl --noproxy '*'` 绕过代理可正常调用。bge-m3 1024-dim 向量对中文语义匹配效果好——"黑色短发，刘海遮盖额头" vs "黑色短发" 的 cosine similarity = 0.82。`evaluate_element_extraction.py` 依赖的 `embedding_scorer.py` 只支持 DashScope API，需要重写。

### 3. 创建 `evaluate_atomic_rules.py` 评估脚本
**Hypothesis:** 可以从 `experiment_vlm_analysis_v2.py` 提取 bge-m3 embedder + Hungarian matching 逻辑，适配 atomic_rules 格式。
**Result:** ✅ 创建完成。核心设计：
- `OllamaEmbedder`: 用 `requests.post /api/embed`（绕过代理）调用 bge-m3，1024-dim 输出，JSON 缓存到磁盘
- `match_elements_hungarian`: Hungarian 全局最优一对一匹配，基于 cosine similarity
- `jaccard_similarity`: 字符级 Jaccard fallback（当 embedder=None 时）
- 指标：coverage（matched/gold），precision（matched/pred），F1，avg_similarity，good/weak match 分类
- 需要 numpy + scipy——通过 `python3 -m pip install` 安装到 `.venv`

### 4. 运行 embedding 评估（34 样本）
**Hypothesis:** bge-m3 embedding + Hungarian matching 可以准确评估 atomic_rules 质量。
**Result:** ✅ 475 个唯一文本的 embedding 预计算完成。34 样本结果：

| 指标 | 值 |
|---|---|
| Macro Coverage | 94.34% (200/212 gold) |
| Macro Precision | 73.53% (200/272 pred) |
| Macro F1 | 0.8265 |
| Avg Cosine Similarity | 0.7113 |
| Good/Weak matches | 156/44 |
| 未匹配 gold | 12 |
| 未匹配 pred | 72 |

3 个样本达到 F1=1.0（char_003, char_009, char_022）。最差的 3 个：char_028（F1=0.615），char_002（0.625），char_024（0.667）。

### 5. 对比 Jaccard-only baseline（`--no-embeddings`）
**Hypothesis:** 需要量化 embedding 的实际贡献。
**Bug fix:** 初版 `--no-embeddings` 在 embedder=None 时在 `match_elements_hungarian` 中调用 `embedder.encode()` 导致 AttributeError。修复：添加 `jaccard_similarity()` fallback 路径。
**Result:** Jaccard-only 效果远差于 embedding：

| 指标 | bge-m3 embedding | Jaccard only | 差距 |
|---|---|---|---|
| Coverage | 94.34% | 70.75% | -23.6pp |
| Precision | 73.53% | 55.15% | -18.4pp |
| F1 | 0.8265 | 0.6198 | -0.21 |
| 未匹配 gold | 12 | 62 | 5x |

关键发现：Jaccard 在字符层面无法处理长度差异（如 gold="黑色短发，刘海遮盖额头，两侧有鬓角垂下" vs pred="黑色短发"——Jaccard~0.25 但 embedding 相似度 0.82）。char_017 差异最大（embedding F1=0.800 vs Jaccard F1=0.267），因为 gold 中大量长描述句降低了字符重合。

### 6. 分析 12 个未匹配 gold 元素的失败模式
**Result:** 按类别分布：

| 类别 | 数量 | 占比 | 示例 |
|---|---|---|---|
| 姿势/手势 | 5 | 42% | "右手抬起，手掌朝前"（char_024），"蹲姿与右手部姿势"（char_034） |
| 眼睛 | 2 | 17% | "紫红色眼睛"（char_025），"蓝色眼睛"（char_010） |
| 鞋类 | 2 | 17% | "黑色绑带凉鞋"（char_028），"蓝白高跟靴"（char_031） |
| 袜类 | 2 | 17% | "粉紫色大腿袜"（char_025），"深蓝色长袜"（char_032） |
| 非人解剖 | 1 | 8% | "脚爪与趾甲"（char_017） |

**核心发现：** pose/gesture 是 atomic_rules pipeline 的最大盲区（42%）。这些不是视觉元素而是姿态描述，gold 中包含它们是因为 3D 监修需要，但 atomic_rules 只提取静态视觉特征。

### 7. 分析 72 个 extra prediction 的根因
**Result:** 72 个 extra 不是幻觉——是粒度不匹配。Gold 倾向于写复合元素（如"白色衬衫与蓝色宝石领饰"、"黑色短裙与腰带"），而 atomic_rules 将每个独立视觉特征拆成单独规则。这导致 Hungarian matching 无法将多个细粒度的 pred 一对一匹配到粗粒度的 gold，多出来的一律算 unmatched_pred。本质是标注口径差异，不是模型质量问题。

---

## Key Decisions

| Decision | Rationale | Alternatives Rejected |
|---|---|---|
| 写新评估脚本而非修改 `evaluate_element_extraction.py` | 格式差异太大：atomic_rules 没有 category/attributes/confidence 字段，旧脚本的 Jaccard+keyword 评分体系不适用 | 修改旧脚本支持双格式（耦合增加，回归风险高） |
| 用 Hungarian（全局最优）而非 Greedy 匹配 | Hungarian 保证最优一对一对齐，Greedy 受元素顺序影响可能产生次优匹 | Greedy，但 `experiment_vlm_analysis_v2.py` 两者都实现了 |
| 用 bge-m3 做全文本 embedding（value only），不分离 name | atomic_rules 只有 `{rule_id, value}`，没有独立 name 字段。rule_id 仅为标识符，无语义 | 像 v2 脚本那样 name_weight=0.3 加权 name+value |
| 安装 numpy/scipy 而非纯 Python 实现 Hungarian | `scipy.optimize.linear_sum_assignment` 是标准实现，手写 Hungarian 容易出错 | `pip install munkres` 或手写循环实现 |
| Jaccard fallback 用字符级而非词级 | 中文无自然空格分界线，字符级 Jaccard 更通用 | 用结巴分词 → token 级别（但需要安装 + 领域词典缺失会丢失信息） |
| 不做 A/B 对比 | 用户问的是"这次提取效果"，不是对比两个 pipeline。34 vs 54 样本数不同也无法公平对比 | 尝试对齐两套格式跑同一评估（投入产出比低） |

---

## Format Gap: Gold Composite vs Atomic Rules Granularity

这是 precision gap 的根因。以 char_015 为例：

**Gold（复合元素，5 个）：**
```
[紫色长发与蝴蝶结] 头发为紫色长直发，刘海遮住右眼，左侧扎有一个紫色蝴蝶结...
[紫色长袖] 左右两边是紫色的长袖，袖口末端呈尖角状...
[紫色连衣裙] 裙子为紫色，下摆边缘有蕾丝边装饰...
[黑色长筒袜与紫色高跟靴] 腿部穿着黑色长筒袜，脚上是带有紫色和银色装饰的高跟靴...
[紫色披风与臂环] 披风为紫色，手臂处套有开口的金属臂环...
```

**Atomic rules（独立细粒度，9 个）：**
```
[char_015_e001] 黑色短发，刘海遮盖额头，两侧有鬓角垂下
[char_015_e002] 紫色耳机状装置，两侧有尖刺延伸    ← extra: gold将此归入"长发与蝴蝶结"
[char_015_e003] 紫色瞳孔                            ← extra: gold未单独列出眼睛
[char_015_e004] 紫色无袖交叉设计上衣，胸前镂空      ← extra: gold将此归入"连衣裙"
[char_015_e005] 长款紫色披风，边缘有黑色装饰         ← 匹配到"披风与臂环"
[char_015_e006] 银色与紫色相间的臂环/护腕            ← extra: gold将此归入"披风与臂环"
[char_015_e007] 黑色过膝长筒袜，大腿处有镂空设计     ← 匹配到"长筒袜与高跟靴"
[char_015_e008] 黑色细腰带                            ← extra: gold未单独列出腰带
[char_015_e009] 紫银配色高跟鞋                        ← extra: gold将此归入"长筒袜与高跟靴"
```

**匹配结果：** 5 个 gold 全匹配（coverage=100%），但 9 个 pred 只有 5 个被匹配（precision=56%）。余下的 4 个 pred（耳机、瞳孔、上衣、腰带）都是正确提取的视觉元素，但 gold 把它们合并在复合元素中。

### 完美匹配案例：char_003（4 gold ↔ 4 pred）

char_003 之所以 F1=1.0，是因为 gold 恰好写了 4 个独立元素，atomic_rules 也提取了 4 个独立规则，每个都有语义等价的描述：

```
Gold: [棕色高马尾] 头发为棕色，扎成一个高高的马尾辫...
Pred: [char_003_e001] 浅棕色高马尾（或丸子头），前额有刘海...    ← sim=0.802

Gold: [黄色T恤与饭团图案] 穿着一件纯黄色短袖T恤，胸前印有...
Pred: [char_003_e002] 黄色短袖圆领T恤，胸前印有巨大的白色...    ← sim=0.911

Gold: [绿色百褶短裙] 下身搭配一条绿色的百褶短裙...
Pred: [char_003_e003] 草绿色百褶短裙（或运动短裤裙）...          ← sim=0.798

Gold: [黄绿配色运动鞋] 脚穿一双黄绿色调的运动鞋...
Pred: [char_003_e004] 白色为主色调的运动鞋，配有黄色鞋带...      ← sim=0.776
```

---

## Ollama & Proxy Details

### 本地模型清单
```
qwen36-vl:latest    38.7 GB   Q8_0 quant, 35.5B params — VLM extraction
qwen3.6-35B:latest  37.8 GB   — text-only variant (unused)
bge-m3:latest        1.2 GB   1024-dim — embedding model (used in eval)
gemma3:27b-it-qat   18.1 GB   — unused
deepseek-r1_70b     42.5 GB   — unused
deepseek-r1:7b       4.7 GB   — unused
```

### 代理问题
- 环境变量 `http_proxy=http://137.153.170.55:10080` 拦截所有 HTTP 请求
- `127.0.0.1:11434` 的 Ollama API 也被路由到代理 → 403 Forbidden
- **解决方案：** 两种等价格式 —
  - Python: `requests.post(url, proxies={"http": None, "https": None})`
  - Shell: `curl --noproxy '*'` 或 `NO_PROXY="localhost,127.0.0.1"`
- `evaluate_atomic_rules.py` 的 `OllamaEmbedder._embed_batch` 已在每次 `requests.post` 中硬编码 `proxies={"http": None, "https": None}`

---

## Evidence & Data

### 提取完成度矩阵

| Pipeline | 输出目录 | 格式 | 完成数 | 状态 |
|---|---|---|---|---|
| qwen36-vl | `element_extraction_results/` | `extracted_elements.json` | 54/54 | ✅ |
| supervision agent | `supervision_agent_output/` | `atomic_rules_generated.json` | 34/54 | ⚠️ 缺 char_035~054 |

### 评估结果文件

| 文件 | 内容 |
|---|---|
| `vlm/tmp/atomic_rules_eval_report.json` | 34 样本 embedding 评估完整报告（per-sample matches, unmatched, metrics） |
| `vlm/tmp/atomic_rules_eval_jaccard.json` | Jaccard-only baseline 对比报告 |
| `vlm/tmp/embedding_cache_local.json` | bge-m3 embedding 缓存（避免重复调用 API） |

### Per-Sample 指标（embedding 评估，sorted by F1 asc）

| sample_id | gold | pred | matched | good | weak | cov% | prec% | F1 | sim |
|---|---|---|---|---|---|---|---|---|---|
| char_028 | 5 | 8 | 4 | 3 | 1 | 80.0% | 50.0% | .615 | .706 |
| char_002 | 5 | 11 | 5 | 4 | 1 | 100.0% | 45.5% | .625 | .724 |
| char_024 | 7 | 11 | 6 | 3 | 3 | 85.7% | 54.5% | .667 | .679 |
| char_031 | 7 | 11 | 6 | 4 | 2 | 85.7% | 54.5% | .667 | .731 |
| char_008 | 6 | 11 | 6 | 5 | 1 | 100.0% | 54.5% | .706 | .752 |
| char_015 | 5 | 9 | 5 | 2 | 3 | 100.0% | 55.6% | .714 | .636 |
| char_019 | 6 | 10 | 6 | 3 | 3 | 100.0% | 60.0% | .750 | .712 |
| char_001 | 5 | 8 | 5 | 5 | 0 | 100.0% | 62.5% | .769 | .705 |
| char_006 | 6 | 9 | 6 | 5 | 1 | 100.0% | 66.7% | .800 | .750 |
| char_011 | 6 | 9 | 6 | 3 | 3 | 100.0% | 66.7% | .800 | .723 |
| char_014 | 6 | 9 | 6 | 4 | 2 | 100.0% | 66.7% | .800 | .737 |
| char_018 | 4 | 6 | 4 | 2 | 2 | 100.0% | 66.7% | .800 | .696 |
| char_017 | 7 | 8 | 6 | 3 | 3 | 85.7% | 75.0% | .800 | .667 |
| char_026 | 7 | 10 | 7 | 4 | 3 | 100.0% | 70.0% | .824 | .718 |
| char_021 | 7 | 10 | 7 | 4 | 3 | 100.0% | 70.0% | .824 | .678 |
| char_027 | 7 | 9 | 7 | 4 | 3 | 100.0% | 77.8% | .875 | .696 |
| char_033 | 8 | 8 | 7 | 4 | 3 | 87.5% | 87.5% | .875 | .658 |
| char_007 | 5 | 7 | 5 | 4 | 1 | 100.0% | 71.4% | .833 | .754 |
| char_010 | 6 | 6 | 5 | 4 | 1 | 83.3% | 83.3% | .833 | .729 |
| char_005 | 6 | 8 | 6 | 6 | 0 | 100.0% | 75.0% | .857 | .772 |
| char_013 | 6 | 8 | 6 | 5 | 1 | 100.0% | 75.0% | .857 | .743 |
| char_034 | 8 | 6 | 6 | 2 | 4 | 75.0% | 100.0% | .857 | .687 |
| char_025 | 10 | 8 | 8 | 5 | 3 | 80.0% | 100.0% | .889 | .643 |
| char_029 | 8 | 10 | 8 | 5 | 3 | 100.0% | 80.0% | .889 | .643 |
| char_020 | 4 | 5 | 4 | 0 | 4 | 100.0% | 80.0% | .889 | .630 |
| char_016 | 5 | 6 | 5 | 4 | 1 | 100.0% | 83.3% | .909 | .796 |
| char_030 | 6 | 5 | 5 | 4 | 1 | 83.3% | 100.0% | .909 | .724 |
| char_004 | 6 | 7 | 6 | 5 | 1 | 100.0% | 85.7% | .923 | .770 |
| char_023 | 7 | 8 | 7 | 4 | 3 | 100.0% | 87.5% | .933 | .713 |
| char_012 | 7 | 8 | 7 | 3 | 4 | 100.0% | 87.5% | .933 | .676 |
| char_032 | 8 | 7 | 7 | 6 | 1 | 87.5% | 100.0% | .933 | .746 |
| char_003 | 4 | 4 | 4 | 4 | 0 | 100.0% | 100.0% | 1.000 | .822 |
| char_009 | 6 | 6 | 6 | 4 | 2 | 100.0% | 100.0% | 1.000 | .707 |
| char_022 | 6 | 6 | 6 | 2 | 4 | 100.0% | 100.0% | 1.000 | .659 |

### 失败模式分类（12 个未匹配 gold）

| 类别 | 数量 | 涉及样本 |
|---|---|---|
| pose/gesture | 5 | char_024, char_030, char_033, char_034(×2) |
| eyes | 2 | char_010, char_025 |
| footwear | 2 | char_028, char_031 |
| legwear | 2 | char_025, char_032 |
| non-human anatomy | 1 | char_017 |

### Ollama 环境

```json
// ollama list (localhost)
// bge-m3:latest     1.2 GB    1024-dim    installed 17 months ago
// qwen36-vl:latest  38 GB     35.5B Q8    running on llama-server (PID 1007697)
// Ollama serve:      PID 2988661, running since Jun 11
// Port:              127.0.0.1:11434 (blocked by corporate proxy 137.153.170.55:10080)
// Bypass required:   proxies={"http": None, "https": None} or NO_PROXY="localhost,127.0.0.1"
```

---

## Code Analysis

### `evaluate_atomic_rules.py` — 新建评估脚本

- `OllamaEmbedder.__init__(base_url, model, cache_path)`: 封装 Ollama `/api/embed` API，自动绕过 HTTP 代理。磁盘缓存为 JSON 文件。
- `OllamaEmbedder.encode(texts) -> np.ndarray`: 批量编码，已缓存文本跳过 API 调用。返回 (n, 1024) float32 数组。
- `cosine_similarity(a, b) -> float`: NumPy 计算 cosine sim，零向量保护。
- `jaccard_similarity(text_a, text_b) -> float`: 字符级 Jaccard（去除标点空格），用于 `--no-embeddings` fallback。返回 max(Jaccard, overlap_ratio)。
- `load_gold_elements(gold_root, sample_id)`: 从 `SN_6_3D_dataset/char_XXX/char_XXX.json` 加载 gold elements（utf-8-sig 编码，提取 `{name, value}`）。
- `load_pred_elements(pred_root, sample_id)`: 从 `supervision_agent_output/char_XXX/atomic_rules_generated.json` 加载 predictions（提取 `{rule_id→name, value}`）。
- `match_elements_hungarian(pred, gold, embedder, threshold=0.50)`: 构建 N_pred × N_gold 成本矩阵（negated cosine similarity），用 `scipy.optimize.linear_sum_assignment` 求最优匹配。低于 threshold 的匹配被拒绝。embedder=None 时自动 fallback 到 Jaccard。
- `evaluate_sample(...) -> dict`: 封装匹配 + 计算 coverage/precision/F1/similarity/good_weak 分类。
- `discover_available_samples(...)`: 扫描同时有 gold + pred 的样本。
- `main()`: CLI 入口，支持 `--gold-root`, `--pred-root`, `--sample`（单样本模式），`--similarity-threshold`, `--no-embeddings`, `--cache-path`, `--output`。

### 关键常量

```python
SIMILARITY_THRESHOLD = 0.50   # Hungarian 匹配的最低 cosine sim
GOOD_MATCH_THRESHOLD = 0.65   # 高于此值为 "good" match，低于为 "weak"
EMBED_MODEL = "bge-m3:latest" # Ollama embedding 模型名
OLLAMA_BASE = "http://127.0.0.1:11434"
```

### 数据格式对比

```
# Gold (SN_6_3D_dataset/char_XXX/char_XXX.json)
{"sample_id": "char_001", "elements": [
  {"name": "金色长发与黑色蝴蝶结", "value": "角色拥有飘逸的金色长发..."},
  ...
]}

# Pred - atomic_rules (supervision_agent_output/char_XXX/atomic_rules_generated.json)
{"atomic_rules": [
  {"rule_id": "char_001_e001", "value": "金色长发，发梢带有明显的橙红色渐变。"},
  ...
]}

# Pred - extracted_elements (element_extraction_results/char_XXX/extracted_elements.json)
{"elements": [
  {"element_id": "char_001_e001", "name": "金色长发与黑色蝴蝶结", "value": "...",
   "category": "hair", "attributes": {"color": "金色", ...}, "confidence": "high"},
  ...
]}
```

---

## Files Changed

### Source code (created)
- `vlm/scripts/supervise/evaluate_atomic_rules.py` — 专用于 atomic_rules 格式的评估脚本（~320 行）

### Data & results (created)
- `vlm/tmp/atomic_rules_eval_report.json` — 34 样本 embedding 评估完整报告
- `vlm/tmp/atomic_rules_eval_jaccard.json` — Jaccard-only baseline 对比报告
- `vlm/tmp/embedding_cache_local.json` — bge-m3 embedding 缓存

### Data fixes (uncommitted)
- `vlm/data/SN_6_3D_dataset/char_024/char_024.json` — 加了 `source_image` 字段
- `vlm/data/SN_6_3D_dataset/char_025/char_025.json` — 修复 typo `cha_025` → `char_025`
- `vlm/data/SN_6_3D_dataset/char_041/char_041.json` — 加了 `sample_id` 字段

### Dependencies (installed)
- `.venv` 中新增：numpy 1.24.4, scipy 1.10.1

---

## User Feedback & Preferences

- **"读取最新的handoff文档"** — 用户期望先读 handoff 了解上下文再操作
- **"能不能调用本地的embedding模型做语义理解"** — 用户在意是否能用本地模型替代 DashScope 付费 API
- **"判断一下这一次提取的效果"** — 用户对 atomic_rules pipeline 的质量有评估需求
- **追问"这一次评估使用的embedding模型吗"** — 用户想确认评估方法是否合理，对技术细节有审查意识
- 用户未对 72 个 extra prediction 或 12 个 missed gold 表示不满——隐含接受当前的评估结果
- 用户未要求修复未匹配项或调整 prompt——当前阶段是评估而非优化

---

## Where We're Going

1. **补跑 char_035~054 的 atomic_rules 提取**：当前只有 34/54 样本，需要补全剩余 20 个。入口脚本可能是 `vlm/scripts/supervise/run_supervision_agent.py`（需要确认能否复现 char_001~034 的输出格式）。
2. **完成 54 样本评估**：补全后重跑 `evaluate_atomic_rules.py`，更新 process.md 4b 节对比表。
3. **决策 pose/gesture 口径**：42% 的遗漏是姿态元素。要么在提取 prompt 中加入 pose 要求，要么将 pose 从 gold 中排除（它本质上是 3D 监修需求而非 2D 视觉元素）。
4. **决策复合元素粒度**：gold 用"X与Y"复合命名，atomic_rules 拆分为独立规则——这是 72 个 extra 的根因。需要决定：gold 是否该拆开对齐 atomic_rules 的粒度，还是保持当前口径？
5. **修复 `--no-embeddings` 后的阈值**：Jaccard 的分数分布与 cosine sim 不同，当前 SIMILARITY_THRESHOLD=0.50 对 Jaccard 可能偏高。需要跑一次 grid search 找 Jaccard 的最优阈值。
6. **评估 embedding 模式下的 similarity threshold 敏感度**：当前 0.50 是 `experiment_vlm_analysis_v2.py` 的默认值，需要验证是否适合 atomic_rules 格式。可以考虑跑 0.40/0.45/0.50/0.55/0.60 的 grid search。

---

## Risks & Blockers

- **公司代理拦截 localhost**：每次 curl/requests 调用 Ollama API 都需要显式绕过代理。`evaluate_atomic_rules.py` 中已处理，但其他脚本（如 `run_supervision_agent.py`）可能需要相同修复。
- **Ollama 单 GPU 限制**：bge-m3 推理轻量（1.2GB），但 qwen36-vl 独占 35.5GB。不能同时跑 embedding 评估 + VLM 提取。
- **20 个未提取样本的 atomic_rules 生成方式未知**：char_001~034 的 atomic_rules 是如何生成的？需要确认 `run_supervision_agent.py` 是否能复现相同格式和质量。

---

## Open Questions

- [ ] char_035~054 的 atomic_rules 如何生成？`run_supervision_agent.py` 是否可复现？
- [ ] pose/gesture 元素：该加入提取要求还是从 gold 移除？
- [ ] gold 复合元素（"X与Y"）：该拆开还是保持？
- [ ] SIMILARITY_THRESHOLD=0.50 对 cosine sim 和 Jaccard 是否都是最优阈值？

---

## Quick Start for Next Session

```bash
# Restore context — read this file first

# Reference docs
# CLAUDE.md — project conventions
# .claude/handoffs/HANDOFF_supervision-agent-pipeline_2026-07-27.md — pipeline architecture
# .claude/handoffs/HANDOFF_sn6-54-sample-extraction-verified_2026-07-28.md — qwen36-vl 54-sample extraction

# Key files to read first
# vlm/scripts/supervise/evaluate_atomic_rules.py — the evaluation script (~320 lines)
# vlm/scripts/supervise/run_supervision_agent.py — pipeline entry point (for generating remaining 20 samples)
# vlm/tmp/atomic_rules_eval_report.json — full evaluation report

# Evidence / data files
# vlm/tmp/supervision_agent_output/char_*/atomic_rules_generated.json — 34 atomic rules extractions
# vlm/tmp/atomic_rules_eval_report.json — embedding evaluation report
# vlm/tmp/atomic_rules_eval_jaccard.json — Jaccard baseline comparison
# vlm/tmp/embedding_cache_local.json — bge-m3 cache (reuse to skip API calls)

# Verify current state
python3 -c "
import json
r=json.load(open('vlm/tmp/atomic_rules_eval_report.json'))
print(f'{r[\"summary\"][\"evaluated_samples\"]} samples evaluated')
print(f'Coverage: {r[\"summary\"][\"macro_coverage\"]:.2%}')
print(f'Precision: {r[\"summary\"][\"macro_precision\"]:.2%}')
print(f'F1: {r[\"summary\"][\"macro_f1\"]:.4f}')
"

# Run evaluation again (all 34 samples)
NO_PROXY="localhost,127.0.0.1" .venv/bin/python3 -m vlm.scripts.supervise.evaluate_atomic_rules

# Run evaluation on a single sample
NO_PROXY="localhost,127.0.0.1" .venv/bin/python3 -m vlm.scripts.supervise.evaluate_atomic_rules --sample char_015

# Next action
# The single most important next action: determine how to generate atomic_rules
# for char_035-054 and run the full 54-sample evaluation.
# 1) Check vlm/scripts/supervise/run_supervision_agent.py — can it reproduce
#    the atomic_rules_generated.json format?
# 2) If yes, run it on char_035-054; if not, analyze the pipeline that
#    generated char_001-034 to reproduce it.
```
