# VLM 监修下一步流程

更新日期：2026-07-06 18:30 +08:00

## 当前结论

1. 人工标注回来前，先完善标注产物生成、Qwen baseline、prompt/视角规则和后续评测脚本。
2. v3 标注系统暂不新增 `excluded`；商品范围外的身体部位仍按 v3 表格填写：
   - `*_visible=invisible`
   - `*_status=correct`
   - `result=correct`
   - 不使用 `correct invisible`。
3. Qwen 已能按上面规则输出结构化 JSON，但仅靠通用 prompt 仍会误判 backpack 的 back view，需要加入品类视角语义。
4. Claude Code 已接入 Qwen API，但不要让 Claude Code 原生 `Read` 图片文件；百炼 Anthropic 兼容接口会拒绝 Claude Code 的 `tool_result` 图片消息，报 `Unexpected item type in content`。需要看图时使用项目内 Qwen-VL CLI，返回纯文本/JSON 给 Claude Code。
5. **人工标注采用三段式流程**（详见"人工标注 + 评估工作流"章节）：先建立人工视觉真值，再审核 atomic_rules 本身，最后融合出 verified gold。
6. **atomic_rules 不是天然 gold**：它是 Qwen review 的输入，也是需要被标注员审核的资产。评估时必须拆开 generation quality、atomic rule quality、Qwen review quality。

## 核心路径

```text
项目根目录: D:\索尼实习
数据集根目录: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20
试标数据集: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/multi_view试标数据集
人工标注说明: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/multi_view试标数据集/动漫IP多品类商品设计检修标注说明v3.pdf
API 环境变量: vlm/config/api.env
标注产物脚本: vlm/scripts/supervise/build_annotation_products.py
Claude Code 看图入口: vlm/scripts/supervise/qwen_vl_image_tool.py
```

## Claude Code + Qwen 图片理解修复

已完成：

- 新增 `vlm/scripts/supervise/qwen_vl_image_tool.py`，通过 `QWEN_API_KEY`、`QWEN_BASE_URL` 调用 OpenAI-compatible Qwen 视觉模型，并把图片理解结果作为纯文本/JSON 输出。
- 已在 `CLAUDE.md` 记录约束：Claude Code 不要直接 `Read` 图片文件；需要图片理解时调用 `qwen_vl_image_tool.py`。
- 已在 `C:\Users\ZhuanZ\.claude\settings.json` 增加图片后缀的 `permissions.deny`，拦截 `.png/.jpg/.jpeg/.webp/.gif/.bmp/.tif/.tiff` 直接读取，避免再次触发百炼 400。
- 已验证 `python -m vlm.scripts.supervise.qwen_vl_image_tool --model qwen-vl-max --json ...` 可以返回结构化 JSON。
- 已验证 Claude Code 直接 `Read` 图片会被权限拒绝，不再把图片作为 `tool_result image/base64` 发给 Qwen。
- 旧 Claude Code 会话历史中如果已经包含图片 `tool_result`，继续 resume 该会话仍可能复现 400；修复后请从新 Claude Code 会话开始，或用文本 handoff 接续。

Claude Code 中需要看图时使用：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.qwen_vl_image_tool `
  --model qwen-vl-max `
  --json `
  --prompt "请分析这张图中可见的角色/商品特征，输出用于监修的结构化 JSON。" `
  "path\to\image.png"
```

## 已有产物

```text
06.10 旧试标产物:
vlm/tmp/annotation_products_script_check_20260706

v3 schema 临时设计:
vlm/tmp/supervision_agent_output_schema_20260706

Qwen v3 单样本预测 (旧 prompt，back_visible 有误判):
vlm/tmp/qwen_v3_prediction_backpack_2807649_scope_as_correct_invisible_20260706
vlm/tmp/qwen_v3_prediction_backpack_2812503_invisible_status_correct_20260706

v3 schema 固化 + 视角语义规则:
vlm/tmp/v3_schema_and_backpack_view_rules_20260706

Qwen v3 修正 prompt 重跑 (新 prompt，back_visible 已修正):
vlm/tmp/backpack_supervision_review_v3/2812503_v3_view_semantics_20260706_135832
vlm/tmp/backpack_supervision_review_v3/2807649_v3_view_semantics_20260706_140006

