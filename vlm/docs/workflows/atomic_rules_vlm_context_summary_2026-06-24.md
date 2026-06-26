# Atomic Rules / VLM Context Summary

更新日期：2026-06-26

本文件是当前项目的压缩上下文，用于后续继续开发时快速恢复状态。它保留项目目标、目录结构、关键决策、已修改文件、验证结果、风险和下一步。

## 项目目标

当前项目主线是动漫 IP 监修 VLM 工作流：

1. 从 2D 动漫角色图中抽取 `atomic_rules`。
2. 基于 2D 图和 `atomic_rules` 生成 3D 手办/商品设计图，当前模型为 `wan2.7-image-pro`。
3. 后续让 VLM 输入 2D 图、3D 图和规则，判断 3D 设计是否符合 2D 设计。
4. `atomic_rules` 可以作为 3D 设计和 VLM 判断的重要依据，但不应替代图像本身。它适合承载可验证的显式约束，例如发色、发型、服装、配饰、手持物颜色等。

## 当前目录结构

工作区根目录：`D:\索尼实习`

根目录当前保持简洁：

```text
.venv/
README.md
vlm/
```

`vlm/` 是当前活跃项目目录：

```text
vlm/
  config/
  data/
  docs/
  prompts/
  reference/
  scripts/
  tmp/
  README.md
  requirements.txt
```

`ip_review_project` 已不再作为独立主项目使用：

- 代码参考：`vlm/reference/ip_review_project/`
- 旧数据和输出：`vlm/data/legacy/ip_review_project/`

不要再把新脚本或新数据放回根目录或旧 `ip_review_project`。

## 关键决策

- 当前 `atomic_rules` 主跑 prompt 质量可用，不建议因为 `ip_review_project` 中的 prompt 直接 overwrite 1000+ 张图的规则。
- `ip_review_project` prompt 有少量可吸收内容，但更多是锦上添花，没有明显提高核心准确度的证据。
- 对 3D 生成来说，`atomic_rules` 应作为强约束输入；但如果规则漏掉关键视觉点，模型仍会按常识补全，例如把 `bell` 默认画成金色。
- 不建议把错误样本和正样本混在一起不标注。后续如果要训练 VLM 纠错能力，可以做负样本，但要显式记录错误类型、期望结论和 defect label。
- 3D 正式产出统一放在模型目录下的 `dataset_figurine/<sample_id>/`，每个样本目录只放核心三件套：2D 原图、3D 图、对应 `atomic_rules.json`。不再使用 `review_samples/` 或根层 `dataset_figurine/`。
- 3D 生成不能长期只覆盖 PVC 手办。后续应采用“通用母模板 + 商品类型 product block”的方式支持多品类周边，例如 PVC 手办、Q 版全身公仔、蛋糕卷、头部挂饰、痛包、背包等。
- `atomic_rules` 的颜色短标签只是粗约束，不能替代 2D 图里的颜色分布。生成 prompt 已加入通用颜色与图案保真约束，要求保留渐变、分区色、透明/半透明变化、高光、图案、符号和左右不对称配色，避免把多色小物件压成单色。
- 对 `atomic_rules` 中“存在性规则有了但缺少颜色/渐变/图案 counterpart”的问题，优先使用 patch-only 修复：保留原 JSON，只让 Qwen 针对 audit CSV 指出的对象补充新增规则并原地 append，不整份重抽。

## Atomic Rules 状态

活跃数据集：

`vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20`

当前文件计数核对：

- `metadata.jsonl`：1115 行
- `atomic_rules/`：1115 个 `_atomic_rules.json` 文件
- `rejected_post_ids.txt`：已有坏样本跳过列表，包含 `3991439`、`3153422`

最新轻量 QA 核对是在 2026-06-26 临时跑的，输出到：

`vlm/tmp/context_summary_qa_check/atomic_rules_qa_report.md`

结果：

- Metadata rows: 1115
- JSON-valid samples: 1027
- Samples with fail issues: 88
- Total fail issues: 197
- Issue breakdown: `invalid_length_value`

这意味着 06-25 旧报告中的 88 个 `missing_json` 已经不再是当前主要问题；现在需要处理的是这 88 个样本里 `*_length` 使用了 `high/low`，而 QA 规则要求 `short/medium/long`。

正式报告目录仍是：

`vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/reports/`

注意：正式 `reports/atomic_rules_qa_report.md` 还是 2026-06-25 的旧结果，显示 88 个 `missing_json`。下一步修复长度值后，应重新跑 QA 并更新正式报告。

最新颜色/细节完整性审计：

