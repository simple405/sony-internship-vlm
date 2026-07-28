# VLM Image Analysis Experiment Report

**Model**: qwen36-vl:latest
**Embedding Model**: bge-m3:latest (via Ollama)
**Date**: 2026-07-28 11:52:01
**Total Samples**: 34
**Total Time**: 139.4s

## Aggregate Metrics

| Metric | Value |
|--------|-------|
| Avg Semantic Similarity | 0.6782 |
| Min Similarity | 0.5619 |
| Max Similarity | 0.8467 |
| Avg Coverage (GT recall) | 0.9568 |
| Avg Precision | 0.7385 |
| Total GT Elements | 204 |
| Total Predicted Elements | 272 |
| Total Matched | 194 |
| Total Unmatched (extra predictions) | 78 |
| Total Unmatched (missed GT) | 10 |
| Overall Coverage | 0.951 |
| Overall Precision | 0.7132 |

## Per-Category Breakdown

| Category | Precision | Matched / Total | Avg Similarity |
|----------|-----------|-----------------|----------------|
| accessory | 0.6769 | 44/65 | 0.6509 |
| clothing | 0.7979 | 75/94 | 0.6671 |
| face | 0.65 | 13/20 | 0.6966 |
| footwear | 0.2857 | 10/35 | 0.7251 |
| hair | 1.0 | 33/33 | 0.7122 |
| headwear | 1.0 | 10/10 | 0.6886 |
| other | 0.8 | 4/5 | 0.6143 |
| prop | 0.0 | 0/4 | 0 |
| skin_body | 0.8333 | 5/6 | 0.6478 |

## Per-Sample Details

### char_001

- **GT elements**: 5, **Pred elements**: 8
- **Matched**: 5, **Avg Similarity**: 0.6729
- **Coverage**: 1.0, **Precision**: 0.625
- **Inference time**: 4.2s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 金色长发与黑色蝴蝶结 | 0.7056 |
| 2 | 眼睛 | 红色眼睛 | 0.7957 |
| 3 | 头饰 | 白色衬衫与蓝色宝石领饰 | 0.6032 |
| 4 | 外套 | 白色外套 | 0.7479 |
| 5 | 衬衫 | 黑色短裙与腰带 | 0.5121 |

#### Extra Predictions (model found, not in GT)

- **领饰**: 黑色领结及垂坠装饰，中央镶嵌醒目的蓝色圆形宝石，下方连接垂直排列的黑色装饰扣链。
- **裙子**: 深棕色百褶裙。
- **腰带**: 深色腰带，配有金属扣环。

---

### char_002

- **GT elements**: 5, **Pred elements**: 11
- **Matched**: 5, **Avg Similarity**: 0.6111
- **Coverage**: 1.0, **Precision**: 0.4545
- **Inference time**: 5.6s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 黑白相间的发型 | 0.7465 |
| 2 | 眼镜 | 黑色手套 | 0.5088 |
| 3 | 面部纹路 | 红色长外套与金色火焰纹饰 | 0.5024 |
| 4 | 红色长外套 | 蓝色灯笼裤与红色靴套 | 0.6002 |
| 5 | 白色高领内搭 | 白色高领内衬与骷髅腰带 | 0.6977 |

#### Extra Predictions (model found, not in GT)

- **胡须**: 下巴处有黑色山羊胡
- **项链**: 黑色细绳，挂有红色吊坠
- **骷髅腰带**: 黑色宽腰带/护腹，中央印有银色骷髅头图案
- **蓝色长裤**: 深蓝色宽松灯笼裤，裤脚收紧
- **黑色手套**: 黑色露指手套
- **红黑短靴**: 脚踝处为红色包裹设计，鞋头及鞋底为深灰色/黑色

---

### char_003

- **GT elements**: 4, **Pred elements**: 4
- **Matched**: 4, **Avg Similarity**: 0.8467
- **Coverage**: 1.0, **Precision**: 1.0
- **Inference time**: 5.3s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型与发色 | 棕色高马尾 | 0.7566 |
| 2 | 黄色饭团图案T恤 | 黄色T恤与饭团图案 | 0.9371 |
| 3 | 绿色短裙 | 绿色百褶短裙 | 0.8698 |
| 4 | 运动鞋 | 黄绿配色运动鞋 | 0.8233 |

