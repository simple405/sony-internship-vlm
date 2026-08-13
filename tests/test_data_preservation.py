"""Regression tests for non-destructive publication of generated artifacts."""

import json
from argparse import Namespace
from pathlib import Path

import pytest
from PIL import Image

from vlm.scripts import prepare_sn7_smoke_test as smoke
from vlm.scripts._preservation import publish_staged_directory
from vlm.scripts.package_sn7_dataset import package_dataset
from vlm.scripts.supervise import prepare_paired_front_view_human_gold as human_gold
from vlm.scripts.supervise.sync_paired_front_view_review import (
    REVIEW_VERSION,
    build_central_review_summary,
    sync_one,
)


def _only_archive(container: Path) -> Path:
    archives = list(container.iterdir())
    assert len(archives) == 1
    return archives[0]


def test_publish_staged_directory_archives_existing_data(tmp_path: Path):
    data_root = tmp_path / "data"
    destination = data_root / "dataset" / "deliverables"
    destination.mkdir(parents=True)
    (destination / "old.txt").write_text("old", encoding="utf-8")
    staged = destination.parent / ".deliverables.staged"
    staged.mkdir()
    (staged / "new.txt").write_text("new", encoding="utf-8")

    archived = publish_staged_directory(
        staged,
        destination,
        protected_root=data_root,
    )

    assert archived is not None
    assert (destination / "new.txt").read_text(encoding="utf-8") == "new"
    assert (archived / "old.txt").read_text(encoding="utf-8") == "old"
    assert archived.parent == data_root / "_archive" / "dataset" / "deliverables"


def test_publish_staged_directory_refuses_protected_root(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    staged = tmp_path / ".data.staged"
    staged.mkdir()

    with pytest.raises(ValueError, match="protected root"):
        publish_staged_directory(
            staged,
            data_root,
            protected_root=data_root,
        )

    assert data_root.is_dir()
    assert staged.is_dir()


def test_publish_staged_directory_restores_existing_data_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    data_root = tmp_path / "data"
    destination = data_root / "dataset"
    destination.mkdir(parents=True)
    (destination / "old.txt").write_text("old", encoding="utf-8")
    staged = data_root / ".dataset.staged"
    staged.mkdir()
    (staged / "new.txt").write_text("new", encoding="utf-8")
    original_replace = Path.replace

    def fail_staged_publish(path: Path, target: Path) -> Path:
        if path == staged and Path(target) == destination:
            raise OSError("simulated publish failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_staged_publish)

    with pytest.raises(OSError, match="simulated publish failure"):
        publish_staged_directory(
            staged,
            destination,
            protected_root=data_root,
        )

    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"
    assert (staged / "new.txt").read_text(encoding="utf-8") == "new"
    assert not list((data_root / "_archive" / "dataset").iterdir())


def test_smoke_overwrite_archives_existing_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    data_root = tmp_path / "data"
    sources: dict[str, Path] = {}
    for source_name in ("cs", "ta", "cd"):
        source = tmp_path / source_name
        source.mkdir()
        for index in range(4):
            Image.new("RGB", (8, 8), (index * 20, 0, 0)).save(
                source / f"{source_name}-{index}.png"
            )
        sources[source_name] = source
    monkeypatch.setattr(smoke, "DATA_ROOT", data_root)
    monkeypatch.setattr(smoke, "SOURCES", sources)

    output_root = data_root / "smoke12"
    output_root.mkdir(parents=True)
    (output_root / "old.txt").write_text("old", encoding="utf-8")

    summary = smoke.prepare_smoke_dataset(
        Namespace(output_root=output_root, overwrite=True)
    )

    assert summary["sample_count"] == 12
    assert not (output_root / "old.txt").exists()
    archive = _only_archive(data_root / "_archive" / "smoke12")
    assert (archive / "old.txt").read_text(encoding="utf-8") == "old"


def test_package_overwrite_archives_previous_deliverable(tmp_path: Path):
    root = tmp_path / "dataset"
    source_image = root / "image" / "sample.png"
    source_image.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), "white").save(source_image)
    (root / "manifest.csv").write_text(
        "post_id,image_path\nsample,image/sample.png\n",
        encoding="utf-8",
    )
    assignment = root / "assignments.csv"
    assignment.write_text(
        "sample_id,primary_category\nsample,plush\n",
        encoding="utf-8",
    )
    atomic = root / "atomic_rules" / "sample" / "atomic_rules.json"
    atomic.parent.mkdir(parents=True)
    atomic.write_text(
        json.dumps(
            {
                "atomic_rules": [
                    {"id": "hair_color", "location": "head", "value": "red"}
                ]
            }
        ),
        encoding="utf-8",
    )
    generated = root / "generated" / "plush" / "sample" / "sample_plush.png"
    generated.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), "white").save(generated)
    package_root = root / "deliverables"
    package_root.mkdir()
    (package_root / "old.txt").write_text("old", encoding="utf-8")

    summary = package_dataset(
        Namespace(
            root=root,
            manifest=None,
            assignment_csv=assignment,
            generated_root=None,
            package_root=package_root,
            overwrite=True,
            allow_incomplete=False,
        )
    )

    assert summary["package_replaced"] is True
    assert (package_root / "plush" / "sample" / "atomic_rules.json").is_file()
    archive = _only_archive(root / "_archive" / "deliverables")
    assert (archive / "old.txt").read_text(encoding="utf-8") == "old"


