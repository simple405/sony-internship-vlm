"""Build a VLM SFT dataset for anime element extraction from paired samples.

Input layout:
    paired_root/
      manifest.csv
      SAMPLE_ID/
        SAMPLE_ID.json
        SAMPLE_ID.png|jpg|jpeg|webp

Output layout:
    output_root/
      images/
      train.jsonl
      val.jsonl
      test.jsonl
      manifest.csv
      split_summary.json

Each JSONL row uses a common LLaVA/Qwen-style conversation format:
    {
      "id": "...",
      "image": "images/....png",
      "conversations": [
        {"from": "human", "value": "<image>..."},
        {"from": "gpt", "value": "[{\"element\": ..., \"description\": ..., \"bbox\": [...]}]"}
      ]
    }
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vlm.scripts.dataset.element_extraction_schema import (
    ATOMIC_RULES_SCHEMA,
    ELEMENTS_SCHEMA,
    OUTPUT_SCHEMAS,
    elements_to_atomic_rules,
)

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

DEFAULT_USER_PROMPT = (
    "<image>\n"
    "请识别图中角色的关键身份元素，输出 JSON 数组。"
    "每个对象必须包含 element、description、bbox。"
    "bbox 使用 [x1, y1, x2, y2] 像素坐标，不要输出解释文字。"
)
ATOMIC_USER_PROMPT = (
    "<image>\n"
    "请按 atomic_rules 格式识别图中角色的少量核心身份元素。"
    "输出 {code, atomic_rules}，每条规则包含 id、value、bbox，不要输出解释。"
)


@dataclass(frozen=True)
class Sample:
    sample_id: str
    json_path: Path
    image_path: Path
    image_bytes: int


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_bbox(raw: Any, path: Path, index: int) -> list[int | float]:
    if not isinstance(raw, list) or len(raw) != 4:
        raise ValueError(f"{path}: item #{index} bbox must be a 4-number list")
    bbox: list[int | float] = []
    for value in raw:
        if not isinstance(value, (int, float)):
            raise ValueError(f"{path}: item #{index} bbox contains non-number: {value!r}")
        bbox.append(value)
    return bbox


def normalize_annotation(path: Path) -> list[dict[str, Any]]:
    data = load_json(path)
    if not isinstance(data, list):
        raise ValueError(f"{path}: top-level JSON must be a list")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: item #{index} must be an object")
        element = str(item.get("element", "")).strip()
        description = str(item.get("description", "")).strip()
        if not element:
            raise ValueError(f"{path}: item #{index} misses element")
        if not description:
            raise ValueError(f"{path}: item #{index} misses description")
        normalized.append(
            {
                "element": element,
                "description": description,
                "bbox": normalize_bbox(item.get("bbox"), path, index),
            }
        )
    return normalized


def read_manifest_samples(input_root: Path) -> list[Sample]:
    manifest = input_root / "manifest.csv"
    if not manifest.exists():
        raise FileNotFoundError(f"missing manifest.csv: {manifest}")

    samples: list[Sample] = []
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"sample_id", "json_file", "image_file"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{manifest}: missing required columns: {sorted(missing)}")
        for row in reader:
            sample_id = (row.get("sample_id") or "").strip()
            json_file = (row.get("json_file") or "").strip()
            image_file = (row.get("image_file") or "").strip()
            if not sample_id or not json_file or not image_file:
                raise ValueError(f"{manifest}: malformed row: {row}")
            json_path = input_root / json_file
            image_path = input_root / image_file
            if not json_path.exists():
                raise FileNotFoundError(f"missing annotation JSON for {sample_id}: {json_path}")
            if not image_path.exists():
                raise FileNotFoundError(f"missing image for {sample_id}: {image_path}")
            if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                raise ValueError(f"unsupported image suffix for {sample_id}: {image_path}")
            samples.append(
                Sample(
                    sample_id=sample_id,
                    json_path=json_path,
                    image_path=image_path,
                    image_bytes=image_path.stat().st_size,
                )
            )
    return samples


def split_samples(
    samples: list[Sample],
    train_ratio: float,
    val_ratio: float,
    seed: int,
) -> dict[str, list[Sample]]:
    if not samples:
        raise ValueError("no samples to split")
    if train_ratio <= 0 or val_ratio < 0 or train_ratio + val_ratio >= 1:
        raise ValueError("ratios must satisfy: train_ratio > 0, val_ratio >= 0, train_ratio + val_ratio < 1")

    ordered = list(samples)
    random.Random(seed).shuffle(ordered)

    total = len(ordered)
    train_count = int(total * train_ratio)
    val_count = int(total * val_ratio)
    return {
        "train": ordered[:train_count],
        "val": ordered[train_count : train_count + val_count],
        "test": ordered[train_count + val_count :],
    }


def ensure_clean_output_files(output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for name in ("train.jsonl", "val.jsonl", "test.jsonl", "manifest.csv", "split_summary.json"):
        path = output_root / name
        if path.exists():
            path.unlink()
    (output_root / "images").mkdir(parents=True, exist_ok=True)


def place_image(src: Path, dst: Path, image_mode: str) -> str:
    if image_mode == "relative":
        return os.path.relpath(src.resolve(), dst.parent.parent.resolve()).replace("\\", "/")

    if dst.exists():
        if dst.stat().st_size == src.stat().st_size:
            return os.path.relpath(dst, dst.parent.parent).replace("\\", "/")
        dst.unlink()

    if image_mode == "copy":
        shutil.copy2(src, dst)
    elif image_mode == "hardlink":
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    else:
        raise ValueError(f"unsupported image_mode: {image_mode}")
    return os.path.relpath(dst, dst.parent.parent).replace("\\", "/")


def build_record(
    sample: Sample,
    output_root: Path,
    image_mode: str,
    prompt: str,
    output_schema: str,
) -> tuple[dict[str, Any], str]:
    image_dst = output_root / "images" / f"{sample.sample_id}{sample.image_path.suffix.lower()}"
    image_rel = place_image(sample.image_path, image_dst, image_mode)
    annotation = normalize_annotation(sample.json_path)
    target: Any = annotation
    if output_schema == ATOMIC_RULES_SCHEMA:
        target = {"code": sample.sample_id, "atomic_rules": elements_to_atomic_rules(annotation)}
    assistant_value = json.dumps(target, ensure_ascii=False, separators=(",", ":"))
    return (
        {
            "id": sample.sample_id,
            "image": image_rel,
            "conversations": [
                {"from": "human", "value": prompt},
                {"from": "gpt", "value": assistant_value},
            ],
        },
        assistant_value,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def validate_output(output_root: Path, splits: dict[str, list[dict[str, Any]]], output_schema: str) -> dict[str, Any]:
    errors: list[str] = []
    total_records = 0
    total_elements = 0

    for split_name, records in splits.items():
        jsonl_path = output_root / f"{split_name}.jsonl"
        if not jsonl_path.exists():
            errors.append(f"missing split file: {jsonl_path}")
            continue
        line_count = 0
        with jsonl_path.open("r", encoding="utf-8-sig") as handle:
            for line_no, line in enumerate(handle, start=1):
                line_count += 1
                total_records += 1
                try:
                    record = json.loads(line)
                    image_path = output_root / record["image"]
                    if not image_path.exists():
                        errors.append(f"{jsonl_path}:{line_no}: missing image {record['image']}")
                    assistant = record["conversations"][1]["value"]
                    parsed = json.loads(assistant)
                    if output_schema == ATOMIC_RULES_SCHEMA:
                        parsed = parsed.get("atomic_rules") if isinstance(parsed, dict) else None
                    if not isinstance(parsed, list):
                        errors.append(f"{jsonl_path}:{line_no}: assistant JSON has wrong schema")
                        continue
                    total_elements += len(parsed)
                    for index, item in enumerate(parsed, start=1):
                        if not isinstance(item, dict):
                            errors.append(f"{jsonl_path}:{line_no}: item #{index} is not an object")
                            continue
                        required_keys = ("id", "value", "bbox") if output_schema == ATOMIC_RULES_SCHEMA else (
                            "element", "description", "bbox"
                        )
                        for key in required_keys:
                            if key not in item:
                                errors.append(f"{jsonl_path}:{line_no}: item #{index} misses {key}")
                        if "bbox" in item:
                            normalize_bbox(item["bbox"], jsonl_path, index)
                except Exception as exc:  # noqa: BLE001 - validation should collect all row-level failures
                    errors.append(f"{jsonl_path}:{line_no}: {exc}")
        if line_count != len(records):
            errors.append(f"{jsonl_path}: expected {len(records)} rows, got {line_count}")

    return {
        "ok": not errors,
        "error_count": len(errors),
        "errors": errors[:50],
        "record_count": total_records,
        "element_count": total_elements,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build element-extraction VLM SFT JSONL dataset from paired samples.")
    parser.add_argument("--input-root", type=Path, default=Path("vlm/data/1-动漫标注结果导出_paired_samples"))
    parser.add_argument("--output-root", type=Path, default=Path("vlm/data/element_extraction_sft_export"))
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20260805)
    parser.add_argument(
        "--image-mode",
        choices=("hardlink", "copy", "relative"),
        default="hardlink",
        help="hardlink saves disk on the same Windows volume; falls back to copy if linking fails.",
    )
    parser.add_argument("--prompt", default=DEFAULT_USER_PROMPT)
    parser.add_argument(
        "--output-schema",
        choices=OUTPUT_SCHEMAS,
        default=ELEMENTS_SCHEMA,
        help="SFT assistant target schema; atomic_rules.v1 mirrors atomic_rules.json format.",
    )
    parser.add_argument("--limit", type=int, help="Optional debug limit before splitting.")
    args = parser.parse_args()

    input_root = args.input_root.resolve()
    output_root = args.output_root.resolve()

    samples = read_manifest_samples(input_root)
    if args.limit is not None:
        samples = samples[: args.limit]
    splits_raw = split_samples(samples, args.train_ratio, args.val_ratio, args.seed)

    if args.output_schema == ATOMIC_RULES_SCHEMA and args.prompt == DEFAULT_USER_PROMPT:
        args.prompt = ATOMIC_USER_PROMPT

    ensure_clean_output_files(output_root)

    split_records: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}
    manifest_rows: list[dict[str, Any]] = []
    split_element_counts = {"train": 0, "val": 0, "test": 0}

    for split_name, split_samples_list in splits_raw.items():
        for sample in split_samples_list:
            record, assistant_value = build_record(
                sample, output_root, args.image_mode, args.prompt, args.output_schema
            )
            annotation = json.loads(assistant_value)
            split_records[split_name].append(record)
            elements = annotation.get("atomic_rules", []) if args.output_schema == ATOMIC_RULES_SCHEMA else annotation
            split_element_counts[split_name] += len(elements)
            manifest_rows.append(
                {
                    "sample_id": sample.sample_id,
                    "split": split_name,
                    "image": record["image"],
                    "annotation_json": os.path.relpath(sample.json_path.resolve(), output_root).replace("\\", "/"),
                    "element_count": len(elements),
                    "image_bytes": sample.image_bytes,
                }
            )

    for split_name, records in split_records.items():
        write_jsonl(output_root / f"{split_name}.jsonl", records)

    with (output_root / "manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("sample_id", "split", "image", "annotation_json", "element_count", "image_bytes"),
        )
        writer.writeheader()
        writer.writerows(sorted(manifest_rows, key=lambda row: (row["split"], row["sample_id"])))

    validation = validate_output(output_root, split_records, args.output_schema)
    summary = {
        "input_root": str(input_root),
        "output_root": str(output_root),
        "sample_count": len(samples),
        "split_counts": {name: len(records) for name, records in split_records.items()},
        "split_element_counts": split_element_counts,
        "train_ratio": args.train_ratio,
        "val_ratio": args.val_ratio,
        "test_ratio_effective": len(split_records["test"]) / len(samples),
        "seed": args.seed,
        "image_mode": args.image_mode,
        "prompt": args.prompt,
        "output_schema": args.output_schema,
        "files": {
            "train": str(output_root / "train.jsonl"),
            "val": str(output_root / "val.jsonl"),
            "test": str(output_root / "test.jsonl"),
            "manifest": str(output_root / "manifest.csv"),
        },
        "sha256": {
            "train": sha256_file(output_root / "train.jsonl"),
            "val": sha256_file(output_root / "val.jsonl"),
            "test": sha256_file(output_root / "test.jsonl"),
            "manifest": sha256_file(output_root / "manifest.csv"),
        },
        "validation": validation,
    }
    (output_root / "split_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not validation["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