---

### char_004

- **GT elements**: 6, **Pred elements**: 7
- **Matched**: 6, **Avg Similarity**: 0.7915
- **Coverage**: 1.0, **Precision**: 0.8571
- **Inference time**: 3.4s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 浅棕色长发 | 0.795 |
| 2 | 发饰 | 发饰（蓝色宝石发夹） | 0.8221 |
| 3 | 眼睛 | 蓝色眼睛 | 0.8243 |
| 4 | 外套 | 粉色外套与黑色袖口 | 0.7718 |
| 5 | 领结 | 粉色蝴蝶结领结 | 0.7859 |
| 6 | 裙子 | 白色连衣裙与绿色内衬 | 0.7502 |

#### Extra Predictions (model found, not in GT)

- **腰带**: 腰部系着的浅蓝灰色宽腰带

---

### char_005

- **GT elements**: 6, **Pred elements**: 8
- **Matched**: 6, **Avg Similarity**: 0.7381
- **Coverage**: 1.0, **Precision**: 0.75
- **Inference time**: 5.8s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 银白色短发 | 0.7542 |
| 2 | 外套 | 白色长礼服与燕尾设计 | 0.7494 |
| 3 | 马甲 | 灰色马甲与金色链条 | 0.7629 |
| 4 | 领结 | 黑色领结 | 0.7738 |
| 5 | 裤子 | 白色皮鞋 | 0.5522 |
| 6 | 手套 | 白色手套 | 0.8359 |

#### Extra Predictions (model found, not in GT)

- **鞋子**: 白色尖头皮鞋。
- **腰间链条**: 金色细链条，垂挂在腰部前方，连接在腰侧。

---

### char_006

- **GT elements**: 6, **Pred elements**: 9
- **Matched**: 6, **Avg Similarity**: 0.6957
- **Coverage**: 1.0, **Precision**: 0.6667
- **Inference time**: 3.2s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 双麻花辫发型 | 0.7363 |
| 2 | 帽子 | 米色帽子与太阳镜 | 0.7186 |
| 3 | 上衣 | 浅紫色套装 | 0.7363 |
| 4 | 内搭 | 白色高跟鞋 | 0.5916 |
| 5 | 腰带 | 白色宽腰带 | 0.7906 |
| 6 | 裙子 | 浅紫色手提包 | 0.6006 |

#### Extra Predictions (model found, not in GT)

- **墨镜**: 黑色大框太阳镜，遮挡眼部
- **手提包**: 淡紫色单肩手提包，配有细肩带
- **鞋子**: 白色浅口高跟鞋

---

### char_007

- **GT elements**: 5, **Pred elements**: 7
- **Matched**: 5, **Avg Similarity**: 0.7584
- **Coverage**: 1.0, **Precision**: 0.7143
- **Inference time**: 5.5s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型 | 棕色长发与侧边辫子 | 0.7673 |
| 2 | 眼镜 | 圆形眼镜 | 0.8048 |
| 3 | 西装外套 | 蓝色西装外套与红色领结 | 0.6908 |
| 4 | 短裙 | 灰色百褶短裙 | 0.848 |
| 5 | 中筒袜 | 灰色长袜与棕色皮鞋 | 0.6811 |

#### Extra Predictions (model found, not in GT)

- **领结**: 红色大蝴蝶结，系于白色衬衫领口。
- **皮鞋**: 棕色圆头乐福鞋（制服鞋）。

---

### char_008

- **GT elements**: 6, **Pred elements**: 11
- **Matched**: 6, **Avg Similarity**: 0.6558
- **Coverage**: 1.0, **Precision**: 0.5455
- **Inference time**: 6.0s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 白色动物造型面具 | 白色小丑面具与红色鼻子 | 0.7602 |
| 2 | 红色鬓发 | 红黑相间的头发 | 0.7206 |
| 3 | 黄色毛绒领饰 | 黄色毛领与紫色条纹服装 | 0.778 |
| 4 | 蓝白竖条纹上衣 | 蓝色手套 | 0.5898 |
| 5 | 白色荷叶边袖口 | 红色腰带与飘带 | 0.5585 |
| 6 | 红色宽腰带 | 蓝色长靴 | 0.5278 |

#### Extra Predictions (model found, not in GT)

