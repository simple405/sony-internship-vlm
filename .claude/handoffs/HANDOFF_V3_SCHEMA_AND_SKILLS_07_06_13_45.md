# Handoff: V3 Schema 固化 + Backpack 视角语义规则 + 工程化 Skills 安装

**Created:** 2026-07-06 14:00 +08:00 (updated)
**Branch:** main
**Session Duration:** ~4 小时

---

## Summary

本会话完成了三件事：(1) 分析了整个 VLM 监修项目的结构和进度，确认当前处于"监修审核"阶段；(2) 固化了 v3 输出 schema（去掉 `correct invisible`，改用 `invisible + correct`），编写了 backpack 品类视角语义规则，生成了示例输出文件；(3) 研究并安装了 4 个工程化 skills（Superpowers、GSD Core、/atomic-commit、/handoff）。

---

## Work Completed

### Changes Made

- [x] 创建 v3 固化 schema（`supervision_agent_output_v3_final.schema.json`）—— 移除 `correct invisible`，拆分为 `view_status_visible` 和 `view_status_invisible` 两个子定义
- [x] 创建 v3 示例输出（`supervision_agent_output_v3_final.example.json`）—— 使用 backpack/2812503 的 27 条规则，展示正确的 back_visible 判断
- [x] 编写 backpack 视角语义规则文档（`backpack_view_semantics.md`）—— 核心原则：背包的 front/side/back 指的是背包自身的面，不是角色的朝向
- [x] 编写整合了视角语义的 Qwen prompt 模板（`qwen_prompt_v3_final_backpack.txt`）—— 6 个 section 结构
- [x] 生成 flattened CSV/JSONL/QC 报告（3 个文件，27 条规则全部 PASS）
- [x] 安装 `/atomic-commit` 命令到 `.claude/commands/`
- [x] 安装 `/handoff` 命令到 `.claude/commands/`
- [x] 安装 GSD Core（69 个 skills）到 `~/.claude/skills/`
- [x] 克隆 Superpowers（14 个 skills）到 `~/.claude/plugins/superpowers/`
- [x] 修复 Superpowers 激活问题：将 skills 从 plugins/ 复制到 `~/.claude/skills/`（因为 `/plugin install` 在 VS Code 环境中不可用）
- [x] 创建项目 `CLAUDE.md`，引导 Claude 在新会话中使用已安装的 skills

### Key Decisions

| Decision | Rationale | Alternatives Considered |
|----------|-----------|------------------------|
| 移除 `correct invisible`，统一用 `invisible + correct` | process.md 已确定此约定；简化 status 枚举，减少 Qwen 输出混淆 | 保留 `correct invisible` 作为独立状态值 |
| Backpack 背面：角色正面特征一律 invisible | Qwen 把 11 条角色特征错误标为 `back_visible=visible`，核心误判原因是混淆"角色背面"和"商品背面" | 逐条规则判断是否可见（太细碎，不通用） |
| `headwear_ribbon` 在背面标为 visible | 贝雷帽蝴蝶结系在帽子后方，物理上延伸到背包背板上沿，是实际存在于背包背面的元素 | 全部头饰在背面 invisible（过于粗暴） |
| 修正 Plan C 去掉 `/todo` | `/todo` 的 worktree 管理和 GSD Core 冲突，COMMIT 模型和 `/atomic-commit` 冲突，Superpowers 已覆盖其功能 | 保留 `/todo` 并手动避免冲突 |
| Superpowers = 微观自动层，GSD Core = 宏观手动层 | 两者在不同粒度工作：Superpowers 自动触发单会话方法论，GSD Core 手动触发跨会话项目管理 | 只用其中一个 |

---

## Files Affected

### Created

- `vlm/tmp/v3_schema_and_backpack_view_rules_20260706/README.md` - 变更说明 + 后续待办
- `vlm/tmp/v3_schema_and_backpack_view_rules_20260706/supervision_agent_output_v3_final.schema.json` - 固化后的 v3 JSON Schema
- `vlm/tmp/v3_schema_and_backpack_view_rules_20260706/supervision_agent_output_v3_final.example.json` - backpack/2812503 的 27 条规则示例
- `vlm/tmp/v3_schema_and_backpack_view_rules_20260706/backpack_view_semantics.md` - Backpack 品类视角语义规则（中文）
- `vlm/tmp/v3_schema_and_backpack_view_rules_20260706/qwen_prompt_v3_final_backpack.txt` - 整合视角语义的 Qwen prompt
- `vlm/tmp/v3_schema_and_backpack_view_rules_20260706/flattened_rules_v3.csv` - 27 条规则的扁平 CSV
- `vlm/tmp/v3_schema_and_backpack_view_rules_20260706/flattened_rules_v3.jsonl` - 27 条规则的扁平 JSONL
- `vlm/tmp/v3_schema_and_backpack_view_rules_20260706/qc_report_v3.csv` - QC 报告（27 条全部 PASS）
- `.claude/commands/atomic-commit.md` - 原子提交 skill
- `.claude/commands/handoff.md` - 会话交接 skill
- `CLAUDE.md`（项目根目录）- 项目说明 + skills 使用引导

