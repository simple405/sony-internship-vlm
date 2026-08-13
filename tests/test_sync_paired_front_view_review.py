"""Tests for syncing reviewer results into generated sample directories."""

import json
from argparse import Namespace
from pathlib import Path

import pytest

from vlm.scripts.supervise import sync_paired_front_view_review as review_sync
from vlm.scripts.supervise.sync_paired_front_view_review import (
    build_central_review_summary,
    discover_review_ids,
    sync_one,
)


def test_discover_review_ids_requires_prediction(tmp_path: Path):
    root = tmp_path / "review"
    (root / "sample-b").mkdir(parents=True)
    (root / "sample-a").mkdir(parents=True)
    (root / "sample-a" / "prediction.json").write_text("{}", encoding="utf-8")
    assert discover_review_ids(root) == ["sample-a"]


def test_sync_one_copies_only_human_csv_without_touching_top_level_data(tmp_path: Path):
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
        json.dumps(
            {
                "inputs": {"source_image_used": False},
                "overall_decision": "fail",
                "aggregate_counts": {"pass": 0, "partial": 0, "fail": 1},
            }
        ),
        encoding="utf-8",
    )
    (review_dir / "qc.csv").write_text("rule_index\n", encoding="utf-8")
    (review_dir / "raw_response.txt").write_text("raw", encoding="utf-8")
    stale_target = sample_dir / "_review" / "paired_front_view_review_v1"
    stale_target.mkdir(parents=True)
    (stale_target / "prediction.json").write_text("old", encoding="utf-8")
    (stale_target / "sync_manifest.json").write_text("old", encoding="utf-8")

    result = sync_one("sample-a", review_root, generation_root)
    target = stale_target
    assert result["synced_files"] == ["qc.csv"]
    assert (target / "qc.csv").is_file()
    assert not (target / "prediction.json").exists()
    assert not (target / "raw_response.txt").exists()
    assert not (target / "sync_manifest.json").exists()
    assert (sample_dir / "sample-a_original.png").read_bytes() == b"original"
    assert (sample_dir / "sample-a_q_front_view.png").read_bytes() == b"generated"


def test_build_central_review_summary_writes_aggregate_files(tmp_path: Path):
    review_root = tmp_path / "review"
    generation_root = tmp_path / "generation"
    review_dir = review_root / "sample-a"
    review_dir.mkdir(parents=True)
    generation_root.mkdir()
    (review_root / "batch_summary.json").write_text(
        json.dumps({"sample_count": 1}), encoding="utf-8"
    )
    (review_dir / "prediction.json").write_text(
        json.dumps(
            {
                "sample_id": "sample-a",
                "inputs": {"source_image_used": False},
                "overall_decision": "pass",
                "aggregate_counts": {"pass": 1, "partial": 0, "fail": 0},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (review_dir / "qc.csv").write_text(
        "rule_index,element,result\n1,红色眼睛,pass\n", encoding="utf-8"
    )
    (review_dir / "request_preview.json").write_text(
        json.dumps(
            {
                "generated_image_sha256": "abc",
                "prompt_sha256": "def",
                "gold_element_count": 1,
                "source_image_used": False,
                "request": {"image_count": 1},
            }
        ),
        encoding="utf-8",
    )

    summary = build_central_review_summary(
        review_root,
        generation_root,
        ["sample-a"],
        [{"sample_id": "sample-a"}],
        [],
    )

    central = generation_root / "_review" / "paired_front_view_review_v1"
    assert summary["central_files"] == [
        "qc_all.csv",
        "prediction_summary.csv",
        "predictions.jsonl",
        "request_audit.csv",
        "batch_summary.json",
    ]
    assert "sample-a,1,红色眼睛,pass" in (
        central / "qc_all.csv"
    ).read_text(encoding="utf-8-sig")
    assert (central / "predictions.jsonl").read_text(encoding="utf-8").count("\n") == 1
    assert (central / "request_audit.csv").is_file()


def test_main_preserves_central_summary_when_any_sample_sync_fails(
    monkeypatch, tmp_path: Path
):
    review_root = tmp_path / "review"
    generation_root = tmp_path / "generation"
    review_root.mkdir()
    central = generation_root / "_review" / "paired_front_view_review_v1"
    central.mkdir(parents=True)
    sentinel = central / "sync_summary.json"
    sentinel.write_text("previous", encoding="utf-8")
    args = Namespace(
        review_root=review_root,
        generation_root=generation_root,
        sample_id=["sample-a"],
        no_overwrite=False,
    )
    monkeypatch.setattr(review_sync, "parse_args", lambda: args)
    monkeypatch.setattr(
        review_sync,
        "sync_one",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failed")),
    )
    monkeypatch.setattr(
        review_sync,
        "build_central_review_summary",
        lambda *args, **kwargs: pytest.fail("central summary must not be replaced"),
    )

    with pytest.raises(SystemExit) as exc:
        review_sync.main()

    assert exc.value.code == 1
    assert sentinel.read_text(encoding="utf-8") == "previous"
    summary = json.loads((review_root / "sync_summary.json").read_text(encoding="utf-8"))
    assert summary["central_review_updated"] is False