- **红色长飘带**: 从腰部后方垂下的两条红色长条状飘带，末端呈不规则撕裂状。
- **蓝白竖条纹长裤**: 与上衣同色系的蓝白竖条纹宽松长裤，裤脚收紧。
- **蓝色长手套**: 覆盖双手及前臂的深蓝色手套。
- **深蓝色长筒袜**: 覆盖小腿至脚踝的深蓝色长筒袜（或紧身裤延伸）。
- **深蓝色尖头靴**: 深蓝色的尖头短靴，鞋尖向上弯曲。

---

### char_009

- **GT elements**: 6, **Pred elements**: 6
- **Matched**: 6, **Avg Similarity**: 0.64
- **Coverage**: 1.0, **Precision**: 1.0
- **Inference time**: 3.6s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 紫色猫耳与长发 | 0.7328 |
| 2 | 猫耳 | 黄色眼睛 | 0.5339 |
| 3 | 眼睛 | 和服 | 0.5284 |
| 4 | 和服上衣 | 红色长裙 | 0.5679 |
| 5 | 腰带 | 棕色腰带与金色绳结 | 0.7994 |
| 6 | 鞋子 | 红棕木屐和白色袜子 | 0.6777 |

---

### char_010

- **GT elements**: 6, **Pred elements**: 6
- **Matched**: 4, **Avg Similarity**: 0.6872
- **Coverage**: 0.6667, **Precision**: 0.6667
- **Inference time**: 6.5s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 长发 | 紫色渐变长发 | 0.7956 |
| 2 | 头巾发饰 | 头饰（带粉色尖角的头箍） | 0.7661 |
| 3 | 短披肩 | 蓝白相间的连衣裙 | 0.568 |
| 4 | 连衣裙 | 紫色长筒袜 | 0.6189 |

#### Extra Predictions (model found, not in GT)

- **过膝袜**: 深紫色过膝长袜，脚踝处有白色V形开口或装饰细节。
- **短靴**: 深紫色短靴，与过膝袜颜色一致，脚踝处有白色细节装饰。

#### Missed Elements (in GT, model didn't find)

- **蓝色眼睛**: 眼睛为明亮的蓝色，瞳孔清晰，眼神中带有淡淡的高光，显得灵动有神。
- **领饰**: 白色蝴蝶结领结

---

### char_011

- **GT elements**: 6, **Pred elements**: 9
- **Matched**: 6, **Avg Similarity**: 0.5916
- **Coverage**: 1.0, **Precision**: 0.6667
- **Inference time**: 6.4s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 兽耳 | 粉色猫耳与猫尾 | 0.6785 |
| 2 | 尾巴 | 粉色长卷发与发饰 | 0.6051 |
| 3 | 头发 | 棕色腰带与黄色大蝴蝶结 | 0.5722 |
| 4 | 蝴蝶结发饰 | 淡紫色和服上衣与花卉图案 | 0.559 |
| 5 | 和服上衣 | 深棕色下裙与底部花纹 | 0.6052 |
| 6 | 腰带 | 白色袜子与木屐 | 0.5293 |

#### Extra Predictions (model found, not in GT)

- **眼睛**: 蓝色瞳孔。
- **下身裙装**: 深红褐色长裙，底部露出带有彩色花卉图案的粉色内衬。
- **木屐**: 白色带子的传统木屐。

---

### char_012

- **GT elements**: 7, **Pred elements**: 8
- **Matched**: 7, **Avg Similarity**: 0.6284
- **Coverage**: 1.0, **Precision**: 0.875
- **Inference time**: 6.1s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型 | 棕色头巾 | 0.6058 |
| 2 | 头巾 | 卡其色毛皮装饰的棕色外衣 | 0.5533 |
| 3 | 肤色 | 绿色皮肤 | 0.7587 |
| 4 | 毛皮外套 | 白色裤子与毛皮裤脚 | 0.6712 |
| 5 | 毛边长裤 | 浅棕色绑腿与靴子 | 0.5612 |
| 6 | 四肢绑带 | 手臂上的浅棕色护腕 | 0.6138 |
| 7 | 红色腰封 | 白色内衬与棕色腰带 | 0.635 |

#### Extra Predictions (model found, not in GT)

- **兽耳**: 头部两侧长有尖长的绿色兽耳

---

### char_013

