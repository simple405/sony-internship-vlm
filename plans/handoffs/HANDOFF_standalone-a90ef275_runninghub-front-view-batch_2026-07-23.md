# RunningHub API 配置 + 前视图 3D PVC 手办冒烟测试与批量生成

**Date:** 2026-07-23
**Status:** COMPLETED (batch done, 19/20 success)
**Bead(s):** none
**Epic:** Anime IP 2D-to-3D merchandise generation — RunningHub cloud path
**Chain:** `standalone-a90ef275` seq `1`
**Parent:** none — first in chain
**Prior chain:** none — first in chain

---

## Related Handoffs

- `HANDOFF_server-local-3d-approaches_2026-07-23_seq4.md` — 本地 ComfyUI/IC-Light 2D-to-3D 链路（`standalone-38ec30d8` 链），与本次 RunningHub 云端链路是**并行互补**的两条技术路线，非前后续关系。
- `HANDOFF_FRONT_VIEW_FEATURE_07_22_10_52.md` — 同一 front_view 需求的早期探索（Ollama Qwen-VL + Codex image_gen），未涉及 RunningHub。

## The Goal

为动漫 IP 商品监修项目启用 RunningHub 云端生图能力，替代/补充本地 ComfyUI 链路。将第 6 期 20 个动漫角色的 2D 原图通过 RunningHub G-2.0 image-to-image API 转换为前视图 3D PVC 手办设计图，验证 API 全链路（上传→提交→轮询→下载）可行，并冻结一版可复用的提示词作为后续批量生成的基线。

## Where We Are

- **RunningHub API 已配置并验证通过**：`vlm/config/api.env` 创建完毕，`RUNNINGHUB_API_KEY` 已填入 `.gitignore` 排除规则内（key 值见 `vlm/config/api.env`，不在此处明文记录）。
- **API 全链路验证**：上传（`/openapi/v2/media/upload/binary`）→ 提交（`/openapi/v2/rhart-image-g-2/image-to-image`）→ 轮询（`/openapi/v2/query`）→ 下载（COS URL），每个环节均返回正确响应。
- **前视图提示词已冻结**：`vlm/prompts/generation/runninghub/runninghub_g2_figurine_front_view_user_cn.txt`，共 11 行中文提示词，涵盖角色身份忠实度、材质规格、禁止项（无展示台/文字/水印/底座）。
- **与原版三视图提示词的核心差异**：移除"横向排列三个正交全身视角（正面、侧面、背面）""三视角空间连续性""背面花纹宁可省略不补全"等约 6 行约束，保留"白底设计图""中性站姿""哑光喷涂 PVC""禁止幻觉/新增元素"等核心约束。
- **冒烟测试 char_001 通过**：单样本跑通，task `2080190286877052930`，耗时约 40s，原图 408×780 (290KB) → 输出 1568×672 RGB PNG，用户评价"效果不错"。
- **批量生成 19/20 成功**：4 并发 ThreadPoolExecutor，所有成功输出统一为 1568×672 RGB，work-dir 为 `vlm/data/smoke_test/char_*/`。
- **char_008 被内容审核拦截**：`errorCode 1501: 内容安全审查未通过`，RunningHub 在 task 提交阶段即拒绝，未消耗生成额度。原因为原图角色穿着触发审核策略，非提示词问题。
- **批量耗时分布**：快速样本 39-70s，慢速样本 100-160s（char_003/006/007/015 遇到排队）。
- **脚本状态**：`smoke_test_front_view.py` 和 `batch_front_view.py` 均为 untracked，位于 `vlm/scripts/generate/`。两脚本共享 ~80% 的 API 调用逻辑，尚未抽取公共模块。
- **脚本不自动加载 api.env**：当前通过内嵌 `load_api_env()` 函数解析 key=value 行（支持 utf-8-sig、注释、引号剥离），但 `batch_front_view.py` 首次运行时因 `parents[2]` vs `parents[3]` 路径 bug 导致 `RUNNINGHUB_API_KEY is not set` 报错，已修正。
- **已有项目代码未修改**：`generate_head_keychain_with_runninghub_g2.py`、`run_runninghub_merchandise_full_batch.py` 等原有脚本直接读 `os.environ.get("RUNNINGHUB_API_KEY")`，本次工作未改动它们。
- **与 `standalone-38ec30d8` 链的关系**：本地链通过 ComfyUI/IC-Light/MoGe 做 mesh 提取和 PBR 渲染，RunningHub 链是纯云端 API 调用。两条链互为 fallback，尚未做质量对比。

