# VLM Image Analysis Experiment Report

**Model**: qwen36-vl:latest
**Embedding Model**: bge-m3:latest (via Ollama)
**Date**: 2026-07-23 17:34:21
**Total Samples**: 20
**Total Time**: 432.6s

## Aggregate Metrics

| Metric | Value |
|--------|-------|
| Avg Semantic Similarity | 0.6818 |
| Min Similarity | 0.6002 |
| Max Similarity | 0.7928 |
| Avg Coverage (GT recall) | 0.9762 |
| Avg Precision | 0.9099 |
| Total GT Elements | 111 |
| Total Predicted Elements | 120 |
| Total Matched | 108 |
| Total Unmatched (extra predictions) | 12 |
| Total Unmatched (missed GT) | 3 |
| Overall Coverage | 0.973 |
| Overall Precision | 0.9 |

## Per-Sample Details

### char_001

- **GT elements**: 5, **Pred elements**: 6
- **Matched**: 5, **Avg Similarity**: 0.6807
- **Coverage**: 1.0, **Precision**: 0.8333
- **Inference time**: 46.4s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型发色 | 金色长发与黑色蝴蝶结 | 0.6878 |
| 2 | 头饰 | 白色衬衫与蓝色宝石领饰 | 0.6166 |
| 3 | 眼睛颜色和形状 | 红色眼睛 | 0.7874 |
| 4 | 上衣 | 白色外套 | 0.718 |
| 5 | 颈部配饰 | 黑色短裙与腰带 | 0.5937 |

#### Extra Predictions (model found, not in GT)

- **下装**: 下身穿着深棕色或黑色的裙子（或裤裙），腰部有明显的束腰设计，颜色与上衣形成对比。

---

### char_002

- **GT elements**: 5, **Pred elements**: 8
- **Matched**: 5, **Avg Similarity**: 0.6422
- **Coverage**: 1.0, **Precision**: 0.625
- **Inference time**: 21.1s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型发色 | 黑白相间的发型 | 0.7431 |
| 2 | 面部特征 | 黑色手套 | 0.5281 |
| 3 | 外套 | 红色长外套与金色火焰纹饰 | 0.7052 |
| 4 | 内搭衣物 | 白色高领内衬与骷髅腰带 | 0.6899 |
| 5 | 腰部配饰 | 蓝色灯笼裤与红色靴套 | 0.5446 |

#### Extra Predictions (model found, not in GT)

- **下装**: 深蓝色宽松灯笼裤，裤脚处收紧
- **鞋履**: 红色短靴套搭配深灰色尖头鞋
- **项链**: 黑色细绳项链，悬挂一颗红色的水滴状吊坠

---

### char_003

- **GT elements**: 4, **Pred elements**: 5
- **Matched**: 4, **Avg Similarity**: 0.6342
- **Coverage**: 1.0, **Precision**: 0.8
- **Inference time**: 21.1s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型与发色 | 棕色高马尾 | 0.7373 |
| 2 | 眼睛特征 | 绿色百褶短裙 | 0.4791 |
| 3 | 上衣设计 | 黄色T恤与饭团图案 | 0.7631 |
| 4 | 下装款式 | 黄绿配色运动鞋 | 0.5575 |

#### Extra Predictions (model found, not in GT)

- **鞋履**: 白色为主色调的运动鞋或帆布鞋，配有黄色的鞋带（或装饰线条）以及黑色的鞋底边缘和侧面细节。

---

### char_004

- **GT elements**: 6, **Pred elements**: 5
- **Matched**: 5, **Avg Similarity**: 0.7928
- **Coverage**: 0.8333, **Precision**: 1.0
- **Inference time**: 19.8s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型与发色 | 浅棕色长发 | 0.8021 |
| 2 | 眼睛颜色与形状 | 蓝色眼睛 | 0.7688 |
| 3 | 外套 | 粉色外套与黑色袖口 | 0.7536 |
| 4 | 内搭连衣裙与领结 | 白色连衣裙与绿色内衬 | 0.8022 |
| 5 | 发饰 | 发饰（蓝色宝石发夹） | 0.8374 |

#### Missed Elements (in GT, model didn't find)

- **粉色蝴蝶结领结**: 胸前系有一个大而饱满的粉色蝴蝶结，位置居中，边缘有褶皱细节，颜色鲜艳。

---

### char_005