- **GT elements**: 6, **Pred elements**: 8
- **Matched**: 6, **Avg Similarity**: 0.6693
- **Coverage**: 1.0, **Precision**: 0.75
- **Inference time**: 11.6s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 金色短发与胡须 | 0.7501 |
| 2 | 内搭上衣 | 黑色外衣与黄色内衬 | 0.8068 |
| 3 | 外套 | 毛边围裙与裤脚毛饰 | 0.5618 |
| 4 | 肩甲 | 左肩金属护甲 | 0.7952 |
| 5 | 下裙 | 棕色皮质腰带与斜挎剑鞘 | 0.5918 |
| 6 | 肩带 | 棕色靴子与深色袜子 | 0.5099 |

#### Extra Predictions (model found, not in GT)

- **胡须**: 下巴处有深色山羊胡
- **靴子**: 棕色短靴

---

### char_014

- **GT elements**: 6, **Pred elements**: 9
- **Matched**: 6, **Avg Similarity**: 0.7367
- **Coverage**: 1.0, **Precision**: 0.6667
- **Inference time**: 6.5s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 白色短发 | 0.785 |
| 2 | 眼罩 | 黑色眼罩 | 0.8454 |
| 3 | 右眼 | 红色右眼 | 0.7863 |
| 4 | 西装外套 | 黑红配色服装 | 0.615 |
| 5 | 领带 | 双枪武器 | 0.5151 |
| 6 | 机械义肢手套 | 机械义肢 | 0.8732 |

#### Extra Predictions (model found, not in GT)

- **内搭**: 灰色衣物，正面可见一排黑色纽扣
- **右臂金属护具**: 右前臂佩戴的银色光滑金属护臂，连接机械手套
- **双持枪械**: 双手各持一把黑色左轮手枪，枪身带有红色装饰纹路

---

### char_015

- **GT elements**: 5, **Pred elements**: 9
- **Matched**: 5, **Avg Similarity**: 0.608
- **Coverage**: 1.0, **Precision**: 0.5556
- **Inference time**: 3.8s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 深灰色短发与紫色尖角头饰 | 0.6369 |
| 2 | 头饰 | 紫色长袖 | 0.555 |
| 3 | 眼睛 | 发红色眼睛 | 0.6681 |
| 4 | 上衣 | 紫色与黑色相间的紧身战斗服 | 0.6178 |
| 5 | 披风 | 黑色长筒袜与紫色高跟靴 | 0.5621 |

#### Extra Predictions (model found, not in GT)

- **手臂护具**: 银色与紫色相间的臂环/护腕
- **腿部服饰**: 黑色过膝长筒袜，大腿处有镂空设计
- **腰带**: 黑色细腰带
- **鞋子**: 紫银配色高跟鞋

---

### char_016

- **GT elements**: 5, **Pred elements**: 6
- **Matched**: 5, **Avg Similarity**: 0.794
- **Coverage**: 1.0, **Precision**: 0.8333
- **Inference time**: 3.3s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 黑色短发 | 0.7652 |
| 2 | 眼睛 | 绿色眼睛 | 0.7896 |
| 3 | 上衣 | 黄色运动上衣 | 0.8424 |
| 4 | 短裤 | 黑色运动短裤 | 0.8858 |
| 5 | 袜子 | 白色运动鞋 | 0.687 |

#### Extra Predictions (model found, not in GT)

- **鞋子**: 黑白配色运动鞋，鞋带孔或标志处有橙色点缀。

---

### char_017

- **GT elements**: 7, **Pred elements**: 8
- **Matched**: 7, **Avg Similarity**: 0.6339
- **Coverage**: 1.0, **Precision**: 0.875
- **Inference time**: 3.9s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 羽毛头饰/羽冠 | 白色羽毛头饰与红色尖端 | 0.831 |
| 2 | 面部特征与肤色 | 蓝绿色皮肤与黄色眼睛 | 0.6791 |
| 3 | 躯干上衣 | 毛皮披肩与棕色绑带 | 0.6556 |
| 4 | 腰部束带 | 长尾与尾尖弯钩 | 0.5563 |
| 5 | 腰侧裙片/下装 | 几何图案装饰（黄红相间） | 0.606 |
| 6 | 侧挂流苏布条 | 兽角与银白色的羽毛装饰 | 0.5005 |
| 7 | 尾巴与体表特征 | 脚爪与趾甲 | 0.609 |