对比报告:
vlm/tmp/backpack_supervision_review_v3/COMPARISON_REPORT.md

正式配置文件:
vlm/config/supervision/supervision_agent_output_v3.schema.json
vlm/config/supervision/supervision_agent_output_v3.example.json
vlm/config/supervision/backpack_review_samples.json

审核脚本:
vlm/scripts/supervise/run_backpack_supervision_review.py
vlm/scripts/supervise/run_multicategory_supervision_review.py
```

## 多品类视角语义规则 + 小批次测试

更新日期：2026-07-06 16:10

### 新增产物

```text
品类 Prompt 模板（6-section 结构，SECTION 3 视角语义按品类定制）:
vlm/prompts/supervision/qwen_prompt_v3_head_key_chain.txt
vlm/prompts/supervision/qwen_prompt_v3_plush.txt
vlm/prompts/supervision/qwen_prompt_v3_cake_roll.txt

多品类审核脚本（泛化 backpack 版本，自动匹配品类 prompt）:
vlm/scripts/supervise/run_multicategory_supervision_review.py

审核样本配置:
vlm/config/supervision/head_key_chain_review_samples.json
vlm/config/supervision/cake_roll_review_samples.json
vlm/config/supervision/plush_review_samples.json

小批次测试结果:
vlm/tmp/multicategory_supervision_review_v3/head_key_chain/
vlm/tmp/multicategory_supervision_review_v3/cake_roll/
vlm/tmp/multicategory_supervision_review_v3/plush/
```

### 小批次测试结果（每品类 2 个样本）

| 品类 | 样本 | QC PASS | QC FAIL | correct | wrong | 备注 |
|------|------|---------|---------|---------|-------|------|
| head_key_chain | 1784345 | 31/31 | 0 | 31 | 0 | ✅ |
| head_key_chain | 1906753 | 20/20 | 0 | 18 | 2 | hair_style + eye_color 视觉差异 |
| cake_roll | 2175989 | 19/19 | 0 | 30 | 0 | 11 WARN = 模型多余 + 自动填充 |
| cake_roll | 2175991 | 21/21 | 0 | 33 | 0 | 12 WARN = 同上 |
| plush | 2028681 | 26/26 | 0 | 25 | 1 | 1 个合理视觉差异 |
| plush | 2028685 | 29/29 | 0 | 27 | 4 | 2 WARN = 模型多余规则 |

**全部 6 个样本 QC FAIL = 0**。

### 修复的 3 个问题

1. **`wrong_color` → `wrong color` 下划线问题**：Qwen 输出的 status 值用下划线而非空格。脚本端添加 `normalize_prediction()` 后处理。
2. **`wrong invisible` 混淆**：Qwen 对预期不可见的特征（如 head_key_chain 背面的 eye_color）输出 `invisible + wrong invisible`，应为 `invisible + correct`。在 prompt SECTION 3 加入明确的示例和 `⚠️ CRITICAL STATUS RULE` 说明。
3. **out-of-scope 规则缺失**：Qwen 对 head_key_chain/cake_roll 跳过下半身规则而非输出 `invisible + correct`。在 prompt 中强调 "MUST OUTPUT EVERY RULE_ID" + 脚本端 `fill_missing_out_of_scope_rules()` 自动填充。

### 品类视角语义核心差异

| 品类 | BACK 视角含义 | 身体规则范围 |
|------|--------------|-------------|
| backpack | 背包背板（不是角色背面） | 下半身 out-of-scope |
| head_key_chain | 角色后脑勺（是角色背面） | 颈部以下全部 out-of-scope |
| cake_roll | 螺旋纹面（不是角色背面） | 全部身体/服装 out-of-scope |
| plush | 角色全身背面（是角色背面） | 全部 in-scope（全身产品） |

### 待处理

- figurine 和 QSItFigures 品类暂无生成数据集，等 RunningHub 补图后添加
- 扩大每品类测试到 5-10 个样本（样本配置已更新到 10 个，待运行 API 测试）
- 检查 Qwen 是否有多输出额外规则的倾向（WARN），考虑在 prompt 中约束只输出请求的 rule_id
- 将 Qwen 预测结果合并放入样本文件夹（backpack/2812503 已完成示例）

## 人工标注 + 评估工作流

更新日期：2026-07-06 18:30

### 设计原则

标注员的实际工作流是：先拿原始 2D 图和生成出来的 multi_view 图做视觉对比，填写监修标注 v3 表；随后再根据 2D 图判断 atomic_rules 是否正确。因此 atomic_rules 不能默认当 gold standard，它本身要先被审核。

新的主线是：

```text
2D 原图 + generated multi_view
        ↓
