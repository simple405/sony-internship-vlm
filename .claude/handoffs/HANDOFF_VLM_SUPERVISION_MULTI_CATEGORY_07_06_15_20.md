# Handoff: VLM 监修工作流 — 多品类视角语义规则与小批次处理

**Created:** 2026-07-06 15:20
**Branch:** main
**Session Duration:** ~30 min

---

## Summary

本次会话完成了三个主要工作：(1) 验证 `qwen_vl_image_tool.py` 可正常分析图片；(2) 配置 PreToolUse hook 防止 Claude Code 直接 Read 图片导致 DashScope 400 错误；(3) 梳理了当前工作流状态，明确了下一步任务——为 head_key_chain、plush、cake_roll、figurine 等品类编写视角语义规则并进行小批次测试。

---

## Work Completed

### Changes Made

- [x] 验证 `qwen_vl_image_tool.py` 对三张图片（head_key_chain/1784345, cake_roll/2175989, plush/2028681）均成功返回分析结果
- [x] 创建 PreToolUse hook 脚本 `C:\Users\ZhuanZ\.claude\hooks\pre_tool_use_block_image_read.py`，拦截图片 Read 调用并输出替代命令
- [x] 在 `C:\Users\ZhuanZ\.claude\settings.json` 添加 hooks 配置（PreToolUse → Read → hook 脚本）
- [x] 修复 hook 路径转义问题（反斜杠 → 正斜杠）

### Key Decisions

| Decision | Rationale | Alternatives Considered |
|----------|-----------|------------------------|
| 使用 Python hook 而非仅 permissions.deny | permissions.deny 已存在但仍触发了 400 错误，hook 可提供更友好的拦截提示 | 仅依赖 permissions.deny（不够可靠） |
| Hook 使用 exit code 2 + JSON 输出 | Claude Code hook 规范：exit 0 = allow, exit 2 = block with reason | 直接退出（无法传递阻止原因） |
| 使用正斜杠路径 `C:/Users/ZhuanZ/` | 反斜杠在 JSON 中被吞掉导致路径错误 | 双重转义 `\\\\`（更易出错） |

---

## Files Affected

### Created

- `C:\Users\ZhuanZ\.claude\hooks\pre_tool_use_block_image_read.py` — PreToolUse hook，拦截 .png/.jpg/.jpeg/.webp/.gif/.bmp/.tif/.tiff 的 Read 调用，输出替代 CLI 命令

### Modified

- `C:\Users\ZhuanZ\.claude\settings.json` — 添加 `hooks.PreToolUse` 配置块，matcher=Read，command 指向 hook 脚本（正斜杠路径）

### Read (Reference)

- `vlm/docs/workflows/process.md` — 当前工作流状态文档，包含已完成/待完成任务清单
- `vlm/config/supervision/category_rules.json` — 6 个品类的高层规则定义（head_key_chain, backpack, cake_roll, plush, dataset_QSitFigures, dataset_figurine）
- `vlm/scripts/supervise/run_backpack_supervision_review.py` — backpack 审核脚本，可作为其他品类审核脚本的模板
- `vlm/tmp/v3_schema_and_backpack_view_rules_20260706/qwen_prompt_v3_final_backpack.txt` — backpack 的 prompt 模板，包含 6 个 SECTION（PRODUCT SCOPE, STATUS CONVENTION, VIEW SEMANTICS, OUT-OF-SCOPE, PROPS, JUDGMENT PROCEDURE）
- `vlm/scripts/supervise/qwen_vl_image_tool.py` — Qwen VL 图片理解 CLI 工具
- `vlm/tmp/backpack_supervision_review_v3/2812503_.../qwen_prediction_qc_report_v3.csv` — QC 报告示例

---

## Technical Context

### 品类视角语义规则的核心概念

**视角语义规则**是 Prompt 中 SECTION 3 的指令文本，告诉 Qwen VL 如何理解每个品类商品的正面/侧面/背面。不同品类的"背面"含义不同：

