# `multi_view试标数据集_rev` 数据生产命令指南

更新日期：2026-08-04  
目标目录：`D:\索尼实习\vlm\data\multi_view试标数据集_rev`

本指南用于复现/重建当前 `multi_view试标数据集_rev` 这种试标交付包。每个样本目录最终应包含：

```text
2d_original.<jpg|png>
atomic_rules.json
multiview_design.png
<sample_id>.xlsx
```

当前 `rev` 包规模：

| category | sample_id |
|---|---|
| `backpack` | `2807649`, `2812503`, `3442502`, `3468461` |
| `cake_roll` | `3084017`, `3182913`, `3206137`, `3543402` |
| `dataset_figurine` | `2028680`, `2028688`, `2174996`, `2174998` |
| `dataset_QSitFigures` | `1907867`, `2026807`, `2028679`, `2028682` |
| `head_key_chain` | `2873444`, `3182879`, `3182884`, `3408800` |
| `plush` | `2180426`, `2180430`, `2245121`, `2572477` |

合计：`24` 个样本，当前 `.xlsx` 共 `576` 条 rule 行。

> 注意：生成 `atomic_rules.json` 需要 Qwen API；生成 `multiview_design.png` 需要 RunningHub API。若本地已经有对应 `atomic_rules` 和 `generated` 图片，最终打包成 Excel/目录结构可以纯脚本完成，不需要再调 API。

---

## 0. 进入仓库并检查环境

所有命令都从仓库根目录运行：

```powershell
Set-Location "D:\索尼实习"

# 推荐使用项目虚拟环境
.\.venv\Scripts\python.exe -V
.\.venv\Scripts\python.exe -c "import openpyxl, PIL, requests; print('deps ok')"

# API key 通常放这里；不要提交真实 key
Get-Content .\vlm\config\api.env
```

如果需要真实 API 生产，确认 `vlm/config/api.env` 至少包含：

```text
QWEN_API_KEY=...
RUNNINGHUB_API_KEY=...
```

---

## 1. 创建本次生产工作目录

不要直接覆盖正式目录，先写到 `vlm/tmp` 的 staging 目录：

```powershell
$Root = "vlm/data/safebooru_2d"
$Reference = "vlm/data/multi_view试标数据集_rev"
$Work = "vlm/tmp/multi_view_rev_production_$(Get-Date -Format yyyyMMdd_HHmmss)"
$AtomicWork = "$Work/atomic_rules"
$GeneratedWork = "$Work/generated"
$PackageWork = "$Work/package_multi_view试标数据集_rev"

New-Item -ItemType Directory -Force $Work, $AtomicWork, $GeneratedWork, $PackageWork | Out-Null
Write-Host "WORK=$Work"
```

---

## 2. 生成 24 个样本的 manifest、assignment 和 sample list

这一步从全量 `vlm/data/safebooru_2d/manifest.csv` 中抽出 `rev` 包使用的 24 个样本，并固定它们的品类。

```powershell
$env:ROOT = $Root
$env:WORK = $Work

@'
from pathlib import Path
import csv
import os

root = Path(os.environ["ROOT"])
work = Path(os.environ["WORK"])

sample_map = {
    "backpack": ["2807649", "2812503", "3442502", "3468461"],
    "cake_roll": ["3084017", "3182913", "3206137", "3543402"],
    "dataset_figurine": ["2028680", "2028688", "2174996", "2174998"],
    "dataset_QSitFigures": ["1907867", "2026807", "2028679", "2028682"],
    "head_key_chain": ["2873444", "3182879", "3182884", "3408800"],
    "plush": ["2180426", "2180430", "2245121", "2572477"],
}

manifest_path = root / "manifest.csv"
rows = []
with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
    reader = csv.DictReader(handle)
    fieldnames = reader.fieldnames or []
    by_id = {str(row["post_id"]): row for row in reader if row.get("post_id")}

wanted_ids = [sample_id for ids in sample_map.values() for sample_id in ids]
missing = [sample_id for sample_id in wanted_ids if sample_id not in by_id]
if missing:
    raise SystemExit(f"missing sample ids in manifest: {missing}")

selected_manifest = work / "selected_manifest.csv"
with selected_manifest.open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for sample_id in wanted_ids:
        writer.writerow(by_id[sample_id])

assignment_columns = [
    "sample_id", "primary_category", "candidate_categories", "assignment_source",
    "review_required", "image_path", "crawl_label", "reason", "key_tags",
    "primary_score",
    "score_backpack", "score_cake_roll", "score_dataset_figurine",
    "score_dataset_QSitFigures", "score_head_key_chain", "score_plush",
]
assignment_path = work / "assignment.csv"
with assignment_path.open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=assignment_columns)
    writer.writeheader()
    for category, ids in sample_map.items():
        for sample_id in ids:
            source = by_id[sample_id]
            writer.writerow({
                "sample_id": sample_id,
                "primary_category": category,
                "candidate_categories": category,
                "assignment_source": "fixed_multi_view_rev_reproduction",
                "review_required": "false",
                "image_path": source.get("image_path", ""),
                "crawl_label": source.get("crawl_label", ""),
                "reason": "fixed rev package sample",
                "key_tags": "",
                "primary_score": "100",
                **{f"score_{name}": ("100" if name == category else "0") for name in sample_map},
            })

sample_list_dir = work / "sample_lists"
sample_list_dir.mkdir(parents=True, exist_ok=True)
for category, ids in sample_map.items():
    (sample_list_dir / f"{category}.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")

print(f"selected_manifest={selected_manifest}")
print(f"assignment={assignment_path}")
print(f"samples={len(wanted_ids)}")
'@ | .\.venv\Scripts\python.exe -
```

