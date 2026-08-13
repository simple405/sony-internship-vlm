"""Shared helpers for exporting atomic_rules.json data to xlsx."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Mapping


HEAD_ONLY_CATEGORIES = ("head_key_chain", "cake_roll", "backpack")
XLSX_COLUMNS = (
    "样本编号",
    "规则名称",
    "位置",
    "取值",
    "正面可见性",
    "正面状态",
    "侧面可见性",
    "侧面状态",
    "背面可见性",
    "背面状态",
    "备注",
    "\u539f\u59cb\u89c4\u5219ID",
    "\u539f\u59cb\u53d6\u503c",
)


ANNOTATION_VISIBLE_VALUES = ("可见", "不可见")
VISIBLE_STATUS_VALUES = (
    "正确",
    "颜色错误",
    "材质错误",
    "形状错误",
    "位置错误",
    "多余元素",
)
INVISIBLE_STATUS_VALUES = ("正确不可见", "错误不可见")
ANNOTATION_STATUS_VALUES = VISIBLE_STATUS_VALUES + INVISIBLE_STATUS_VALUES


LOCATION_CN = {"head": "头部", "body": "身体", "头部": "头部", "身体": "身体"}
LOCATION_CANONICAL = {"head": "head", "body": "body", "头部": "head", "身体": "body"}
TRANSLATION_CACHE_RELATIVE_PATH = (
    Path("reports") / "atomic_rule_translation" / "qwen_zh_cache.json"
)
EXACT_RULE_CN = {
    "sample_id": "样本编号",
    "rule_id": "规则名称",
    "location": "位置",
    "value": "取值",
    "hair_bangs": "刘海",
    "eye_color": "眼睛颜色",
    "eye_state": "眼睛状态",
    "expression": "表情",
    "skin_tone": "肤色",
    "top_type": "上装类型",
    "top_color": "上装颜色",
    "top_style": "上装样式",
    "bottom_type": "下装类型",
    "bottom_color": "下装颜色",
    "bottom_style": "下装样式",
    "sleeve_length": "袖长",
    "skirt_type": "裙子类型",
    "skirt_color": "裙子颜色",
    "skirt_length": "裙长",
    "dress_type": "连衣裙类型",
    "dress_color": "连衣裙颜色",
    "pants_type": "裤子类型",
    "pants_color": "裤子颜色",
    "legwear_type": "腿部穿着类型",
    "legwear_color": "腿部穿着颜色",
    "footwear_type": "鞋子类型",
    "footwear_color": "鞋子颜色",
    "collar_type": "领子类型",
    "collar_color": "领子颜色",
    "has_belt": "是否有腰带",
    "belt_color": "腰带颜色",
    "has_gloves": "是否有手套",
    "glove_color": "手套颜色",
    "has_choker": "是否有颈圈",
    "choker_color": "颈圈颜色",
    "has_necktie": "是否有领带",
    "necktie_color": "领带颜色",
    "has_necklace": "是否有项链",
    "necklace_color": "项链颜色",
    "has_weapon": "是否有武器",
    "weapon_type": "武器类型",
    "weapon_color": "武器颜色",
    "has_handheld_item": "是否有手持物",
    "handheld_item_type": "手持物类型",
    "handheld_item_color": "手持物颜色",
    "has_bag": "是否有包",
    "bag_color": "包颜色",
    "has_tail": "是否有尾巴",
    "tail_color": "尾巴颜色",
    "has_wings": "是否有翅膀",
    "wing_color": "翅膀颜色",
    "has_horn": "是否有角",
    "horn_color": "角颜色",
    "has_pointed_ears": "是否有尖耳",
    "has_glasses": "是否有眼镜",
    "glasses_color": "眼镜颜色",
    "headwear_type": "头饰类型",
    "headwear_color": "头饰颜色",
    "hair_accessory_type": "发饰类型",
    "hair_accessory_color": "发饰颜色",
    "has_hair_accessory": "是否有发饰",
    "has_hair_ribbon": "是否有发带",
    "hair_ribbon_color": "发带颜色",
}
TOKEN_CN = {
    "a": "梯形",
    "accent": "强调",
    "accessory": "配件",
    "armor": "盔甲",
    "armored": "盔甲",
    "arm": "手臂",
    "armband": "臂带",
    "back": "背部",
    "backpack": "背包",
    "badge": "徽章",
    "bag": "包",
    "band": "绑带",
    "bangs": "刘海",
    "beard": "胡须",
    "belt": "腰带",
    "blazer": "西装外套",
    "body": "身体",
    "bottom": "下装",
    "bow": "蝴蝶结",
    "bowtie": "领结",
    "bracelet": "手镯",
    "braid": "辫子",
    "buckle": "扣",
    "button": "纽扣",
    "cape": "披风",
    "capelet": "短披肩",
    "cat": "猫",
    "chain": "链条",
    "cheek": "脸颊",
    "chest": "胸部",
    "choker": "颈圈",
    "claw": "爪",
    "cloak": "斗篷",
    "coat": "外套",
    "collar": "领子",
    "color": "颜色",
    "count": "数量",
    "cuff": "袖口",
    "decoration": "装饰",
    "decal": "贴花",
    "detail": "细节",
    "dress": "连衣裙",
    "ear": "耳朵",
    "earring": "耳环",
    "earrings": "耳环",
    "ears": "耳朵",
    "edge": "边缘",
    "emblem": "徽记",
    "eye": "眼睛",
    "face": "脸部",
    "facial": "脸部",
    "flower": "花",
    "footwear": "鞋子",
    "forehead": "额头",
    "front": "正面",
    "fur": "毛边",
    "garter": "吊袜带",
    "glasses": "眼镜",
    "glove": "手套",
    "gloves": "手套",
    "hair": "头发",
    "halo": "光环",
    "hand": "手",
    "handheld": "手持物",
    "has": "是否有",
    "head": "头部",
    "headband": "发箍",
    "headphone": "耳机",
    "headphones": "耳机",
    "headset": "耳机",
    "headwear": "头饰",
    "helmet": "头盔",
    "hem": "下摆",
    "hip": "臀侧",
    "hood": "兜帽",
    "horn": "角",
    "inner": "内层",
    "jacket": "夹克",
    "knee": "膝盖",
    "layer": "层",
    "leg": "腿",
    "leggings": "打底裤",
    "legwear": "腿部穿着",
    "length": "长度",
    "lining": "内衬",
    "mark": "标记",
    "marking": "标记",
    "mask": "面具",
    "material": "材质",
    "mouth": "嘴",
    "neck": "颈部",
    "necklace": "项链",
    "necktie": "领带",
    "nose": "鼻子",
    "outer": "外层",
    "outerwear": "外套",
    "pad": "护垫",
    "pants": "裤子",
    "patch": "补丁",
    "pattern": "图案",
    "pendant": "吊坠",
    "piercing": "穿孔",
    "position": "位置",
    "print": "印花",
    "ribbon": "丝带",
    "ruffle": "荷叶边",
    "sash": "腰封",
    "scarf": "围巾",
    "shape": "形状",
    "shield": "盾牌",
    "shirt": "衬衫",
    "shoe": "鞋",
    "shoes": "鞋",
    "shorts": "短裤",
    "shoulder": "肩部",
    "side": "侧面",
    "sides": "侧面",
    "skirt": "裙子",
    "sleeve": "袖子",
    "sock": "袜子",
    "socks": "袜子",
    "spike": "尖刺",
    "spikes": "尖刺",
    "stone": "宝石",
    "strap": "带子",
    "style": "样式",
    "tail": "尾巴",
    "tassel": "流苏",
    "thigh": "大腿",
    "tie": "领带",
    "tip": "尖端",
    "top": "上装",
    "trim": "滚边",
    "type": "类型",
    "vest": "马甲",
    "waist": "腰部",
    "weapon": "武器",
    "wing": "翅膀",
    "wings": "翅膀",
    "wristband": "腕带",
}
VALUE_TOKEN_CN = {
    **TOKEN_CN,
    "true": "是",
    "false": "否",
    "yes": "是",
    "no": "否",
    "none": "无",
    "unknown": "未知",
    "visible": "可见",
    "invisible": "不可见",
    "black": "黑色",
    "white": "白色",
    "red": "红色",
    "blue": "蓝色",
    "green": "绿色",
    "yellow": "黄色",
    "pink": "粉色",
    "purple": "紫色",
    "orange": "橙色",
    "brown": "棕色",
    "gray": "灰色",
    "grey": "灰色",
    "gold": "金色",
    "silver": "银色",
    "cyan": "青色",
    "teal": "蓝绿色",
    "navy": "藏蓝色",
    "maroon": "酒红色",
    "beige": "米色",
    "cream": "奶油色",
    "blonde": "金发",
    "lavender": "薰衣草色",
    "mint": "薄荷色",
    "dark": "深",
    "light": "浅",
    "long": "长",
    "short": "短",
    "medium": "中等",
    "very": "非常",
    "full": "完整",
    "side": "侧分",
    "center": "中分",
    "parted": "分缝",
    "swept": "斜扫",
    "twin": "双",
    "tails": "马尾",
    "tail": "尾巴",
    "ponytail": "马尾",
    "braids": "辫子",
    "buns": "丸子头",
    "bob": "波波头",
    "cut": "剪裁",
    "straight": "直",
    "wavy": "波浪",
    "curly": "卷曲",
    "spiky": "尖刺状",
    "messy": "凌乱",
    "smooth": "顺滑",
    "layered": "分层",
    "asymmetrical": "不对称",
    "neutral": "中性",
    "smile": "微笑",
    "smiling": "微笑",
    "angry": "愤怒",
    "serious": "严肃",
    "surprised": "惊讶",
    "happy": "开心",
    "calm": "平静",
    "determined": "坚定",
    "smirk": "坏笑",
    "smirking": "坏笑",
    "open": "张开",
    "closed": "闭合",
    "winking": "眨眼",
    "boots": "靴子",
    "boot": "靴子",
    "sneakers": "运动鞋",
    "sneaker": "运动鞋",
    "sandals": "凉鞋",
    "heels": "高跟鞋",
    "loafer": "乐福鞋",
    "loafers": "乐福鞋",
    "mary": "玛丽",
    "jane": "珍",
    "geta": "木屐",
    "tabi": "足袋",
    "thigh": "大腿",
    "high": "高",
    "knee": "膝",
    "ankle": "脚踝",
    "floor": "及地",
    "mini": "迷你",
    "midi": "中长",
    "pleated": "百褶",
    "ruffled": "荷叶边",
    "flared": "喇叭形",
    "sleeveless": "无袖",
    "collared": "有领",
    "hooded": "带兜帽",
    "pointed": "尖",
    "striped": "条纹",
    "plaid": "格纹",
    "floral": "花卉",
    "mechanical": "机械",
    "metallic": "金属质感",
    "weapon": "武器",
    "sword": "剑",
    "katana": "武士刀",
    "staff": "法杖",
    "rifle": "步枪",
    "gun": "枪",
    "shield": "盾牌",
    "fan": "扇子",
    "book": "书",
    "umbrella": "伞",
    "microphone": "麦克风",
    "bag": "包",
    "ribbon": "丝带",
    "bow": "蝴蝶结",
    "flower": "花",
    "crown": "王冠",
    "hat": "帽子",
    "beret": "贝雷帽",
    "helmet": "头盔",
    "hood": "兜帽",
    "gloves": "手套",
    "choker": "颈圈",
    "pendant": "吊坠",
    "ring": "戒指",
    "bell": "铃铛",
    "round": "圆形",
    "standard": "标准",
    "integrated": "一体化",
    "segmented": "分段",
    "oversized": "宽大",
    "cropped": "短款",
    "transparent": "透明",
    "gradient": "渐变",
    "multicolor": "多色",
    "left": "左",
    "right": "右",
    "both": "双侧",
    "front": "前",
    "back": "后",
}


def add_annotation_dropdowns(worksheet: Any) -> None:
    """Add the standard visible/status dropdowns to an annotation worksheet."""
    from openpyxl.worksheet.datavalidation import DataValidation

    visible_formula = f'"{",".join(ANNOTATION_VISIBLE_VALUES)}"'
    status_formula = f'"{",".join(ANNOTATION_STATUS_VALUES)}"'
    for validation in list(worksheet.data_validations.dataValidation):
        if validation.type == "list" and validation.formula1 in {visible_formula, status_formula}:
            worksheet.data_validations.dataValidation.remove(validation)

    last_row = max(worksheet.max_row, 2)
    for column in ("E", "G", "I"):
        validation = DataValidation(type="list", formula1=visible_formula, allow_blank=True)
        validation.errorTitle = "无效的可见性"
        validation.error = "请选择 visible 或 invisible。"
        worksheet.add_data_validation(validation)
        validation.add(f"{column}2:{column}{last_row}")
    for column in ("F", "H", "J"):
        validation = DataValidation(type="list", formula1=status_formula, allow_blank=True)
        validation.errorTitle = "无效的视角状态"
        validation.error = "请从下拉列表中选择状态。"
        worksheet.add_data_validation(validation)
        validation.add(f"{column}2:{column}{last_row}")


def _tokenize_identifier(value: str) -> list[str]:
    """Split snake/camel/kebab identifiers into lowercase translation tokens."""
    normalized = re.sub(r"([a-z])([A-Z])", r"\1_\2", value.strip())
    return [
        token.lower()
        for token in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", normalized)
        if token
    ]


def _display_from_tokens(
    value: str,
    token_map: dict[str, str],
    *,
    separator: str = "、",
) -> str:
    """Translate an identifier-like value into Chinese-only display text."""
    if not value:
        return ""
    if re.search(r"[\u4e00-\u9fff]", value) and not re.search(r"[A-Za-z]", value):
        return value
    tokens = _tokenize_identifier(value)
    translated: list[str] = []
    for token in tokens:
        if re.fullmatch(r"\d+", token):
            translated.append(token)
            continue
        text = token_map.get(token)
        if text is None:
            text = f"\u672a\u7ffb\u8bd1:{token}"
        if text and (not translated or translated[-1] != text):
            translated.append(text)
    return separator.join(translated)


def canonical_rule_value(value: Any) -> str:
    """Return the stable text used to identify a rule/value translation pair."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value).strip()


