"""Package SN-7 source, atomic rules, multiview output, and review workbook."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from vlm.scripts._dataset_manifest import (
    CONSOLIDATED_MANIFEST,
    SN7_DATASET_ROOT,
    SN7_DATASET_ID,
    index_manifest_rows,
    resolve_manifest_image,
)
from vlm.scripts._preservation import publish_staged_directory
from vlm.scripts._sn7_artifacts import (
    CATEGORIES,
    CATEGORY_OUTPUT_SUFFIXES as OUTPUT_SUFFIXES,
    IMAGE_SUFFIXES,
    find_category_generated_output,
)
from vlm.scripts._validation import (
    require_within,
    validate_path_component,
)
from vlm.scripts.utils.atomic_rule_xlsx import write_atomic_rules_xlsx


DEFAULT_ROOT = SN7_DATASET_ROOT
DEFAULT_ASSIGNMENT = (
    DEFAULT_ROOT
    / "reports"
    / "merchandise_category_assignment"
    / "merchandise_category_assignments.csv"
)
DEFAULT_PACKAGE = DEFAULT_ROOT / "deliverables"
def parse_args() -> argparse.Namespace:
    """Parse SN-7 packager arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--assignment-csv", type=Path, default=None)
    parser.add_argument("--generated-root", type=Path, default=None)
    parser.add_argument("--package-root", type=Path, default=None)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Publish a new package and archive the existing package root.",
    )
    parser.add_argument("--allow-incomplete", action="store_true")
    return parser.parse_args()


def _read_csv(path: Path, id_field: str) -> dict[str, dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sample_id = validate_path_component(row.get(id_field, ""), "sample ID")
            if sample_id in rows:
                raise ValueError(f"Duplicate sample ID in {path}: {sample_id}")
            rows[sample_id] = dict(row)
    return rows


def find_atomic_file(root: Path, sample_id: str) -> Path | None:
    """Find the canonical or historical atomic-rules filename for one sample."""
    sample_dir = root / sample_id
    if (sample_dir / "error.json").is_file():
        return None
    for name in ("atomic_rules.json", f"{sample_id}_atomic_rules.json"):
        candidate = sample_dir / name
        if candidate.is_file():
            return candidate
    return None


def find_multiview_file(root: Path, category: str, sample_id: str) -> Path | None:
    """Find the valid canonical generated image for one category assignment."""
    return find_category_generated_output(root, category, sample_id)


def _copy_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".part")
    try:
        shutil.copy2(source, temp)
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()