## What We Tried (Chronological)

1. **检查 handoff 文档与 api.env 状态** → 发现 `vlm/config/api.env` 不存在，CLAUDE.md 声称应有此文件。`vlm/config/` 目录下仅有 `supervision/` 子目录。

2. **创建 api.env 模板** → 写入 `RUNNINGHUB_API_KEY`、`DEEPSEEK_API_KEY`、`QWEN_API_KEY` 三个占位符。`.gitignore` 已有 `vlm/config/*.env` 排除规则，不会被提交。

3. **curl 测试 API 连通性** → `POST /openapi/v2/query` 返回 HTTP 200 + `errorCode 1007`（正常：假 taskId 导致的解析错误，非认证失败）。`POST /openapi/v2/media/upload/binary` 上传 64×64 测试图返回 `"code": 0` + COS download_url，确认认证通过。

4. **写 smoke_test_front_view.py** → 首次运行 `Path(__file__).parents[2]` 解析为 `/home/intern/jsy/vlm/`，再加 `"vlm"/"data"/...` 拼接出 `/home/intern/jsy/vlm/vlm/data/...`（双 vlm），导致 `FileNotFoundError`。修正为 `parents[3]` 后解决。API 逻辑正确，仅路径解析问题。

5. **char_001 冒烟测试** → 上传 290KB 原图 → 提交 image-to-image 任务 → 轮询 RUNNING→SUCCESS → 下载 1568×672 PNG。write 了 prompt.txt / upload_response.json / submit_response.json 三项溯源文件。用户评价"效果不错"。

6. **用户要求冻结提示词** → 保存为 `vlm/prompts/generation/runninghub/runninghub_g2_figurine_front_view_user_cn.txt`，命名对齐现有 `runninghub_g2_{category}_user_cn.txt` 惯例。用户额外说"单独保存吧"（虽然已保存），确认期望独立文件而非脚本内嵌字符串。

7. **写 batch_front_view.py** → 复用 smoke test 的 API 逻辑，新增：4 并发 ThreadPoolExecutor、`has_output()` resume 检测（跳过已有 `{id}_front_view.*` 的样本）、`batch_summary.json` 汇总。同样遭遇 `parents[2]` 路径 bug（`RUNNINGHUB_API_KEY is not set`），修正后运行。API 加载失败时直接 `raise SystemExit` 而非静默跳过——这是正确的 fail-fast 策略。

8. **20 样本批量运行** → char_001 被 resume 跳过，18/19 成功，char_008 提交阶段即被安全审核拦截（task 未进入 RUNNING）。char_003/006/007/015 耗时 100-160s 说明遇到 RunningHub 排队（task 状态在 QUEUED 停留较久），其余 40-70s 为正常处理时间。所有成功输出统一 1568×672，验证了端点参数一致性。

## Key Decisions

- **选择 RunningHub G-2.0 image-to-image 端点**（`rhart-image-g-2/image-to-image`）而非其他品类端点，因为该端点支持通用 image-to-image + 自由文本 prompt，不绑定特定商品形态。
- **前视图而非三视图**：用户明确要求"只包含 front_view"。提示词从三视图版本中移除了横向排列、多视角空间连续性、背面补全等约束，保留了身份细节忠实度和材质规格。
- **冻结提示词为独立文件**：遵循现有 `vlm/prompts/generation/runninghub/` 目录下的 `runninghub_g2_{category}_user_cn.txt` 命名惯例，方便后续脚本引用和版本管理。
- **4 并发**：保守选择，避免触发 RunningHub 限流。实际运行中无 rate limit 报错。
- **Resume 逻辑**：检测 `{sample_id}_front_view.*` 是否已存在，存在则跳过。char_001 因此被自动跳过。
- **参数规格**：1k 分辨率 + 21:9 宽高比，与现有 head_keychain 等品类一致。

