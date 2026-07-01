# RunningHub Merchandise Process

更新日期：2026-07-01 +08:00

## 当前结论

- 新增生图统一走 RunningHub API；不再用 Qwen 生图。
- 不覆盖已有生成图；续跑前先查进程和本地输出。
- RunningHub 只用 `runninghub.cn`；环境变量是 `RUNNINGHUB_API_KEY`。
- 请求只上传完整 2D 原图，不上传 `head_reference` 裁剪图。
- `dataset_figurine` 的 RunningHub prompt 已冻结，可用于后续批量。
- `dataset_QSitFigures` 已用历史 Qwen prompt 做 RunningHub smoke test，3/3 成功，效果可用；正式补齐时不要覆盖已有 Qwen 结果。
- `sample_lists/*.txt` 现在是全量互斥分类清单，不再是“剩余待生成”清单；脚本读取时必须过滤 `#` 注释行。
- 完成度必须按“样本目录内存在非 `_original.*` 的生成图”统计，不能只按样本目录是否存在统计。
- 平台风控/内容安全确认无法生成的样本必须记录到 `runninghub_blocked_samples.csv`，后续替换 2D 原图，不要反复重跑。

## 核心路径

```text
项目根目录: D:\索尼实习
数据集: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20
原图: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/image
atomic_rules: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/atomic_rules
输出根目录: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d_no_rules/runninghub
分类报告: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/reports/merchandise_category_assignment
风控失败记录: vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/reports/merchandise_category_assignment/runninghub_blocked_samples.csv
```

## 脚本和 Prompt

```text
vlm/scripts/data/assign_merchandise_categories.py
  刷新分类、sample_lists、contact_sheets。

vlm/scripts/orchestrate/run_runninghub_merchandise_full_batch.py
  续跑四类：head_key_chain -> backpack -> cake_roll -> plush；会跳过已有输出。

vlm/scripts/generate/generate_head_keychain_with_runninghub_g2.py
  RunningHub 底层脚本；用于单类/小批量调试。
```

冻结 prompt：

```text
vlm/prompts/generation/runninghub/runninghub_g2_head_keychain_user_cn.txt
vlm/prompts/generation/runninghub/runninghub_g2_backpack_user_cn.txt
vlm/prompts/generation/runninghub/runninghub_g2_cake_roll_user_cn.txt
vlm/prompts/generation/runninghub/runninghub_g2_plush_user_cn.txt
vlm/prompts/generation/runninghub/runninghub_g2_dataset_figurine_user_cn.txt
```

`dataset_figurine` 冻结依据：`3206142_figurine_pattern_fix2.png` 用户确认可用。该 prompt 加入了服装局部花纹位置/形状约束，避免把侧边或弯曲花纹移动到背面中心，或幻觉成十字、T 形、菱形等新符号。

`dataset_QSitFigures` smoke test 复用历史 Qwen prompt：

```text
vlm/archive/2026-06-29_cleanup/debug_outputs/qwen-image-2.0-pro-2026-06-22/_debug/1521302/1521302_qwen_image_edit_prompt.txt
```

## 当前状态

最后核查：2026-07-01 +08:00。续跑前必须按下方命令重新检查 RunningHub Python 进程。

当前真实完成度按“存在非 `_original.*` 的生成图”统计：

```text
head_key_chain        36 / 36    100.0%
backpack             143 / 143   100.0%
cake_roll             37 / 102    36.3%   # 当前正在恢复跑，缺口应继续减少
plush                108 / 109    99.1%   # 2436714 内容安全 1501，需替换 2D 原图
dataset_figurine     548 / 571    96.0%   # 含 2726312 内容安全 1501
dataset_QSitFigures   10 / 154     6.5%   # 历史 Qwen 结果保留，RunningHub 只补缺口

总计: 882 / 1115，完成 79.1%，缺 233
```

不要再用“目录数”等同于“完成数”。部分目录只有 `_original` 和 `atomic_rules`，没有生成图。

已知样本备注：

```text
3206142_figurine_pattern_fix2.png  可用，作为 dataset_figurine prompt 冻结样本
2436714                            plush 内容安全 1501；已记录，后续替换 2D 原图
2726312                            dataset_figurine 内容安全 1501；已记录，后续替换 2D 原图
3980916                            与 3980945 原图重复，用户已删除其输出目录
3873006                            重复生图，用户要求停止；本地进程已无
```

