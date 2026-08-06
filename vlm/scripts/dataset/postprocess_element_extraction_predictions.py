"""Apply conservative, schema-aware cleanup to atomic extraction predictions."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from vlm.scripts.dataset.element_extraction_schema import infer_rule_id, normalize_bbox
from vlm.scripts.dataset.evaluate_element_extraction_predictions import (
    evaluate_sample_dir,
    write_json,
)

_DARK_EYE = re.compile(r"黑|棕|褐|深色|闭合|闭着")
_VIVID_EYE = re.compile(r"黄|金|蓝|青|绿|紫|粉|红|异色|特殊")
_ORDINARY_POSE = re.compile(r"自然下垂|普通站姿|微笑表情|站立")
_ATTACHED_ACCESSORY = re.compile(r"领结|领带|蝴蝶结|领子|领边")
_LOW_VALUE_DETAIL = re.compile(r"血迹|血渍|污渍|污点|下摆裙边|随机小图案")


def bbox_contained(inner: Any, outer: Any, *, tolerance: float = 0.03) -> bool:
    first = normalize_bbox(inner)
    second = normalize_bbox(outer)
    if first is None or second is None:
        return False
    width = second[2] - second[0]
    height = second[3] - second[1]
    return (
        first[0] >= second[0] - width * tolerance
        and first[1] >= second[1] - height * tolerance
        and first[2] <= second[2] + width * tolerance
        and first[3] <= second[3] + height * tolerance
    )


def filter_atomic_rules(rules: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return kept rules and machine-readable drop reasons.

    These rules target generic low-value observations, not a particular sample's
    gold labels.  Distinctive footwear, legwear, gloves, animal endpoints and
    props are intentionally left untouched.
    """
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    animal_rules = [item for item in rules if item.get("id") == "animal_feature"]
    top_rules = [item for item in rules if item.get("id") == "top"]

    for item in rules:
        rule_id = str(item.get("id", ""))
        value = str(item.get("value", "")).strip()
        reason = ""
        if rule_id == "eye" and _DARK_EYE.search(value) and not _VIVID_EYE.search(value):
            reason = "ordinary_dark_eye"
        elif rule_id == "face" and not re.search(r"右眼|左眼|单眼|特殊面部", value):
            reason = "ordinary_face_detail"
        elif rule_id == "pose" and _ORDINARY_POSE.search(value) and not re.search(r"交叠|伸出|叉腰|抬手|抱|托", value):
            reason = "ordinary_pose"
        elif rule_id == "accessory" and _LOW_VALUE_DETAIL.search(value):
            reason = "low_value_clothing_detail"
        elif rule_id == "head_accessory" and re.search(r"^.*发饰$", value):
            reason = "generic_hair_accessory"
        elif rule_id == "bottom" and _LOW_VALUE_DETAIL.search(value):
            reason = "low_value_bottom_detail"
        elif rule_id == "tail" and any(
            "猫耳与猫尾" in str(animal.get("value", ""))
            or "耳朵与尾巴" in str(animal.get("value", ""))
            for animal in animal_rules
        ):
            reason = "duplicate_animal_tail"
        elif rule_id == "eye" and any(
            re.search(r"眼睛|眼色|身体与", str(animal.get("value", "")))
            and bbox_contained(item.get("bbox"), animal.get("bbox"))
            for animal in animal_rules
        ):
            reason = "duplicate_animal_eye"
        elif rule_id == "accessory" and _ATTACHED_ACCESSORY.search(value) and any(
            bbox_contained(item.get("bbox"), top.get("bbox")) for top in top_rules
        ):
            reason = "attached_accessory_already_in_top"

        if reason:
            dropped.append({"rule": item, "reason": reason})
        else:
            kept.append(item)
    return kept, dropped


def legacy_rule_id(value: str) -> str:
    if re.search(r"手势|姿势|交叠|伸出|叉腰|抬手|自然下垂", value):
        return "pose"
    if re.search(r"表情|眉毛|鼻子|嘴|下巴", value) and not re.search(r"狗狗|动物|兽化", value):
        return "face"
    if _ATTACHED_ACCESSORY.search(value) and not re.search(r"衬衫|上衣|外套|马甲|背心|水手服|连衣裙|长袍", value):
        return "accessory"
    if re.search(r"眼睛|眼瞳|瞳孔|闭眼|双眼", value):
        return "eye"
    return infer_rule_id(value)