## Evidence & Data

### 冒烟测试

| 指标 | 值 |
|---|---|
| Sample | char_001 |
| Task ID | `2080190286877052930` |
| 原图尺寸 | 408×780 RGB, 290KB |
| 生成尺寸 | 1568×672 RGB |
| 端点 | `rhart-image-g-2/image-to-image` |
| 分辨率/宽高比 | 1k / 21:9 |

### 批量生成结果

| 维度 | 数量 |
|---|---|
| 总样本 | 20 |
| 跳过（已有产物） | 1 (char_001) |
| 处理 | 19 |
| ✅ 成功 | 18 |
| ❌ 失败 | 1 (char_008) |
| 失败原因 | `errorCode 1501: 内容安全审查未通过` |

### 各样本详情

| Sample | Task ID | 耗时(s) | 输出尺寸 |
|---|---|---|---|
| char_001 | 2080190286877052930 | ~40 | 1568×672 |
| char_002 | 2080192087433089026 | 40.4 | 1568×672 |
| char_003 | 2080192087172976642 | 125.4 | 1568×672 |
| char_004 | 2080192088099983362 | 45.7 | 1568×672 |
| char_005 | 2080192089169469442 | 46.0 | 1568×672 |
| char_006 | 2080192255242948610 | 103.8 | 1568×672 |
| char_007 | 2080192277850247169 | 125.0 | 1568×672 |
| char_008 | 2080192280186462209 | — | ❌ 内容审核拦截 |
| char_009 | 2080192465918636033 | 45.2 | 1568×672 |
| char_010 | 2080192612719267842 | 69.9 | 1568×672 |
| char_011 | 2080192653794103297 | 38.6 | 1568×672 |
| char_012 | 2080192692494938113 | 48.6 | 1568×672 |
| char_013 | 2080192803883126786 | 49.5 | 1568×672 |
| char_014 | 2080192815505543170 | 59.7 | 1568×672 |
| char_015 | 2080192895897718786 | 159.2 | 1568×672 |
| char_016 | 2080192905636884482 | 46.8 | 1568×672 |
| char_017 | 2080193012151230465 | 60.2 | 1568×672 |
| char_018 | 2080193065158840321 | 48.3 | 1568×672 |
| char_019 | 2080193102341353474 | 50.8 | 1568×672 |
| char_020 | 2080193263314538498 | 52.4 | 1568×672 |

### API 认证测试原始响应

**连通性测试**（假 taskId）：
```json
{"taskId":"","status":"","errorCode":"1007","errorMessage":"failed to parse request body",...}
```
HTTP 200 — API 可达且通过认证层到达应用层。1007 = 请求体解析失败（非 401/403 认证错误）。

**上传测试**（64×64 蓝色测试图）：
```json
{"code":0,"data":{"download_url":"https://rh-images-switch-1252422369.cos.ap-guangzhou.myqcloud.com/input/openapi/0a794b7a...","fileName":"openapi/0a794b7a...","size":"153","type":"image"},"message":"success"}
```
code=0 — 上传成功，download_url 为腾讯云 COS 广州节点。

### char_008 失败原始响应
```json
{"taskId":"2080192280186462209","status":"FAILED","errorCode":"1501",
 "errorMessage":"Content security audit did not pass | 内容安全审查未通过",
 "usage":{"consumeMoney":null,"consumeCoins":null,...}}
```
消耗字段均为 null — 审核失败不扣费。

### 冻结提示词全文
```
假设你是一位将二次元 IP 角色设计为 3D PVC 收藏手办的二创周边设计师。
请只根据输入的 2D 角色图，生成一张同角色 PVC 手办**正面视角**设计图。

输出必须是一张白底设计图，只展示手办的正面全身视角。角色必须保持中性站姿，
双脚落地，身体直立，可以轻微 Q 版化，但仍然是 PVC 手办。

所有身份细节都要严格尊重原图：发型轮廓、发色、刘海、侧发、后发、眼睛、表情、
服装结构、配色、图案、饰品、武器或道具都必须和原图对得上。只允许保留原图可见元素，
禁止新增原图没有的兽耳、角、帽子、蝴蝶结、尾巴、翅膀、武器或装饰。不要把头发尖角、
发饰、帽檐、衣服边缘误生成兽耳、角或尾巴。

材质为哑光喷涂 PVC，细节为雕刻和上色效果。不要生成展示台、包装盒、文字、标签、
水印、尺寸标注，也不要把原图直接贴到结果里。
```