- 审计 CSV：`vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/reports/atomic_rules_missing_color_or_detail_audit.csv`
- 扫描对象：1115 个 `_atomic_rules.json`
- JSON-valid：1115
- 候选缺失项：1646 条
- 涉及样本：763 个唯一 `sample_id`
- 典型问题：`holding_item = bell`、`has_chest_bow = true`、`has_back_accessory = true`、`legwear_gradient = true` 等存在，但缺少对应颜色、基础色、渐变、图案或 accent color 规则。
- 当前决定：不要用整份重抽覆盖这 763 张；使用 `patch_atomic_rules_from_audit_with_qwen.py` 按样本聚合 audit items，请 Qwen 只返回 `new_atomic_rules` 并原地 merge 到既有 `atomic_rules/<sample_id>/<sample_id>_atomic_rules.json`。

## Atomic Rules 规则口径

冻结输出结构仍然是：

```json
{
  "code": "...",
  "atomic_rules": [
    { "id": "...", "value": "..." }
  ]
}
```

当前规则口径：

- `skin_tone` 只允许 `fair / tan / dark`
- `skin_color` 允许非人类或幻想角色基础颜色，例如 `blue / green / purple / gray / pink`
- `*_length` 只允许 `short / medium / long`
- `*_height` 只允许 `low / medium / high`
- 不输出 `unknown / none / not_visible`
- 不输出 `very_long / slightly_long` 这类副词化 value
- 不可见部位不要强行补规则
- 规则尽量多，但 value 要收紧

## 活跃脚本

主要脚本：

- `vlm/scripts/crawl_safebooru.py`
- `vlm/scripts/atomic_rules_qwen_shared.py`
- `vlm/scripts/extract_atomic_rules_with_qwen.py`
- `vlm/scripts/qa_atomic_rules_batch.py`
- `vlm/scripts/compare_raw_trials_with_qwen.py`
- `vlm/scripts/generate_3d_figurine_with_wan.py`
- `vlm/scripts/patch_atomic_rules_from_audit_with_qwen.py`

`atomic_rules_qwen_shared.py` 当前状态：

- Qwen 抽取 prompt 已加入颜色与细节完整性约束。
- 参考 `vlm/reference/ip_review_project` 的可拆分原则：object、color、pattern、structure、decoration 必须拆成独立 atomic rules。
- 若输出手持物、武器、头饰、发饰、蝴蝶结、铃铛、项链、耳饰、腰带、背部配饰、披风、护甲、手套、鞋袜、尾巴、翅膀、角、身体装饰或标志性符号，应尽量同时输出可见颜色/渐变/图案 counterpart。
- 明确禁止按常识补色，例如不能因为 `bell` 默认补 `gold/yellow`；颜色必须来自 2D 图可见内容。

`extract_atomic_rules_with_qwen.py` 当前状态：

- 新增 `--audit-csv`：读取审计 CSV，自动筛出相关 `sample_id` 并追加样本级 repair guidance。
- 新增 `--sample-ids-file`：按 sample id 子集运行。
- 新增 `--force-continue`：非理想但可用图片也继续抽取可见规则。
- 该脚本适合整份重抽或按子集重抽；当前颜色/细节缺失修复更推荐 patch-only 脚本。

`patch_atomic_rules_from_audit_with_qwen.py` 当前状态：

- 新增脚本，用于从 audit CSV 原地补充缺失颜色/细节规则。
- 默认输入 audit CSV：`reports/atomic_rules_missing_color_or_detail_audit.csv`
- 默认原地修改目录：`vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/atomic_rules`
- 每个 sample 一次 Qwen 请求，输入 2D 图、已有 rules、该 sample 的 audit candidates。
- 只接受 Qwen 返回的 `new_atomic_rules`，经 `normalize_rule_entry` 后 append 到原 JSON；不删除、不重写、不重命名已有规则。
- 运行日志默认写到 `vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/logs/qwen_patch_atomic_rules_<timestamp>.jsonl`
- 已提供 `--limit-samples` 用于 smoke test，`--list-only` 用于不调用 API 的选择集检查。

`generate_3d_figurine_with_wan.py` 当前状态：

- 默认模型：`wan2.7-image-pro`
- 默认 prompt：`vlm/prompts/generation/wan_3d_figurine_from_atomic_rules.txt`
- 默认正式输出：`vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d/wan2.7-image-pro/dataset_figurine/<sample_id>/`
- 使用 DashScope：需要环境变量 `DASHSCOPE_API_KEY`
- 已支持解析 `output.choices[].message.content[].image`
- 默认不再为每个样本保留 prompt/request/response/status；需要调试时显式加 `--keep-debug-files`，调试文件放到 `generated_3d/<model>/_debug/<sample_id>/`
- 2026-06-26 新增参数：
  - `--extra-guidance`
  - `--guidance-file`
  - `--keep-debug-files`