#### Extra Predictions (model found, not in GT)

- **腿部绑带**: 深紫色宽边腿环，紧密缠绕于左侧大腿中段。

---

### char_018

- **GT elements**: 4, **Pred elements**: 6
- **Matched**: 4, **Avg Similarity**: 0.7378
- **Coverage**: 1.0, **Precision**: 0.6667
- **Inference time**: 2.9s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型 | 棕色短发 | 0.7888 |
| 2 | 眼睛颜色 | 橙色眼睛 | 0.7201 |
| 3 | 外套 | 白色制服外套与蓝色绳结 | 0.6957 |
| 4 | 长裤 | 白色长裤与黑色皮鞋 | 0.7467 |

#### Extra Predictions (model found, not in GT)

- **胸前绳结**: 蓝色编织绳结装饰，横向系于胸前，右侧带有流苏垂下
- **鞋子**: 深灰色低帮皮鞋，款式简洁

---

### char_019

- **GT elements**: 6, **Pred elements**: 10
- **Matched**: 6, **Avg Similarity**: 0.5847
- **Coverage**: 1.0, **Precision**: 0.6
- **Inference time**: 3.2s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 蓝色高马尾 | 0.719 |
| 2 | 头部发饰 | 银色手环 | 0.5851 |
| 3 | 领饰 | 紫色与红色相间的上衣 | 0.598 |
| 4 | 上身外套 | 粉色短裙与黑色短裤 | 0.5327 |
| 5 | 紧身胸衣 | 黑色过膝袜与棕色靴子 | 0.5236 |
| 6 | 下身裙装 | 棕色靴子与蕾丝边装饰 | 0.5501 |

#### Extra Predictions (model found, not in GT)

- **右腿袜类**: 黑色过膝长袜（画面左侧腿部）
- **左腿绑带**: 白色大腿绑带/腿环，带有黑色扣饰（画面右侧腿部）
- **鞋靴**: 棕色翻边短靴，材质看似皮革或绒面
- **手部护腕**: 左手佩戴银色金属环状护腕

---

### char_020

- **GT elements**: 4, **Pred elements**: 5
- **Matched**: 4, **Avg Similarity**: 0.6705
- **Coverage**: 1.0, **Precision**: 0.8
- **Inference time**: 2.3s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 黑色长直发 | 0.6829 |
| 2 | 西装外套 | 灰色西装套装 | 0.7281 |
| 3 | 内搭上衣 | 白色内搭 | 0.7193 |
| 4 | 长裤 | 灰色高跟鞋 | 0.5518 |

#### Extra Predictions (model found, not in GT)

- **鞋子**: 黑色尖头高跟鞋

---

### char_021

- **GT elements**: 7, **Pred elements**: 10
- **Matched**: 7, **Avg Similarity**: 0.6779
- **Coverage**: 1.0, **Precision**: 0.7
- **Inference time**: 2.9s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型与发色 | 金色短发与胡须 | 0.7353 |
| 2 | 胸口纹身 | 左胸红色火焰纹身 | 0.7985 |
| 3 | 脸部纹路 | 右手握拳 | 0.507 |
| 4 | 长袍外套 | 橙色斜披布与黑色外袍 | 0.7534 |
| 5 | 斜襟内搭 | 灰色宽松裤与灰色和黑色组合的靴子 | 0.5162 |
| 6 | 编织腰带 | 金色编织腰带与护腕 | 0.7578 |
| 7 | 编织护腕 | 左手持金色护肩 | 0.6768 |

#### Extra Predictions (model found, not in GT)

- **宽松长裤**: 浅灰色灯笼裤，裤脚收紧并带有深色边缘
- **短靴**: 白色鞋面的短靴，脚踝处有深色拼接及鞋底边缘
- **手持道具**: 右手持有一个金色叶片状物体（疑似武器或忍具部件）

---

### char_022

- **GT elements**: 5, **Pred elements**: 6
- **Matched**: 4, **Avg Similarity**: 0.6699
- **Coverage**: 0.8, **Precision**: 0.6667
- **Inference time**: 2.4s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 深紫色长发 | 0.6589 |
| 2 | 帽子 | 红色贝雷帽 | 0.7784 |
| 3 | 上衣 | 紫红色上衣与深紫色短裙 | 0.671 |
| 4 | 裙子 | 深紫色过膝袜与黑色靴子 | 0.5715 |

