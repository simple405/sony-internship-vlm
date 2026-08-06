"""Normalize element-extraction payloads across legacy and atomic schemas."""

from __future__ import annotations

import json
import math
import re
from typing import Any

ELEMENTS_SCHEMA = "elements.v1"
ATOMIC_RULES_SCHEMA = "atomic_rules.v1"
OUTPUT_SCHEMAS = (ELEMENTS_SCHEMA, ATOMIC_RULES_SCHEMA)

ATOMIC_RULE_IDS = {
    "hair",
    "eye",
    "face",
    "animal_feature",
    "body_feature",
    "head_accessory",
    "top",
    "bottom",
    "legwear",
    "legwear_left",
    "legwear_right",
    "footwear",
    "footwear_left",
    "footwear_right",
    "glove",
    "glove_left",
    "glove_right",
    "accessory",
    "prop",
    "pose",
    "tail",
    "other",
}

_RULE_PATTERNS = (
    ("prop", re.compile(r"手持|抱着|餐巾|漫画书|书籍|道具|雨伞|武器|剑|杖")),
    ("pose", re.compile(r"手势|姿势|交叠|伸出|叉腰|抬手|表情")),
    ("animal_feature", re.compile(r"狗狗|猫耳|兽化|耳朵尖|内耳|动物外形|面部特征")),
    ("tail", re.compile(r"尾巴|尾部|尾尖")),
    ("hair", re.compile(r"头发|发型|长发|短发|马尾|辫|刘海|卷发|直发")),
    ("eye", re.compile(r"眼睛|眼瞳|瞳孔|右眼|左眼")),
    ("head_accessory", re.compile(r"发夹|头饰|耳钉|耳环|眼镜|帽子|帽|头巾|发带")),
    ("glove", re.compile(r"手套")),
    ("legwear", re.compile(r"袜|腿套")),
    ("footwear", re.compile(r"鞋|靴|凉鞋")),
    ("bottom", re.compile(r"裤|裙|腰带|下装|裙摆")),
    (
        "top",
        re.compile(r"衬衫|上衣|外套|马甲|背心|卫衣|水手服|长袍|披风|围裙|护甲|领结|领带|胸花|胸针|领子|肩章|口袋巾"),
    ),
    ("body_feature", re.compile(r"身体|皮肤|翅膀|角|鳞|爪")),
    ("face", re.compile(r"眉毛|鼻子|嘴|脸部|面部")),
)


def normalize_bbox(raw: Any) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        bbox = [float(value) for value in raw]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in bbox):
        return None
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return None
    return bbox


def infer_rule_id(value: Any) -> str:
    text = str(value or "").strip()
    for rule_id, pattern in _RULE_PATTERNS:
        if pattern.search(text):
            return rule_id
    return "other"


def extract_json_payload(raw_text: str) -> Any:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    if text.startswith("[") and text.endswith("]"):
        return json.loads(text)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1] if start >= 0 and end > start else text)


def normalize_elements(candidates: Any) -> list[dict[str, Any]]:
    if not isinstance(candidates, list):
        raise ValueError("response has no elements list")
    elements: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        element = str(item.get("element", "")).strip()
        description = str(item.get("description", "")).strip()
        bbox = normalize_bbox(item.get("bbox"))
        if element and description and bbox is not None:
            elements.append({"element": element, "description": description, "bbox": bbox})
    if not elements:
        raise ValueError("response contained no valid element records")
    return elements


def normalize_atomic_rules(candidates: Any) -> list[dict[str, Any]]:
    if not isinstance(candidates, list):
        raise ValueError("response has no atomic_rules list")
    rules: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value", item.get("element", ""))).strip()
        bbox = normalize_bbox(item.get("bbox"))
        if not value or bbox is None:
            continue
        raw_id = str(item.get("id", "")).strip().lower()
        rule_id = raw_id if raw_id in ATOMIC_RULE_IDS else infer_rule_id(value)
        rules.append({"id": rule_id, "value": value, "bbox": bbox})
    return rules


