import csv
import json
from pathlib import Path

import pytest
from PIL import Image

from vlm.scripts.generate.generate_paired_front_view import (
    Sample,
    process_one,
    read_manifest,
    select_samples,
)


def _image(path: Path, size: tuple[int, int] = (32, 64), fmt: str = "PNG") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path, format=fmt)


def test_read_manifest_uses_image_columns_without_opening_paired_json(tmp_path: Path):
    sample_dir = tmp_path / "sample-1"
    image_path = sample_dir / "sample-1.png"
    _image(image_path)
    (sample_dir / "sample-1.json").write_text("not valid json", encoding="utf-8")
    with (tmp_path / "manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sample_id", "json_file", "image_file"])
        writer.writeheader()
        writer.writerow(
            {
                "sample_id": "sample-1",
                "json_file": "sample-1/sample-1.json",
                "image_file": "sample-1/sample-1.png",
            }
        )

    samples = read_manifest(tmp_path)

    assert [sample.sample_id for sample in samples] == ["sample-1"]
    assert samples[0].image_path == image_path
    assert samples[0].gold_path == sample_dir / "sample-1.json"


def test_select_samples_is_deterministic_and_covers_visual_strata(tmp_path: Path):
    samples = []
    for sample_id, suffix, size in (
        ("a", ".png", (30, 90)),
        ("b", ".png", (90, 30)),
        ("c", ".jpg", (60, 60)),
    ):
        path = tmp_path / f"{sample_id}{suffix}"
        _image(path, size=size, fmt="JPEG" if suffix == ".jpg" else "PNG")
        gold_path = tmp_path / f"{sample_id}.json"
        gold_path.write_text("{}", encoding="utf-8")
        samples.append(Sample(sample_id, path, suffix, path.stat().st_size, gold_path))

    first = select_samples(samples, [], 3)
    second = select_samples(reversed(samples), [], 3)

    assert [sample.sample_id for sample in first] == [sample.sample_id for sample in second]
    assert {sample.sample_id for sample in first} == {"a", "b", "c"}


def test_dry_run_preview_contains_one_image_and_frozen_prompt_only(tmp_path: Path):
    image_path = tmp_path / "input" / "sample-1" / "sample-1.png"
    _image(image_path)
    paired_json = image_path.with_suffix(".json")
    paired_json.write_text('{"secret_annotation": "must not leak"}', encoding="utf-8")
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("frozen prompt", encoding="utf-8")
    sample = Sample("sample-1", image_path, ".png", image_path.stat().st_size, paired_json)

    status = process_one(
        sample,
        tmp_path / "output",
        prompt_file,
        "frozen prompt",
        dry_run=True,
    )

    sample_output = tmp_path / "output" / "sample-1"
    metadata_output = tmp_path / "output" / "_metadata" / "sample-1"
    preview = json.loads((metadata_output / "request_preview.json").read_text(encoding="utf-8"))
    serialized = json.dumps(preview, ensure_ascii=False)
    assert status["status"] == "dry_run"
    assert preview["request"]["prompt"] == "frozen prompt"
    assert preview["request"]["sourceImages"] == [str(image_path)]
    assert preview["request"]["image_count"] == 1
    assert "secret_annotation" not in serialized
    assert str(paired_json) not in serialized
    assert (metadata_output / "prompt.txt").read_text(encoding="utf-8") == "frozen prompt"
    assert not sample_output.exists()


def test_resume_skips_a_valid_existing_result(tmp_path: Path):
    image_path = tmp_path / "input.png"
    _image(image_path)
    gold_path = tmp_path / "input.json"
    gold_path.write_text('{"gold": true}', encoding="utf-8")
    sample = Sample("sample-1", image_path, ".png", image_path.stat().st_size, gold_path)
    existing = tmp_path / "output" / "sample-1" / "sample-1_q_front_view.png"
    _image(existing)
    prompt_snapshot = existing.parent / "prompt.txt"
    prompt_snapshot.write_text("frozen prompt", encoding="utf-8")
    original_status = existing.parent / "status.json"
    original_status.write_text('{"status": "succeeded"}', encoding="utf-8")

    status = process_one(
        sample,
        tmp_path / "output",
        tmp_path / "prompt.txt",
        "frozen prompt",
        dry_run=False,
        api_key="unused",
    )

    assert status["status"] == "skipped"
    assert status["reason"] == "success_exists"
    metadata_dir = tmp_path / "output" / "_metadata" / "sample-1"
    assert json.loads((metadata_dir / "status.json").read_text(encoding="utf-8"))["status"] == "succeeded"
    assert sorted(path.name for path in existing.parent.iterdir()) == [
        "sample-1.json",
        "sample-1_original.png",
        "sample-1_q_front_view.png",
    ]
    assert (existing.parent / "sample-1.json").read_bytes() == gold_path.read_bytes()


def test_resume_rejects_prompt_drift(tmp_path: Path):
    image_path = tmp_path / "input.png"
    _image(image_path)
    gold_path = tmp_path / "input.json"
    gold_path.write_text("{}", encoding="utf-8")
    sample = Sample("sample-1", image_path, ".png", image_path.stat().st_size, gold_path)
    existing = tmp_path / "output" / "sample-1" / "sample-1_q_front_view.png"
    _image(existing)
    (existing.parent / "prompt.txt").write_text("original prompt", encoding="utf-8")

    with pytest.raises(RuntimeError, match="different prompt"):
        process_one(
            sample,
            tmp_path / "output",
            tmp_path / "prompt.txt",
            "changed prompt",
            dry_run=False,
            api_key="unused",
        )
