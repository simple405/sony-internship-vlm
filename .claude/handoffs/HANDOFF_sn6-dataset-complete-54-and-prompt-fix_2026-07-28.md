# Handoff: SN_6_3D_dataset 补全至 54 样本 + 元素提取提示词修复

**Created:** 2026-07-28
**Branch:** main
**Parent:** `HANDOFF_standalone-bbd103dc_batch-supervision-34-complete_2026-07-28.md`

---

## Summary

本次会话完成两件事：(1) 将 `vlm/data/SN_6_3D_dataset/` 从 34 个样本补全到 54 个（char_035~054 通过 RunningHub API 生成 front_view，并发 4→2），清理生成过程中的调试文件，统一全部 54 个 JSON 为 2-space 缩进 + utf-8-sig 编码；(2) 根据历史 handoff 中记录的元素提取已知缺陷（char_013 漏检胡须/袜子、25 处 unsupported extra、成对部位标注口径），对 `element_extraction_from_2d.txt` 提示词做了 3 处针对性修复。未连接任何模型验证效果（用户中止了模型调用步骤），修复基于既有文档证据，未做超出记录问题范围的改动。

---

## Work Completed

### Changes Made

- [x] 生成 char_035~052 的 18 个 front_view（RunningHub API，并发 4，`batch_front_view.py --source-root/--output-root` 均指向 `SN_6_3D_dataset`）
- [x] 生成 char_053~054 的 2 个 front_view（同脚本，剩余 2 个样本天然并发 2）
- [x] 删除 char_035~054 中的调试文件（`prompt.txt`/`upload_response.json`/`submit_response.json`，共 60 个文件）
- [x] 统一全部 54 个样本 JSON 格式（2-space indent，`ensure_ascii=False`，utf-8-sig 编码）
- [x] 扫描发现 26 个样本 JSON 存在重复 element（鞋袜类为主）——**未处理**，历史 handoff 已确认这类重复多为有意义的对称部位标注，本次未进一步改动
- [x] 修复 `element_extraction_from_2d.txt` 三处已知缺陷（见下方 Technical Context）

### Key Decisions

| Decision | Rationale | Alternatives Considered |
|---|---|---|
| source/output 都指向 `SN_6_3D_dataset` 本身 | 该目录已是 2D 原图 + JSON 所在地，省去中间目录搬运 | 用 `sn6_intermediate_gen` 中间目录再 assemble |
| 删除调试文件而非保留 | 与 char_001~034 保持目录结构一致（仅 3 文件） | 保留供追溯 |
| 提示词修复仅覆盖 handoff 中已记录的 3 个问题 | 避免无证据的猜测式改动，过拟合风险 | 全面重写提示词 |
| 未连接模型验证提示词效果 | 用户中止了模型调用步骤（拒绝了 DashScope 连接测试） | 用现有 34 样本跑一次对比评估 |
| 26 个重复 element 样本未去重 | 沿用上一份 handoff 的判断：这类重复多代表对称部位，非噪声 | 批量去重 |

---

## Files Affected

### Created
- `vlm/data/SN_6_3D_dataset/char_035~054/char_XXX_front_view.png` — 20 个 RunningHub 生成的正视图（1915×821，RGB）

### Modified
- `vlm/data/SN_6_3D_dataset/char_001~054/char_XXX.json` — 全部 54 个 JSON 重新格式化（2-space indent + utf-8-sig）
- `vlm/prompts/supervision/element_extraction_from_2d.txt` — 见下方 Technical Context

### Deleted
- `vlm/data/SN_6_3D_dataset/char_035~054/{prompt.txt, upload_response.json, submit_response.json}` — 60 个 RunningHub 中间调试文件