#### Extra Predictions (model found, not in GT)

- **袜子**: 深紫色过膝长袜，长度至大腿中部
- **鞋子**: 黑色短靴，系带设计

#### Missed Elements (in GT, model didn't find)

- **黑色蝴蝶结装饰**: 上衣领口处有一个黑色的小蝴蝶结，作为点缀，位置居中，需注意其对称性和细节。

---

### char_023

- **GT elements**: 7, **Pred elements**: 8
- **Matched**: 7, **Avg Similarity**: 0.7358
- **Coverage**: 1.0, **Precision**: 0.875
- **Inference time**: 2.9s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 银灰色短发 | 0.7065 |
| 2 | 外套 | 米白色长外套与深红色内衬 | 0.773 |
| 3 | 内搭上衣 | 浅蓝色内搭 | 0.7528 |
| 4 | 腰封/腰带 | 棕色腰带与布料缠绕 | 0.7533 |
| 5 | 裤子 | 深灰色宽松裤装 | 0.714 |
| 6 | 手套 | 棕色手套和短靴 | 0.7408 |
| 7 | 鞋子 | 棕色手套与短靴 | 0.7105 |

#### Extra Predictions (model found, not in GT)

- **胡须**: 下巴处有明显的黑色短须/胡茬。

---

### char_024

- **GT elements**: 7, **Pred elements**: 11
- **Matched**: 6, **Avg Similarity**: 0.6599
- **Coverage**: 0.8571, **Precision**: 0.5455
- **Inference time**: 3.3s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 红色长发与头饰 | 0.6996 |
| 2 | 眼睛 | 蓝色眼睛 | 0.8245 |
| 3 | 外套 | 红紫色学院风外套 | 0.7113 |
| 4 | 领饰 | 格纹短裙与白色蕾丝边 | 0.5686 |
| 5 | 领带 | 肤色裤袜与深色靴子 | 0.5254 |
| 6 | 手套 | 左手姿势 | 0.6302 |

#### Extra Predictions (model found, not in GT)

- **发箍**: 银色小皇冠造型发箍，位于头顶
- **裙子**: 紫色格纹短裙，下摆露出白色荷叶边衬裙
- **腰带**: 黑色宽腰带，束在腰部
- **袜子**: 深紫色长筒袜，覆盖小腿部分
- **鞋子**: 深色高跟短靴，鞋头略尖

#### Missed Elements (in GT, model didn't find)

- **右手姿势**: 右手抬起，手掌朝前，手指自然张开，需注意手指比例和线条。

---

### char_025

- **GT elements**: 8, **Pred elements**: 8
- **Matched**: 7, **Avg Similarity**: 0.578
- **Coverage**: 0.875, **Precision**: 0.875
- **Inference time**: 2.8s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型 | 紫红色短发与头饰 | 0.6517 |
| 2 | 耳饰 | 左手黑色手套与袖套 | 0.5697 |
| 3 | 恶魔翼 | 紫红色披风与背部装饰 | 0.5659 |
| 4 | 披风 | 白色连衣裙与粉色蝴蝶结 | 0.5507 |
| 5 | 抹胸上衣 | 右手黑色手套与袖套 | 0.5734 |
| 6 | 百褶裙 | 粉紫色大腿袜与白色图案 | 0.5433 |
| 7 | 过膝袜 | 紫红色鞋子与蝴蝶结 | 0.5913 |

#### Extra Predictions (model found, not in GT)

- **玛丽珍鞋**: 粉紫色玛丽珍单鞋，脚背处有蝴蝶结装饰。

#### Missed Elements (in GT, model didn't find)

- **紫红色眼睛**: 眼睛为明亮的紫红色，眼神温和，眼型又大又圆，需注意瞳孔高光的位置和形状。

---

### char_026

- **GT elements**: 6, **Pred elements**: 10
- **Matched**: 6, **Avg Similarity**: 0.6142
- **Coverage**: 1.0, **Precision**: 0.6
- **Inference time**: 2.6s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型与发色 | 金色马尾 | 0.699 |
| 2 | 瞳孔颜色 | 黄色眼睛 | 0.7097 |
| 3 | 耳饰 | 黑色腰带与十字架装饰 | 0.5799 |
| 4 | 领结 | 蓝紫色背心与白色衬衫 | 0.6216 |
| 5 | 马甲 | 深灰色长裙 | 0.5277 |
| 6 | 腰带 | 棕色丝袜与灰色皮鞋 | 0.5475 |