新增参数用于给单张样本加局部生成约束，不污染通用 prompt，也不用修改原始 Qwen 规则。

## 3D 生成 Prompt

当前有两份 3D 生成模板：

- `vlm/prompts/generation/wan_3d_figurine_from_atomic_rules.txt`
  - 当前脚本默认使用的 PVC 手办三视图模板。
  - 已加入颜色与图案保真约束，避免粗粒度 `atomic_rules` 把渐变、多色、图案小物件压成单色。
- `vlm/prompts/generation/wan_3d_merchandise_from_atomic_rules.txt`
  - 新增的多品类周边母模板。
  - 包含 `{{PRODUCT_TYPE}}`、`{{PRODUCT_SCOPE}}`、`{{PRODUCT_BLOCK}}`、`{{RULE_VISIBILITY_POLICY}}` 占位符。
  - 设计目标是后续通过商品类型 block 支持 PVC 手办、Q 版公仔、蛋糕卷、头部挂饰、痛包、背包等品类。

PVC 手办模板核心要求：

- 使用 2D 图作为主视觉参考
- 输出 3D PVC 手办/收藏玩具风格
- 白色背景
- 横向排列 front / side / back 三视图
- 保持比例、发型、眼睛、服装、配饰、颜色和 `atomic_rules`
- 避免文字、水印、额外角色、裁切、手指错误等

多品类母模板尚未接入生成脚本默认流程。下一步需要在脚本中增加 `--product-type`，按商品类型填充 product block 和 rule visibility policy。

## 多品类生成策略

后续 3D 商品生成不应按品类平均分配，而应按监修能力覆盖分层：

| 商品层级 | 示例 | 主要覆盖能力 |
| --- | --- | --- |
| 全身高保真类 | PVC 手办、站姿全身公仔 | 头部、服装、腿袜、鞋、背部、手持物、全身配色 |
| 全身 Q 版/变形类 | Q 版公仔、毛绒全身公仔、坐姿公仔 | 比例压缩后的角色识别、核心发型/服装/配色保留 |
| 头部/局部类 | 蛋糕卷、头部挂饰、头部毛绒挂件 | 发型、发色、眼睛、头饰、脸部标志 |
| 商品载体/强变形类 | 痛包、背包、装饰挂件、容器类周边 | 角色元素映射、图案化、局部装饰、颜色分布、标志性元素 |

建议第一批 100 张 pilot 比例：

```text
PVC 手办：30
Q 版公仔：20
蛋糕卷：12
头部挂饰：13
痛包：15
背包/其他载体：10
```

不要让每个角色都生成所有品类。建议大多数角色只生成 1 个商品类型，部分角色生成 2 个商品类型，少量核心角色生成 3-4 个商品类型，用于观察同一角色跨品类的一致性。

## 统一 3D 产出结构

用户希望仿照 raw trial 数据结构，但不放 Excel。当前统一结构：

```text
vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/
  generated_3d/
    wan2.7-image-pro/
      dataset_figurine/
        <sample_id>/
          <sample_id>_original.jpg
          <sample_id>_figurine.png
          <sample_id>_atomic_rules.json
      generation_runs.jsonl
```

如需保留单样本 API 调试文件，运行时加 `--keep-debug-files`，调试文件放到：

```text
vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/
  generated_3d/
    wan2.7-image-pro/
      _debug/
        <sample_id>/
```

## 当前统一 3D 样本

当前统一目录：

`vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d/wan2.7-image-pro/dataset_figurine/`

当前已有样本：

- `1521302/`
- `3186795/`

每个样本目录只保留三件套：

```text
<sample_id>_original.jpg / <sample_id>_original.png
<sample_id>_figurine.png
<sample_id>_atomic_rules.json
```

## 本轮已修改文件

- `vlm/scripts/generate_3d_figurine_with_wan.py`
  - 新增 `--extra-guidance`
  - 新增 `--guidance-file`
  - prompt 构建阶段会把额外约束追加到 `Additional sample-specific guidance`
  - 新增 `--keep-debug-files`
  - 默认正式三件套直接输出到 `generated_3d/<model>/dataset_figurine/<sample_id>/`
  - 默认不再逐样本保留 prompt/request/response/status