---

## 3. 准备 `atomic_rules.json`

### 3.1 优先复用已有 atomic rules

如果 `vlm/data/safebooru_2d/atomic_rules/<sample_id>/atomic_rules.json` 已经存在，先复制到本次 staging 目录：

```powershell
$env:ROOT = $Root
$env:WORK = $Work

@'
from pathlib import Path
import os
import shutil

root = Path(os.environ["ROOT"])
work = Path(os.environ["WORK"])
selected = []
for line in (work / "selected_manifest.csv").read_text(encoding="utf-8-sig").splitlines()[1:]:
    if not line.strip():
        continue
    # post_id 是 manifest 第一列
    selected.append(line.split(",", 1)[0].strip().strip('"'))

copied = 0
missing = []
for sample_id in selected:
    src_dir = root / "atomic_rules" / sample_id
    src = src_dir / "atomic_rules.json"
    if not src.exists():
        legacy = src_dir / f"{sample_id}_atomic_rules.json"
        src = legacy if legacy.exists() else src
    if src.exists():
        dst = work / "atomic_rules" / sample_id / "atomic_rules.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    else:
        missing.append(sample_id)

print({"copied": copied, "missing": missing})
'@ | .\.venv\Scripts\python.exe -
```

### 3.2 若有缺失，再调用 Qwen API 补齐

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.extract_atomic_rules_safebooru `
  --manifest "$Work/selected_manifest.csv" `
  --output-root "$AtomicWork" `
  --limit 0 `
  --workers 2
```

说明：

- 已存在的 `atomic_rules.json` 默认会跳过，不会重复计费。
- 如果要强制重跑，加 `--overwrite`，但正式生产不建议这么干。
- 若只是检查路径，不调用 API，加 `--dry-run`。

---

## 4. 调用 RunningHub 生成六类三视图

这一步会真实消耗 RunningHub 额度。每类单独跑，方便失败后重试。

### 4.1 head_key_chain

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.generate.generate_head_keychain_with_runninghub_g2 `
  --sample-id 2873444 --sample-id 3182879 --sample-id 3182884 --sample-id 3408800 `
  --source-dir "$Root/image" `
  --atomic-dir "$AtomicWork" `
  --direct-output-dir "$GeneratedWork/head_key_chain" `
  --prompt-file "vlm/prompts/generation/runninghub/runninghub_g2_head_keychain_user_cn.txt" `
  --output-suffix head_keychain `
  --category head_key_chain `
  --aspect-ratio 21:9 `
  --resolution 1k `
  --poll-interval 8 `
  --timeout 1200 `
  --workers 4 `
  --keep-debug-files
```

### 4.2 cake_roll

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.generate.generate_head_keychain_with_runninghub_g2 `
  --sample-id 3084017 --sample-id 3182913 --sample-id 3206137 --sample-id 3543402 `
  --source-dir "$Root/image" `
  --atomic-dir "$AtomicWork" `
  --direct-output-dir "$GeneratedWork/cake_roll" `
  --prompt-file "vlm/prompts/generation/runninghub/runninghub_g2_cake_roll_user_cn.txt" `
  --output-suffix cake_roll `
  --category cake_roll `
  --aspect-ratio 21:9 `
  --resolution 1k `
  --poll-interval 8 `
  --timeout 1200 `
  --workers 4 `
  --keep-debug-files