#### Extra Predictions (model found, not in GT)

- **长袖衬衫**: 白色长袖衬衫，袖口有褶皱设计。
- **半身裙**: 深灰色中长款A字裙，长度过膝。
- **连裤袜**: 深棕色连裤袜。
- **高跟鞋**: 黑色细带高跟皮鞋。

---

### char_027

- **GT elements**: 6, **Pred elements**: 9
- **Matched**: 6, **Avg Similarity**: 0.5619
- **Coverage**: 1.0, **Precision**: 0.6667
- **Inference time**: 2.8s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 金色头冠 | 0.539 |
| 2 | 头冠 | 银色盔甲 | 0.6164 |
| 3 | 胡须 | 红色披风 | 0.5036 |
| 4 | 胸甲与肩甲 | 深蓝色内搭与棕色护腕 | 0.5984 |
| 5 | 披风 | 银色长靴与银色护胫 | 0.5407 |
| 6 | 手臂绑带 | 深蓝色腰带与X形扣环 | 0.5733 |

#### Extra Predictions (model found, not in GT)

- **腰带**: 黑色宽腰带，配有巨大的金色圆形交叉扣环
- **腿甲**: 银白色金属护胫，覆盖小腿，带有尖刺设计
- **战靴**: 银白色金属战靴，鞋头有尖刺装饰

---

### char_028

- **GT elements**: 4, **Pred elements**: 8
- **Matched**: 4, **Avg Similarity**: 0.6128
- **Coverage**: 1.0, **Precision**: 0.5
- **Inference time**: 2.5s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型 | 棕色短发与红色蝴蝶结 | 0.673 |
| 2 | 红色蝴蝶结发带 | 蓝色腰带与小包 | 0.556 |
| 3 | 蓝色短披肩 | 白色的连衣裙 | 0.6284 |
| 4 | 蓝色编织绳腰带 | 黑色绑带凉鞋 | 0.5939 |

#### Extra Predictions (model found, not in GT)

- **眼睛**: 绿色瞳孔
- **白色连衣裙**: 裙摆处有两条黄色横条纹
- **棕色动物造型腰包**: 挂在腰间的棕色动物头像造型小包
- **棕色绑带鞋**: 交叉绑带设计的短靴/凉鞋

---

### char_029

- **GT elements**: 6, **Pred elements**: 10
- **Matched**: 6, **Avg Similarity**: 0.6643
- **Coverage**: 1.0, **Precision**: 0.6
- **Inference time**: 2.4s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 白色绑腿与棕色靴子 | 0.5418 |
| 2 | 头带 | 深红色头巾 | 0.7043 |
| 3 | 连帽衫 | 绿色连帽上衣 | 0.8042 |
| 4 | 马甲 | 棕色背心与黑色纽扣 | 0.6874 |
| 5 | 腰带 | 灰色灯笼裤与棕色腰带 | 0.7236 |
| 6 | 腰间垂布 | 黑色手套 | 0.5244 |

#### Extra Predictions (model found, not in GT)

- **胡须**: 黑色山羊胡
- **长裤**: 灰绿色宽松长裤，裤脚收紧
- **腿部绷带**: 白色绷带缠绕于小腿处
- **短靴**: 棕色短筒皮靴

---

### char_030

- **GT elements**: 6, **Pred elements**: 5
- **Matched**: 5, **Avg Similarity**: 0.7381
- **Coverage**: 0.8333, **Precision**: 1.0
- **Inference time**: 2.4s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 发型发色 | 棕色短发 | 0.7715 |
| 2 | 瞳孔颜色 | 蓝色眼睛 | 0.7236 |
| 3 | 上衣 | 白色水手服上衣 | 0.8523 |
| 4 | 裤子 | 深蓝色裤子 | 0.7723 |
| 5 | 腰部配饰 | 右手叉腰姿势 | 0.5706 |

#### Missed Elements (in GT, model didn't find)

- **左手自然下垂**: 左手自然垂放。

---

### char_031

