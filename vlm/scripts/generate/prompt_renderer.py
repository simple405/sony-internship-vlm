"""Render one merchandise generation template for SN-6 and SN-7."""

from __future__ import annotations


CATEGORY_REQUIREMENTS = {
    "head_key_chain": (
        "商品是只包含角色头部的 Q 版毛绒钥匙链。保留发型、五官和头饰身份特征，"
        "用柔软毛绒、缝线和刺绣表达；不要生成身体或原图不存在的耳朵、角、尾巴。"
    ),
    "cake_roll": (
        "商品是圆润的瑞士卷形毛绒挂件，不是真实食物或普通手办。正面表现脸部，"
        "侧面只表现连续圆柱外侧和厚度，不出现切面、螺旋或夹心；只有背面使用角色配色的卷纹。"
    ),
    "backpack": (
        "商品是角色主题的 Q 版软质双肩背包。发型、眼睛、头饰、服饰色块和纹样应转化为包体特征；"
        "背带、挂扣、口袋、侧面厚度和背部结构必须连贯。"
    ),
    "plush": (
        "商品是同角色全身站姿毛绒玩偶，不是坐姿手办。双脚落地、身体直立，可轻微 Q 化；"
        "服装结构、配色和配件以毛绒、缝线和刺绣方式保留。"
    ),
    "dataset_QSitFigures": (
        "商品是 QSitFigures 坐姿 PVC 小手办，不是站姿手办或毛绒玩偶。双腿自然收拢、盘坐或跪坐，"
        "重心稳定；服装布片、纹样和配件在各视角保持同一拓扑。"
    ),
    "dataset_figurine": (
        "商品是哑光喷涂 PVC 收藏手办，细节以雕刻和上色表达。角色保持中性站姿、双脚落地、身体直立，"
        "允许简洁透明或白色支撑结构，但不要生成展示台。"
    ),
}

MERCHANDISE_LABELS = {
    "head_key_chain": "Q 版毛绒头部钥匙链",
    "cake_roll": "蛋糕卷毛绒挂件",
    "backpack": "角色主题双肩背包",
    "plush": "全身站姿毛绒玩偶",
    "dataset_QSitFigures": "QSitFigures 坐姿 PVC 小手办",
    "dataset_figurine": "3D PVC 收藏手办",
}

VIEW_REQUIREMENTS = {
    "front": "白底，只展示同一商品的正面全貌，不要拼入原始 2D 图或其他视角。",
    "multiview": (
        "白底，横向排列同一实体商品的三个正交视角：正面、侧面、背面。三视角的比例、颜色、"
        "材质、结构和装饰位置必须连续一致，不能分别重新设计。"
    ),
}


def render_generation_prompt(template: str, category: str, view_mode: str) -> str:
    """Render and validate the shared generation prompt template."""
    try:
        values = {
            "{{MERCHANDISE_CATEGORY}}": MERCHANDISE_LABELS[category],
            "{{VIEW_REQUIREMENTS}}": VIEW_REQUIREMENTS[view_mode],
            "{{CATEGORY_REQUIREMENTS}}": CATEGORY_REQUIREMENTS[category],
        }
    except KeyError as exc:
        raise ValueError(f"Unsupported prompt context: {exc.args[0]}") from exc
    rendered = template.strip()
    for placeholder, value in values.items():
        if placeholder not in rendered:
            raise ValueError(f"Prompt template is missing {placeholder}")
        rendered = rendered.replace(placeholder, value)
    if "{{" in rendered or "}}" in rendered:
        raise ValueError("Prompt template contains an unresolved placeholder")
    return rendered