### Read (Reference)
- `.claude/handoffs/HANDOFF_standalone-bbd103dc_batch-supervision-34-complete_2026-07-28.md`
- `.claude/handoffs/HANDOFF_sn6-dataset-normalization-and-finetune-plan_2026-07-27.md`
- `.claude/handoffs/HANDOFF_finetune-element-extraction-plan_2026-07-27.md`
- `vlm/docs/workflows/process.md`（4b 元素提取模型对比表）
- `vlm/scripts/generate/batch_front_view.py`
- `vlm/scripts/generate/build_sn6_dataset.py`
- `vlm/scripts/_paths.py`

---

## Technical Context

### SN_6_3D_dataset 最终结构（54 样本）

```
vlm/data/SN_6_3D_dataset/
    assembly_summary.json   # 陈旧：仅记录 char_001~020，未更新
    batch_summary.json      # 陈旧：仅最后一轮 2 样本重跑记录
    char_001/ ~ char_054/
        char_XXX.json           # gold 标注 {sample_id, source_image, elements:[{name,value}]}
        char_XXX.png             # 2D 原图
        char_XXX_front_view.png  # RunningHub 生成正视图（1915x821）
```

### 元素提取提示词修复（`element_extraction_from_2d.txt`）

三处改动均有 handoff/process.md 中的直接证据支撑：

**1. 新增胡须/面部毛发规则**（第 24 行）——process.md 4b 节明确记录"所有模型共同漏掉 char_013 的'胡须'和'袜子'……提示词无面部毛发/腿部叠层规则"：
```
- 胡须/面部毛发：仅当图中有明确可见的胡子、络腮胡、八字胡等面部毛发时单独提取，是角色重要辨识特征。
```

**2. 袜类补充半遮挡说明**（第 31 行）——同一处证据里的"腿部叠层规则"缺失：
```
- 袜类（长筒袜、短袜等，清晰可见时提取；即使被裙摆部分遮挡，只要能确认其存在和颜色，也应提取）。
```

**3. 新增成对部位规则**（第 36 行）——对齐 process.md 第 1 节会议纪要口径（"成对物品或身体部位……若两侧在外观上无任何差异，描述内容可完全相同；若存在差异，则需分别描述"），此前提示词完全没有这条：
```
- 成对部位规则：对于成对出现的物品或身体部位（如双靴、双手套、双耳饰等），若左右两侧外观有明显差异则分别提取为独立元素；若完全相同，合并为一条元素并在 `value` 中注明"左右相同"或"对称"。
```

**未改动的部分**：`attributes` 结构化字段（category/color/material/shape/location/confidence）、5–8 元素数量指导、反幻觉总则均保持原样——这些没有 handoff 中的具体失败证据支撑改动方向，改了容易过拟合猜测。

### 已知但本次未处理的问题

- **26 个样本 JSON 含重复 element**（char_022/025/026/027/028/029/031~054 部分样本，集中在鞋袜类）：上一份 handoff（`HANDOFF_sn6-dataset-normalization-and-finetune-plan_2026-07-27.md`）已确认这类重复代表左右对称部位标注，是有意义的，不是噪声，故未去重。但注意本次新增的成对部位规则里要求"完全相同的对称部位应合并为一条并注明'左右相同'"——这与现有金标"重复两条"的标注方式不一致，**下次微调 Phase 0 数据清洗时需要决定：金标是否要统一改成提示词里新定的合并写法，还是提示词改回允许重复输出**。这是一个新发现的口径冲突，需要用户决策。
- `assembly_summary.json` 和 `batch_summary.json` 未更新到 54 样本状态，仍是陈旧记录。

---

## Things to Know

### Gotchas & Pitfalls

- `vlm/data/` 整体在 `.gitignore` 里，push 数据需要 `git add -f`
- RunningHub 生成的 front_view 尺寸统一为 1915×821（本次 20 个新样本与之前 34 个一致）
- 提示词修复**未经模型验证**——用户中止了 DashScope 连接测试步骤，这三处改动目前只是基于文档证据的合理推断，没有实测 coverage/conflict 数字支撑

### Assumptions Made

- 假设 char_035~054 的人工标注 JSON（`{sample_id, source_image, elements}`）在补图前已经存在且格式与 char_001~034 一致（未逐一核对内容正确性，只核对了格式/编码）

