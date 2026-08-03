"""Build the six-category Safebooru trial package from extracted atomic rules.

The script is intentionally local and deterministic after the API extraction step:
it reads the crawler manifest and per-sample atomic_rules.json files, copies each
source image into the reference-style package, tags rules as head/body, and writes
the annotation workbook with the same columns as multi_view试标数据集_rev.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import requests

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from vlm.scripts.data.assign_merchandise_categories import (
    CATEGORIES,
    FULL_BODY_CATEGORIES,
    HEAD_ONLY_CATEGORIES,
    candidate_categories,
    key_tags,
    score_row,
)
from vlm.scripts.utils.atomic_rule_xlsx import add_annotation_dropdowns, normalize_position_value
from vlm.scripts._paths import API_ENV_FILE, load_api_env

DEFAULT_ROOT = Path("vlm/data/safebooru_2d")
DEFAULT_PACKAGE = DEFAULT_ROOT / "multi_view试标数据集_new"
DEFAULT_GENERATED = DEFAULT_ROOT / "generated"
REFERENCE_ROOT = Path("vlm/data/multi_view试标数据集_rev")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
DESIGN_OUTPUT_SUFFIXES = {
    "head_key_chain": "head_keychain",
    "cake_roll": "cake_roll",
    "backpack": "backpack",
    "plush": "plush",
    "dataset_QSitFigures": "SitFigures",
    "dataset_figurine": "figurine",
}
XLSX_COLUMNS = [
    "sample_id",
    "rule_id",
    "location",
    "value",
    "front_visible",
    "front_status",
    "side_visible",
    "side_status",
    "back_visible",
    "back_status",
    "note",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Safebooru multi-view trial package.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--atomic-root", type=Path, default=None)
    parser.add_argument("--package-root", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--generated-root", type=Path, default=DEFAULT_GENERATED)
    parser.add_argument("--assignment-csv", type=Path, default=None)
    parser.add_argument("--reference-root", type=Path, default=REFERENCE_ROOT)
    parser.add_argument("--contact-sheet-limit", type=int, default=40)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--env-file", type=Path, default=API_ENV_FILE)
    parser.add_argument("--model", default="qwen3-max")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--skip-qwen-location", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Rewrite package files from the current source assets.")
    parser.add_argument(
        "--sync-generated",
        action="store_true",
        help="Synchronize generated sample rule snapshots and workbooks from the current atomic rules.",
    )
    return parser.parse_args()


def read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle) if row.get("post_id")]


def read_assignment_csv(path: Path, manifest_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    manifest_by_id = {str(row["post_id"]): row for row in manifest_rows}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle) if row.get("sample_id")]
    assignments: list[dict[str, Any]] = []
    for row in rows:
        sample_id = str(row["sample_id"])
        manifest = manifest_by_id.get(sample_id, {})
        assignments.append({
            "sample_id": sample_id,
            "primary_category": row.get("primary_category", ""),
            "candidate_categories": row.get("candidate_categories", ""),
            "assignment_source": row.get("assignment_source", "assignment_csv"),
            "review_required": row.get("review_required", "false"),
            "image_path": row.get("image_path") or manifest.get("image_path", ""),
            "crawl_label": row.get("crawl_label") or manifest.get("crawl_label", ""),
            "reason": row.get("reason", ""),
            "key_tags": row.get("key_tags", ""),
            "primary_score": row.get("primary_score", ""),
            **{f"score_{category}": row.get(f"score_{category}", "") for category in CATEGORIES},
        })
    return assignments


def discover_reference_rule_ids(reference_root: Path) -> set[str]:
    rule_ids: set[str] = set()
    if not reference_root.exists():
        return rule_ids
    for path in reference_root.rglob("atomic_rules.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for rule in data.get("atomic_rules", []):
            if isinstance(rule, dict) and rule.get("id"):
                rule_ids.add(str(rule["id"]))
    return rule_ids


def find_atomic_file(atomic_root: Path, sample_id: str) -> Path | None:
    current = atomic_root / sample_id / "atomic_rules.json"
    if current.exists():
        return current
    legacy = atomic_root / sample_id / f"{sample_id}_atomic_rules.json"
    return legacy if legacy.exists() else None


def find_multiview_file(generated_root: Path, category: str, sample_id: str) -> Path | None:
    sample_dirs = [
        generated_root / category / sample_id,
        generated_root / "runninghub" / category / sample_id,
    ]
    output_suffix = DESIGN_OUTPUT_SUFFIXES.get(category, category)
    for sample_dir in sample_dirs:
        if not sample_dir.exists():
            continue
        for suffix in IMAGE_SUFFIXES:
            candidate = sample_dir / f"{sample_id}_{output_suffix}{suffix}"
            if candidate.exists():
                return candidate
        for suffix in IMAGE_SUFFIXES:
            candidate = sample_dir / f"multiview_design{suffix}"
            if candidate.exists():
                return candidate
        image_candidates = sorted(
            path for path in sample_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in IMAGE_SUFFIXES
            and "original" not in path.name.lower()
            and "reference" not in path.name.lower()
        )
        if image_candidates:
            return image_candidates[0]
    return None


def copy_png(source: Path, target: Path) -> None:
    from PIL import Image

    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.save(target, format="PNG")


def load_location_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(key): value for key, value in data.items() if value in {"head", "body"}}


def classify_rule_id(rule_id: str) -> str | None:
    """Classify unambiguous IDs locally; return None for ambiguous IDs."""
    rid = rule_id.lower()
    head_prefixes = (
        "hair_", "eye_", "glasses_", "headwear_", "headband_",
        "head_accessory", "head_ribbon", "horn_", "bangs_", "mouth_",
        "ponytail_", "head_",
    )
    head_exact = {
        "expression", "skin_tone", "skin_color", "has_ahoge", "has_wink",
        "has_bangs", "has_pointed_ears", "has_ponytail", "hair_over_eye",
        "has_hair_between_eyes",
    }
    if rid in head_exact or rid.startswith(head_prefixes):
        return "head"
    if any(token in rid for token in ("hair_ribbon", "hair_ornament", "hair_accessory")):
        return "head"
    body_tokens = (
        "top_", "bottom_", "dress_", "skirt_", "pants_", "sleeve_", "collar_",
        "legwear_", "footwear_", "shoe_", "shoes_", "boot_", "glove_", "belt_",
        "choker_", "necklace_", "bracelet_", "wrist_", "ankle_", "bag_", "weapon_",
        "wing_", "tail_", "handheld_", "holding_", "body_", "clothing_", "outfit_",
        "upper_", "lower_", "sash_", "cape_", "armor_", "jacket_", "coat_",
    )
    if rid.startswith(body_tokens) or rid in {"gender", "has_bag", "has_weapon", "has_wings"}:
        return "body"
    return None


def qwen_classify_unknown(
    rule_ids: list[str], *, api_key: str, base_url: str, model: str, timeout: int = 180
) -> dict[str, str]:
    if not rule_ids:
        return {}
    prompt = (
        "Classify each anime character attribute rule ID as exactly 'head' or 'body'. "
        "head means on or above the neck, including hair, eyes, face, glasses, hats, "
        "head accessories, horns, and ears. body means clothing, footwear, neckwear, "
        "jewelry below the neck, bags, weapons, wings, tails, and body structure. "
        "Return only a JSON object mapping every input ID to head or body.\n\n"
        + "\n".join(rule_ids)
    )
    response = requests.post(
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    raw = response.json()["choices"][0]["message"]["content"]
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Qwen location response must be a JSON object")
    result = {}
    for rule_id in rule_ids:
        value = str(parsed.get(rule_id, "")).strip().lower()
        if value not in {"head", "body"}:
            raise ValueError(f"Qwen did not classify rule_id: {rule_id}")
        result[rule_id] = value
    return result


def ensure_location_map(
    atomic_files: list[Path],
    *,
    reference_root: Path,
    existing_path: Path,
    qwen_config: dict[str, str] | None = None,
    skip_qwen: bool = False,
) -> tuple[dict[str, str], list[str]]:
    location_map = load_location_map(existing_path)
    ids = sorted(
        {
            str(rule["id"])
            for path in atomic_files
            for rule in json.loads(path.read_text(encoding="utf-8")).get("atomic_rules", [])
            if isinstance(rule, dict) and rule.get("id")
        }
    )
    known_reference_ids = discover_reference_rule_ids(reference_root)
    unknown_ids: list[str] = []
    ambiguous_ids: list[str] = []
    for rule_id in ids:
        if rule_id not in location_map:
            local = classify_rule_id(rule_id)
            if local:
                location_map[rule_id] = local
            else:
                ambiguous_ids.append(rule_id)
        if rule_id not in known_reference_ids:
            unknown_ids.append(rule_id)
    if ambiguous_ids and not skip_qwen and qwen_config and qwen_config.get("api_key"):
        location_map.update(qwen_classify_unknown(ambiguous_ids, **qwen_config))
    for rule_id in ambiguous_ids:
        location_map.setdefault(rule_id, "body")
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(json.dumps(dict(sorted(location_map.items())), ensure_ascii=False, indent=2), encoding="utf-8")
    return location_map, unknown_ids


def write_xlsx(json_path: Path, output_path: Path, location_map: dict[str, str], category: str) -> int:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    data = json.loads(json_path.read_text(encoding="utf-8"))
    sample_id = str(data.get("code") or data.get("sample_id") or json_path.parent.name)
    rules = data.get("atomic_rules", [])
    if category in HEAD_ONLY_CATEGORIES:
        rules = [
            rule
            for rule in rules
            if rule.get("location") in {"head", "body"}
            and rule["location"] == "head"
            or rule.get("location") not in {"head", "body"}
            and location_map.get(str(rule.get("id")), "body") == "head"
        ]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    for column, name in enumerate(XLSX_COLUMNS, start=1):
        cell = sheet.cell(row=1, column=column, value=name)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9D9D9")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_number, rule in enumerate(rules, start=2):
        rule_id = str(rule.get("id", ""))
        value = rule.get("value", "")
        display_value = normalize_position_value(rule_id, str(value) if isinstance(value, bool) else value)
        location = rule.get("location") if rule.get("location") in {"head", "body"} else location_map.get(rule_id, "body")
        row = [sample_id, rule_id, location, display_value]
        row.extend([""] * (len(XLSX_COLUMNS) - len(row)))
        for column, value in enumerate(row, start=1):
            sheet.cell(row=row_number, column=column, value=value)
    add_annotation_dropdowns(sheet)
    for column_cells in sheet.columns:
        width = max((len(str(cell.value or "")) for cell in column_cells), default=0)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(width + 4, 40)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    return len(rules)


def write_package_atomic_rules(source_json: Path, target_json: Path, sample_id: str) -> None:
    """Write the reference dataset's compact package JSON shape."""
    data = json.loads(source_json.read_text(encoding="utf-8"))
    rules = []
    for rule in data.get("atomic_rules", []):
        if not isinstance(rule, dict):
            continue
        location = rule.get("location")
        if location not in {"head", "body"}:
            raise ValueError(f"Package rule {rule.get('id')!r} is missing location")
        rules.append({"id": str(rule.get("id", "")), "location": location, "value": rule.get("value")})
    target_json.write_text(
        json.dumps({"code": sample_id, "atomic_rules": rules}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def sync_generated_artifacts(
    assignments: list[dict[str, Any]], atomic_root: Path, generated_root: Path, location_map: dict[str, str]
) -> int:
    """Refresh generated sample rule snapshots and their annotation workbooks in place."""
    synced = 0
    for assignment in assignments:
        sample_id = str(assignment["sample_id"])
        category = str(assignment["primary_category"])
        source_json = find_atomic_file(atomic_root, sample_id)
        sample_dir = generated_root / category / sample_id
        if source_json is None or not sample_dir.is_dir():
            continue
        snapshot_path = sample_dir / f"{sample_id}_atomic_rules.json"
        shutil.copy2(source_json, snapshot_path)
        write_xlsx(snapshot_path, sample_dir / f"{sample_id}.xlsx", location_map, category)
        synced += 1
    return synced


def assign_categories(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for row in rows:
        scores, reasons = score_row(row)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        primary_category = ranked[0][0]
        candidates = candidate_categories(scores)
        margin = ranked[0][1] - ranked[1][1] if len(ranked) > 1 else ranked[0][1]
        review = margin < 10 or ranked[0][1] <= 0
        assignments.append({
            "sample_id": str(row["post_id"]),
            "primary_category": primary_category,
            "candidate_categories": "|".join(candidates),
            "assignment_source": "rule_score",
            "review_required": str(review).lower(),
            "image_path": row.get("image_path", ""),
            "crawl_label": row.get("crawl_label", ""),
            "reason": ";".join(reasons),
            "key_tags": key_tags(row),
            "primary_score": ranked[0][1],
            **{f"score_{category}": scores[category] for category in CATEGORIES},
        })
    return assignments


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def build_package(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root
    manifest_path = args.manifest or root / "manifest.csv"
    atomic_root = args.atomic_root or root / "atomic_rules"
    location_path = args.package_root / "rule_location_tags.json"
    rows = read_manifest(manifest_path)
    if args.assignment_csv:
        assignments = read_assignment_csv(args.assignment_csv, rows)
    else:
        assignments = assign_categories(rows)
    report_columns = [
        "sample_id", "primary_category", "candidate_categories", "assignment_source",
        "review_required", "image_path", "crawl_label", "reason", "key_tags",
        "primary_score", *(f"score_{category}" for category in CATEGORIES),
    ]
    write_csv(args.package_root / "category_assignment.csv", assignments, report_columns)
    write_csv(
        args.package_root / "category_review_queue.csv",
        [row for row in assignments if row["review_required"] == "true"],
        report_columns,
    )

    atomic_files = sorted(
        path for path in atomic_root.rglob("*.json")
        if path.name == "atomic_rules.json" or path.name.endswith("_atomic_rules.json")
    )
    load_api_env(args.env_file)
    qwen_config = {
        "api_key": args.api_key or os.environ.get("QWEN_API_KEY", ""),
        "base_url": args.base_url or os.environ.get("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "model": args.model,
    }
    if not args.dry_run and not args.skip_qwen_location and not qwen_config["api_key"]:
        raise SystemExit("QWEN_API_KEY is required to classify ambiguous rule IDs; use --skip-qwen-location to defer it")
    location_map, unknown_ids = ensure_location_map(
        atomic_files,
        reference_root=args.reference_root,
        existing_path=location_path,
        qwen_config=qwen_config,
        skip_qwen=args.skip_qwen_location or args.dry_run,
    )
    (args.package_root / "unknown_rule_ids.json").write_text(
        json.dumps(unknown_ids, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    generated_sync_count = 0
    if args.sync_generated and not args.dry_run:
        generated_sync_count = sync_generated_artifacts(assignments, atomic_root, args.generated_root, location_map)

    copied = 0
    workbook_count = 0
    multiview_count = 0
    missing_multiview: list[str] = []
    for assignment in assignments:
        sample_id = assignment["sample_id"]
        category = assignment["primary_category"]
        image_path = Path(assignment["image_path"])
        if not image_path.is_absolute():
            image_path = Path.cwd() / image_path
        if not image_path.exists():
            image_path = root / "image" / image_path.name
        source_json = find_atomic_file(atomic_root, sample_id)
        if source_json is None:
            continue
        sample_dir = args.package_root / category / sample_id
        target_image = sample_dir / f"2d_original{image_path.suffix.lower()}"
        target_json = sample_dir / "atomic_rules.json"
        target_xlsx = sample_dir / f"{sample_id}.xlsx"
        target_multiview = sample_dir / "multiview_design.png"
        source_multiview = find_multiview_file(args.generated_root, category, sample_id)
        if not args.dry_run:
            sample_dir.mkdir(parents=True, exist_ok=True)
            if image_path.exists() and (args.overwrite or not target_image.exists()):
                shutil.copy2(image_path, target_image)
            if args.overwrite or not target_json.exists():
                write_package_atomic_rules(source_json, target_json, sample_id)
            write_xlsx(target_json, target_xlsx, location_map, category)
            if source_multiview and (args.overwrite or not target_multiview.exists()):
                copy_png(source_multiview, target_multiview)
        copied += 1
        workbook_count += 1
        if source_multiview:
            multiview_count += 1
        else:
            missing_multiview.append(sample_id)
    return {
        "assignment_count": len(assignments),
        "packaged_count": copied,
        "workbook_count": workbook_count,
        "multiview_count": multiview_count,
        "missing_multiview_count": len(missing_multiview),
        "unknown_rule_count": len(unknown_ids),
        "generated_sync_count": generated_sync_count,
        "categories": CATEGORIES,
    }


def main() -> None:
    args = parse_args()
    result = build_package(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
