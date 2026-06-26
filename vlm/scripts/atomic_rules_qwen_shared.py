"""Shared Qwen atomic_rules discovery helpers for smoke tests and raw_trials."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dashscope import MultiModalConversation


DEFAULT_SOURCE_TAG_HINTS = "No source tags are available."
BANNED_EMPTY_VALUES = {
    "none",
    "no",
    "n_a",
    "na",
    "not_visible",
    "not_applicable",
    "unknown",
    "unclear",
    "hidden",
    "occluded",
    "covered",
    "fully_covered",
    "covered_by_helmet",
    "hidden_by_helmet",
    "covered_by_hood",
    "hidden_by_hood",
    "covered_by_mask",
    "hidden_by_mask",
    "eyes_closed",
    "closed_eyes",
    "eye_closed",
    "closed_eye",
}
BANNED_VALUE_MODIFIERS = {
    "very",
    "slightly",
    "extremely",
    "super",
    "somewhat",
    "rather",
    "quite",
    "fairly",
    "really",
    "moderately",
    "bit",
    "a",
    "kind",
    "sort",
    "of",
}
NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
COUNT_RULE_KEYWORDS = {"count", "number", "quantity", "amount", "num", "total"}
LENGTH_VALUE_ALIASES = {
    "very_long": "long",
    "long_sleeve": "long",
    "long_sleeves": "long",
    "full_length": "long",
    "waist_length": "long",
    "hip_length": "long",
    "knee_length": "long",
    "knee_high": "long",
    "knee_highs": "long",
    "thigh_high": "long",
    "thigh_highs": "long",
    "thighhigh": "long",
    "thighhighs": "long",
    "over_knee": "long",
    "floor_length": "long",
    "trailing": "long",
    "three_quarter": "medium",
    "three_quarter_sleeve": "medium",
    "three_quarter_sleeves": "medium",
    "midi": "medium",
    "elbow": "medium",
    "elbow_length": "medium",
    "mid_calf": "medium",
    "calf_length": "medium",
    "shoulder_length": "medium",
    "medium_length": "medium",
    "mid_length": "medium",
    "short_sleeve": "short",
    "short_sleeves": "short",
    "sleeveless": "short",
    "cropped": "short",
    "crop": "short",
    "mini": "short",
    "miniskirt": "short",
    "micro": "short",
    "ankle": "short",
    "ankle_length": "short",
    "neck": "short",
    "neck_length": "short",
    "very_short": "short",
}
HEIGHT_VALUE_ALIASES = {
    "low": "low",
    "short": "low",
    "flat": "low",
    "ankle": "low",
    "ankle_high": "low",
    "ankle_boot": "low",
    "ankle_boots": "low",
    "low_heel": "low",
    "low_heels": "low",
    "medium": "medium",
    "mid": "medium",
    "moderate": "medium",
    "mid_height": "medium",
    "mid_calf": "medium",
    "calf": "medium",
    "calf_high": "medium",
    "high": "high",
    "tall": "high",
    "long": "high",
    "high_waist": "high",
    "knee": "high",
    "knee_high": "high",
    "thigh": "high",
    "thigh_high": "high",
    "thighhigh": "high",
    "platform": "high",
    "high_heel": "high",
    "high_heels": "high",
}
COLOR_VALUE_ALIASES = {
    "grey": "gray",
    "light_gray": "gray",
    "light_grey": "gray",
    "dark_gray": "gray",
    "dark_grey": "gray",
    "silver_gray": "gray",
    "silver_grey": "gray",
    "navy": "blue",
    "navy_blue": "blue",
    "light_blue": "blue",
    "dark_blue": "blue",
    "sky_blue": "blue",
    "cyan": "blue",
    "aqua": "blue",
    "teal": "blue",
    "turquoise": "blue",
    "light_green": "green",
    "dark_green": "green",
    "lime": "green",
    "blond": "blonde",
    "golden": "blonde",
    "golden_blonde": "blonde",
    "light_brown": "brown",
    "dark_brown": "brown",
    "chestnut": "brown",
    "auburn": "brown",
    "light_purple": "purple",
    "dark_purple": "purple",
    "violet": "purple",
    "lavender": "purple",
    "magenta": "pink",
    "light_pink": "pink",
    "dark_pink": "pink",
    "crimson": "red",
    "scarlet": "red",
    "maroon": "red",
    "light_red": "red",
    "dark_red": "red",
    "gold": "yellow",
    "golden_yellow": "yellow",
    "cream": "white",
    "off_white": "white",
}
HAIR_SHAPE_VALUE_ALIASES = {
    "twin_tails": "twintails",
    "twin_tail": "twintails",
    "two_side_tails": "twintails",
    "double_ponytail": "twintails",
    "double_ponytails": "twintails",
    "single_ponytail": "ponytail",
    "high_ponytail": "ponytail",
    "low_ponytail": "ponytail",
    "side_tail": "side_ponytail",
    "side_tail_hair": "side_ponytail",
    "side_ponytails": "side_ponytail",
    "plait": "braid",
    "braided_hair": "braid",
    "single_braid": "braid",
    "twin_braid": "twin_braids",
    "double_braid": "twin_braids",
    "double_braids": "twin_braids",
    "wavy_hair": "wavy",
    "curly_hair": "curly",
    "straight_hair": "straight",
    "bob_cut": "bob",
    "hime": "hime_cut",
    "hime_haircut": "hime_cut",
    "side_swept": "side_swept_bangs",
    "swept_bangs": "side_swept_bangs",
    "front_bang": "front_bangs",
    "straight_bangs": "front_bangs",
    "bangs": "front_bangs",
    "blunt_bang": "blunt_bangs",
    "sidelock": "sidelocks",
    "hair_over_eye": "hair_over_one_eye",
}
EYE_SHAPE_VALUE_ALIASES = {
    "closed_eyes": "closed",
    "closed_eye": "closed",
    "sleepy": "closed",
    "open_eyes": "open",
    "round_eyes": "round",
    "almond_shaped": "almond",
    "almond_eyes": "almond",
    "narrow_eyes": "narrow",
    "sharp_eyes": "sharp",
    "slanted_eyes": "slanted",
}
MOUTH_SHAPE_VALUE_ALIASES = {
    "closed_mouth": "closed",
    "open_mouth": "open",
    "smiling": "smile",
    "smile_mouth": "smile",
    "frowning": "frown",
    "frown_mouth": "frown",
    "neutral_mouth": "neutral",
}
OUTFIT_SHAPE_VALUE_ALIASES = {
    "school_uniform": "uniform",
    "sailor_uniform": "uniform",
    "military_uniform": "uniform",
    "maid_outfit": "maid_uniform",
    "maid_dress": "maid_uniform",
    "dress_outfit": "dress",
    "frilled_dress": "dress",
    "long_dress": "dress",
    "short_dress": "dress",
    "kimono_outfit": "kimono",
    "japanese_clothes": "kimono",
    "hooded_robe": "robe",
    "armored_outfit": "armor",
    "swimwear": "swimsuit",
    "school_swimsuit": "swimsuit",
    "jacket_outfit": "jacket",
}
CANONICAL_VALUE_ALIASES = {
    **LENGTH_VALUE_ALIASES,
    **HEIGHT_VALUE_ALIASES,
    **COLOR_VALUE_ALIASES,
    **HAIR_SHAPE_VALUE_ALIASES,
    **EYE_SHAPE_VALUE_ALIASES,
    **MOUTH_SHAPE_VALUE_ALIASES,
    **OUTFIT_SHAPE_VALUE_ALIASES,
}
SKIN_TONE_ALLOWED_VALUES = {
    "fair",
    "tan",
    "dark",
}
SKIN_TONE_VALUE_ALIASES = {
    "light": "fair",
    "fair": "fair",
    "light_peach": "fair",
    "pale": "fair",
    "peach": "fair",
    "ivory": "fair",
    "beige": "fair",
    "warm_beige": "fair",
    "light_tan": "tan",
    "wheat": "tan",
    "wheatish": "tan",
    "tanned": "tan",
    "brown": "dark",
    "dark_skin": "dark",
    "dark_brown": "dark",
    "deep_brown": "dark",
    "gray_skin": "dark",
    "grey_skin": "dark",
    "gray": "dark",
    "grey": "dark",
    "metallic_gray": "dark",
    "metallic_grey": "dark",
}

SYSTEM_PROMPT = """你是动漫 IP 角色设定监修助手。
你的任务是观察同一角色的 2D 彩色设定图/多视图图像，直接抽取后续 2D/3D 监修需要检查的 atomic_rules。
atomic_rules 只表示角色可见且稳定的属性名称及其标准值。
不要识别人物身份，不要猜测不可见区域，不要输出 JSON 以外的文字。
"""

QUALITY_RULES_STRICT = """图片质量:
- 如果图片不是日本 ACG 风格、不是 2D 彩色人类/人形角色、不是全身或多视图设定图，则 atomic_rules 输出空数组。
- 如果主体是动物、怪物、非人形生物，atomic_rules 输出空数组。"""

QUALITY_RULES_FORCE_CONTINUE = """图片质量:
- 尽量按日本 ACG 风格、2D 彩色、人形角色、全身或多视图设定图的标准来观察图片。
- 即使图片不是理想的设定图或构图不完整，也继续抽取清楚可见、稳定、适合监修比对的 atomic_rules，不要因为图片质量不完美而直接输出空数组。
- 如果局部不可见，只跳过对应规则，不要猜测不可见区域。"""

USER_PROMPT_TEMPLATE = """请根据这张 2D 动漫角色设定图输出严格 JSON。

