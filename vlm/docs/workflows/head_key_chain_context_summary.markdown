# Head Keychain Prompt Debug Summary

更新日期：2026-06-29

## 项目背景

工作区根目录：

```text
D:\索尼实习
```

当前任务是为动漫 IP 监修流程生成 `head_keychain` 类型的 3D/Q 版毛绒头部挂件设计图。当前主模型为 DashScope:

```text
model: qwen-image-2.0-pro-2026-06-22
script: vlm/scripts/generate_3d_with_qwen_image_edit.py
rule_mode: none
```

重要约束：后续生成阶段不能依赖 `atomic_rules`，因为用户认为当前 `atomic_rules` 不一定准确。生成输入只能使用：

```text
1. prompt
2. 2D 原图
```

旧版 head_keychain prompt 仍在：

```text
vlm/prompts/generation/qwen_head_keychain_no_rules.txt
```

旧版已生成 head_keychain 输出仍在：

```text
vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d_no_rules/qwen-image-2.0-pro-2026-06-22/head_keychain
```

## 用户指出的旧版问题

以下是用户逐样本指出的问题，并已通过原图/生成图对照基本确认：

```text
2027251
原角色是单马尾/高位扎发，但 head_keychain 输出变成散发，后视图没有保留马尾结构。

2028680
原图是黄色头部发饰/蝴蝶结一类装饰，生成图把它误生成了兽耳/尖耳感。

2028681
原图眼睛是闭上的或低垂闭眼感，生成图眼睛睁开了。
原图背后有多束发尾/发结结构，用户描述为五个辫子，但生成图简化成约两个。

2028685
原素材中有扎好的辫子/后方扎发结构，3D 设计图没有保留。

2028690
生成图没有保留黑色帽子，也没有保留侧辫。

2166018
原图头部特征主要是头发/角状结构，生成时额外幻觉出了兽耳/猫耳。
注意：atomic_rules 里有 has_horns，但用户强调生成图里出现的是不应有的兽耳；如果画角，也必须按原图画成角，不能改成猫耳/动物耳。
```

对照图曾生成在：

```text
vlm/tmp/head_keychain_error_review/head_keychain_user_corrections_review.jpg
```


### 2. 泛化中文 prompt

根据“不能用 atomic_rules，只能 prompt + 2D 原图”的约束，创建了中文泛化 prompt：

```text
vlm/prompts/generation/qwen_head_keychain_general_cn.txt
```

核心思想：

```text
- 用中文提示 Qwen
- 先观察原图头部特征，再毛绒化
- 条件式保留发型、发色、头饰、眼睛开闭、背面发束
- 禁止把发饰/头发尖角/帽子边缘误画成兽耳
- 禁止新增原图没有的头部元素
```

运行输出目录：

```text
vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated_3d_no_rules/qwen-image-2.0-pro-2026-06-22/head_keychain_general_cn
```

本轮运行已被用户中断并要求终止。进程已终止，相关 Python 进程剩余数为 0。

中断前已生成 2 个样本：

```text
2027251
2028680
```

用户反馈第一张效果图仍不对，因此不要继续沿用该中文泛化 prompt 直接批量跑。

## 当前脚本状态

脚本：

```text
vlm/scripts/generate_3d_with_qwen_image_edit.py
```

当前已加入以下能力：

```text
--workers
  可调并发 worker 数，默认 1。
  注意：DashScope 批量生图可能触发 429 或网络不稳定，workers 不应开太高。

--output-dataset
  可把输出写到模型目录下的新同层目录，避免覆盖旧结果。
  例如：--output-dataset head_keychain_general_cn

实时进度 JSONL 输出
  stdout 会实时打印 batch_started、sample_request_started、waiting_for_request_slot、sample_finished、sample_failed、finished 等 JSONL。

请求异常重试
  已捕获 requests 层网络异常，例如 DNS/ConnectionError，并按 retry-base-sleep 退避。
```

