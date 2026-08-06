"""Tests for the paired front-view human-gold package builder."""

import json
from pathlib import Path

from vlm.scripts.supervise.prepare_paired_front_view_human_gold import (
    build_rows,
    count_pending_rows,
    load_review_queue,
    validate_rows,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_fixture(tmp_path: Path) -> tuple[Path, Path]:
    review_root = tmp_path / "review"
    generation_root = tmp_path / "generation"
    review_root.mkdir()
    generation_root.mkdir()
    samples = {
        "sample-fail": "fail",
        "sample-partial-only": "pass",
    }
    for sample_id, overall in samples.items():
        sample_dir = generation_root / sample_id
        sample_dir.mkdir()
        (sample_dir / f"{sample_id}_q_front_view.png").write_bytes(b"png")
        (sample_dir / f"{sample_id}_original.png").write_bytes(b"png")
        _write_json(sample_dir / f"{sample_id}.json", [{"element": "hair", "description": "green", "bbox": [0, 0, 1, 1]}])
        output_dir = review_root / sample_id
        output_dir.mkdir()
        result = "fail" if sample_id == "sample-fail" else "partial"
        _write_json(output_dir / "prediction.json", {
            "sample_id": sample_id,
            "overall_decision": overall,
            "rules": [{"result": result, "confidence": 0.8, "reason": "model"}],
            "extra_elements": [{"element": "hat", "confidence": 0.7, "reason": "extra"}],
        })
    _write_json(review_root / "batch_summary.json", {
        "selected_sample_ids": list(samples),
    })
    return review_root, generation_root


def test_queue_uses_rule_level_partial_even_when_sample_passes(tmp_path: Path):
    review_root, generation_root = _make_fixture(tmp_path)
    records, missing = load_review_queue(review_root, generation_root)
    assert missing == []
    assert [record["sample_id"] for record in records] == ["sample-fail", "sample-partial-only"]


def test_build_rows_keeps_model_and_human_columns_separate(tmp_path: Path):
    review_root, generation_root = _make_fixture(tmp_path)
    records, _ = load_review_queue(review_root, generation_root)
    rule_rows, extra_rows, manifest_rows = build_rows(records, tmp_path)
    assert rule_rows[0]["model_result"] == "fail"
    assert rule_rows[0]["human_result"] == ""
    assert extra_rows[0]["human_result"] == ""
    assert manifest_rows[0]["annotation_status"] == "pending"


def test_validate_rows_allows_pending_but_rejects_unknown_values():
    assert validate_rows([{"sample_id": "s", "human_result": ""}], ["sample_id", "human_result"]) == []
    assert count_pending_rows([{"human_result": ""}, {"human_result": "pass"}]) == 1
    assert validate_rows([{"sample_id": "s", "human_result": "wat"}], ["sample_id", "human_result"])
    assert validate_rows([{"sample_id": "s", "human_result": "accept_extra"}], ["sample_id", "human_result"], extra=True) == []