```

### 4.3 backpack

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.generate.generate_head_keychain_with_runninghub_g2 `
  --sample-id 2807649 --sample-id 2812503 --sample-id 3442502 --sample-id 3468461 `
  --source-dir "$Root/image" `
  --atomic-dir "$AtomicWork" `
  --direct-output-dir "$GeneratedWork/backpack" `
  --prompt-file "vlm/prompts/generation/runninghub/runninghub_g2_backpack_user_cn.txt" `
  --output-suffix backpack `
  --category backpack `
  --aspect-ratio 21:9 `
  --resolution 1k `
  --poll-interval 8 `
  --timeout 1200 `
  --workers 4 `
  --keep-debug-files
```

### 4.4 plush

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.generate.generate_head_keychain_with_runninghub_g2 `
  --sample-id 2180426 --sample-id 2180430 --sample-id 2245121 --sample-id 2572477 `
  --source-dir "$Root/image" `
  --atomic-dir "$AtomicWork" `
  --direct-output-dir "$GeneratedWork/plush" `
  --prompt-file "vlm/prompts/generation/runninghub/runninghub_g2_plush_user_cn.txt" `
  --output-suffix plush `
  --category plush `
  --aspect-ratio 21:9 `
  --resolution 1k `
  --poll-interval 8 `
  --timeout 1200 `
  --workers 4 `
  --keep-debug-files
```

### 4.5 dataset_QSitFigures

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.generate.generate_head_keychain_with_runninghub_g2 `
  --sample-id 1907867 --sample-id 2026807 --sample-id 2028679 --sample-id 2028682 `
  --source-dir "$Root/image" `
  --atomic-dir "$AtomicWork" `
  --direct-output-dir "$GeneratedWork/dataset_QSitFigures" `
  --prompt-file "vlm/prompts/generation/runninghub/runninghub_g2_dataset_QSitFigures_user_cn.txt" `
  --output-suffix SitFigures `
  --category dataset_QSitFigures `
  --aspect-ratio 21:9 `
  --resolution 1k `
  --poll-interval 8 `
  --timeout 1200 `
  --workers 4 `
  --keep-debug-files
```

### 4.6 dataset_figurine

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.generate.generate_head_keychain_with_runninghub_g2 `
  --sample-id 2028680 --sample-id 2028688 --sample-id 2174996 --sample-id 2174998 `
  --source-dir "$Root/image" `
  --atomic-dir "$AtomicWork" `
  --direct-output-dir "$GeneratedWork/dataset_figurine" `
  --prompt-file "vlm/prompts/generation/runninghub/runninghub_g2_dataset_figurine_user_cn.txt" `
  --output-suffix figurine `
  --category dataset_figurine `
  --aspect-ratio 21:9 `
  --resolution 1k `
  --poll-interval 8 `
  --timeout 1200 `
  --workers 4 `
  --keep-debug-files
```

重试规则：

- 某个样本失败时，只重跑该样本所在类别，删掉命令里其他 `--sample-id` 即可。
- 生成成功后会在 `$GeneratedWork/<category>/<sample_id>/` 下看到 `<sample_id>_<suffix>.png` 和 `<sample_id>.xlsx`。
- 如果只是预检路径/请求，不调用 RunningHub，加 `--dry-run`。

---

## 5. 打包成 `multi_view试标数据集_rev` 结构

先打到 staging 包目录：

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.build_safebooru_trial_dataset `
  --root "$Root" `
  --manifest "$Work/selected_manifest.csv" `
  --atomic-root "$AtomicWork" `
  --generated-root "$GeneratedWork" `
  --assignment-csv "$Work/assignment.csv" `
  --package-root "$PackageWork" `
  --reference-root "$Reference" `
  --skip-qwen-location `
  --overwrite
```

复制标注说明 PDF：

```powershell
Copy-Item `
  "$Reference/动漫IP多品类商品设计监修标注说明v2_已修改.pdf" `
  "$PackageWork/动漫IP多品类商品设计监修标注说明v2_已修改.pdf" `
  -Force
```

---

## 6. 同步 Excel 下拉框并做结构校验

### 6.1 同步 `.xlsx` 下拉选项

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.utils.sync_annotation_workbook_validations `
  --root "$PackageWork"
```

### 6.2 校验四件套完整性