- **GT elements**: 6, **Pred elements**: 8
- **Matched**: 6, **Avg Similarity**: 0.6804
- **Coverage**: 1.0, **Precision**: 0.75
- **Inference time**: 22.4s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型发色 | 银白色短发 | 0.7116 |
| 2 | 眼睛与眉毛 | 黑色领结 | 0.529 |
| 3 | 白色长款燕尾服外套 | 白色长礼服与燕尾设计 | 0.8599 |
| 4 | 浅灰蓝色马甲 | 灰色马甲与金色链条 | 0.756 |
| 5 | 黑色蝴蝶结领结 | 白色手套 | 0.5905 |
| 6 | 白色手套 | 白色皮鞋 | 0.6354 |

#### Extra Predictions (model found, not in GT)

- **金色腰链**: 腰间系有一条细细的金色链条（类似怀表链），从马甲左侧腰部延伸出来，呈弧形垂落在身前，增加了细节装饰。
- **浅灰色长裤与皮鞋**: 下身穿着浅灰色的修身长裤，裤线笔直。脚踩一双白色的尖头皮鞋，整体色调与上衣保持一致，显得整洁优雅。

---

### char_006

- **GT elements**: 6, **Pred elements**: 6
- **Matched**: 6, **Avg Similarity**: 0.721
- **Coverage**: 1.0, **Precision**: 1.0
- **Inference time**: 23.8s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型发色 | 双麻花辫发型 | 0.7419 |
| 2 | 帽子 | 米色帽子与太阳镜 | 0.7835 |
| 3 | 墨镜 | 浅紫色手提包 | 0.5561 |
| 4 | 服装（套装裙） | 浅紫色套装 | 0.7766 |
| 5 | 鞋子 | 白色高跟鞋 | 0.852 |
| 6 | 配饰（手提包） | 白色宽腰带 | 0.6162 |

---

### char_007

- **GT elements**: 5, **Pred elements**: 5
- **Matched**: 5, **Avg Similarity**: 0.7416
- **Coverage**: 1.0, **Precision**: 1.0
- **Inference time**: 16.3s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型与发色 | 棕色长发与侧边辫子 | 0.7634 |
| 2 | 眼镜与眼睛 | 圆形眼镜 | 0.7667 |
| 3 | 上身制服 | 蓝色西装外套与红色领结 | 0.664 |
| 4 | 下身裙装 | 灰色百褶短裙 | 0.7628 |
| 5 | 鞋袜配饰 | 灰色长袜与棕色皮鞋 | 0.751 |

---

### char_008

- **GT elements**: 6, **Pred elements**: 6
- **Matched**: 6, **Avg Similarity**: 0.6177
- **Coverage**: 1.0, **Precision**: 1.0
- **Inference time**: 23.3s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头部头饰 | 白色小丑面具与红色鼻子 | 0.6424 |
| 2 | 面部特征 | 红黑相间的头发 | 0.6506 |
| 3 | 颈部装饰 | 黄色毛领与紫色条纹服装 | 0.657 |
| 4 | 上衣 | 红色腰带与飘带 | 0.565 |
| 5 | 腰部配饰 | 蓝色手套 | 0.5232 |
| 6 | 手部与腿部装备 | 蓝色长靴 | 0.6681 |

---

### char_009

- **GT elements**: 6, **Pred elements**: 5
- **Matched**: 5, **Avg Similarity**: 0.7269
- **Coverage**: 0.8333, **Precision**: 1.0
- **Inference time**: 18.0s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型与发色 | 紫色猫耳与长发 | 0.8042 |
| 2 | 眼睛特征 | 黄色眼睛 | 0.7173 |
| 3 | 服装 (和服) | 和服 | 0.8295 |
| 4 | 袖口细节 | 棕色腰带与金色绳结 | 0.5911 |
| 5 | 鞋子与足部 | 红棕木屐和白色袜子 | 0.6922 |

#### Missed Elements (in GT, model didn't find)

- **红色长裙**: 外穿红色长裙，裙摆覆盖至小腿，需注意层次感。

---

### char_010