def translation_key(rule_id: str, value: Any) -> str:
    """Return a deterministic cache key for one contextual translation."""
    payload = json.dumps(
        [str(rule_id).strip(), canonical_rule_value(value)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_translation_cache(path: Path) -> dict[str, dict[str, str]]:
    """Load and validate a Qwen translation cache, returning an empty map if absent."""
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    raw_translations = payload.get("translations", {})
    if not isinstance(raw_translations, dict):
        raise ValueError(f"translations must be an object: {path}")
    translations: dict[str, dict[str, str]] = {}
    for key, entry in raw_translations.items():
        if not isinstance(entry, dict):
            continue
        rule_name = str(entry.get("rule_name_cn", "")).strip()
        value_cn = str(entry.get("value_cn", "")).strip()
        if rule_name and value_cn:
            translations[str(key)] = {
                "rule_id": str(entry.get("rule_id", "")),
                "value": str(entry.get("value", "")),
                "rule_name_cn": rule_name,
                "value_cn": value_cn,
            }
    return translations


def find_translation_cache(json_path: Path) -> Path | None:
    """Find the dataset-level translation cache above an atomic-rules file."""
    resolved = json_path.resolve()
    for parent in resolved.parents:
        candidate = parent / TRANSLATION_CACHE_RELATIVE_PATH
        if candidate.is_file():
            return candidate
    return None


def contextual_translation(
    translations: Mapping[str, Mapping[str, str]],
    rule_id: str,
    value: Any,
) -> Mapping[str, str] | None:
    """Return a cached contextual translation if the source pair still matches."""
    entry = translations.get(translation_key(rule_id, value))
    if not entry:
        return None
    if entry.get("rule_id") != rule_id:
        return None
    if entry.get("value") != canonical_rule_value(value):
        return None
    return entry


def display_rule_id(rule_id: str) -> str:
    """Return the Chinese label shown for one atomic rule id."""
    return EXACT_RULE_CN.get(rule_id, _display_from_tokens(rule_id, TOKEN_CN))


def display_location(location: str) -> str:
    """Return the Chinese label shown for a rule location."""
    return LOCATION_CN.get(location, _display_from_tokens(location, TOKEN_CN))


def canonical_location(location: Any) -> str:
    """Return canonical head/body for English or Chinese location labels."""
    return LOCATION_CANONICAL.get(str(location).strip(), str(location).strip())


def display_value(value: Any) -> Any:
    """Return the Chinese value shown in the annotation workbook."""
    if isinstance(value, bool):
        return "是" if value else "否"
    if value is None:
        return "无"
    if isinstance(value, (int, float)):
        return value
    return _display_from_tokens(str(value).strip(), VALUE_TOKEN_CN, separator="")


def normalize_position_value(rule_id: str, value: Any) -> Any:
    """Return the atomic-rule value exactly as emitted.

    Historical trial scripts flipped ``left`` and ``right`` while writing xlsx
    files. The current SN-7 contract requires atomic_rules values to already be
    in annotator/viewer coordinates, so export must not rewrite them.
    """
    return value


def write_atomic_rules_xlsx(
    json_path: Path,
    output_path: Path,
    category: str,
    location_map: dict[str, str] | None = None,
    translation_cache: Mapping[str, Mapping[str, str]] | None = None,
) -> int:
    """Export atomic rules to the standard three-view annotation workbook."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    data = json.loads(json_path.read_text(encoding="utf-8-sig"))
    rules = data.get("atomic_rules", [])
    if not isinstance(rules, list):
        raise ValueError(f"atomic_rules must be a list: {json_path}")
    locations = location_map or {}
    translations = translation_cache
    if translations is None:
        cache_path = find_translation_cache(json_path)
        translations = load_translation_cache(cache_path) if cache_path else {}
    if category in HEAD_ONLY_CATEGORIES:
        rules = [
            rule
            for rule in rules
            if isinstance(rule, dict)
            and (
                canonical_location(rule.get("location")) == "head"
                or (
                    canonical_location(rule.get("location")) not in {"head", "body"}
                    and locations.get(str(rule.get("id")), "body") == "head"
                )
            )
        ]

    sample_id = str(data.get("code") or data.get("sample_id") or json_path.parent.name)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    for column, name in enumerate(XLSX_COLUMNS, start=1):
        cell = sheet.cell(row=1, column=column, value=name)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9D9D9")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_number, rule in enumerate(rules, start=2):
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("id", ""))
        location = canonical_location(rule.get("location") or locations.get(rule_id, ""))
        if location not in {"head", "body"}:
            raise ValueError(f"Rule {rule_id!r} is missing location=head/body")
        value = normalize_position_value(rule_id, rule.get("value", ""))
        translated = contextual_translation(translations, rule_id, value)
        rule_name = (
            str(translated["rule_name_cn"])
            if translated is not None
            else display_rule_id(rule_id)
        )
        value_cn: Any = (
            str(translated["value_cn"])
            if translated is not None
            else display_value(value)
        )
        if isinstance(value_cn, str) and "、" in value_cn:
            raise ValueError(
                f"Rule {rule_id!r} has forbidden dunhao in Chinese value: {value_cn!r}"
            )
        row = [sample_id, rule_name, display_location(location), value_cn]
        row.extend([""] * (11 - len(row)))
        row.extend([rule_id, "" if value is None else str(value)])
        row.extend([""] * (len(XLSX_COLUMNS) - len(row)))
        for column, cell_value in enumerate(row, start=1):
            sheet.cell(row=row_number, column=column, value=cell_value)

    add_annotation_dropdowns(sheet)
    for column_cells in sheet.columns:
        width = max((len(str(cell.value or "")) for cell in column_cells), default=0)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(width + 4, 40)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(
        f".{output_path.stem}.{os.getpid()}.{threading.get_ident()}.tmp.xlsx"
    )
    try:
        workbook.save(temp_path)
        temp_path.replace(output_path)
    finally:
        workbook.close()
        temp_path.unlink(missing_ok=True)
    return len(rules)
