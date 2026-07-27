# Handoff: 批量监修 + 微调方向讨论

**Created:** 2026-07-27
**Branch:** main
**Session Duration:** ~2 小时

---

## 摘要

本次会话完成了 `SN_6_3D_dataset` 20 个样本的端到端批量监修（char_001~020，char_021 无 front_view 跳过），使用 `run_supervision_agent.py` + `qwen3.7-plus`。同时讨论了用 6000 个人工标注样本做 Qwen-VL fine-tuning 的方向，以及数据传输到服务器的方案（scp/rsync，服务器 SSH 端口待确认）。

---

## Work Completed

### Changes Made

- [x] 读取上次 handoff（`HANDOFF_supervision-agent-pipeline_2026-07-27.md`），确认 pipeline 架构
- [x] 跑通 char_001 真实端到端（Step1 元素提取 + Step2 监修审查），确认 API 正常
- [x] 批量跑完 char_001~020（char_021 跳过，无 front_view），全部输出到 `vlm/tmp/supervision_agent_output/`
- [x] 汇总 20 个样本结果

### 批量结果汇总

| 样本 | 规则数 | correct | wrong | billable issues | design notes |
|------|--------|---------|-------|-----------------|--------------|
| char_001 | 8 | 7 | 1 | 1 | 0 |
| char_002 | 9 | 9 | 0 | 0 | 0 |
| char_003 | 4 | 3 | 1 | 1 | 0 |
| char_004 | 6 | 6 | 0 | 0 | 0 |
| char_005 | 7 | 7 | 0 | 0 | 0 |
| char_006 | 9 | 5 | 4 | 4 | 0 |
| char_007 | 7 | 7 | 0 | 0 | 0 |
| char_008 | 9 | 4 | 5 | 5 | 0 |
| char_009 | 6 | 5 | 1 | 1 | 0 |
| char_010 | 7 | 7 | 0 | 0 | 0 |
| char_011 | 9 | 6 | 3 | 1 | 2 |
| char_012 | 10 | 8 | 2 | 2 | 0 |
| char_013 | 12 | 10 | 2 | 1 | 1 |
| char_014 | 8 | 7 | 1 | 1 | 0 |
| char_015 | 8 | 8 | 0 | 0 | 0 |
| char_016 | 6 | 6 | 0 | 0 | 0 |
| char_017 | 7 | 6 | 1 | 1 | 0 |
| char_018 | 6 | 6 | 0 | 0 | 0 |
| char_019 | 8 | 6 | 2 | 2 | 0 |
| char_020 | 5 | 5 | 0 | 0 | 0 |
| **合计** | **151** | **128** | **23** | **20** | **3** |

- 9/20 样本 0 billable issue（pass）
- 问题最集中：char_006（4个）、char_008（5个）
- 这些 issue 反映的是 3D front_view 生图对 2D 原图的正视图还原质量，side/back 全部硬性 invisible+correct

### Key Decisions

| Decision | Rationale | Alternatives Considered |
|---|---|---|
| 超时设置 --timeout 120 | 默认300s太长，120s让卡住的调用快速失败 | 保持默认300s |
| char_021 跳过 | 无 front_view 文件，pipeline 无法运行 | 报错退出 |
| fine-tuning 方向（6000样本） | 样本量足够（1000+即可），few-shot天花板低 | few-shot prompt优化 |

---

## Files Affected

### Created (未 commit)

- `vlm/scripts/supervise/run_supervision_agent.py` — 端到端主入口（上次 session 创建，本次使用）
- `vlm/prompts/supervision/qwen_prompt_v3_figurine.txt` — figurine 品类 prompt（上次 session 创建）
- `vlm/tmp/supervision_agent_output/char_001~020/` — 各样本审查输出（tmp 目录，不进 git）

### Modified (未 commit)

- `vlm/docs/workflows/process.md` — 上次 session 已修改

---

## Technical Context

### 已知问题：overall_decision 空字符串

`agent_summary.json` 里 `overall_decision` 是空字符串 `""`，但 `qwen_prediction_v3.json` 里正确写了 `"fail"` 或 `"pass"`。

根本原因：`run_supervision_agent.py:234` 从 `review_result` 读 `overall_decision`，但 `run_one_sample()` 的返回值里这个字段是空的，实际 overall_decision 写在更深的 `qwen_prediction_v3.json` 里。

修复方式：在 `main()` 里，写 `agent_summary.json` 之前，从 `qwen_prediction_v3.json` 里读取 `overall_decision`：
```python
pred_path = Path(review_result["output_dir"]) / "qwen_prediction_v3.json"
pred = json.loads(pred_path.read_text(encoding="utf-8"))
overall_decision = pred.get("overall_decision", "")
```

### 数据传输方案

服务器：`intern@43.82.14.65`，目标路径：`/home/intern/jsy/vlm/data/`