### Read (Reference)

- `README.md` - 项目总览
- `vlm/README.md` - VLM workspace 结构
- `vlm/docs/workflows/process.md` - 当前工作流和下一步规划（核心参考）
- `vlm/config/supervision/category_rules.json` - 6 个品类的规则定义
- `vlm/scripts/supervise/review_schemas.py` - ReviewPair/Finding/ReviewResult 等 dataclass 定义
- `vlm/scripts/supervise/build_annotation_products.py` - 标注产物生成脚本（V3_COLUMNS, qc_v3 函数）
- `vlm/tmp/supervision_agent_output_schema_20260706/` - 旧版 v3 schema 设计
- `vlm/tmp/qwen_v3_prediction_backpack_2812503_invisible_status_correct_20260706/` - Qwen 预测输出（27 条规则，全部 correct，但 back_visible 有误判）
- `vlm/tmp/qwen_v3_prediction_backpack_2807649_scope_as_correct_invisible_20260706/` - 另一个 Qwen 预测样本
- `vlm/tmp/v3_single_sample_output_20260706/flattened_rules_v3.csv` - CSV 格式参考

---

## Technical Context

### Architecture/Design Notes

**V3 Schema 核心设计**：
- 每条规则 = `{rule_id, value, front_visible, front_status, side_visible, side_status, back_visible, back_status, result, confidence, reason, evidence}`
- `visible` 只能是 `visible` / `invisible`
- `status` 枚举：`correct`, `wrong color`, `wrong shape`, `extra`, `wrong invisible`（共 5 个值）
- 当 `visible=visible` → status 只能是 `correct`/`wrong color`/`wrong shape`/`extra`
- 当 `visible=invisible` → status 只能是 `correct`/`wrong invisible`
- `result` 由三个视角 status 自动汇总：任一 status 为 error → `wrong`，否则 → `correct`

**Backpack 视角语义核心**：
- front = 背包正面板上的角色插画（头部+上身）
- side = 背包侧面实际可见元素
- back = 背包背板 + 肩带（不是角色背面！）
- 范围外规则（下半身）：hard override 为全视角 invisible+correct
- 角色道具（has_bag, bag_color）：默认全视角 invisible+correct

**Qwen API 调用方式**：
- atomic_rules 是内联到 prompt 文本中的（不是独立字段）
- 两张图片以 base64 编码传入（source_2d + multiview_design）
- 使用 `response_format: {type: "json_object"}` 确保输出 JSON

### Dependencies

- GSD Core v1.6.1（通过 npx 安装到 `~/.claude/`）
- Superpowers（git clone 到 `~/.claude/plugins/superpowers/`，**尚未通过 /plugin install 激活**）
- Python 环境已有：PIL, requests, openpyxl, tqdm, numpy, pymupdf

### Configuration Changes

- `.claude/commands/` 目录新建，包含 `atomic-commit.md` 和 `handoff.md`
- `~/.claude/skills/` 新增 69 个 GSD Core skills（`gsd-*` 前缀）
- `~/.claude/plugins/superpowers/` 新增 14 个 Superpowers skills

---

## Things to Know

### Gotchas & Pitfalls

- **Superpowers 已激活**：skills 已复制到 `~/.claude/skills/`，Claude Code 自动发现（无需 `/plugin install`）。VS Code 环境不支持 `/plugin` 命令，但手动复制 skills 文件效果等价。
- **GSD Core 安装时 statusline 步骤崩溃**：TypeError on `statuslineRuntimes.includes(r.runtime)`，但核心安装（69 skills + agents + hooks）已成功完成，不影响使用
- **build_annotation_products.py 需要更新**：`INVISIBLE_STATUS_VALUES` 需要从 `{"correct invisible", "wrong invisible"}` 改为 `{"correct", "wrong invisible"}` 以匹配新 schema
- **现有数据需要批量替换**：所有使用 `correct invisible` 的标注数据需要替换为 `correct`
- **`vlm/config/api.env` 包含真实 API 密钥**：已被 `.gitignore` 覆盖（`vlm/config/*.env` 规则），不要提交

### Assumptions Made

- `headwear_ribbon` 在背包背面可见是基于"蝴蝶结物理上延伸到背板上沿"的假设——需要看实际商品图确认
- 示例中 27 条规则全部 `result=correct`——实际商品图可能确实没问题，也可能有 Qwen 未发现的错误

