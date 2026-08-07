"""Focused tests for the retained SN-7 dataset workflow."""

import json
from argparse import Namespace
from pathlib import Path

import pytest
from openpyxl import load_workbook
from PIL import Image

from vlm.scripts.import_sn7_design_sheet_dataset import import_image
from vlm.scripts.package_sn7_dataset import find_multiview_file, package_dataset
from vlm.scripts.data.assign_merchandise_categories import (
    CATEGORIES,
    apply_balanced_assignment,
    balanced_target_counts,
    discover_generated,
)
from vlm.scripts.extract_atomic_rules import normalize_rules, parse_json
from vlm.scripts.utils.atomic_rule_xlsx import write_atomic_rules_xlsx
from vlm.scripts.utils.sync_generated_annotation_xlsx import sync_sample


def test_parse_json_accepts_fenced_model_output():
    parsed = parse_json('```json\n{"code":"1","atomic_rules":[]}\n```')
    assert parsed["code"] == "1"


def test_normalize_rules_deduplicates_and_keeps_scalar_values(tmp_path: Path):
    image = tmp_path / "1.jpg"
    image.write_bytes(b"image")
    result = normalize_rules(
        {"atomic_rules": [
            {"id": "Hair Color", "location": "head", "value": "orange"},
            {"id": "hair_color", "location": "head", "value": "duplicate"},
            {"id": "has_glasses", "location": "head", "value": True},
        ]},
        "1",
        image,
        "qwen3-vl-plus",
        "prompt",
        0.1,
    )
    assert [rule["id"] for rule in result["atomic_rules"]] == ["hair_color", "has_glasses"]
    assert result["atomic_rules"][0]["location"] == "head"
    assert result["atomic_rules"][1]["value"] is True


def test_head_only_xlsx_filters_body_rules(tmp_path: Path):
    json_path = tmp_path / "atomic_rules.json"
    json_path.write_text(json.dumps({
        "code": "123",
        "atomic_rules": [
            {"id": "hair_color", "value": "orange"},
            {"id": "top_color", "value": "blue"},
        ],
    }), encoding="utf-8")
    output_path = tmp_path / "123.xlsx"
    write_atomic_rules_xlsx(
        json_path,
        output_path,
        "head_key_chain",
        {"hair_color": "head", "top_color": "body"},
    )
    sheet = load_workbook(output_path, read_only=True).active
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0] == (
        "sample_id", "rule_id", "location", "value", "front_visible",
        "front_status", "side_visible", "side_status", "back_visible",
        "back_status", "note",
    )
    assert len(rows) == 2
    assert rows[1][1:4] == ("hair_color", "head", "orange")


def test_xlsx_status_dropdown_includes_wrong_prosition(tmp_path: Path):
    json_path = tmp_path / "atomic_rules.json"
    json_path.write_text(json.dumps({"code": "123", "atomic_rules": []}), encoding="utf-8")
    output_path = tmp_path / "123.xlsx"
    write_atomic_rules_xlsx(json_path, output_path, "plush")
    workbook = load_workbook(output_path, read_only=False)
    formulas = {validation.formula1 for validation in workbook.active.data_validations.dataValidation}
    workbook.close()

    assert any("wrong_prosition" in formula for formula in formulas)


def test_sync_generated_sample_writes_xlsx_after_image_download(tmp_path: Path):
    sample_dir = tmp_path / "plush" / "123"
    sample_dir.mkdir(parents=True)
    (sample_dir / "123_atomic_rules.json").write_text(json.dumps({
        "code": "123",
        "atomic_rules": [{"id": "hair_color", "location": "head", "value": "red"}],
    }), encoding="utf-8")
    (sample_dir / "123_plush.png").write_bytes(b"image")

    assert sync_sample(sample_dir, "plush", "plush") is True
    assert (sample_dir / "123.xlsx").exists()
    assert sync_sample(sample_dir, "plush", "plush") is False