```powershell
$env:PACKAGE = $PackageWork

@'
from pathlib import Path
from openpyxl import load_workbook
import os

root = Path(os.environ["PACKAGE"])
expected = {
    "backpack": ["2807649", "2812503", "3442502", "3468461"],
    "cake_roll": ["3084017", "3182913", "3206137", "3543402"],
    "dataset_figurine": ["2028680", "2028688", "2174996", "2174998"],
    "dataset_QSitFigures": ["1907867", "2026807", "2028679", "2028682"],
    "head_key_chain": ["2873444", "3182879", "3182884", "3408800"],
    "plush": ["2180426", "2180430", "2245121", "2572477"],
}
required_headers = [
    "sample_id", "rule_id", "location", "value",
    "front_visible", "front_status", "side_visible", "side_status",
    "back_visible", "back_status", "note",
]
missing = []
rule_rows = 0
for category, ids in expected.items():
    for sample_id in ids:
        sample_dir = root / category / sample_id
        if not sample_dir.is_dir():
            missing.append(str(sample_dir))
            continue
        if not any((sample_dir / f"2d_original{suffix}").exists() for suffix in [".jpg", ".jpeg", ".png", ".webp"]):
            missing.append(str(sample_dir / "2d_original.<image>"))
        for name in ["atomic_rules.json", "multiview_design.png", f"{sample_id}.xlsx"]:
            if not (sample_dir / name).exists():
                missing.append(str(sample_dir / name))
        xlsx = sample_dir / f"{sample_id}.xlsx"
        if xlsx.exists():
            wb = load_workbook(xlsx, read_only=True)
            ws = wb.active
            headers = [cell.value for cell in ws[1]]
            if headers[:len(required_headers)] != required_headers:
                missing.append(f"{xlsx}: bad headers {headers}")
            rule_rows += ws.max_row - 1
            wb.close()

print({"samples": sum(len(v) for v in expected.values()), "xlsx_rule_rows": rule_rows, "missing_or_bad": missing})
if missing:
    raise SystemExit(1)
'@ | .\.venv\Scripts\python.exe -
```

### 6.3 跑最相关单测

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_safebooru_trial_workflow.py
```

---

## 7. 提升为正式目录

确认 staging 包没问题后，再替换正式目录。先备份，不要直接删：

```powershell
$Backup = "vlm/data/multi_view试标数据集_rev_backup_$(Get-Date -Format yyyyMMdd_HHmmss)"
Move-Item "$Reference" "$Backup"
Move-Item "$PackageWork" "$Reference"

Write-Host "backup=$Backup"
Write-Host "target=$Reference"
```

如果只是要生成一份新的交付包，不要替换旧目录，直接把 `$PackageWork` 压缩交付即可：

```powershell
Compress-Archive -Path "$PackageWork/*" -DestinationPath "$Work/multi_view试标数据集_rev.zip" -Force
```

---

## 8. 常见问题

### 8.1 什么时候必须调 API？

| 缺失内容 | 是否需要 API | 命令 |
|---|---:|---|
| `atomic_rules.json` 缺失 | 需要 Qwen API | `vlm.scripts.extract_atomic_rules_safebooru` |
| `multiview_design.png` 缺失 | 需要 RunningHub API | `vlm.scripts.generate.generate_head_keychain_with_runninghub_g2` |
| 只缺 `.xlsx` | 不需要 | `vlm.scripts.build_safebooru_trial_dataset` |
| 只缺 Excel 下拉框 | 不需要 | `vlm.scripts.utils.sync_annotation_workbook_validations` |

### 8.2 当前 `.xlsx` 是否包含中文？

当前脚本生成的是机器可读英文枚举和值：

```text
visible / invisible
correct / wrong color / wrong shape / wrong_prosition / extra / correct invisible / wrong invisible
```

如果要给只看中文的标注员，建议另起脚本给 Excel 增加中文辅助列或中文说明 sheet，不要直接改机器枚举值，否则后续解析/QC 会失败。

### 8.3 `result` 列问题

当前 `multi_view试标数据集_rev` 的历史模板列是：

```text
sample_id, rule_id, location, value,
front_visible, front_status, side_visible, side_status, back_visible, back_status, note
```

近期 QC 报告指出正式标注验收可能需要额外 `result` 汇总列。若甲方确认新模板必须有 `result`，需要先修改共享 xlsx writer，再重新执行第 5-6 步；不要让标注员手工临时加列后直接进入机器评测链路。