Stage 1：人工视觉监修标注
        ↓
得到 human_visual_findings / annotator_gold
        ↓
Stage 2：atomic_rules 正误审核
        ↓
得到 atomic_rule_audit
        ↓
Stage 3：融合 verified_evaluation_gold
        ↓
Stage 4：三类评估报告
```

评估口径拆成三类：

| 维度 | 问题 | 数据来源 |
|------|------|----------|
| Generation Quality | 生成图相对 2D 是否正确 | Stage 1 人工视觉监修 |
| Atomic Rule Quality | atomic_rules 是否正确覆盖 2D | Stage 2 atomic rule audit |
| Qwen Review Quality | Qwen 能否基于正确规则发现生成图问题 | verified gold vs Qwen prediction |

### 三段式标注流程

```text
                    2D 原图 + 3D 多视角生成图
                           │
                           ↓
        Stage 1: 人工视觉监修标注（不把 atomic_rules 当真值）
                           ↓
          human_visual_findings.csv + annotator_gold.csv
                           ↓
          Stage 2: atomic_rules 正误审核（只看 2D + rules）
                           ↓
                    atomic_rule_audit.csv
                           ↓
          Stage 3: build_verified_evaluation_gold.py
                           ↓
       verified_evaluation_gold.csv + coverage gaps + rule errors
                           ↓
          Stage 4: Qwen / generation / rules 三类评估
