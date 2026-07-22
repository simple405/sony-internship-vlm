#!/usr/bin/env python3
"""Audit a paired image/JSON VLM dataset without modifying source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_size(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as handle:
        header = handle.read(32)
        if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
            return struct.unpack(">II", header[16:24])
        if header[:6] in (b"GIF87a", b"GIF89a") and len(header) >= 10:
            return struct.unpack("<HH", header[6:10])
        if header[:2] == b"\xff\xd8":
            handle.seek(2)
            start_of_frame = {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }
            while True:
                byte = handle.read(1)
                if not byte:
                    break
                if byte != b"\xff":
                    continue
                while byte == b"\xff":
                    byte = handle.read(1)
                marker = byte[0]
                if marker in (0xD8, 0xD9):
                    continue
                length_bytes = handle.read(2)
                if len(length_bytes) != 2:
                    break
                segment_length = struct.unpack(">H", length_bytes)[0]
                if segment_length < 2:
                    break
                if marker in start_of_frame:
                    data = handle.read(5)
                    if len(data) != 5:
                        break
                    height, width = struct.unpack(">HH", data[1:5])
                    return width, height
                handle.seek(segment_length - 2, 1)

    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except (ImportError, OSError, ValueError):
        return None


def relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def audit(root: Path, excluded_output: Path | None = None) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    records: list[dict[str, Any]] = []
    sample_ids: defaultdict[str, list[str]] = defaultdict(list)
    referenced_images: set[Path] = set()

    def issue(target: list[dict[str, str]], code: str, path: Path, message: str) -> None:
        target.append({"code": code, "path": relative(path, root), "message": message})

    json_files = [path for path in sorted(root.rglob("*.json")) if path != excluded_output]
    all_images = {
        path.resolve()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    }

    for json_path in json_files:
        record: dict[str, Any] = {"metadata_json": relative(json_path, root)}
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            issue(errors, "invalid_json", json_path, str(exc))
            record["valid"] = False
            records.append(record)
            continue

        if not isinstance(payload, dict):
            issue(errors, "invalid_root", json_path, "JSON root must be an object")
            record["valid"] = False
            records.append(record)
            continue

        sample_id = payload.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id.strip():
            issue(errors, "invalid_sample_id", json_path, "sample_id must be a non-empty string")
            sample_id = ""
        else:
            sample_ids[sample_id].append(relative(json_path, root))
        record["sample_id"] = sample_id

        source_image = payload.get("source_image")
        image_path: Path | None = None
        if not isinstance(source_image, str) or not source_image.strip():
            issue(errors, "invalid_source_image", json_path, "source_image must be a non-empty string")
        else:
            source_path = Path(source_image)
            if source_path.is_absolute():
                issue(warnings, "absolute_source_path", json_path, "source_image is not portable")
                image_path = source_path.resolve()
            else:
                image_path = (json_path.parent / source_path).resolve()
            record["source_image"] = relative(image_path, root)
            if not image_path.is_file():
                issue(errors, "missing_source_image", image_path, "referenced image does not exist")
            else:
                referenced_images.add(image_path)
                try:
                    dimensions = image_size(image_path)
                except OSError as exc:
                    dimensions = None
                    issue(errors, "unreadable_image", image_path, str(exc))
                if dimensions is None:
                    issue(warnings, "unknown_dimensions", image_path, "image dimensions could not be read")
                else:
                    record["width"], record["height"] = dimensions

        elements = payload.get("elements")
        valid_element_count = 0
        element_names: list[str] = []
        if not isinstance(elements, list):
            issue(errors, "invalid_elements", json_path, "elements must be a list")
        else:
            for index, element in enumerate(elements):
                if not isinstance(element, dict):
                    issue(errors, "invalid_element", json_path, f"elements[{index}] must be an object")
                    continue
                name = element.get("name")
                value = element.get("value")
                if not isinstance(name, str) or not name.strip():
                    issue(errors, "invalid_element_name", json_path, f"elements[{index}].name is empty")
                    continue
                if not isinstance(value, str) or not value.strip():
                    issue(errors, "invalid_element_value", json_path, f"elements[{index}].value is empty")
                    continue
                element_names.append(name.strip())
                valid_element_count += 1
            duplicate_names = sorted(name for name, count in Counter(element_names).items() if count > 1)
            if duplicate_names:
                issue(warnings, "duplicate_element_names", json_path, ", ".join(duplicate_names))
        record["element_count"] = valid_element_count
        record["valid"] = not any(item["path"] == relative(json_path, root) for item in errors)
        records.append(record)

    for sample_id, paths in sorted(sample_ids.items()):
        if len(paths) > 1:
            for path in paths:
                issue(errors, "duplicate_sample_id", root / path, f"sample_id {sample_id!r} appears {len(paths)} times")

    hashes: defaultdict[str, list[Path]] = defaultdict(list)
    for image_path in sorted(all_images):
        try:
            hashes[sha256_file(image_path)].append(image_path)
        except OSError as exc:
            issue(errors, "unreadable_image", image_path, str(exc))

    duplicate_groups = []
    for digest, paths in sorted(hashes.items()):
        if len(paths) > 1:
            group = [relative(path, root) for path in paths]
            duplicate_groups.append({"sha256": digest, "paths": group})
            for path in paths:
                issue(warnings, "duplicate_image", path, f"same bytes as {len(paths) - 1} other image(s)")

    for orphan in sorted(all_images - referenced_images):
        issue(warnings, "orphan_image", orphan, "image is not referenced by a sample JSON")

    widths = [record["width"] for record in records if "width" in record]
    heights = [record["height"] for record in records if "height" in record]
    result = {
        "dataset_root": str(root),
        "summary": {
            "json_files": len(json_files),
            "image_files": len(all_images),
            "referenced_images": len(referenced_images),
            "valid_samples": sum(1 for record in records if record.get("valid")),
            "element_count": sum(record.get("element_count", 0) for record in records),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "duplicate_image_groups": len(duplicate_groups),
            "width_range": [min(widths), max(widths)] if widths else None,
            "height_range": [min(heights), max(heights)] if heights else None,
        },
        "errors": errors,
        "warnings": warnings,
        "duplicate_images": duplicate_groups,
        "samples": records,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="Dataset root to audit")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"dataset root is not a directory: {root}")
    output = args.output.resolve() if args.output else None
    result = audit(root, output)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(json.dumps(result["summary"], ensure_ascii=False))
        print(f"report={output}")
    else:
        print(rendered)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