def normalize_model_response(raw_text: str, *, output_schema: str, code: str) -> dict[str, Any]:
    parsed = extract_json_payload(raw_text)
    if output_schema == ELEMENTS_SCHEMA:
        candidates = parsed.get("elements") if isinstance(parsed, dict) else parsed
        return {"elements": normalize_elements(candidates)}
    if output_schema == ATOMIC_RULES_SCHEMA:
        candidates = parsed.get("atomic_rules") if isinstance(parsed, dict) else parsed
        return {"code": code, "atomic_rules": normalize_atomic_rules(candidates)}
    raise ValueError(f"unsupported output schema: {output_schema}")


def prediction_elements(payload: Any) -> list[dict[str, Any]]:
    """Return a legacy element view for either supported prediction schema."""
    if isinstance(payload, list):
        candidates = payload
        atomic = False
    elif isinstance(payload, dict) and isinstance(payload.get("elements"), list):
        candidates = payload["elements"]
        atomic = False
    elif isinstance(payload, dict) and isinstance(payload.get("atomic_rules"), list):
        candidates = payload["atomic_rules"]
        atomic = True
    else:
        return []

    elements: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if atomic:
            value = str(item.get("value", "")).strip()
            if not value:
                continue
            elements.append(
                {
                    "element": value,
                    "description": str(item.get("description", value)).strip() or value,
                    "bbox": item.get("bbox"),
                    "rule_id": str(item.get("id", "")).strip(),
                }
            )
        else:
            elements.append(item)
    return elements


def elements_to_atomic_rules(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert human gold elements to atomic-rule-shaped SFT targets."""
    prepared: list[dict[str, Any]] = []
    for item in elements:
        value = str(item.get("element", "")).strip()
        prepared.append(
            {
                "id": infer_rule_id(value),
                "value": value,
                "bbox": item.get("bbox"),
                "_center_x": sum(item.get("bbox", [0, 0, 0, 0])[::2]) / 2,
            }
        )

    side_capable = {"footwear", "legwear", "glove"}
    for base_id in side_capable:
        group = [item for item in prepared if item["id"] == base_id]
        if len(group) == 2:
            for side, item in zip(("left", "right"), sorted(group, key=lambda entry: entry["_center_x"])):
                item["id"] = f"{base_id}_{side}"

    for item in prepared:
        item.pop("_center_x", None)
    return prepared


def convert_prediction_payload(payload: dict[str, Any], *, output_schema: str, code: str) -> dict[str, Any]:
    """Convert an already-normalized response to the requested artifact schema."""
    if output_schema == ELEMENTS_SCHEMA:
        if isinstance(payload.get("elements"), list):
            return {"elements": payload["elements"]}
        return {
            "elements": [
                {"element": item["element"], "description": item["description"], "bbox": item.get("bbox")}
                for item in prediction_elements(payload)
            ]
        }
    if output_schema == ATOMIC_RULES_SCHEMA:
        if isinstance(payload.get("atomic_rules"), list):
            return {"code": code, "atomic_rules": payload["atomic_rules"]}
        elements = payload.get("elements") if isinstance(payload.get("elements"), list) else []
        return {"code": code, "atomic_rules": elements_to_atomic_rules(elements)}
    raise ValueError(f"unsupported output schema: {output_schema}")


def scale_prediction_bboxes(payload: dict[str, Any], *, width: int, height: int, mode: str) -> dict[str, Any]:
    """Scale normalized 0-1000 boxes to source-image pixels when requested."""
    if mode == "pixel":
        return payload
    if mode != "normalized_1000":
        raise ValueError(f"unsupported bbox mode: {mode}")
    for key in ("elements", "atomic_rules"):
        for item in payload.get(key, []) if isinstance(payload.get(key), list) else []:
            bbox = item.get("bbox") if isinstance(item, dict) else None
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            item["bbox"] = [
                float(bbox[0]) * width / 1000,
                float(bbox[1]) * height / 1000,
                float(bbox[2]) * width / 1000,
                float(bbox[3]) * height / 1000,
            ]
    return payload