任务目标:
- 尽可能多发现清楚可见、稳定、适合后续 2D/3D 监修比对的 atomic_rules。
- rule_id 可以灵活发现，但必须清晰、可填表、可复查，并使用英文 snake_case。
- value 必须是短 canonical label 或 true；不要输出自然语言描述、长组合短语、程度副词、数字或不确定占位值。

__QUALITY_RULES__

观察维度:
- 头部：头发、眼睛、嘴、肤色、脸部固有特征、头部配饰。
- 身体：服装、身体配饰、身体固有特征、图案、手持/随身物件、腿脚。
- 视角：综合 front/side/back 信息，只记录能从图中确认的稳定规则。

颜色与细节完整性:
- 参考旧项目的原子化原则：物体、颜色、图案、结构、装饰必须拆成独立规则；不要把颜色塞进物体 value。
- 如果输出任何可见物体/配饰/手持物/武器/标志物的存在或类型规则，必须同时检查并输出对应颜色或细节规则。
- 重点不要漏掉：手持物、武器、头饰、发饰、蝴蝶结、铃铛、项链、耳饰、腰带、背部配饰、披风、护甲、手套、鞋袜、尾巴、翅膀、角、身体装饰和标志性符号。
- 推荐拆法：`holding_item = bell` 之外，如果可见颜色，还要输出 `holding_item_color` 或 `bell_color`；`has_chest_bow = true` 之外，还要输出 `chest_bow_color`；`has_back_accessory = true` 之外，还要输出 `back_accessory_color`。
- 如果某个小物件有渐变、多色分区、半透明、高光、金属色偏、图案、符号或左右不对称配色，应额外输出短规则，例如 `legwear_gradient = true`、`skirt_pattern = plaid`、`weapon_accent_color = red`。
- 如果输出 `*_gradient = true` 或 `*_pattern`，也要尽量输出同一对象的基础 `*_color`，避免只有“有渐变/有图案”但没有颜色锚点。
- 只有在图片中能看清时才输出颜色和细节；不要根据常识补色。例如不要因为物体是 bell 就默认输出 gold/yellow，必须以 2D 图可见颜色为准。