- `vlm/scripts/atomic_rules_qwen_shared.py`
  - Qwen 抽取 prompt 新增颜色与细节完整性段落。
  - 强调物体、颜色、图案、结构、装饰拆分，不把颜色塞进物体 value。
  - 要求手持物、配饰、武器、身体装饰、标志性符号等存在时尽量补可见的 `*_color`、`*_gradient`、`*_pattern` 或 accent-color 规则。

- `vlm/scripts/extract_atomic_rules_with_qwen.py`
  - 新增 `--audit-csv`
  - 新增 `--sample-ids-file`
  - 新增 `--force-continue`
  - 可按 audit CSV 筛出 763 个样本整份重抽，但当前不推荐作为颜色/细节缺失的第一选择。

- `vlm/scripts/patch_atomic_rules_from_audit_with_qwen.py`
  - 新增 patch-only 修复脚本。
  - 读取 audit CSV，按 sample 聚合缺失项。
  - 调用 Qwen 只返回新增 `new_atomic_rules`。
  - 原地 merge 到已有 `atomic_rules/<sample_id>/<sample_id>_atomic_rules.json`，不写新输出目录。

- `vlm/prompts/generation/wan_3d_figurine_from_atomic_rules.txt`
  - 加入通用颜色与图案保真规则。
  - 明确 `atomic_rules` 是粗身份约束，不替代 2D 图中可见细节。
  - 对渐变、分区色、多色物件、图案、透明/半透明变化、高光、符号、左右不对称配色增加保真要求。

- `vlm/prompts/generation/wan_3d_merchandise_from_atomic_rules.txt`
  - 新增多品类周边母模板。
  - 预留商品类型、商品范围、商品专属约束、规则可见性策略等占位符。

- `vlm/prompts/README.md`
  - 增加多品类周边 prompt 文件说明。

- `vlm/docs/workflows/atomic_rules_vlm_workflow.md`
  - Step 2 从单一 3D 手办生成扩展为多品类 3D 商品设计稿生成。
  - 新增商品类型分层、100 张 pilot 品类比例、商品类型选择原则、颜色和图案保真规则。
  - Step 3 从两类粗分类更新为 `full_body`、`head_only`、`carrier_mapped`、`hybrid` 四类 `product_scope`。

- `vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d/wan2.7-image-pro/dataset_figurine/`
  - 统一为 3D 正式三件套目录。
  - 当前包含 `1521302/` 和 `3186795/` 两个样本，每个样本目录只保留 2D 原图、3D 图、atomic_rules 三个文件。
  - 已删除旧的 `review_samples/`、根层 `dataset_figurine/` 和 `generated_3d/wan2.7-image-pro/1521302/` 等散落位置。

- `vlm/tmp/context_summary_qa_check/`
  - 临时 QA 核对输出，用于确认当前 atomic_rules 实际状态

## 已验证

- 使用 `.venv` 下 Python 可正常导入 `dashscope`
- `generate_3d_figurine_with_wan.py` 已用 `.venv` 执行 `py_compile` 通过
- `3186795_atomic_rules.json` 可被 `ConvertFrom-Json` 正常解析
- 统一 `dataset_figurine/<sample_id>/` 样本目录均为三件套
- 旧的 `review_samples/`、根层 `dataset_figurine/`、`generated_3d/wan2.7-image-pro/1521302/` 已不存在
- 最终 `3186795_figurine.png` 已视觉检查：手持饰品主色为蓝/青色
- `wan2.7-image-pro` 单样本 API 调用成功
- 多品类 prompt 文件已保存并在 `vlm/prompts/README.md` 中登记
- 当前临时 QA 结果显示：1115 行 metadata，1027 个 JSON-valid，88 个样本仍需处理 `invalid_length_value`
- `atomic_rules_missing_color_or_detail_audit.csv` 已生成并复核：1646 条候选缺口，763 个唯一样本。
- `extract_atomic_rules_with_qwen.py` 和 `patch_atomic_rules_from_audit_with_qwen.py` 已用 `.venv` 执行 `py_compile` 通过。
- `patch_atomic_rules_from_audit_with_qwen.py --list-only` 已验证选中 763 个 audited samples，未调用 API。
- 30 张 smoke test 已由用户查看，输出符合预期；可以进入 763 个 audited samples 的全量 patch。
- 763 张全量 patch 命令已给出，但当前上下文尚未记录全量 patch 已完成。

## 常用命令

运行正式 QA：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\qa_atomic_rules_batch.py `
  --metadata .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\metadata.jsonl `
  --atomic-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\atomic_rules `
  --report-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\reports
```

