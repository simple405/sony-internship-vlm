"""Tests for syncing reviewer results into generated sample directories."""

import json
from pathlib import Path

from vlm.scripts.supervise.sync_paired_front_view_review import (
    discover_review_ids,
    sync_one,
)


def test_discover_review_ids_requires_prediction(tmp_path: Path):
    root = tmp_path / "review"
    (root / "sample-b").mkdir(parents=True)
    (root / "sample-a").mkdir(parents=True)
    (root / "sample-a" / "prediction.json").write_text("{}", encoding="utf-8")
    assert discover_review_ids(root) == ["sample-a"]


def test_sync_one_copies_review_files_without_touching_top_level_data(tmp_path: Path):
    review_root = tmp_path / "review"
    generation_root = tmp_path / "generation"
    review_dir = review_root / "sample-a"
    sample_dir = generation_root / "sample-a"
    review_dir.mkdir(parents=True)
    sample_dir.mkdir(parents=True)
    (sample_dir / "sample-a_original.png").write_bytes(b"original")
    (sample_dir / "sample-a_q_front_view.png").write_bytes(b"generated")
    (sample_dir / "sample-a.json").write_text("[]", encoding="utf-8")
    (review_dir / "prediction.json").write_text(
        json.dumps({"inputs": {"source_image_used": False}, "overall_decision": "fail"}),
        encoding="utf-8",
    )
    (review_dir / "qc.csv").write_text("rule_index\n", encoding="utf-8")

    result = sync_one("sample-a", review_root, generation_root)
    target = sample_dir / "_review" / "paired_front_view_review_v1"
    assert result["synced_files"] == ["prediction.json", "qc.csv"]
    assert (target / "prediction.json").is_file()
    assert (target / "qc.csv").is_file()
    assert (sample_dir / "sample-a_original.png").read_bytes() == b"original"
    assert (sample_dir / "sample-a_q_front_view.png").read_bytes() == b"generated"
    assert (target / "sync_manifest.json").is_file()