通用原则:
- 只根据图片可见内容判断；被遮挡、闭眼、头盔/面具覆盖、局部不可见时，直接省略对应 rule，不要猜测。
- 复杂外观拆成多个 facet，例如 length、shape、color、type、position；不要把多个属性塞进一个 value。
- value 尽量收敛：skin_tone 只能是 fair/tan/dark；如果是非人类或幻想肤色，用 skin_color 输出基础颜色；所有 *_length 只能是 short/medium/long，不要直接输出 sleeveless、mini、midi、knee_high、thigh_high、elbow_length 这类词；所有 *_height 只能是 low/medium/high，不要直接输出 ankle、mid_calf、knee_high、thigh_high、high_heel、platform 这类词；细分同义词由后处理归一。
- 后天添加物归为 accessory；先天、固有或身体结构特征归为 signature feature。
- 不输出精确数量规则；数量差异后续按样式、结构或缺失问题处理。
- 位置不确定时使用较宽泛区域；普通局部细节不要过度拆分，除非是醒目的监修关键特征。
- source tags 只是弱提示，图片可见内容优先。

输出 schema:
{
  "code": "__CODE__",
  "atomic_rules": [
    {
      "id": "<english_snake_case_rule_id>",
      "value": "<short_canonical_label_or_true>"
    }
  ]
}