- **GT elements**: 6, **Pred elements**: 6
- **Matched**: 6, **Avg Similarity**: 0.6682
- **Coverage**: 1.0, **Precision**: 1.0
- **Inference time**: 20.7s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型与发色 | 紫色渐变长发 | 0.7921 |
| 2 | 眼睛颜色与形状 | 蓝色眼睛 | 0.7793 |
| 3 | 头部配饰 | 头饰（带粉色尖角的头箍） | 0.7946 |
| 4 | 上身服装 | 蓝白相间的连衣裙 | 0.6088 |
| 5 | 下身裙摆 | 紫色长筒袜 | 0.5647 |
| 6 | 腿部与鞋袜 | 领饰 | 0.4694 |

---

### char_011

- **GT elements**: 6, **Pred elements**: 6
- **Matched**: 6, **Avg Similarity**: 0.6394
- **Coverage**: 1.0, **Precision**: 1.0
- **Inference time**: 21.0s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型与发色 | 粉色长卷发与发饰 | 0.7426 |
| 2 | 眼睛 | 粉色猫耳与猫尾 | 0.5399 |
| 3 | 服装 (和服) | 淡紫色和服上衣与花卉图案 | 0.7585 |
| 4 | 尾巴 | 棕色腰带与黄色大蝴蝶结 | 0.5648 |
| 5 | 头饰 | 深棕色下裙与底部花纹 | 0.498 |
| 6 | 鞋子 | 白色袜子与木屐 | 0.7326 |

---

### char_012

- **GT elements**: 7, **Pred elements**: 8
- **Matched**: 7, **Avg Similarity**: 0.6113
- **Coverage**: 1.0, **Precision**: 0.875
- **Inference time**: 29.3s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头部特征 | 绿色皮肤 | 0.6002 |
| 2 | 面部细节 | 棕色头巾 | 0.5464 |
| 3 | 上身外套 | 卡其色毛皮装饰的棕色外衣 | 0.7483 |
| 4 | 内搭衣物 | 白色内衬与棕色腰带 | 0.6648 |
| 5 | 腰部装饰 | 白色裤子与毛皮裤脚 | 0.5943 |
| 6 | 下身围裙/下摆 | 浅棕色绑腿与靴子 | 0.5927 |
| 7 | 裤装与鞋履 | 手臂上的浅棕色护腕 | 0.5325 |

#### Extra Predictions (model found, not in GT)

- **四肢护具**: 双臂的小臂部分以及双腿的小腿部分都缠绕着黄褐色的绷带或布条，作为护腕和护胫使用。

---

### char_013

- **GT elements**: 6, **Pred elements**: 6
- **Matched**: 6, **Avg Similarity**: 0.633
- **Coverage**: 1.0, **Precision**: 1.0
- **Inference time**: 18.4s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型与发色 | 金色短发与胡须 | 0.791 |
| 2 | 面部特征 | 黑色外衣与黄色内衬 | 0.5235 |
| 3 | 上身服装 | 毛边围裙与裤脚毛饰 | 0.612 |
| 4 | 下身服装 | 棕色靴子与深色袜子 | 0.6681 |
| 5 | 鞋履 | 棕色皮质腰带与斜挎剑鞘 | 0.5276 |
| 6 | 装备与配饰 | 左肩金属护甲 | 0.676 |

---

### char_014

- **GT elements**: 6, **Pred elements**: 6
- **Matched**: 6, **Avg Similarity**: 0.7408
- **Coverage**: 1.0, **Precision**: 1.0
- **Inference time**: 17.8s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型发色 | 白色短发 | 0.723 |
| 2 | 眼睛特征 | 红色右眼 | 0.7455 |
| 3 | 服装 | 黑红配色服装 | 0.6879 |
| 4 | 机械义肢 | 机械义肢 | 0.8797 |
| 5 | 武器 | 双枪武器 | 0.8244 |
| 6 | 手部装备 | 黑色眼罩 | 0.5843 |

---

### char_015

- **GT elements**: 5, **Pred elements**: 7
- **Matched**: 5, **Avg Similarity**: 0.6365
- **Coverage**: 1.0, **Precision**: 0.7143
- **Inference time**: 21.1s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型与发色 | 深灰色短发与紫色尖角头饰 | 0.6951 |
| 2 | 头部机械装饰 | 紫色与黑色相间的紧身战斗服 | 0.5413 |
| 3 | 眼睛特征 | 发红色眼睛 | 0.7783 |
| 4 | 上身服装 | 紫色长袖 | 0.6248 |
| 5 | 长披风 | 黑色长筒袜与紫色高跟靴 | 0.5429 |

