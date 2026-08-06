"""Convert normalized element predictions between supported artifact schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image

from vlm.scripts.dataset.element_extraction_schema import (
    ATOMIC_RULES_SCHEMA,
    OUTPUT_SCHEMAS,
    convert_prediction_payload,
    scale_prediction_bboxes,
)
from vlm.scripts.dataset.evaluate_element_extraction_predictions import evaluate_sample_dir, write_json


def convert_sample(sample_dir: Path, input_file: str, output_file: str, output_schema: str, bbox_mode: str) -> dict[str, Any]:
    input_path = sample_dir / input_file
    payload = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{input_path}: expected prediction object")
    response_schema = "atomic_rules.v1" if isinstance(payload.get("atomic_rules"), list) else "elements.v1"
    response_payload = {"atomic_rules": payload["atomic_rules"]} if response_schema == "atomic_rules.v1" else {
        "elements": payload.get("elements", [])
    }
    image_name = str(payload.get("source_image", "")).strip()
    image_path = sample_dir / image_name if image_name else None
    if image_path is None or not image_path.exists():
        candidates = [path for suffix in (".png", ".jpg", ".jpeg", ".webp") for path in sample_dir.glob(f"*{suffix}")]
        if len(candidates) != 1:
            raise ValueError(f"{sample_dir}: cannot resolve one source image")
        image_path = candidates[0]
    with Image.open(image_path) as image:
        width, height = image.size
    scale_prediction_bboxes(response_payload, width=width, height=height, mode=bbox_mode)
    normalized = convert_prediction_payload(response_payload, output_schema=output_schema, code=sample_dir.name)
    output = {
        "schema_version": (
            "element_extraction_atomic_rules.v1"
            if output_schema == ATOMIC_RULES_SCHEMA
            else "element_extraction_prediction.v1"
        ),
        **normalized,
        "sample_id": sample_dir.name,
        "source_image": payload.get("source_image"),
        "metadata": {
            **(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
            "output_schema": output_schema,
            "converted_from": input_file,
        },
    }
    write_json(sample_dir / output_file, output)
    return evaluate_sample_dir(sample_dir, prediction_file=output_file)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert element prediction artifact schemas.")
    parser.add_argument("--paired-root", type=Path, required=True)
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--output-schema", choices=OUTPUT_SCHEMAS, required=True)
    parser.add_argument("--bbox-mode", choices=("pixel", "normalized_1000"), default="pixel")
    parser.add_argument("--summary-file", default="")
    args = parser.parse_args()

    root = args.paired_root.resolve()
    sample_dirs = sorted(path for path in root.iterdir() if path.is_dir() and (path / args.input_file).exists())
    results = [convert_sample(path, args.input_file, args.output_file, args.output_schema, args.bbox_mode) for path in sample_dirs]
    total_matches = sum(item["match_count"] for item in results)
    total_gold = sum(item["gold_element_count"] for item in results)
    total_predictions = sum(item["prediction_element_count"] for item in results)
    precision = total_matches / total_predictions if total_predictions else 1.0
    recall = total_matches / total_gold if total_gold else 1.0
    summary = {
        "schema_version": "element_extraction_conversion_summary.v1",
        "input_file": args.input_file,
        "output_file": args.output_file,
        "output_schema": args.output_schema,
        "sample_count": len(results),
        "micro_precision": round(precision, 4),
        "micro_recall": round(recall, 4),
        "micro_f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "total_gold_elements": total_gold,
        "total_prediction_elements": total_predictions,
        "total_matches": total_matches,
    }
    summary_file = args.summary_file or f"{Path(args.output_file).stem}_summary.json"
    write_json(root / summary_file, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