```

#### Stage 1：人工视觉监修

- **输入**：2D 原图 + 3D 多视角生成图
- **做什么**：标注员先记录生成图相对 2D 的真实视觉差异，再填写 v3 规则级表
- **产出**：`human_visual_findings.csv`、`annotator_gold.csv`
- **价值**：发现 atomic_rules 覆盖不到的问题，用于审计规则库完整性

#### Stage 2：atomic_rules 正误审核

- **输入**：2D 原图 + atomic_rules.json
- **做什么**：标注员判断每条 atomic rule 是否真实描述 2D 图
- **产出**：`atomic_rule_audit.csv`
- **价值**：把 rule extraction error 和 generation/Qwen error 拆开

#### Stage 3：融合 verified gold

- **输入**：`annotator_gold.csv` + `atomic_rule_audit.csv` + 可选 `human_visual_findings.csv`
- **做什么**：只保留 `rule_validity=correct` 且当前商品品类 in-scope 的规则进入 Qwen 评估 gold
- **产出**：`verified_evaluation_gold.csv`、`atomic_rule_quality_report.csv`、`coverage_gap_report.csv`
- **价值**：避免错误 atomic_rules 污染 Qwen review accuracy

### 样本文件夹结构（目标状态）

```text
{category}/{sample_id}/
├── 2d_original.jpg                      ← 原始角色图
├── multiview_design.png                 ← 多视角生成图
├── atomic_rules.json                    ← 原子规则定义
├── qwen_supervision_result.csv          ← Qwen 预测（已有）
├── qwen_supervision_result_summary.json ← Qwen 预测摘要
├── human_visual_findings.csv            ← 标注员 Stage 1 视觉发现（待标注回来）
├── annotator_gold.csv                   ← 标注员 Stage 1 v3 规则级表（待标注回来）
├── atomic_rule_audit.csv                ← 标注员 Stage 2 rule 正误审核（待标注回来）
└── verified_evaluation_gold.csv         ← Stage 3 融合输出（脚本生成）
```

### 标准 CSV schema

字段定义已固化到：

```text
vlm/config/supervision/human_annotation_csv_schemas.md
```

核心文件：

```text
human_visual_findings.csv
atomic_rule_audit.csv
annotator_gold.csv
verified_evaluation_gold.csv
```

### 脚本

已新增：

```text
vlm/scripts/supervise/validate_human_annotations.py
vlm/scripts/supervise/build_verified_evaluation_gold.py
```

待人工数据回来后再适配：

```text
convert_annotator_xlsx.py  # 等拿到实际 xlsx 格式后开发
compare_predictions.py     # 等 verified gold 和 Qwen 大批量结果就绪后开发
```

### 当前状态

- ✅ 样本文件夹结构已定义
- ✅ Qwen 预测结果合并示例已完成（backpack/2812503）
- ✅ 新工作流已拆成 Stage 1/2/3/4
- ✅ 标准 CSV schema 已定义
- ✅ 人工标注校验脚本已建立
- ✅ verified gold 融合脚本骨架已建立，支持无人工数据 dry-run
- ⏳ 等人工标注数据回来
- ⏳ 拿到实际 .xlsx 后开发 `convert_annotator_xlsx.py`
- ⏳ 有 verified gold 后开发 `compare_predictions.py`

## Qwen Baseline 发现的问题

已测样本：

```text
backpack/2807649
backpack/2812503
```

确认有效：

- Qwen 可以输出 v3 rule-level JSON。
- 范围外下半身规则可以通过 hard override 约束为 `visible=invisible,status=correct,result=correct`。
- 每次调用必须保存 prompt、脱敏 request、raw response、flattened CSV/JSONL、QC report。

必须修正：

- backpack 的 `back` 视角不是角色背面，而是背包背面。
- 角色头发、脸、眼睛、眼镜、胸前装饰、正面衣服细节等不能默认 `back_visible=visible`。
- 只有明确出现在背包背面的元素才可 `back_visible=visible`，例如背包背面图案、背带、背包装饰、背面实际可见的发饰/蝴蝶结。
- 后续 prompt 必须加入 category-specific view semantics，否则 Qwen 会把角色背面和商品背面混淆。

## 下一步

已完成：
- [x] 固化 v3 schema 到 `vlm/config/supervision/`
- [x] 更新 `build_annotation_products.py` 的 `INVISIBLE_STATUS_VALUES`
- [x] 为 backpack 写视角语义规则
- [x] 重写 Qwen baseline prompt（含 SECTION 3 view semantics）
- [x] 用修正 prompt 重跑 2807649 和 2812503 — **back_visible 误判全部修复**（2812503: 11 条修正，2807649: 8 条修正）
- [x] 编写可复用的审核脚本 `run_backpack_supervision_review.py`
- [x] 多品类 prompt 模板（head_key_chain, plush, cake_roll）
- [x] 多品类审核脚本 `run_multicategory_supervision_review.py`
- [x] 小批次测试 3 品类 × 2 样本 = 6 样本全部 QC FAIL = 0
- [x] 样本配置扩展到每品类 10 个样本（待运行 API 测试）
- [x] Qwen 预测结果合并到样本文件夹（backpack/2812503 示例完成）
- [x] 设计两阶段标注 + 三方对比评估工作流
- [x] 更新为三段式人工标注 + verified gold 工作流
- [x] 定义 human_visual_findings / atomic_rule_audit CSV schema
- [x] 新增 `validate_human_annotations.py`
- [x] 新增 `build_verified_evaluation_gold.py` dry-run 骨架

进行中：
- [ ] 扩大测试到 10 样本/品类（head_key_chain, cake_roll, plush）— 配置已就绪
- [ ] 扩大 backpack 测试到 10 样本 — 配置已就绪

等人工标注回来后：
1. 拿到 .xlsx → 开发 `convert_annotator_xlsx.py` 转标准格式
2. 开发 `compare_predictions.py` 三方对比脚本
3. 运行评估：Qwen 准确率 + atomic_rules 覆盖率
4. 错误分析 → 优化 prompt / 补充规则库
5. 决定下一步：prompt 够用还是需要做 LoRA/SFT

## RunningHub 补图

补图不是当前主线，只在需要恢复生成时处理。

规则：

1. 图生图走 RunningHub，环境变量是 `RUNNINGHUB_API_KEY`。
2. 不覆盖已有生成图；只补没有非 `_original.*` 生成图的样本。
3. 续跑前先查 RunningHub Python 进程。
4. 跳过 `runninghub_blocked_samples.csv` 里的风控样本。
5. 不要随意运行 `assign_merchandise_categories.py`，它可能重写 `sample_lists/*.txt`。

查进程：

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'python|pythonw' -and $_.CommandLine -match 'runninghub|generate_head_keychain|run_runninghub' } |
  Select-Object ProcessId,Name,CommandLine |
  Format-List
```