实现风险提示：`--workers` 已支持，但当前请求安全边界建议低并发，最好从 `--workers=1` 或 `--workers=2` 开始，并配合：

```text
--request-sleep 90
--retries 3
--retry-base-sleep 90
```

## 可复现命令

这条命令是刚才用来跑中文泛化 prompt 的版本。它已证明第一张效果不理想，后续不要直接继续跑，除非先换 prompt。

```powershell
.\.venv\Scripts\python.exe .\vlm\scripts\generate_3d_with_qwen_image_edit.py `
  --source-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\generated_3d_no_rules\qwen-image-2.0-pro-2026-06-22\head_keychain `
  --atomic-dir .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\atomic_rules `
  --output-root .\vlm\data\safebooru_2d\japanese_anime_turnaround_pilot_20\generated_3d_no_rules `
  --model qwen-image-2.0-pro-2026-06-22 `
  --product-type head_keychain `
  --output-dataset head_keychain_general_cn `
  --all-source-samples `
  --prompt-file .\vlm\prompts\generation\qwen_head_keychain_general_cn.txt `
  --size 2048*872 `
  --no-prompt-extend `
  --request-sleep 90 `
  --retries 3 `
  --retry-base-sleep 90 `
  --workers=1 `
  --keep-debug-files
```

实时关注进度可以直接看终端 stdout；如果后台运行，查看：

```powershell
Get-Content -Tail 50 .\vlm\tmp\head_keychain_general_cn_run\stdout.jsonl
Get-Content -Tail 50 .\vlm\tmp\head_keychain_general_cn_run\stderr.log
```

## 当前判断

旧版英文 prompt 的主要问题不是商品形态，而是身份结构保真：

```text
- 发型结构丢失：马尾、侧辫、扎发、多束发尾被简化成散发或圆头。
- 配饰误读：发饰、帽子边缘、头发尖角容易被误画成兽耳/猫耳。
- 面部状态改变：闭眼被改成睁眼。
- 头部关键物缺失：帽子、侧辫、发饰等被省略。
```

`identity_v2` 和中文泛化 prompt 都说明，仅仅把“保留身份”写得更强，并不能保证更好；模型可能转而自创更多细节或仍然忽略关键结构。

## 下一步建议

后续新对话中应优先解决 prompt 设计，而不是继续跑批。

建议方向：

```text
1. 不使用 atomic_rules。
2. 不写死某个样本的帽子、侧辫、兽耳等特征，避免过拟合。
3. 但 prompt 需要更明确地区分：
   - 原图已有元素：必须保留
   - 原图没有元素：绝对不要新增
   - 头发/发饰/帽子边缘：不要误判成兽耳
4. 需要减少抽象长列表，改成更短、更硬的生成约束。
5. 可以考虑将任务拆成更明确的生成范式：
   “把原图头部做成毛绒头部三视图设定稿”，而不是“商品化成通用毛绒头挂件”。
6. 如果仍失败，考虑输入预处理：用原图裁出更清晰的头部区域作为参考图，而不是直接给复杂整张设定图。
```

可能的新 prompt 方向：

```text
请只根据输入图中角色的头部设计生成毛绒头部挂件三视图。
不要创造新角色，不要套用通用毛绒头模板。

生成前必须先遵守这条规则：
图中存在的头部结构必须保留；图中不存在的头部结构不能新增。

重点保留原图中实际可见的：
发型轮廓、刘海、侧发、后发、马尾、辫子、发髻、发色分布、帽子、发饰、角、耳朵、眼睛开闭状态。

如果原图没有兽耳或猫耳，禁止生成兽耳或猫耳。
不要把发饰、帽子边缘、头发尖角误画成兽耳。
不要把马尾、辫子、发髻或长后发改成散发或短发。
不要改变闭眼/睁眼状态。

输出一张白底三视图：正面、侧面、背面。
只画头部挂件，不画身体、脖子、肩膀、包装、文字、标签、水印。
允许毛绒材质和刺绣五官，但不能删除或新增身份关键特征。
```

这个方向还未重新测试。