### Known Issues

- Qwen 对 backpack back view 的误判尚未用修正后的 prompt 重新验证
- 只为 backpack 写了视角语义规则，其他 5 个品类（head_key_chain, cake_roll, plush, dataset_QSitFigures, dataset_figurine）尚未写
- 评测脚本（对比 Qwen 预测 vs 人工标注）尚未创建

---

## Current State

### What's Working

- v3 schema 设计 ✅ —— JSON Schema + 示例 + CSV 已生成并通过 QC
- Backpack 视角语义规则 ✅ —— 文档完成，覆盖了 27 条规则的判断
- Qwen prompt 模板 ✅ —— 6 section 结构，包含视角语义
- 工程化 skills 安装 ✅ —— 4 个组件全部就位并激活（Superpowers 14 skills + GSD Core 69 skills + 2 个自定义命令）
- `/handoff` 命令 ✅ —— 已验证可用（本会话成功运行了两次）

### What's Not Working

- 修正后的 prompt 尚未实际调用 Qwen API 验证效果
- `build_annotation_products.py` 的 QC 逻辑尚未更新以匹配新 schema

### Tests

- [x] v3 schema QC：27 条规则全部 PASS
- [ ] Qwen API 重跑验证：未测试
- [ ] 人工标注对比：等待人工标注返回

---

## Next Steps

### Immediate (Start Here)

1. **用修正后的 prompt 重跑 backpack/2807649 和 backpack/2812503**：
   - prompt 文件：`vlm/tmp/v3_schema_and_backpack_view_rules_20260706/qwen_prompt_v3_final_backpack.txt`
   - 需要把 atomic_rules 内联到 prompt 中
   - 对比新旧预测的 `back_visible` 差异，确认 11 条误判已修复
2. **更新 `build_annotation_products.py`**：将 `INVISIBLE_STATUS_VALUES` 从 `{"correct invisible", "wrong invisible"}` 改为 `{"correct", "wrong invisible"}`
3. **将 v3 schema 从 tmp 移到正式位置**：`vlm/config/supervision/`

### Subsequent

- 将 v3 schema 从 tmp 移到 `vlm/config/supervision/` 正式位置
- 为其他品类（head_key_chain, plush, figurine 等）写视角语义规则
- 扩大到 5-10 个样本测试
- 创建评测脚本（对比 Qwen 预测 vs 人工标注 gold annotations）

### Blocked On

- 人工标注尚未返回（依赖外部标注员）
- 实际 backpack 商品图确认（headwear_ribbon 是否真的在背板可见）

---

## Related Resources

### Documentation

- 项目进度文档：`vlm/docs/workflows/process.md`（2026-07-06 更新）
- 开发计划：`vlm/docs/workflows/supervision_agent_development_plan.md`（~2000 行详细计划）
- 本次输出目录：`vlm/tmp/v3_schema_and_backpack_view_rules_20260706/`

### Commands to Run

```bash
# 激活 Superpowers（新会话中）
/plugin install superpowers@claude-plugins-official

# 查看 GSD 项目进度
/gsd-progress

# 开始新项目规划
/gsd-new-project

# 原子提交当前改动
/atomic-commit

# 会话结束前保存进度
/handoff
```

### Search Queries

- `grep -r "correct invisible" vlm/scripts/` - 找到所有需要更新为 `correct` 的代码位置
- `grep -r "INVISIBLE_STATUS_VALUES" vlm/` - 找到 QC 逻辑需要修改的位置
- `grep -r "back_visible" vlm/tmp/qwen_v3_prediction_backpack*/` - 查看所有 backpack 预测的 back_visible 值

---

## Open Questions

- [ ] `headwear_ribbon` 在背包背面是否真的可见？需要看实际商品图确认
- [ ] 其他品类的视角语义规则怎么写？（plush 和 figurine 是全身品类，front/side/back 含义和 backpack 完全不同）
- [ ] Qwen 修正 prompt 后是否仍存在"全部判 correct 的过宽松倾向"？

---

## Session Notes

- 项目只有 4 次 git commit，但 working tree 有大量未提交变更（12 文件，427 行改动）——建议尽快用 `/atomic-commit` 分批提交
- Qwen API 请求中 atomic_rules 是内联到 prompt 文本的，不是作为独立结构化字段传入
- `process.md` 是项目的核心导航文档，每次工作前和结束时都应更新它
- 项目路径包含中文（`D:\索尼实习`），所有文件编码使用 `utf-8-sig`（Excel 兼容）

---

_This handoff was generated at 2026-07-06 13:45 +08:00. Start a new session and use this document as your initial context._