def _write_package_rules(source: Path, target: Path, sample_id: str) -> None:
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    rules: list[dict[str, Any]] = []
    for rule in payload.get("atomic_rules", []):
        location = str(rule.get("location", "")).strip() if isinstance(rule, dict) else ""
        if location in {"头部", "身体"}:
            canonical_location = {"头部": "head", "身体": "body"}[location]
        else:
            canonical_location = location
        if not isinstance(rule, dict) or canonical_location not in {"head", "body"}:
            raise ValueError(f"Invalid atomic rule for {sample_id}: {rule!r}")
        rules.append(
            {
                "id": str(rule.get("id", "")),
                "location": location,
                "value": rule.get("value"),
            }
        )
    temp = target.with_suffix(target.suffix + ".tmp")
    try:
        temp.write_text(
            json.dumps(
                {"code": sample_id, "atomic_rules": rules},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()


def _copy_as_png(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".png.part")
    try:
        with Image.open(source) as image:
            image.load()
            image.convert("RGBA" if "A" in image.getbands() else "RGB").save(
                temp, format="PNG"
            )
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON without exposing a partially written destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def _write_incomplete_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write the incomplete-sample report atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        with temp.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["sample_id", "missing"])
            writer.writeheader()
            writer.writerows(rows)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def package_dataset(args: argparse.Namespace) -> dict[str, Any]:
    """Build deterministic SN-7 deliverable folders and return a summary."""
    root = args.root.resolve()
    if args.manifest:
        manifest_path = args.manifest.resolve()
    elif root == DEFAULT_ROOT.resolve() and CONSOLIDATED_MANIFEST.is_file():
        manifest_path = CONSOLIDATED_MANIFEST.resolve()
    else:
        manifest_path = root / "manifest.csv"
    assignment_path = (args.assignment_csv or root / DEFAULT_ASSIGNMENT.relative_to(DEFAULT_ROOT)).resolve()
    generated_root = (args.generated_root or root / "generated").resolve()
    package_root = require_within(
        root,
        (args.package_root or root / "deliverables").resolve(),
        "package root",
    )
    atomic_root = root / "atomic_rules"

    if package_root.exists() and not args.overwrite:
        raise FileExistsError(
            f"Package root already exists: {package_root}. Pass --overwrite to "
            "archive it and publish a replacement."
        )

    manifest = index_manifest_rows(
        manifest_path,
        dataset_id=(
            SN7_DATASET_ID
            if manifest_path == CONSOLIDATED_MANIFEST.resolve()
            else None
        ),
    )
    assignments = _read_csv(assignment_path, "sample_id")
    if set(manifest) != set(assignments):
        missing_assignment = sorted(set(manifest) - set(assignments))
        unknown_assignment = sorted(set(assignments) - set(manifest))
        raise ValueError(
            "Manifest/assignment sample IDs differ: "
            f"missing={missing_assignment[:10]}, unknown={unknown_assignment[:10]}"
        )

    package_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{package_root.name}.", dir=package_root.parent)
    )
    published = False
    try:
        packaged: list[str] = []
        incomplete: list[dict[str, str]] = []
        for sample_id in sorted(manifest):
            category = assignments[sample_id].get("primary_category", "")
            if category not in CATEGORIES:
                raise ValueError(f"Unsupported category for {sample_id}: {category!r}")
            source_image = resolve_manifest_image(manifest_path, manifest[sample_id])
            atomic_file = find_atomic_file(atomic_root, sample_id)
            multiview_file = find_multiview_file(generated_root, category, sample_id)
            missing = [
                name
                for name, path in (
                    ("source_image", source_image if source_image.is_file() else None),
                    ("atomic_rules", atomic_file),
                    ("multiview", multiview_file),
                )
                if path is None
            ]
            if missing:
                incomplete.append(
                    {"sample_id": sample_id, "missing": "|".join(missing)}
                )
                continue

            assert atomic_file is not None and multiview_file is not None
            sample_dir = staging / category / sample_id
            original_target = sample_dir / f"2d_original{source_image.suffix.lower()}"
            rules_target = sample_dir / "atomic_rules.json"
            multiview_target = sample_dir / "multiview_design.png"
            workbook_target = sample_dir / f"{sample_id}.xlsx"
            _copy_atomic(source_image, original_target)
            _write_package_rules(atomic_file, rules_target, sample_id)
            _copy_as_png(multiview_file, multiview_target)
            write_atomic_rules_xlsx(rules_target, workbook_target, category)
            packaged.append(sample_id)

        summary = {
            "schema_version": "sn7_package.v1",
            "manifest_count": len(manifest),
            "packaged_count": len(packaged),
            "incomplete_count": len(incomplete),
            "package_root": str(package_root),
            "package_replaced": not incomplete or bool(args.allow_incomplete),
        }
        report_dir = staging / "_reports"
        _write_incomplete_csv(report_dir / "incomplete_samples.csv", incomplete)
        _write_json_atomic(report_dir / "package_summary.json", summary)

        if incomplete and not args.allow_incomplete:
            validation_dir = root / "reports" / "package_validation"
            _write_incomplete_csv(
                validation_dir / "incomplete_samples.csv", incomplete
            )
            _write_json_atomic(validation_dir / "package_summary.json", summary)
            return summary

        publish_staged_directory(staging, package_root)
        published = True
        return summary
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging)


def main() -> None:
    """Run the SN-7 packager."""
    args = parse_args()
    summary = package_dataset(args)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if summary["incomplete_count"] and not args.allow_incomplete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