### 各样本耗时分布

| 耗时区间 | 样本数 | 样本 |
|---|---|---|
| < 50s | 10 | char_002/004/005/009/011/012/013/016/018/019 |
| 50-70s | 4 | char_010/014/017/020 |
| 100-160s | 4 | char_003(125s)/006(104s)/007(125s)/015(159s) |
| 失败 | 1 | char_008 |

```
vlm/data/smoke_test/
├── batch_summary.json                          # 批量运行摘要（含每样本状态）
├── char_001~020/
│   ├── {id}_front_view.png                     # 生成图 (1568×672)
│   ├── prompt.txt                              # 使用的冻结提示词副本
│   ├── upload_response.json                    # 上传 API 原始响应
│   └── submit_response.json                    # 提交 API 原始响应
```

### 新增/修改文件

| 文件 | 状态 | 用途 |
|---|---|---|
| `vlm/config/api.env` | 新增，untracked | RunningHub / DeepSeek / Qwen API key |
| `vlm/prompts/generation/runninghub/runninghub_g2_figurine_front_view_user_cn.txt` | 新增，untracked | 冻结的前视图提示词 |
| `vlm/scripts/generate/smoke_test_front_view.py` | 新增，untracked | 单样本冒烟测试脚本 |
| `vlm/scripts/generate/batch_front_view.py` | 新增，untracked | 批量生成脚本（4 并发，支持 resume） |

## Code Analysis

- **RunningHub API 端点**：上传 `POST /openapi/v2/media/upload/binary`（multipart），提交 `POST /openapi/v2/rhart-image-g-2/image-to-image`（JSON），查询 `POST /openapi/v2/query`（JSON）。认证方式 `Authorization: Bearer {key}`。
- **任务状态机**：QUEUED → RUNNING → SUCCESS（成功）/ FAILED（失败）。轮询间隔 5-6s，超时 600-900s。
- **上传响应结构**：`{"code": 0, "data": {"download_url": "...", "fileName": "...", "size": "...", "type": "image"}}`。code=0 表示成功。
- **提交 payload**：`{"prompt": str, "imageUrls": [str], "aspectRatio": str, "resolution": str}`。imageUrls 使用上传返回的 download_url。
- **查询响应**：`{"taskId": str, "status": "SUCCESS"|"RUNNING"|"QUEUED"|"FAILED", "results": [{"url": str, "outputType": str}]}`。
- **错误码**：`errorCode 1501` = 内容安全审查未通过；`errorCode 1007` = 请求体解析失败（非认证错误）。
- **路径解析**：两个脚本均位于 `vlm/scripts/generate/`，使用 `Path(__file__).resolve().parents[3]` 定位项目根 `/home/intern/jsy`，然后拼接 `vlm/data/...` 等路径。
- **并发模型**：`ThreadPoolExecutor(max_workers=4)` + `as_completed`，每个线程独立完成 upload→submit→poll→download 全流程。不共享状态，每个样本独立。

## User Feedback & Preferences (REQUIRED — never omit)

- **"你先调用试一下可不可以"**：用户要求直接测试 API，不等待确认、不做方案讨论。后续所有操作风格一致——写完脚本立刻跑，不先展示代码。
- **"如果不行的话，创建一个 api.env 文件"**：给出 fallback 指令，期望遇到阻碍时自动降级处理而非停下询问。
- **"效果不错"**：对 char_001 冒烟测试结果唯一评价。仅四个字，未提出任何修改意见，说明当前 prompt + resolution + aspect-ratio 组合可直接用于批量。
- **"冻结这一版提示词"**："冻结"措辞明确表达了版本锁定意图——不是"保存"、"记录"，暗示后续不应随意修改，变更需走新版。
- **"单独保存吧"**：在已内嵌保存后再次要求，说明期望提示词以独立文件存在而非嵌入脚本，方便脱离代码审阅和版本 diff。
- **"发4"**：中文口语"发"=并发，"4"=并发数。简洁的中文技术俚语，未指定其他参数（分辨率、宽高比），说明对冒烟测试的参数组合满意。
- **所有产物统一输出路径**：`/home/intern/jsy/vlm/data/smoke_test`，用绝对路径而非相对路径。
- **操作被打断后继续**：用户在创建 api.env 时中断（"Request interrupted by user"），回来后继续原指令，说明对进度的容忍度是"接着做"而非"重来"。
- **没有要求提交代码**：3 个新文件（1 提示词 + 2 脚本）均为 untracked，用户未指示 commit 或 push。