- **GT elements**: 7, **Pred elements**: 11
- **Matched**: 7, **Avg Similarity**: 0.6559
- **Coverage**: 1.0, **Precision**: 0.6364
- **Inference time**: 4.2s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 黑灰色头发 | 0.7178 |
| 2 | 尾巴 | 黑灰色长发与角 | 0.6397 |
| 3 | 上衣 | 蓝色比基尼式上衣与下装 | 0.7133 |
| 4 | 肩甲 | 灰色护具与尖刺装饰 | 0.6885 |
| 5 | 护膝 | 红色和金色绑带 | 0.53 |
| 6 | 鞋靴 | 蓝白相间的高跟靴 | 0.774 |
| 7 | 大腿绑带 | 蓝白相间的高跟靴 | 0.5282 |

#### Extra Predictions (model found, not in GT)

- **兽耳**: 白色尖耳（头顶两侧）
- **眼睛**: 蓝灰色瞳孔
- **下装**: 蓝色比基尼式底裤/短裤
- **臂环**: 红黄相间臂环（画面右侧手臂上臂）

---

### char_032

- **GT elements**: 8, **Pred elements**: 7
- **Matched**: 7, **Avg Similarity**: 0.7593
- **Coverage**: 0.875, **Precision**: 1.0
- **Inference time**: 3.1s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 棕色短发 | 0.8001 |
| 2 | 领结 | 蓝色蝴蝶结领结 | 0.7464 |
| 3 | 西装外套 | 深蓝色西装外套与金色镶边 | 0.8438 |
| 4 | 衬衫 | 深蓝色长袜 | 0.5433 |
| 5 | 百褶裙 | 蓝黄格纹百褶裙 | 0.8212 |
| 6 | 长筒袜 | 深蓝色长袜 | 0.7865 |
| 7 | 鞋子 | 棕色皮鞋 | 0.7737 |

#### Missed Elements (in GT, model didn't find)

- **棕色皮鞋**: 左脚穿棕色圆头皮鞋，鞋面光滑无多余装饰，无鞋带。

---

### char_033

- **GT elements**: 8, **Pred elements**: 8
- **Matched**: 7, **Avg Similarity**: 0.6737
- **Coverage**: 0.875, **Precision**: 0.875
- **Inference time**: 2.7s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 绿色短发 | 0.7288 |
| 2 | 眼镜 | 眼镜 | 0.7969 |
| 3 | 西装外套 | 蓝色西装校服 | 0.6616 |
| 4 | 衬衫 | 灰白色衬衫与蓝色领带 | 0.6927 |
| 5 | 领带 | 深蓝色皮鞋 | 0.5735 |
| 6 | 西裤 | 深蓝色皮鞋 | 0.6189 |
| 7 | 胸章 | 左手轻抚胸口 | 0.6436 |

#### Extra Predictions (model found, not in GT)

- **皮鞋**: 深蓝色皮鞋

#### Missed Elements (in GT, model didn't find)

- **右手自然垂下**: 右手自然垂下。

---

### char_034

- **GT elements**: 8, **Pred elements**: 6
- **Matched**: 6, **Avg Similarity**: 0.7052
- **Coverage**: 0.75, **Precision**: 1.0
- **Inference time**: 3.4s

#### Matched Pairs (Prediction ↔ Ground Truth)

| # | Predicted Element | GT Element | Similarity |
|---|-------------------|------------|------------|
| 1 | 头发 | 浅金色短发 | 0.7638 |
| 2 | 黑色连帽外套 | 深灰色连帽斗篷与白色圆点 | 0.7191 |
| 3 | 棕褐色上衣 | 内搭的棕色短袖 | 0.6929 |
| 4 | 白色内搭 | 深灰色高筒系带靴 | 0.5457 |
| 5 | 深蓝色长裤 | 深紫色宽松裤子 | 0.7634 |
| 6 | 黑色靴子 | 深灰色高筒系带靴 | 0.7463 |

#### Missed Elements (in GT, model didn't find)

- **蹲姿与右手部姿势**: 角色呈蹲姿，身体前倾，右手向前伸出，手指微张，姿态充满动感和警觉性，需注意肢体比例和重心。
- **左手部姿势**: 左手自然垂下，手指微张，姿态充满动感和警觉性，需注意肢体比例和重心。

---
