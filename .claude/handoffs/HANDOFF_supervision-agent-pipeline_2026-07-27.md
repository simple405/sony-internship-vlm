# Handoff: 监修 Agent 端到端 Pipeline 实现

**Created:** 2026-07-27
**Branch:** main
**Session Duration:** ~1.5 小时

---

## 摘要

本次会话完成了监修 agent 架构的统一定义和端到端 pipeline 实现。核心结论：监修 agent 输入只有 2D 原图 + 商品设计图，atomic_rules 由 agent 内部自动生成，生图链路（RunningHub/IC-Light）属于上游，不是 agent 的组成部分。`run_supervision_agent.py` 已实现并通过 dry-run 验证，下一步是在 `SN_6_3D_dataset` 上跑真实端到端。

---

## Work Completed

### Changes Made

- [x] 更新 `vlm/docs/workflows/process.md`：新增 1b 节统一定义监修 agent 架构，重写第 6 节下一步（最高优先级改为端到端串联），更新日期
- [x] 创建 `vlm/scripts/supervise/run_supervision_agent.py`：端到端监修 agent 入口脚本
- [x] 创建 `vlm/prompts/supervision/qwen_prompt_v3_figurine.txt`：PVC 手办品类监修 prompt
- [x] dry-run 验证 pipeline 两端都能正常串联

### Key Decisions

| Decision | Rationale | Alternatives Considered |
|---|---|---|
| atomic_rules 由 agent 内部生成，不作为外部输入 | 用户明确要求：输入只有 2D 原图 + 商品设计图 | 沿用旧的 3 件套（含 atomic_rules）输入格式 |
| 生图链路从监修 agent 中剥离 | 监修 agent 职责边界清晰，生图属于上游 | 生图链路作为 agent 可选模块 |
| 直接 import 两个现有脚本的核心函数 | 避免重复代码，两个脚本逻辑已成熟 | 重写或 subprocess 调用 |
| figurine side/back 全部硬性 invisible+correct | 输入只有前视图单张，side/back 无法判断 | 尝试从正面图推断侧面信息 |
| 使用 `SN_6_3D_dataset` 做端到端测试 | 20 个样本已有 2D 原图 + 前视图 PNG，格式完全匹配 | 先做单样本冒烟再扩 |

---

## Files Affected

### Created

- `vlm/scripts/supervise/run_supervision_agent.py` — 端到端监修 agent 主入口，串联 Step 1（元素提取）→ Step 2（VLM 监修审查）
- `vlm/prompts/supervision/qwen_prompt_v3_figurine.txt` — PVC 手办品类 prompt（前视图单张，side/back 硬性 invisible+correct）

### Modified

- `vlm/docs/workflows/process.md` — 新增 1b 节（agent 架构定义），重写第 6 节（下一步优先级），更新日期到 2026-07-27

### Read (Reference)

- `vlm/scripts/supervise/run_element_extraction.py` — 理解元素提取接口（`run_sample()` 函数签名、输出格式 `element_extraction.v1`）
- `vlm/scripts/supervise/run_multicategory_supervision_review.py` — 理解监修审查接口（`run_one_sample()` 函数签名、sample_config 格式）
- `vlm/prompts/supervision/qwen_prompt_v3_plush.txt` — 参考 prompt 结构
- `vlm/prompts/supervision/qwen_prompt_v3_backpack.txt` — 参考 prompt 结构
- `vlm/data/SN_6_3D_dataset/char_001/char_001.json` — 确认数据集格式

---

## Technical Context

### Pipeline 架构

```
CLI: --source <2D原图> --product <商品设计图> --category dataset_figurine --sample-id char_001
  ↓
Step 1: run_element_extraction.run_sample()
        输入: 2D 原图
        输出: vlm/tmp/supervision_agent_output/{id}/extraction/{id}/extracted_elements.json
              schema: element_extraction.v1，elements[].element_id + value
  ↓
Step 2: elements_to_atomic_rules()
        映射: element_id → rule_id，value → value
        写出: vlm/tmp/supervision_agent_output/{id}/atomic_rules_generated.json
  ↓
Step 3: run_multicategory_supervision_review.run_one_sample()
        输入: source_image, multiview_image, atomic_rules_generated.json, category
        输出: vlm/tmp/supervision_agent_output/{id}/review/{category}/{id}_v3_{timestamp}/
              qwen_prediction_v3.json, qwen_prediction_flattened_v3.csv, summary.json
  ↓
最终: vlm/tmp/supervision_agent_output/{id}/agent_summary.json
      含: element_count, billable_annotation_issue_count, overall_decision 等
```

### 数据集

`vlm/data/SN_6_3D_dataset/` — 20 个样本，每个含：
- `char_XXX.png` → `--source`（2D 原图）
- `char_XXX_front_view.png` → `--product`（生成前视图）
- `char_XXX.json` → 含 elements 列表（agent 不使用此文件，会自动提取）

### 依赖关系

`run_supervision_agent.py` 直接 import：
- `vlm.scripts.supervise.run_element_extraction.run_sample`
- `vlm.scripts.supervise.run_element_extraction.load_env_file` / `DEFAULT_*`
- `vlm.scripts.supervise.run_multicategory_supervision_review.run_one_sample`