def test_sample_review_sync_archives_previous_review(tmp_path: Path):
    review_root = tmp_path / "review"
    generation_root = tmp_path / "generation"
    source = review_root / "sample-a"
    sample = generation_root / "sample-a"
    source.mkdir(parents=True)
    sample.mkdir(parents=True)
    (source / "prediction.json").write_text(
        json.dumps({"inputs": {}, "overall_decision": "pass"}),
        encoding="utf-8",
    )
    (source / "qc.csv").write_text("new", encoding="utf-8")
    destination = sample / "_review" / REVIEW_VERSION
    destination.mkdir(parents=True)
    (destination / "qc.csv").write_text("old", encoding="utf-8")
    (destination / "raw_response.txt").write_text("evidence", encoding="utf-8")

    sync_one("sample-a", review_root, generation_root)

    assert (destination / "qc.csv").read_text(encoding="utf-8") == "new"
    archive = _only_archive(destination.parent / "_archive" / REVIEW_VERSION)
    assert (archive / "qc.csv").read_text(encoding="utf-8") == "old"
    assert (archive / "raw_response.txt").read_text(encoding="utf-8") == "evidence"


def test_central_review_sync_archives_previous_summary(tmp_path: Path):
    review_root = tmp_path / "review"
    generation_root = tmp_path / "generation"
    source = review_root / "sample-a"
    source.mkdir(parents=True)
    generation_root.mkdir()
    (source / "prediction.json").write_text(
        json.dumps(
            {
                "sample_id": "sample-a",
                "inputs": {},
                "overall_decision": "pass",
                "aggregate_counts": {},
            }
        ),
        encoding="utf-8",
    )
    (source / "qc.csv").write_text("rule_index\n", encoding="utf-8")
    destination = generation_root / "_review" / REVIEW_VERSION
    destination.mkdir(parents=True)
    (destination / "old.txt").write_text("old", encoding="utf-8")

    build_central_review_summary(
        review_root,
        generation_root,
        ["sample-a"],
        [{"sample_id": "sample-a"}],
        [],
    )

    assert (destination / "sync_summary.json").is_file()
    archive = _only_archive(destination.parent / "_archive" / REVIEW_VERSION)
    assert (archive / "old.txt").read_text(encoding="utf-8") == "old"


def test_human_gold_overwrite_archives_manual_annotations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    output_root = tmp_path / "human_gold"
    output_root.mkdir()
    (output_root / "human_gold_rules.csv").write_text(
        "manual-edit",
        encoding="utf-8",
    )
    args = Namespace(
        review_root=tmp_path / "review",
        generation_root=tmp_path / "generation",
        output_root=output_root,
        sample_id=[],
        include_pass=False,
        validate=False,
        overwrite=True,
    )
    monkeypatch.setattr(human_gold, "parse_args", lambda: args)
    monkeypatch.setattr(
        human_gold,
        "load_review_queue",
        lambda *args, **kwargs: ([{"sample_id": "sample-a"}], []),
    )
    monkeypatch.setattr(human_gold, "build_rows", lambda *args: ([], [], []))
    monkeypatch.setattr(
        human_gold,
        "write_contact_sheet",
        lambda records, path: path.write_bytes(b"contact-sheet"),
    )

    human_gold.main()

    assert (output_root / "batch_summary.json").is_file()
    archive = _only_archive(tmp_path / "_archive" / "human_gold")
    assert (archive / "human_gold_rules.csv").read_text(encoding="utf-8") == "manual-edit"