---

## Current State

### What's Working
- ✓ `SN_6_3D_dataset` 54/54 样本三件套齐全（json + 2D 原图 + front_view）
- ✓ 全部 JSON 格式统一

### What's Not Working / Not Started
- 提示词修复未经实测验证（无 coverage/conflict 对比数据）
- 26 个重复 element 样本 vs 新成对部位规则的口径冲突未解决
- `assembly_summary.json` / `batch_summary.json` 未更新

### Tests
- [ ] 提示词修复效果验证：未跑（需要用户明确允许连接 DashScope 或本地 Ollama 后才能测）
- [ ] 54 样本 baseline coverage 评估：未跑

---

## Next Steps

### Immediate (Start Here)
1. **验证提示词修复效果**：用 char_013（已知漏检胡须/袜子的样本）跑一次 `run_element_extraction.py`，对比修复前后的输出差异。需要用户先确认用哪个后端（DashScope `qwen-vl-max` 还是本地 Ollama `qwen36-vl:latest`——本地 Ollama 需要能连通服务器，之前 SSH/端口问题未解决，直连 `43.82.14.65:11434` 已测试超时）
2. **决策成对部位口径冲突**：新提示词规则要求"完全相同的对称部位合并为一条"，但现有 26 个样本金标是"重复两条"。需要用户决定哪种是目标标注规范。

### Subsequent
- 若提示词修复有效，跑一次 54 样本的 baseline coverage 评估，更新 process.md 4b 节对比表
- 更新 `assembly_summary.json` 反映 54 样本状态（如果这个文件还有人在用）
- 继续跟进 6000 训练样本微调 plan（见 `HANDOFF_finetune-element-extraction-plan_2026-07-27.md`）

### Blocked On
- 用户尚未选定验证提示词修复效果时用哪个模型后端连接
- 6000 训练样本整理进度（长期阻塞项，见历史 handoff）

---

## Related Resources

### Documentation
- `.claude/handoffs/HANDOFF_standalone-bbd103dc_batch-supervision-34-complete_2026-07-28.md`
- `.claude/handoffs/HANDOFF_sn6-dataset-normalization-and-finetune-plan_2026-07-27.md`
- `.claude/handoffs/HANDOFF_finetune-element-extraction-plan_2026-07-27.md`
- `vlm/docs/workflows/process.md`

### Commands to Run

```bash
# 补跑缺失 front_view（幂等）
python -m vlm.scripts.generate.batch_front_view \
  --source-root vlm/data/SN_6_3D_dataset --output-root vlm/data/SN_6_3D_dataset

# 验证提示词修复（需先选定后端）
python -m vlm.scripts.supervise.run_element_extraction --sample-id char_013 \
  --qwen-base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen-vl-max

# push 数据（需要 -f 绕过 .gitignore）
git add -f vlm/data/SN_6_3D_dataset/
git add vlm/prompts/supervision/element_extraction_from_2d.txt
git commit -m "..."
git push origin main
```

---

## Open Questions

- [ ] 26 个样本的重复 element 该去重合并（配合新提示词规则）还是保留原样？
- [ ] 提示词修复的效果验证用哪个模型后端？DashScope `qwen-vl-max`（需用户明确同意调用付费 API）还是本地 Ollama（需先解决服务器连通性）？
- [ ] `assembly_summary.json`/`batch_summary.json` 是否还有下游脚本依赖，需要同步更新吗？

---

## Session Notes

用户在本次会话中主动中止了一次 DashScope API 连通性测试（`AskUserQuestion`/工具调用被拒绝），转而要求"先不连接模型，从 handoff 文档里的报告想办法改进提示词"。这是一个明确的方法论偏好：**优先基于已有文档证据做确定性修复，而非用真实 API 调用去试错**。下次涉及模型效果验证时，应先征得明确同意再连接付费 API 或远程服务。

---

_Session closed: 2026-07-28_
