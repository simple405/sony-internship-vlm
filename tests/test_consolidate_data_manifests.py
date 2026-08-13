"""Regression tests for the consolidated local dataset manifest."""

from __future__ import annotations

import csv
import hashlib
import json
from argparse import Namespace
from pathlib import Path

from vlm.scripts.consolidate_data_manifests import consolidate


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_consolidation_merges_status_and_is_rerunnable(tmp_path: Path):
    data_root = tmp_path / "data"
    manifest = data_root / "manifest.csv"
    legacy_image = data_root / "safebooru_character_sheet" / "1.jpg"
    legacy_image.parent.mkdir(parents=True)
    legacy_image.write_bytes(b"legacy")
    legacy_hash = hashlib.sha256(legacy_image.read_bytes()).hexdigest()
    write_csv(
        manifest,
        [{
            "post_id": "cs_1",
            "image_path": "C:/old/batch/cs_1.jpg",
            "source_dataset": "cs",
            "source_path": "cs/1.jpg",
            "original_file_name": "1.jpg",
            "sha256": legacy_hash,
            "width": "10",
            "height": "10",
            "extension": ".jpg",
        }],
    )

    sn7_root = data_root / "design_sheet_10610"
    sn7_image = sn7_root / "image" / "ta_2.jpg"
    sn7_image.parent.mkdir(parents=True)
    sn7_image.write_bytes(b"sn7")
    write_csv(
        sn7_root / "manifest.csv",
        [{
            "post_id": "ta_2",
            "sample_id": "ta_2",
            "image_path": "image/ta_2.jpg",
            "source_dataset": "ta",
            "source_path": "ta/2.jpg",
            "original_file_name": "2.jpg",
            "sha256": hashlib.sha256(sn7_image.read_bytes()).hexdigest(),
            "width": "20",
            "height": "20",
            "extension": ".jpg",
        }],
    )
    write_csv(
        sn7_root / "category_assignment.csv",
        [{
            "sample_id": "ta_2",
            "primary_category": "plush",
            "assignment_source": "balanced",
            "reason": "fixture",
        }],
    )
    error_path = sn7_root / "atomic_rules" / "ta_2" / "error.json"
    error_path.parent.mkdir(parents=True)
    error_path.write_text(
        json.dumps({
            "error_type": "ValueError",
            "error": "black_white_line_art: fixture",
            "rejection_type": "content_policy_or_provider_rejection",
        }),
        encoding="utf-8",
    )
    args = Namespace(manifest=manifest, sn7_root=sn7_root, remove_merged_files=True)

    first = consolidate(args)
    rows = read_csv(manifest)
    sn7 = next(row for row in rows if row["sample_id"] == "ta_2")
    assert first["rows"] == 2
    assert first["atomic_errors"] == 1
    assert sn7["primary_category"] == "plush"
    assert sn7["atomic_rules_used"] == "true"
    assert sn7["atomic_rules_status"] == "error"
    assert sn7["atomic_rules_error_reason"] == "black_white_line_art: fixture"
    assert not (sn7_root / "manifest.csv").exists()
    assert not (sn7_root / "category_assignment.csv").exists()

    second = consolidate(args)
    assert second["rows"] == 2
    assert read_csv(manifest) == rows


def test_consolidation_keeps_manifest_inside_sn7_root(tmp_path: Path):
    data_root = tmp_path / "data"
    sn7_root = data_root / "sn7_data_generation"
    manifest = sn7_root / "manifest.csv"
    image = sn7_root / "image" / "cs_1.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"sn7")
    write_csv(
        manifest,
        [{
            "dataset_id": "design_sheet_10610",
            "post_id": "cs_1",
            "sample_id": "cs_1",
            "image_path": "design_sheet_10610/image/cs_1.jpg",
            "data_status": "available",
            "source_dataset": "cs",
            "source_path": "cs/1.jpg",
            "original_file_name": "1.jpg",
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "width": "10",
            "height": "10",
            "extension": ".jpg",
        }],
    )

    result = consolidate(
        Namespace(manifest=manifest, sn7_root=sn7_root, remove_merged_files=True)
    )

    assert result["rows"] == 1
    assert manifest.is_file()
    assert read_csv(manifest)[0]["image_path"] == "sn7_data_generation/image/cs_1.jpg"