| 品类 | FRONT | SIDE | BACK |
|------|-------|------|------|
| **backpack** | 背包正面（角色插图面板） | 侧面口袋/背带连接 | 背包背板+肩带（**不是角色背面**） |
| **head_key_chain** | 挂件正面（脸部） | 侧面 | 后脑勺（**是角色背面**） |
| **plush** | 玩偶正面 | 侧面 | 玩偶背面（**是角色背面**） |
| **cake_roll** | 蛋糕卷正面（脸部图案） | 圆柱侧面 | 螺旋纹面（**不是角色背面**） |
| **figurine** | 手办正面 | 侧面 | 手办背面（**是角色背面**） |
| **dataset_QSitFigures** | Q版坐姿正面 | 侧面 | 坐姿背面（**是角色背面**） |

关键区别：backpack 和 cake_roll 的"背面"是商品本身的结构面，而 head_key_chain、plush、figurine 的"背面"就是角色的背面。

### v3 Schema 状态约定

- `*_visible`: `visible` 或 `invisible`
- `*_status`（visible 时）: `correct` / `wrong color` / `wrong shape` / `extra`
- `*_status`（invisible 时）: `correct` / `wrong invisible`
- `result`: `correct`（无错误）/ `wrong`（有错误）
- **不使用** `correct invisible`，invisible + correct 即可

### 已有 Prompt 模板结构（backpack 为范例）

```
SECTION 1: PRODUCT SCOPE — 定义商品是什么
SECTION 2: STATUS CONVENTION — visible/status/result 规则
SECTION 3: VIEW SEMANTICS ⚠️ CRITICAL — 品类专属视角语义
SECTION 4: OUT-OF-SCOPE RULES — 范围外规则硬覆盖
SECTION 5: CHARACTER PROPS — 角色道具处理
SECTION 6: JUDGMENT PROCEDURE — 判断流程
```

### 数据集目录结构

```
vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d_no_rules/监修vlm数据/
├── head_only/
│   ├── head_key_chain/
│   │   └── {sample_id}/
│   │       ├── {sample_id}_head_keychain.png  (多视角生成图)
│   │       └── {sample_id}_atomic_rules.json  (原子规则)
│   └── cake_roll/
│       └── {sample_id}/
├── full body/
│   └── plush/
│       └── {sample_id}/
└── body_and_head/
```

### 已有的 Backpack 审核流程

1. `backpack_review_samples.json` 定义样本配置（source_image, multiview_image, atomic_rules, sample_id）
2. `run_backpack_supervision_review.py` 加载 prompt 模板 + 样本配置 → 调用 Qwen VL → 输出 JSON/CSV/QC 报告
3. 输出到 `vlm/tmp/backpack_supervision_review_v3/{sample_id}_v3_view_semantics_{timestamp}/`

### 配置

- API 密钥: `vlm/config/api.env`（QWEN_API_KEY）
- Qwen 模型: `qwen-vl-max`
- Schema: `vlm/config/supervision/supervision_agent_output_v3.schema.json`
- Category rules: `vlm/config/supervision/category_rules.json`

---

## Things to Know

### Gotchas & Pitfalls

- **不要用 Read 工具读取图片文件** — DashScope Anthropic 兼容接口会返回 400 "Unexpected item type in content"。使用 `qwen_vl_image_tool.py` 代替。
- PreToolUse hook 已配置拦截图片 Read，但旧会话如果已包含图片 tool_result 仍可能复现。
- `assign_merchandise_categories.py` 不要随意运行，可能重写 `sample_lists/*.txt`。
- RunningHub 补图前先查进程，跳过 `runninghub_blocked_samples.csv` 风控样本。
- CSV 文件使用 `utf-8-sig` 编码（Excel 兼容）。

### Assumptions Made

- head_key_chain 和 plush 的 back view 是角色背面（与 backpack/cake_roll 不同）
- 每个品类需要一个独立的 prompt 模板（SECTION 3 不同）
- 审核脚本可以泛化为多品类版本，或每个品类一个脚本

### Known Issues