**问题：** SSH 22 端口 connection timed out，端口号未确认。

```bash
# 端口确认后的传输命令（Git Bash）
scp -P <PORT> -r "D:/索尼实习/vlm/data/SN_6期动漫数据标注" intern@43.82.14.65:/home/intern/jsy/vlm/data/

# 断点续传用 rsync
rsync -avz --progress -e "ssh -P <PORT>" "D:/索尼实习/vlm/data/SN_6期动漫数据标注/" intern@43.82.14.65:/home/intern/jsy/vlm/data/SN_6期动漫数据标注/
```

服务器上查端口：
```bash
grep Port /etc/ssh/sshd_config
# 或
ss -tlnp | grep sshd
```

### Fine-tuning 方向

目标：用 6000 个 `(2D原图, 人工标注elements)` 样本微调 Qwen-VL，替换当前 `run_element_extraction.py` 里的 API 调用。

训练数据格式：
```json
{"image": "path/to/char_XXX.png", "elements": [{"element_id": "...", "value": "..."}]}
```

阶段规划：
1. **现在可做**：用 20 个样本对比 VLM 自动提取 vs 人工标注，建立 baseline precision/recall
2. **数据准备**：把原始标注批量转成训练格式（脚本待写）
3. **训练**：数据 + GPU 就位后做 SFT

---

## Things to Know

### Gotchas & Pitfalls

- 每个样本跑两次 Qwen API（元素提取 + 监修审查），单次响应 30–120 秒，20 个样本总耗时约 30–40 分钟，顺序执行
- char_008 单次审查耗时 116 秒（异常慢），可能是 API 侧负载波动
- PowerShell 没有 `scp`，需用 Git Bash 或安装 OpenSSH
- 图片数据集不适合用 git 传输，>100MB 单文件 GitHub 直接拒绝

### Assumptions Made

- 20 个 SN_6_3D_dataset 样本的 billable issues 反映的是 3D 生图正视图还原质量，不是标注质量
- 6000 个人工标注样本路径格式与 `SN_6期动漫数据标注` 一致（待用户确认）

---

## Current State

### What's Working

- `run_supervision_agent.py` — 20 个样本批量跑完，全部成功
- 输出路径：`vlm/tmp/supervision_agent_output/{sample_id}/`，含 `agent_summary.json` + `review/dataset_figurine/{id}_v3_{timestamp}/qwen_prediction_v3.json`

### What's Not Working

- `agent_summary.json` 里 `overall_decision` 字段为空（已分析根因，修复简单）
- 服务器 SSH 端口未知，数据传输阻塞

### Tests

- [x] 20 个样本真实端到端：全部完成
- [ ] overall_decision 空字符串 bug：未修复
- [ ] 自动提取 vs 人工标注 baseline 对比：未做

---

## Next Steps

### Immediate (Start Here)

1. **确认服务器 SSH 端口**，用 Git Bash 运行 scp/rsync 传输 `SN_6期动漫数据标注`
2. **修复 overall_decision 空字符串**：在 `run_supervision_agent.py:234` 附近从 `qwen_prediction_v3.json` 读取该字段
3. **做 20 样本 baseline 对比**：VLM 自动提取（`atomic_rules_generated.json`）vs `char_XXX.json` 人工标注，量化 precision/recall

### Subsequent

- 写批量数据格式转换脚本：将 6000 个原始标注转成 `(image_path, elements_json)` 训练格式
- char_006、char_008 问题最多（4/5个 issue），可人工检查确认是生图问题还是 VLM 误判
- 数据和 GPU 就位后启动 Qwen-VL SFT

### Blocked On

- 服务器 SSH 端口（问服务器管理员或登上服务器查 `/etc/ssh/sshd_config`）
- 6000 个标注样本的路径/格式整理（用户在处理中）

---

## Commands to Run

```bash
# 确认服务器端口后传输数据（Git Bash）
scp -P <PORT> -r "D:/索尼实习/vlm/data/SN_6期动漫数据标注" intern@43.82.14.65:/home/intern/jsy/vlm/data/

# 查看 char_006 问题详情
cat "vlm/tmp/supervision_agent_output/char_006/review/dataset_figurine/$(ls vlm/tmp/supervision_agent_output/char_006/review/dataset_figurine/)/qwen_prediction_v3.json"

# 查看任意样本 agent_summary
cat vlm/tmp/supervision_agent_output/char_008/agent_summary.json
```

---

## Open Questions

- [ ] 服务器 SSH 端口是多少？
- [ ] 6000 个标注样本的格式是否与 `SN_6期动漫数据标注` 完全一致？
- [ ] char_006/char_008 的高 issue 数是生图本身质量差，还是 VLM 误判？
- [ ] fine-tuning 是否有 GPU 资源？如果没有，考虑相似图检索 + few-shot 替代方案

---

_Session closed: 2026-07-27_