### Figurine Prompt 要点

- side/back 全部硬性 `invisible + correct`（单张前视图，无法判断）
- 材质判断：整体硬质 PVC 正常，不因"没有布料质感"判 wrong material
- 比例差异（立体化头身比变化）不算 wrong shape
- 相近色大类处理与其他品类一致

---

## Things to Know

### Gotchas & Pitfalls

- `run_element_extraction.run_sample()` 的 `sample` 参数需要手动构造 dict（`sample_id`, `json_path`, `source_image`, `image_path`），其中 `json_path` 即使文件不存在也可传入，该函数不读取它
- `run_multicategory_supervision_review` 的 `output_dir` 参数接收的是父目录，内部会再创建 `{category}/{sample_id}_v3_{timestamp}/` 子目录，所以 `agent_summary.json` 里的 `review_output_dir` 是带时间戳的深层路径
- `elements_to_atomic_rules()` 只保留有 `element_id` 和 `value` 的元素，空 value 会被跳过
- API key 从 `vlm/config/api.env` 读取 `QWEN_API_KEY`

### Assumptions Made

- 当前 `SN_6_3D_dataset` 的前视图均为 PNG，与脚本 `media_type()` 支持的格式一致
- `qwen3.7-plus` 模型的 API 配额足够跑 20 个样本（元素提取 + 监修各一次调用）

---

## Current State

### What's Working

- `run_supervision_agent.py` — 实现完成，dry-run 验证通过，语法无误
- `qwen_prompt_v3_figurine.txt` — 写入完成，已注册到 `CATEGORY_PROMPT_TEMPLATES["dataset_figurine"]`（该映射在 `run_multicategory_supervision_review.py:52`）
- `process.md` — 已更新，架构定义和下一步均已对齐

### What's Not Working

- 真实端到端未跑过（只做了 dry-run）——API 调用路径、输出 JSON 格式完整性、figurine prompt 的实际审查质量均未验证

### Tests

- [ ] 真实 API 端到端：未运行
- [x] dry-run 验证：通过（`char_001`，`dataset_figurine` 品类）
- [ ] 20 个样本批量跑：未运行

---

## Next Steps

### Immediate (Start Here)

1. **跑 char_001 真实端到端**，确认 API 调用正常、输出格式完整：
   ```powershell
   .venv\Scripts\python.exe -m vlm.scripts.supervise.run_supervision_agent `
       --source vlm/data/SN_6_3D_dataset/char_001/char_001.png `
       --product vlm/data/SN_6_3D_dataset/char_001/char_001_front_view.png `
       --category dataset_figurine `
       --sample-id char_001
   ```
   检查 `vlm/tmp/supervision_agent_output/char_001/agent_summary.json` 的 `overall_decision` 和 `element_count`

2. **检查 figurine prompt 质量**：看 `qwen_prediction_v3.json` 中各 rule 的 front_visible/front_status 是否符合预期，side/back 是否全部 invisible+correct

3. **如果 char_001 通过，批量跑 20 个样本**：
   ```powershell
   # 逐个跑（或写一个 batch 循环脚本）
   for id in char_001 char_002 ... char_020:
       .venv\Scripts\python.exe -m vlm.scripts.supervise.run_supervision_agent \
           --source vlm/data/SN_6_3D_dataset/${id}/${id}.png \
           --product vlm/data/SN_6_3D_dataset/${id}/${id}_front_view.png \
           --category dataset_figurine \
           --sample-id ${id}
   ```

### Subsequent

- 写 `batch_supervision_agent.py` 或 bash 脚本，对整个 `SN_6_3D_dataset` 目录批量调用 `run_supervision_agent`，汇总 overall_decision 分布
- 根据 char_001 的审查结果判断 figurine prompt 是否需要调整（特别是颜色/形状误判率）
- 新数据批次（用户提到可以按 `SN_6期动漫数据标注` 格式提供）到手后，扩充 evaluation gold，评估 precision/recall

### Blocked On

- 无硬性阻塞；需要用户确认 Qwen API 配额充足后可直接跑

---

## Commands to Run

```powershell
# 单样本端到端（从这里开始）
cd D:\索尼实习
.venv\Scripts\python.exe -m vlm.scripts.supervise.run_supervision_agent `
    --source vlm/data/SN_6_3D_dataset/char_001/char_001.png `
    --product vlm/data/SN_6_3D_dataset/char_001/char_001_front_view.png `
    --category dataset_figurine `
    --sample-id char_001

# 查看输出摘要
cat vlm/tmp/supervision_agent_output/char_001/agent_summary.json

# 查看详细审查结果（时间戳部分需要替换）
ls vlm/tmp/supervision_agent_output/char_001/review/dataset_figurine/
```

---

## Open Questions

- [ ] figurine prompt 的 side/back 硬性 invisible+correct 策略是否正确？还是应该尝试从正面图推断侧面可见元素？
- [ ] 新数据批次何时到手？格式与 `SN_6期动漫数据标注` 一致，还是有新的字段？
- [ ] 批量跑完后，evaluation 指标（precision/recall）如何计算？需要人工 gold 标注，还是用现有 `verified_evaluation_gold.csv` 作为参考？

---

_Session closed: 2026-07-27_
