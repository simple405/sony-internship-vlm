# 10610 张设定集图片全量数据生产 Plan

## Summary

主数据源切换为：

```text
vlm/data/safebooru_character_sheet   6217张
vlm/data/safebooru_turnaround        1908张
vlm/data/角色分解                     2485张
```

合计 `10610` 张。旧的 `safebooru_2d` 非设定集数据不再作为主生产对象。新流程全量处理这 `10610` 张：六类分配、Qwen 提取 atomic_rules、RunningHub 生成 multiview 三视图、生成 `.xlsx`，最终每个样本一个文件夹，包含四个核心文件。

## Output Structure

新数据集根目录建议为：

```text
vlm/data/design_sheet_10610
```

最终交付目录：

```text
vlm/data/design_sheet_10610/multi_view试标数据集_new/
  backpack/
    9730/
      2d_original.png
      atomic_rules.json
      multiview_design.png
      9730.xlsx
  cake_roll/
    64577/
      2d_original.jpg
      atomic_rules.json
      multiview_design.png
      64577.xlsx
  dataset_figurine/
  dataset_QSitFigures/
  head_key_chain/
  plush/
```

每个样本文件夹必须包含：

```text
2d_original.<ext>
atomic_rules.json
multiview_design.png
<sample_id>.xlsx
```

生产中间目录：

```text
design_sheet_10610/
  image/
  atomic_rules/
  generated/<category>/<sample_id>/
  reports/
  manifest.csv
  metadata.jsonl
  multi_view试标数据集_new/
```

## Key Changes

- 全量使用 `10610` 张新设定集图片。
- 不再继续旧 `safebooru_2d` 非设定集数据的 4000 张扩容主线。
- 三源图片先导入到统一数据集根目录。
- `sample_id` 使用图片 id；若三个源目录有重复 id，默认加来源前缀避免覆盖：
  ```text
  cs_1054558
  ta_1054558
  cd_1-1014315226
  ```
  这样能保留全量 `10610` 张。
- `.gif` 默认转首帧为 `.png` 后进入数据集；失败记录到 rejected manifest。
- 六类使用现有代码类别名：
  ```text
  backpack
  cake_roll
  dataset_figurine
  dataset_QSitFigures
  head_key_chain
  plush
  ```
  `back_pack` 统一映射为 `backpack`。

## Pipeline

1. **导入与 manifest**
   - 扫描三个源目录。
   - 复制/规范化图片到：
     ```text
     design_sheet_10610/image/<sample_id>.<ext>
     ```
   - 生成：
     ```text
     manifest.csv
     metadata.jsonl
     reports/import_summary.json
     reports/duplicate_ids.csv
     reports/rejected_images.csv
     ```
   - manifest 至少包含：
     ```text
     sample_id, image_path, source_dataset, source_path, original_file_name, sha256, width, height, extension
     ```

2. **六类均衡分配**
   - 对 `10610` 张全量分配到六类。
   - 目标分布：
     ```text
     head_key_chain       1769
     cake_roll            1769
     backpack             1768
     plush                1768
     dataset_QSitFigures  1768
     dataset_figurine     1768
     ```
   - 输出：
     ```text
     reports/merchandise_category_assignment/merchandise_category_assignments.csv
     reports/merchandise_category_assignment/sample_lists/<category>.txt
     ```

3. **Qwen atomic_rules**
   - Qwen 视觉模型读取 2D 原图。
   - 输出：
     ```text
     atomic_rules/<sample_id>/atomic_rules.json
     ```
   - 每条 rule 必须包含：
     ```json
     {"id": "hair_color", "location": "head", "value": "orange"}
     ```
   - `location` 只允许：
     ```text
     head
     body
     ```
   - `*_position` 的 left/right 必须按标注员/观察者视角。
   - Qwen error 写：
     ```text
     atomic_rules/<sample_id>/error.json
     ```

4. **RunningHub multiview**
   - RunningHub 只接收：
     ```text
     原始2D图片 + 类别固定prompt
     ```
   - 不传 atomic_rules。
   - 输出：
     ```text
     generated/<category>/<sample_id>/<sample_id>_<suffix>.png
     ```
   - 失败写：
     ```text
     generated/<category>/<sample_id>/generation_error.json
     ```

5. **最终打包和 `.xlsx`**
   - 打包成最终目录：
     ```text
     multi_view试标数据集_new/<category>/<sample_id>/
     ```
   - 每个样本目录包含：
     ```text
     2d_original.<ext>
     atomic_rules.json
     multiview_design.png
     <sample_id>.xlsx
     ```
   - 头部类只写 `location=head`：
     ```text
     head_key_chain
     cake_roll
     backpack
     ```
   - 全身类写全量 rules：
     ```text
     plush
     dataset_QSitFigures
     dataset_figurine
     ```
   - `.xlsx` 不再机械左右翻转，直接使用 JSON 中已按标注员视角修正的 value。

## Test Plan

- 导入检查：
  - 总样本数应为 `10610`，除非 gif/损坏图被明确记录拒绝。
  - `sample_id` 全局唯一。
  - 每个 manifest 行的 `image_path` 可读。

- Qwen smoke test：
  - 每个源目录各抽样。
  - 每条 rule 都包含 `id/location/value`。
  - `location` 无非法值。
  - 抽查 `*_position` 是否符合标注员视角。

- RunningHub smoke test：
  - 六类每类 2-3 张。
  - 验证输出图片、错误记录、目录命名。

- 最终包检查：
  - 每个成功样本目录必须有四个核心文件。
  - 头部类 `.xlsx` 不含 body rules。
  - 全身类 `.xlsx` 包含全部 rules。
  - `multiview_design.png` 存在且可读。

## Assumptions

- 全量处理新的 `10610` 张。
- 重复图片 id 不去重，使用来源前缀保证全量保留。
- 旧 `safebooru_2d` 只作为代码/方法参考，不作为主生产数据。
- `atomic_rules.json` 每条 rule 直接写入 `location=head/body`。
- 最终包按类别分组，再按 sample_id 建文件夹。