- 当前只有 backpack 有完整的 prompt 模板和审核脚本
- 其他 5 个品类缺少视角语义规则和对应的审核配置

---

## Current State

### What's Working

- ✅ `qwen_vl_image_tool.py` — 三张图片测试均成功
- ✅ PreToolUse hook — 拦截图片 Read 并输出替代命令
- ✅ Backpack 审核流程 — prompt 模板 + 脚本 + 2 个样本已验证
- ✅ v3 schema + category_rules.json — 6 个品类高层规则已定义

### What's Not Working

- ❌ head_key_chain — 无 prompt 模板，无审核脚本
- ❌ cake_roll — 无 prompt 模板，无审核脚本
- ❌ plush — 无 prompt 模板，无审核脚本
- ❌ figurine (dataset_figurine) — 无 prompt 模板，无审核脚本
- ❌ dataset_QSitFigures — 无 prompt 模板，无审核脚本

---

## Next Steps

### Immediate (Start Here)

1. **为每个品类创建 prompt 模板**（参考 backpack 的 6-section 结构）
   - 重点：SECTION 3 视角语义需要针对每个品类的物理结构定制
   - 输出到 `vlm/prompts/supervision/` 或 `vlm/tmp/` 下
   - 品类优先级：head_key_chain → plush → cake_roll → figurine → QSItFigures

2. **为每个品类创建审核样本配置 JSON**
   - 参考 `vlm/config/supervision/backpack_review_samples.json` 格式
   - 从数据集中选取 2-3 个样本做首批测试

3. **泛化审核脚本或为每个品类创建独立脚本**
   - 选项 A：将 `run_backpack_supervision_review.py` 泛化为 `run_supervision_review.py`（接受 --category 参数）
   - 选项 B：每个品类复制一份脚本（更简单但不易维护）

### Subsequent

- 扩大 backpack 测试到 5-10 个样本
- 对每个品类运行小批次（2-3 样本）→ 检查 Qwen 输出 → 调整 prompt
- 等人工标注回来后运行 `build_annotation_products.py` → 自动质检 → 合并 gold annotations

### Blocked On

- 无阻塞项，可立即开始

---

## Related Resources

### 关键文件

- `vlm/docs/workflows/process.md` — 工作流状态总览
- `vlm/config/supervision/category_rules.json` — 品类规则定义
- `vlm/tmp/v3_schema_and_backpack_view_rules_20260706/qwen_prompt_v3_final_backpack.txt` — prompt 模板范例
- `vlm/scripts/supervise/run_backpack_supervision_review.py` — 审核脚本范例
- `vlm/scripts/supervise/qwen_vl_image_tool.py` — 图片理解 CLI

### Commands to Run

```bash
# 图片理解（替代 Read）
.venv/Scripts/python.exe -m vlm.scripts.supervise.qwen_vl_image_tool \
  --model qwen-vl-max --json \
  --prompt "请分析这张图中可见的角色/商品特征，输出用于监修的结构化 JSON。" \
  "path/to/image.png"

# 运行 backpack 审核
.venv/Scripts/python.exe -m vlm.scripts.supervise.run_backpack_supervision_review \
  --sample-config vlm/config/supervision/backpack_review_samples.json

# 查看数据集品类结构
ls "vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d_no_rules/监修vlm数据/"
```

---

## Open Questions

- [ ] 审核脚本应该泛化为多品类版本还是每个品类独立脚本？
- [ ] 每个品类首批测试应选取哪些样本？（需要查看各品类目录下有哪些 sample_id）
- [ ] dataset_QSitFigures 和 dataset_figurine 是否需要单独处理还是合并为 figurine？

---

## Session Notes

- 用户希望每个品类进行小批次处理（2-3 样本），而不是一次性大批量
- 用户需要理解"视角语义规则"是 prompt 文本而非输出文件（已解释）
- 用户需要理解 QC 报告的含义（已解释：验证 Qwen 输出是否符合 v3 schema 规范）
- PreToolUse hook 已配置并验证生效，后续会话无需再处理图片 Read 问题