生成 3D 手办图：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\generate_3d_figurine_with_wan.py `
  --sample-id 3186795 `
  --model wan2.7-image-pro `
  --seed 3186796
```

带样本级额外约束生成：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\generate_3d_figurine_with_wan.py `
  --sample-id 3186795 `
  --model wan2.7-image-pro `
  --seed 3186796 `
  --extra-guidance "The handheld bell/accessory must be blue/cyan like the 2D reference. Do not render it as yellow, gold, brass, bronze, or tan."
```

继续补跑或重跑 atomic_rules：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\extract_atomic_rules_with_qwen.py `
  --metadata .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\metadata.jsonl `
  --out-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\atomic_rules `
  --model qwen3.5-plus `
  --offset 0 `
  --limit 0 `
  --image-source url `
  --workers 4 `
  --sleep 0.5 `
  --retries 2
```

只补 audit CSV 指出的缺失颜色/细节规则，30 张 smoke test，原地修改已有 atomic_rules：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\patch_atomic_rules_from_audit_with_qwen.py `
  --metadata .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\metadata.jsonl `
  --atomic-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\atomic_rules `
  --audit-csv .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\reports\atomic_rules_missing_color_or_detail_audit.csv `
  --model qwen3.5-plus `
  --image-source url `
  --workers 6 `
  --sleep 0.5 `
  --retries 2 `
  --retry-base-sleep 2 `
  --limit-samples 30
```

30 张复核没问题后，全量 patch 763 个 audited samples：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\patch_atomic_rules_from_audit_with_qwen.py `
  --metadata .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\metadata.jsonl `
  --atomic-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\atomic_rules `
  --audit-csv .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\reports\atomic_rules_missing_color_or_detail_audit.csv `
  --model qwen3.5-plus `
  --image-source url `
  --workers 6 `
  --sleep 0.5 `
  --retries 2 `
  --retry-base-sleep 2
```

## 当前风险

- `atomic_rules/` 现在文件数量看起来补齐了，但 QA 仍有 88 个样本失败，原因是 `*_length` value 使用了 `high/low`。这需要机械修正或局部重跑。
- 正式 `reports/atomic_rules_qa_report.md` 尚未反映 2026-06-26 的临时 QA 状态，下一步修复后应重跑正式 QA。
- 3D 生成模型对未显式约束的物体颜色会按常识补全，例如 `bell -> gold`。后续生成前应检查 `atomic_rules` 是否包含手持物颜色、头饰颜色、背部配饰颜色等关键颜色。
- 即使显式写了粗颜色规则，例如 `blue/cyan`，模型仍可能把 2D 图里的渐变、多色、图案细节压成单色。当前 prompt 已加强通用保真约束，但仍需要用更多样本验证。
- patch-only 修复仍然需要 Qwen 看图，不能只靠 CSV 或已有 JSON 推断颜色；30 张 smoke test 已符合预期，但全量 patch 后仍应抽查 patch log 和若干原 JSON。
- patch-only 脚本只 append 新规则，不删除旧规则；如果旧规则本身错误，仍需要单独 QA 或整份重抽。
- 多品类母模板已经保存，但生成脚本还没有实现 `--product-type` 和 product block 填充；当前默认仍是 PVC 手办模板。
- prompt 约束重生图可能修正一个点但引入构图或细节漂移；对于单张样本局部小错，本地局部修图有时更稳。
- 如果要构建负样本训练 VLM 纠错，必须单独标注错误类型，不能和正样本无标记混放。

## 下一步建议

1. 全量运行 `patch_atomic_rules_from_audit_with_qwen.py` 处理 763 个 audited samples，然后抽查 patch log 和若干原 JSON。
2. 重新生成颜色/细节完整性审计 CSV，确认剩余缺口下降。
3. 修复 88 个 `invalid_length_value` 样本，把 `*_length` 的 `high/low` 规范到 `long/short/medium`，然后重跑正式 QA。
4. 把正式 `reports/atomic_rules_qa_report.md` 更新到最新状态。
5. 为 `generate_3d_figurine_with_wan.py` 增加 `--product-type`，用 `wan_3d_merchandise_from_atomic_rules.txt` 填充不同商品 block。
6. 为 3D 生成建立批量脚本或配置：读取 clean atomic_rules，按 pilot 比例生成 PVC 手办、Q 版公仔、蛋糕卷、头部挂饰、痛包、背包等多品类样本。
7. 在 VLM 数据结构中加入监督字段，例如 `expected_verdict`、`defect_type`、`review_notes`，用于区分正样本和故意错误样本。