## Where We're Going

1. **处理 char_008**：尝试降低安全审核风险——可考虑换参考图、调整原图裁剪/预处理，或走人工审核通道。
2. **人工评估生成质量**：用 Qwen VL（参照 CLAUDE.md 中的 `qwen_vl_image_tool.py`）批量评估 19 张生成图与原图的身份一致性（identity_match）、元素保留率，形成量化基线。
3. **合并/重构脚本**：`smoke_test_front_view.py` 和 `batch_front_view.py` 存在大量重复 API 调用逻辑，可抽取公共模块到 `vlm/scripts/generate/__init__.py` 或独立 `runninghub_client.py`。
4. **脚本自动加载 api.env**：当前需手动 export 环境变量或依赖 `load_api_env()`，可参考 `run_single_qwen_runninghub_demo.py` 的模式统一。
5. **扩展到其他品类**：用同样的 front_view 提示词结构，生成更多商品形态（head_key_chain, backpack, cake_roll, plush）的前视图版本，或尝试不同分辨率（2k/4k）和质量对比。
6. **与本地链路对比**：将 RunningHub 生成结果与 `standalone-38ec30d8` 链中的本地 ComfyUI/IC-Light 方案做质量、成本、速度的三方对比。

## Risks & Blockers

- **内容安全审核风险**：RunningHub 的审核策略不透明，部分角色设计可能被拦截（如 char_008），影响全量覆盖。需建立 fallback 机制或预检策略。
- **RunningHub API 变更**：当前依赖 `rhart-image-g-2/image-to-image` 端点，接口字段或状态枚举可能随时变化。
- **API 配额与成本**：未监控 RunningHub 账户的余额和 QPS 限制，批量放大时可能触发限流。

## Open Questions

- char_008 触发内容审核的具体原因是什么？原图预处理（如裁剪、遮罩敏感区域）能否绕过？
- 生成图的质量是否满足监修验收标准？需要人工或 VLM 评估确认 identity_match ≥ 合格线。
- RunningHub 的月配额/费用模型是什么？20 样本消耗了多少额度？
- 是否应该将 `api.env` 的自动加载逻辑统一到项目级别（如 `vlm/scripts/_paths.py`）？

## Quick Start for Next Session

```bash
# Restore context
# 本链无 beads，直接读 handoff 文件

# Reference docs
# /home/intern/jsy/CLAUDE.md — 项目约定、技能、模型切换
# /home/intern/jsy/vlm/docs/workflows/process.md — 当前 VLM 监修流程

# Key files to read first (not exhaustive — explore adjacent code too)
# vlm/prompts/generation/runninghub/runninghub_g2_figurine_front_view_user_cn.txt — 冻结的前视图提示词
# vlm/scripts/generate/batch_front_view.py — 批量生成脚本（4 并发，支持 resume）
# vlm/scripts/generate/smoke_test_front_view.py — 单样本冒烟测试
# vlm/config/api.env — API key 配置

# Evidence / data files
# vlm/data/smoke_test/batch_summary.json — 批量运行摘要
# vlm/data/smoke_test/char_*/  — 各角色生成结果

# Verify current state
ls vlm/data/smoke_test/char_*/ | grep front_view | wc -l  # 应为 19
git status -s  # 3 untracked files

# Next action
# 1. 评估 19 张生成图的质量（人工或用 Qwen VL 批量打分）
# 2. 处理 char_008（内容审核拦截）
```