输出要求:
- code 必须等于 "__CODE__"。
- 只能输出 code 和 atomic_rules。
- 每条 atomic rule 只能有 id 和 value 两个字段。
- `has_*` 布尔规则只记录明确存在的特征，value 只能是 true；不存在或无法确定则不要输出。
- 不要输出 none、unknown、not_visible、not_applicable、unclear 或 false。
- 不要输出 markdown code fence，不要输出 JSON 以外的任何文字。

Source tag weak hints:
__SOURCE_TAG_HINTS__
"""

GUIDANCE_PROMPT = """

额外人工审核 guidance 如下。请只把它当作纠错约束，不要在输出中复述。

__GUIDANCE__
"""


def build_user_prompt(
    code: str,
    source_tag_hints: str = DEFAULT_SOURCE_TAG_HINTS,
    guidance: str = "",
    *,
    force_continue: bool = False,
) -> str:
    quality_rules = QUALITY_RULES_FORCE_CONTINUE if force_continue else QUALITY_RULES_STRICT
    prompt = (
        USER_PROMPT_TEMPLATE
        .replace("__QUALITY_RULES__", quality_rules)
        .replace("__CODE__", code)
        .replace("__SOURCE_TAG_HINTS__", source_tag_hints or DEFAULT_SOURCE_TAG_HINTS)
    )
    if guidance:
        prompt += GUIDANCE_PROMPT.replace("__GUIDANCE__", guidance)
    return prompt


def normalize_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    label = value.strip().lower()
    if not label:
        return None
    label = re.sub(r"[^a-z0-9]+", "_", label).strip("_")
    if not label or label in BANNED_EMPTY_VALUES:
        return None
    return label


def remove_modifier_tokens(label: str) -> str:
    tokens = [token for token in label.split("_") if token and token not in BANNED_VALUE_MODIFIERS]
    compact = "_".join(tokens).strip("_")
    return compact


def normalize_value(value: Any) -> str | bool | None:
    if isinstance(value, bool):
        return value if value else None
    if isinstance(value, int | float):
        return None
    label = normalize_label(value)
    if not label:
        return None
    if label == "true":
        return True
    if label == "false":
        return None
    label = remove_modifier_tokens(label)
    if not label or label in BANNED_EMPTY_VALUES:
        return None
    if label in NUMBER_WORDS or label.isdigit():
        return None
    return CANONICAL_VALUE_ALIASES.get(label, label)


def canonicalize_rule_value(rule_id: str, value: str | bool | None) -> str | bool | None:
    if value is None or value is True:
        return value
    if rule_id == "skin_tone":
        canonical = SKIN_TONE_VALUE_ALIASES.get(value, value)
        if canonical in SKIN_TONE_ALLOWED_VALUES:
            return canonical
    if rule_id == "skin_color":
        return COLOR_VALUE_ALIASES.get(value, value)
    if rule_id.endswith("_color") or rule_id.endswith("color") or "color" in rule_id.split("_"):
        return COLOR_VALUE_ALIASES.get(value, value)
    if rule_id.endswith("_length") or rule_id.endswith("length") or "length" in rule_id.split("_"):
        return LENGTH_VALUE_ALIASES.get(value, value)
    if rule_id.endswith("_height") or rule_id.endswith("height") or "height" in rule_id.split("_"):
        return HEIGHT_VALUE_ALIASES.get(value, value)
    if rule_id in {"hair_shape", "hair_style", "hair_bangs"} or (
        rule_id.startswith("hair_") and any(token in rule_id for token in {"shape", "style", "bang", "bangs"})
    ):
        return HAIR_SHAPE_VALUE_ALIASES.get(value, value)
    if rule_id.endswith("_eye_shape") or rule_id in {"eye_shape", "eyes_shape", "left_eye_shape", "right_eye_shape"}:
        return EYE_SHAPE_VALUE_ALIASES.get(value, value)
    if rule_id in {"mouth_shape", "mouth_style"} or rule_id.endswith("_mouth_shape"):
        return MOUTH_SHAPE_VALUE_ALIASES.get(value, value)
    if rule_id in {"outfit_shape", "outfit_type", "clothing_shape", "clothing_type"}:
        return OUTFIT_SHAPE_VALUE_ALIASES.get(value, value)
    return value


def normalize_rule_entry(rule: Any) -> dict[str, Any] | None:
    if not isinstance(rule, dict):
        return None
    rule_id = normalize_label(rule.get("id"))
    value = normalize_value(rule.get("value"))
    if rule_id:
        value = canonicalize_rule_value(rule_id, value)
    if not rule_id or value is None:
        return None
    if set(rule_id.split("_")) & COUNT_RULE_KEYWORDS:
        return None
    return {"id": rule_id, "value": value}


def normalize_rule_doc(doc: dict[str, Any], code: str) -> dict[str, Any]:
    rules = doc.get("atomic_rules", [])
    if not isinstance(rules, list):
        rules = []

    normalized_rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in rules:
        normalized = normalize_rule_entry(rule)
        if not normalized:
            continue
        key = json.dumps([normalized["id"], normalized["value"]], ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        normalized_rules.append(normalized)
    return {"code": code, "atomic_rules": normalized_rules}


def ensure_dashscope_api_key() -> str:
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY is not set in this process.")
    try:
        api_key.encode("ascii")
    except UnicodeEncodeError as exc:
        raise SystemExit("DASHSCOPE_API_KEY contains non-ASCII characters. Please set the real DashScope API key.") from exc
    return api_key


def response_to_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "__dict__"):
        return dict(response.__dict__)
    return json.loads(json.dumps(response, default=lambda value: getattr(value, "__dict__", str(value))))


def extract_text(response_dict: dict[str, Any]) -> str:
    output = response_dict.get("output", {})
    choices = output.get("choices", []) if isinstance(output, dict) else []
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content)


def parse_json_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def call_qwen_atomic_rules(
    image_ref: str,
    code: str,
    model: str,
    *,
    source_tag_hints: str = DEFAULT_SOURCE_TAG_HINTS,
    guidance: str = "",
    force_continue: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    api_key = ensure_dashscope_api_key()
    user_prompt = build_user_prompt(
        code,
        source_tag_hints=source_tag_hints,
        guidance=guidance,
        force_continue=force_continue,
    )
    response = MultiModalConversation.call(
        model=model,
        messages=[
            {"role": "system", "content": [{"text": SYSTEM_PROMPT}]},
            {
                "role": "user",
                "content": [
                    {"image": image_ref},
                    {"text": user_prompt},
                ],
            },
        ],
        api_key=api_key,
        result_format="message",
        temperature=0.0,
    )
    response_dict = response_to_dict(response)
    status_code = response_dict.get("status_code")
    if status_code and int(status_code) >= 400:
        raise RuntimeError(f"DashScope error {status_code}: {response_dict}")
    return parse_json_text(extract_text(response_dict)), response_dict
