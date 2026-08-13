# SN-6 下一步实验与数据处理建议

Date: 2026-08-11

## 当前可用数据

- 源 paired 数据：`vlm/data/1-动漫标注结果导出_paired_samples/`
  - `manifest.csv`: 6901 samples
  - JSON：6901 个，可解析；每条为 `[{element, description, bbox}, ...]`
  - rule 数：44432；单样本多数为 5-8 条 rule
  - 配对摘要：0 missing image，3 orphan image stem
- SN6 v2 生成集：`vlm/data/front_view_generation_v2/`
  - 6 类商品，每类 10 张，共 60 张
  - generated/original 各 60 张，生成图可读，exact duplicate=0
- Qwen `review_v2`：
  - 60/60 succeeded
  - sample-level：60 pass / 0 fail / 0 review
  - rule-level：267 pass / 10 partial / 0 fail / 128 out_of_scope
  - partial：7 个样本、10 条 rule
- image-only agent v0：
  - 已跑 7 个 partial 样本
  - sample-level：4 pass / 2 fail / 1 review
  - rule-level：25 pass / 20 partial / 3 fail / 1 review / 10 out_of_scope

## 直接结论

1. `review_v2` 现在太顺，适合做 pseudo label / teacher，不适合作为最终 unbiased eval。
2. image-only v0 已经暴露偏严：同样 7 个 weak-pass 样本，silver JSON review 只给 partial，image-only 会打出 fail/review。
3. 下一步不该盲目扩大生成，应该先把 image-only 的误差闭环做起来：看它为什么把合理商品化简化误判为 fail。

## 优先实验

### E1. image-only v0 误差归因

对象：现有 7 个 partial 样本。

要做：
- 对齐 `_agent/image_only_v0/qc.csv` 与 `_review/review_v2/qc.csv`
- 标注每条分歧属于：
  - extractor 漏抽/多抽
  - comparator 口径过严
  - head/body 范围错误
  - color family 错误
  - silver label 本身不完整

验收：
- 输出一个 `disagreement_analysis.csv`
- 至少解释 3 个 image-only fail/review 是否应降级为 partial/pass

### E2. prompt ablation：温和口径 vs 当前口径

对象：先用 7 个 partial + 12 个 high_conf_pass。

变量只改 compare prompt：
- v0：当前 prompt
- v1：加强“商品化合理转换”和“不要因 extractor 额外抽出的细碎元素扣分”
- v2：要求 fail 必须满足“关键身份元素确认缺失/跨大色系/严重结构错位”

指标：
- weak-pass 样本不应被打成 fail/review
- high_conf_pass 不应出现新增 fail
- rule-level partial 数不要无限膨胀

### E3. extractor 稳定性实验

对象：7 个 partial 样本，每张图重复抽取 2-3 次或换 prompt 轻微版本。

看：
- element 数是否稳定
- element 命名是否飘
- bbox 是否可用
- 是否产生源图不存在的负向占位元素

用途：
- 判断要不要引入 element normalization：头发/刘海/眼睛/表情/服装主色块等 canonical class。

### E4. 分层扩容到 120/180 样本

不要直接随机扩；按源 JSON rule 数和图像大小分层。

建议：
- 每类再加 10-20 张
- 分层维度：
  - rule count：<=5、6-8、>=9
  - image bytes：<50k、50-150k、150-500k、>=500k
  - 关键元素：眼睛/鞋袜/手套/眼镜/发饰/武器/尾巴/翅膀

目的：
- 专门找现在 60 张没覆盖的复杂角色和低清图。

### E5. 负样本/扰动集

现在全是正向生成，监修器没法证明能抓错。

构造方式：
- 颜色替换：眼睛、头发、服装主色块跨大色系
- 缺失：移除发饰/眼镜/武器/标志图案
- 结构错位：左右饰品换位、衣领/纽扣缺失
- extra：加入明显不属于角色的帽子/动物耳/大装饰

不一定要重新生图，可以先用已有图做人工/图像编辑小集。

### E6. 人工 gold 最小闭环

不用等 500 条，先做小闭环：
- 7 个 partial 样本全量 rule
- 12 个 high_conf_pass 抽样 rule
- 10-20 条人工构造负样本 rule

目标：
- 建一个 100-200 rule 的 dev set
- 专门调 image-only 口径，不拿来报最终准确率

## 可处理的数据问题

1. `source_json` / `source_image` 仍记录绝对路径，建议生成一个 portable manifest：
   - `sample_id`
   - `json_relpath`
   - `image_relpath`
   - `sha256`
   - `image_ext`
   - `image_bytes`
   - `rule_count`
2. 源 JSON 元素缺 canonical class，建议离线补一列：
   - `canonical_element`: hair / bangs / eyes / expression / glasses / clothing_main / shoes / gloves / accessory / weapon ...
3. `image_only_v0/qc.csv` 与 `review_v2/qc.csv` 缺统一对齐键：
   - 建议统一输出 `sample_key`, `rule_index`, `element`, `location`, `result`, `source`
4. head-only 品类边界要再明确：
   - backpack 当前按 head-only 处理，body 被 out_of_scope；但背包商品可能承载武器/肩甲等 body 视觉，需要决定是否作为“商品可见身份元素”单独评价。
5. 需要拆分数据桶：
   - `high_conf_pass`: 53 samples
   - `weak_pass`: 7 samples
   - `negative_or_mutated`: 待构造
   - `human_dev`: 待人工确认

## 建议下一步顺序

1. 先做 E1，产出分歧表。
2. 改 compare prompt 做 E2，重跑 7+12。
3. 若 v1 口径稳定，再扩容到 120/180。
4. 同时做 portable manifest + canonical element。
5. 最后才考虑大批量 API 或训练。