#### Extra Predictions (model found, not in GT)

- **腿部与鞋履**: 下身穿着深灰色的过膝长筒袜（或连裤袜），大腿部分有类似腿环的紫色装饰细节。脚踩一双尖头高跟鞋，鞋面主要为黑色和紫色，鞋底和鞋跟尖端为白色。
- **手臂护具**: 双臂佩戴着黑白相间的机械风格护臂（或手套），护臂上有紫色的发光细节装饰，看起来像是某种高科技装备的一部分。

---

### char_016

- **GT elements**: 5, **Pred elements**: 5
- **Matched**: 5, **Avg Similarity**: 0.7822
- **Coverage**: 1.0, **Precision**: 1.0
- **Inference time**: 16.2s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型发色 | 黑色短发 | 0.7474 |
| 2 | 眼睛颜色和形状 | 绿色眼睛 | 0.8484 |
| 3 | 上衣服装 | 黄色运动上衣 | 0.7954 |
| 4 | 下装服装 | 黑色运动短裤 | 0.7655 |
| 5 | 鞋袜 | 白色运动鞋 | 0.7543 |

---

### char_017

- **GT elements**: 7, **Pred elements**: 6
- **Matched**: 6, **Avg Similarity**: 0.6699
- **Coverage**: 0.8571, **Precision**: 1.0
- **Inference time**: 27.5s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头部特征 | 蓝绿色皮肤与黄色眼睛 | 0.6603 |
| 2 | 发型与头饰 | 白色羽毛头饰与红色尖端 | 0.7797 |
| 3 | 上身服装 | 毛皮披肩与棕色绑带 | 0.6686 |
| 4 | 下身服装与腿部 | 脚爪与趾甲 | 0.5455 |
| 5 | 尾巴 | 长尾与尾尖弯钩 | 0.7687 |
| 6 | 皮肤与肤色 | 兽角与银白色的羽毛装饰 | 0.5968 |

#### Missed Elements (in GT, model didn't find)

- **几何图案装饰（黄红相间）**: 头部、腰部及腿部护具上有黄红相间的三角形几何图案，需准确绘制图案排列与颜色分界。

---

### char_018

- **GT elements**: 4, **Pred elements**: 5
- **Matched**: 4, **Avg Similarity**: 0.7702
- **Coverage**: 1.0, **Precision**: 0.8
- **Inference time**: 15.4s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型发色 | 棕色短发 | 0.8129 |
| 2 | 眼睛颜色和形状 | 橙色眼睛 | 0.7624 |
| 3 | 上衣服装 | 白色制服外套与蓝色绳结 | 0.7601 |
| 4 | 裤子服装 | 白色长裤与黑色皮鞋 | 0.7454 |

#### Extra Predictions (model found, not in GT)

- **鞋子**: 深灰色或黑色的低帮皮鞋（类似乐福鞋），款式简洁。

---

### char_019

- **GT elements**: 6, **Pred elements**: 6
- **Matched**: 6, **Avg Similarity**: 0.6002
- **Coverage**: 1.0, **Precision**: 1.0
- **Inference time**: 18.6s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型发色 | 蓝色高马尾 | 0.7774 |
| 2 | 眼睛特征 | 紫色与红色相间的上衣 | 0.4848 |
| 3 | 上身服装 | 粉色短裙与黑色短裤 | 0.595 |
| 4 | 下身裙装 | 黑色过膝袜与棕色靴子 | 0.5827 |
| 5 | 腿部装饰与袜饰 | 棕色靴子与蕾丝边装饰 | 0.704 |
| 6 | 鞋履 | 银色手环 | 0.4571 |

---

### char_020

- **GT elements**: 4, **Pred elements**: 5
- **Matched**: 4, **Avg Similarity**: 0.6467
- **Coverage**: 1.0, **Precision**: 0.8
- **Inference time**: 14.7s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型发色 | 黑色长直发 | 0.7183 |
| 2 | 眼睛颜色和形状 | 白色内搭 | 0.5052 |
| 3 | 上身服装 | 灰色西装套装 | 0.7722 |
| 4 | 下身服装 | 灰色高跟鞋 | 0.591 |

#### Extra Predictions (model found, not in GT)

- **鞋子**: 穿着一双深色（黑色或深灰）的尖头高跟鞋，设计简约干练，与整体职业装束相搭配。

---