def test_position_rules_keep_emitted_annotator_view(tmp_path: Path):
    json_path = tmp_path / "atomic_rules.json"
    json_path.write_text(json.dumps({
        "code": "123",
        "atomic_rules": [
            {"id": "horn_position", "location": "body", "value": "right"},
            {"id": "armband_position", "location": "body", "value": "left_arm"},
            {"id": "wing_position", "location": "body", "value": "both_sides"},
        ],
    }), encoding="utf-8")
    output_path = tmp_path / "123.xlsx"
    write_atomic_rules_xlsx(
        json_path,
        output_path,
        "plush",
        {},
    )
    sheet = load_workbook(output_path, read_only=True).active
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[1][1:4] == ("horn_position", "body", "right")
    assert rows[2][1:4] == ("armband_position", "body", "left_arm")
    assert rows[3][1:4] == ("wing_position", "body", "both_sides")


def test_balanced_assignment_preserves_existing_and_fills_targets():
    rows = []
    targets = balanced_target_counts(12)
    for index in range(12):
        existing = "head_key_chain" if index < targets["head_key_chain"] else ""
        row = {
            "sample_id": f"{index:03d}",
            "already_generated_category": existing,
            "primary_category": existing or "head_key_chain",
            "assignment_source": "existing_generated_output" if existing else "rule_score",
            "candidate_categories": "|".join(CATEGORIES),
            "primary_score": 100,
        }
        for category in CATEGORIES:
            row[f"score_{category}"] = 100 if category == "head_key_chain" else 10
        rows.append(row)
    apply_balanced_assignment(rows)
    counts = {category: sum(row["primary_category"] == category for row in rows) for category in CATEGORIES}
    assert counts == targets
    assert all(row["primary_category"] == "head_key_chain" for row in rows[:targets["head_key_chain"]])


def test_find_multiview_file_prefers_canonical_category_suffix(tmp_path: Path):
    sample_dir = tmp_path / "dataset_figurine" / "123"
    sample_dir.mkdir(parents=True)
    fallback = sample_dir / "123_figurine_current_prompt_rerun.png"
    canonical = sample_dir / "123_figurine.png"
    fallback.write_bytes(b"fallback")
    canonical.write_bytes(b"canonical")
    assert find_multiview_file(tmp_path, "dataset_figurine", "123") == canonical


def test_import_image_does_not_replace_valid_target_with_corrupt_input(
    tmp_path: Path,
):
    source = tmp_path / "source.png"
    source.write_bytes(b"not-an-image")
    target = tmp_path / "target.png"
    Image.new("RGB", (8, 8), "white").save(target)
    original = target.read_bytes()

    with pytest.raises(Exception):
        import_image(source, target)

    assert target.read_bytes() == original
    assert not target.with_suffix(".png.part").exists()


def test_incomplete_package_preserves_previous_deliverable(tmp_path: Path):
    root = tmp_path / "dataset"
    image = root / "image" / "sample.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), "white").save(image)
    (root / "manifest.csv").write_text(
        "post_id,image_path\nsample,image/sample.png\n", encoding="utf-8"
    )
    assignment = root / "assignments.csv"
    assignment.write_text(
        "sample_id,primary_category\nsample,plush\n", encoding="utf-8"
    )
    package_root = root / "deliverables"
    package_root.mkdir()
    sentinel = package_root / "previous.txt"
    sentinel.write_text("previous", encoding="utf-8")
    args = Namespace(
        root=root,
        manifest=None,
        assignment_csv=assignment,
        generated_root=None,
        package_root=package_root,
        overwrite=True,
        allow_incomplete=False,
    )

    summary = package_dataset(args)

    assert summary["incomplete_count"] == 1
    assert summary["package_replaced"] is False
    assert sentinel.read_text(encoding="utf-8") == "previous"
    assert (root / "reports" / "package_validation" / "incomplete_samples.csv").is_file()


def test_category_assignment_ignores_incomplete_generated_directory(tmp_path: Path):
    sample_dir = tmp_path / "generated" / "plush" / "sample"
    sample_dir.mkdir(parents=True)
    (sample_dir / "sample_atomic_rules.json").write_text("{}", encoding="utf-8")

    assert discover_generated(tmp_path) == {}