各 `sample_lists/*.txt` 文件尾部已追加状态注释：

```text
backpack.txt            missing_generated_image_retry_needed: 3961013,3999863
cake_roll.txt           missing_generated_image_retry_needed: 71 个样本
plush.txt               blocked_content_safety_1501_replace_2d: 2436714
dataset_figurine.txt    blocked_content_safety_1501_replace_2d: 2726312
dataset_figurine.txt    missing_generated_image_retry_needed: 22 个样本
dataset_QSitFigures.txt 未标注缺口；用户要求先不要在该文件标未处理样本
```

这些注释以 `# runninghub_status_notes 2026-07-01` 开头。后续读取样本 ID 时只读取纯数字行。

## 常用命令

查进程：

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'python|pythonw' -and $_.CommandLine -match 'runninghub|generate_head_keychain|run_runninghub' } |
  Select-Object ProcessId,Name,CommandLine |
  Format-List
```

刷新状态：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\data\assign_merchandise_categories.py

Import-Csv '.\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\reports\merchandise_category_assignment\category_summary.csv' |
  Format-Table -AutoSize
```

注意：`assign_merchandise_categories.py` 当前会按旧逻辑重写 `sample_lists/*.txt` 为“未生成列表”，不要在没有修改脚本前随意运行它，否则会覆盖全量互斥清单和尾部注释。

按真实生成图统计进度：

```powershell
$base='.\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20'
$listDir=Join-Path $base 'reports\merchandise_category_assignment\sample_lists'
$outBase=Join-Path $base 'generated_3d_no_rules\runninghub'
$cats=@('head_key_chain','backpack','cake_roll','plush','dataset_figurine','dataset_QSitFigures')
$rows=@()
foreach($cat in $cats){
  $ids=@(Get-Content -LiteralPath (Join-Path $listDir ($cat+'.txt')) | Where-Object { $_.Trim() -match '^\d+$' } | ForEach-Object { $_.Trim() })
  $done=0
  foreach($id in $ids){
    $dir=Join-Path (Join-Path $outBase $cat) $id
    if(Test-Path -LiteralPath $dir){
      $files=@(Get-ChildItem -LiteralPath $dir -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -notmatch '_original\.' -and $_.Extension.ToLower() -in @('.png','.jpg','.jpeg','.webp') })
      if($files.Count -gt 0){ $done++ }
    }
  }
  $rows += [pscustomobject]@{Category=$cat; Total=$ids.Count; Done=$done; Missing=($ids.Count-$done)}
}
$rows | Format-Table -AutoSize
```

续跑四个已接入批处理的类别：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\orchestrate\run_runninghub_merchandise_full_batch.py `
  --workers 6 `
  --poll-interval 8 `
  --timeout 1200
```

`dataset_figurine` 小批量调试模板：

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\generate\generate_head_keychain_with_runninghub_g2.py `
  --sample-id SAMPLE_ID `
  --source-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\image `
  --atomic-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\atomic_rules `
  --direct-output-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\generated_3d_no_rules\runninghub\dataset_figurine `
  --prompt-file .\vlm\prompts\generation\runninghub\runninghub_g2_dataset_figurine_user_cn.txt `
  --output-suffix figurine `
  --aspect-ratio 21:9 `
  --resolution 1k `
  --poll-interval 8 `
  --timeout 1200 `
  --workers 1 `
  --keep-debug-files
```

恢复全部缺口的原则：

```text
1. 续跑前先查 RunningHub Python 进程，避免重复开同类进程。
2. 只补没有非 original 生成图的样本。
3. 跳过 runninghub_blocked_samples.csv 里的风控样本。
4. dataset_QSitFigures 保留已有 Qwen `*_SitFigures.*`，RunningHub 只补缺口，output-suffix 仍用 `SitFigures`。
5. sample_lists 里有注释，读取时过滤非纯数字行。
```

## 下一步

1. 等当前 `cake_roll` 恢复进程结束后重新统计真实完成度。
2. 继续补 `dataset_QSitFigures` 缺口，保留已有 Qwen 输出，不覆盖。
3. 继续补 `dataset_figurine` 的非风控缺口；`2726312` 需要替换 2D 原图。
4. `plush` 的 `2436714` 需要替换 2D 原图。

