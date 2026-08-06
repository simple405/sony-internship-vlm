"""Build a balanced JSONL queue for manually calibrating strict extras."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from vlm.scripts.dataset.element_extraction_schema import prediction_elements


DEFAULT_ROOT = Path("vlm/data/1-动漫标注结果导出_paired_samples")
DEFAULT_EVALUATION_FILE = "qwen_element_evaluation_holdout30_v4_embedding.json"
DEFAULT_OUTPUT = DEFAULT_ROOT / "extra_prediction_calibration_holdout30_v1.jsonl"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def find_source_image(sample_dir: Path, evaluation: dict[str, Any]) -> Path:
    prediction_path = sample_dir / str(evaluation.get("prediction_path", ""))
    if prediction_path.is_file():
        prediction = read_json(prediction_path)
        source_name = prediction.get("source_image") if isinstance(prediction, dict) else None
        if isinstance(source_name, str) and (sample_dir / source_name).is_file():
            return sample_dir / source_name
    for suffix in IMAGE_SUFFIXES:
        candidate = sample_dir / f"{sample_dir.name}{suffix}"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"source image not found for {sample_dir.name}")


def collect_extra_rows(
    paired_root: Path,
    *,
    evaluation_file: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Collect extras round-robin so the calibration set covers all samples."""
    sample_groups: list[list[dict[str, Any]]] = []
    for sample_dir in sorted(path for path in paired_root.iterdir() if path.is_dir()):
        evaluation_path = sample_dir / evaluation_file
        if not evaluation_path.is_file():
            continue
        evaluation = read_json(evaluation_path)
        extras = evaluation.get("extra_predictions", [])
        if not isinstance(extras, list) or not extras:
            continue
        source_image = find_source_image(sample_dir, evaluation)
        gold_path = sample_dir / str(evaluation.get("gold_path", f"{sample_dir.name}.json"))
        gold_elements = read_json(gold_path)
        prediction_path = sample_dir / str(evaluation.get("prediction_path", ""))
        prediction_payload = read_json(prediction_path) if prediction_path.is_file() else {}
        all_predictions = prediction_elements(prediction_payload)
        sample_groups.append(
            [
                {
                    "schema_version": "element_extra_calibration.v1",
                    "sample_id": sample_dir.name,
                    "strict_extra_index": extra_index,
                    "source_image": source_image.relative_to(paired_root).as_posix(),
                    "prediction": prediction,
                    "gold_elements": gold_elements,
                    "other_predictions": predictions_except_current(all_predictions, prediction),
                    "image_grounded": None,
                    "description_correct": None,
                    "duplicate": None,
                    "conflict": None,
                    "accepted_extra": None,
                    "notes": "",
                }
                for extra_index, prediction in enumerate(extras)
                if isinstance(prediction, dict)
            ]
        )

    rows: list[dict[str, Any]] = []
    offset = 0
    while len(rows) < limit:
        added = False
        for group in sample_groups:
            if offset < len(group):
                rows.append(group[offset])
                added = True
                if len(rows) == limit:
                    break
        if not added:
            break
        offset += 1
    return rows


def predictions_except_current(
    all_predictions: list[dict[str, Any]], current: dict[str, Any]
) -> list[dict[str, Any]]:
    """Remove one exact occurrence of the current prediction from context."""
    remaining = list(all_predictions)
    for index, prediction in enumerate(remaining):
        if prediction == current:
            remaining.pop(index)
            break
    return remaining


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a manual calibration queue from strict extra predictions.")
    parser.add_argument("--paired-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--evaluation-file", default=DEFAULT_EVALUATION_FILE)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.limit <= 0:
        raise SystemExit("--limit must be positive")
    paired_root = args.paired_root.resolve()
    rows = collect_extra_rows(paired_root, evaluation_file=args.evaluation_file, limit=args.limit)
    if not rows:
        raise SystemExit(f"no extras found in {paired_root} using {args.evaluation_file}")
    write_jsonl(args.output, rows)
    print(json.dumps({"output": str(args.output), "row_count": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