def process_sample(sample_dir: Path, input_file: str, output_file: str) -> dict[str, Any]:
    input_path = sample_dir / input_file
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    payload = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{input_path}: expected prediction object")
    is_atomic = isinstance(payload.get("atomic_rules"), list)
    is_legacy = isinstance(payload.get("elements"), list)
    if not is_atomic and not is_legacy:
        raise ValueError(f"{input_path}: expected atomic_rules or elements prediction payload")

    source_items = payload["atomic_rules"] if is_atomic else payload["elements"]
    prepared = source_items
    if is_legacy:
        prepared = [
            {
                "id": legacy_rule_id(str(item.get("element", ""))),
                "value": str(item.get("element", "")),
                "bbox": item.get("bbox"),
                "_source_index": index,
            }
            for index, item in enumerate(source_items)
            if isinstance(item, dict)
        ]
    kept, dropped = filter_atomic_rules(prepared)
    if is_atomic:
        filtered_items = kept
        dropped_records = dropped
        schema_version = "element_extraction_atomic_rules_filtered.v1"
        item_key = "atomic_rules"
    else:
        kept_indexes = {item["_source_index"] for item in kept}
        filtered_items = [item for index, item in enumerate(source_items) if index in kept_indexes]
        dropped_records = [
            {"element": source_items[item["rule"]["_source_index"]], "reason": item["reason"]}
            for item in dropped
        ]
        schema_version = "element_extraction_prediction_filtered.v1"
        item_key = "elements"
    output = {
        **payload,
        "schema_version": schema_version,
        item_key: filtered_items,
        "metadata": {
            **(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
            "post_filter": "conservative_atomic_rules.v1",
            "dropped_count": len(dropped_records),
        },
        "post_filter_dropped": dropped_records,
    }
    output_path = sample_dir / output_file
    write_json(output_path, output)
    evaluation = evaluate_sample_dir(sample_dir, prediction_file=output_file)
    evaluation["post_filter"] = "conservative_atomic_rules.v1"
    return {"sample_id": sample_dir.name, "evaluation": evaluation, "dropped": dropped_records}


def main() -> None:
    parser = argparse.ArgumentParser(description="Conservatively post-filter atomic element predictions.")
    parser.add_argument("--paired-root", type=Path, default=Path("vlm/data/smoke_test/qwen_element_extraction_test10"))
    parser.add_argument("--input-file", default="qwen_element_prediction_atomic_v1.json")
    parser.add_argument("--output-file", default="qwen_element_prediction_atomic_v1_filtered.json")
    parser.add_argument("--summary-file", default="", help="Defaults to <output-file stem>_summary.json.")
    args = parser.parse_args()

    root = args.paired_root.resolve()
    sample_dirs = sorted(path for path in root.iterdir() if path.is_dir() and (path / args.input_file).exists())
    results = [process_sample(path, args.input_file, args.output_file) for path in sample_dirs]
    total_matches = sum(item["evaluation"]["match_count"] for item in results)
    total_gold = sum(item["evaluation"]["gold_element_count"] for item in results)
    total_predictions = sum(item["evaluation"]["prediction_element_count"] for item in results)
    precision = total_matches / total_predictions if total_predictions else 1.0
    recall = total_matches / total_gold if total_gold else 1.0
    summary = {
        "schema_version": "element_extraction_atomic_rules_filtered_summary.v1",
        "input_file": args.input_file,
        "output_file": args.output_file,
        "sample_count": len(results),
        "micro_precision": round(precision, 4),
        "micro_recall": round(recall, 4),
        "micro_f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "total_gold_elements": total_gold,
        "total_prediction_elements": total_predictions,
        "total_matches": total_matches,
        "dropped_count": sum(len(item["dropped"]) for item in results),
        "results": results,
    }
    summary_file = args.summary_file or f"{Path(args.output_file).stem}_summary.json"
    output_path = root / summary_file
    write_json(output_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
