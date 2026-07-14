# Project State: VLM Supervision Pipeline
**Last updated:** 2026-07-14  
**Replaces:** all individual session handoffs 07-06 through 07-14

---

## Pipeline 架构

```
[2D原图]
  │
  ▼  run_element_extraction.py + element_extraction_from_2d.txt
Step 0: 元素提取 + 质量评估  ✅  98.2% gold coverage, 10 conflicts, 0 needs_review
  │     model: qwen3-vl-plus (DashScope API)
  │     eval:  evaluate_element_extraction.py --use-embeddings（现为默认）
  ▼
Step 1: Atomic Rules 生成    ✅  已有预生成产物（generated/ 三件套）
  │
  ├──▶ Step 2: 商品图 VLM 分析  ✅  37/40 样本（backpack 10/10，其余各缺1）
  │           model: qwen3-vl-plus, prompt: qwen_prompt_v3_*.txt
  │
  └──▶ Step 3: 人工标注         🔴 等待康宁姐提供人工标注 CSV
                │
                ▼
          Step 4: Rule Audit    🔴 等待
                │
                ▼
          Step 5: 候选对齐      🔴 等待（align_human_findings_to_atomic_rules.py）
                │
                ▼
          Step 6: Gold 生成     🔴 等待（build_verified_evaluation_gold.py）
                │
                ▼
          Step 7: 评估+迭代     🔴 未开发（compare_predictions.py 框架已有）
```

**主要阻塞：** Step 3 人工标注数据（康宁姐），是唯一卡点。

---

## 当前最终指标（Step 0，2026-07-14）

| 指标 | 值 |
|---|---|
| Gold 覆盖率 | **98.2%** |
| 预测总量 | 154（每样本平均 7.7 个） |
| 未覆盖 gold | 2（真实模型视觉遗漏，不可修） |
| 冲突数 | 10（~8 真实模型错误，~2 评估器配对噪声） |
| needs_review | **0**（embedding 模式下） |
| 样本数 | 20 |

---

## 关键技术决策（非代码显而易见的）

**Prompt 设计原则**  
反幻觉为首要规则，精准为主（5-8元素/角色），无合并规则。之前"宁多勿少"导致 needs_review=43，去掉合并规则后降到 9，开启 embedding 后降到 0。

**评估器 Composite Gold 处理**  
含"与"的复合金标（如"腰带与剑鞘"）会拆分为 sub-name 独立匹配，同一 pred 可覆盖多个 sub-name。整体 covered = all(sub_covered)。见 `audit_composite_gold_element()`。

**Embedding 增强（现为默认）**  
DashScope `text-embedding-v3`，batch_size=10（上限，超过返回400），阈值 0.75。embed 输入只用 `name + value`（过滤英文 category 噪声）。缓存在 `vlm/tmp/embedding_cache.json`（约 330 条向量），首次需调 API，之后走缓存。

**评估器 name-only gold_objects**  
gold value 文本包含配饰描述词，用 full text 会对 pred 注入假 family 要求。Coverage audit 用 `find_keyword_families(element_name(gold), ...)` 规避，relation_score 对 pred 仍用 full text（正常）。

**模型选择**  
- API：`qwen3-vl-plus`（当前账号可用，98.2%）  
- `qwen3-vl-32b-instruct` 在当前账号**不可用**  
- 本地备选：`qwen3-vl:30b-a3b-instruct`（MoE，实际激活3B，24GB单卡可跑，ollama支持）

---

## Gotchas

- 评估器读取 `vlm/data/element_extraction_results/` 下**所有** `extracted_elements.json`，不区分模型。评估新模型前必须先全量重跑，否则混入旧结果。
- `vlm/tmp/` 曾被清空，embedding cache 需重建（首次跑 `--use-embeddings` 会自动重建）。
- DashScope `text-embedding-v3` batch size 上限 10，不是 25。
- `vlm/config/api.env` 禁止 commit。
- 不要用 Read 工具直接读图片，用项目 CLI。

---

## 关键文件路径

```
提取脚本:   vlm/scripts/supervise/run_element_extraction.py
提取 prompt:vlm/prompts/supervision/element_extraction_from_2d.txt
评估脚本:   vlm/scripts/supervise/evaluate_element_extraction.py
评估报告:   vlm/data/element_extraction_results/evaluation_report.json
Pred 数据:  vlm/data/element_extraction_results/char_*/extracted_elements.json
Gold 数据:  vlm/data/SN_6期动漫数据标注/char_*/char_*.json
Embedding:  vlm/scripts/supervise/embedding_scorer.py
Step2 结果: vlm/tmp/multicategory_supervision_review_v3/{品类}/{sample_id}_v3_*/
商品图:     vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated/
流程文档:   vlm/docs/workflows/process.md
```

---

## 常用命令

```bash
# 全量提取
"D:\索尼实习\.venv\Scripts\python.exe" -m vlm.scripts.supervise.run_element_extraction --model qwen3-vl-plus --workers 5

# 评估（embedding 现为默认）
"D:\索尼实习\.venv\Scripts\python.exe" -m vlm.scripts.supervise.evaluate_element_extraction

# 查看评估摘要
"D:\索尼实习\.venv\Scripts\python.exe" -c "import json; d=json.load(open('vlm/data/element_extraction_results/evaluation_report.json',encoding='utf-8')); print(json.dumps(d['summary'],indent=2,ensure_ascii=False))"

# 收到人工标注数据后
"D:\索尼实习\.venv\Scripts\python.exe" -m vlm.scripts.supervise.validate_human_annotations --input <csv路径>
```

---

## 可选后续改进（非阻塞）

- 给 prompt 加发长定义（短/中/长发）—— 可能消除 char_008/016 的形状冲突（约 2 个）
- 清理历史大文件：`vlm/data/legacy/`(572M)、`raw_trials/`(193M)、`safebooru_2d/`(2.6G)
- 补跑 Step 2 缺失的 3 个样本（非关键路径）

---

_Consolidated from sessions 07-06 through 07-14._
