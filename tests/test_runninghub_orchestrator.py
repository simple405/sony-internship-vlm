from pathlib import Path

from PIL import Image

from vlm.scripts.orchestrate.run_runninghub_merchandise_full_batch import (
    categorize_sample_ids,
    is_nonfatal_sample_failure,
)


def test_categorize_sample_ids_keeps_follow_queue_resumable(tmp_path: Path):
    output_dir = tmp_path / "generated"
    atomic_dir = tmp_path / "atomic_rules"
    sample_ids = ["existing", "attempted", "ready", "atomic_error", "waiting"]

    (output_dir / "existing").mkdir(parents=True)
    Image.new("RGB", (8, 8), "white").save(
        output_dir / "existing" / "existing_head_keychain.png"
    )
    (atomic_dir / "ready").mkdir(parents=True)
    (atomic_dir / "ready" / "atomic_rules.json").write_text("{}", encoding="utf-8")
    (atomic_dir / "atomic_error").mkdir(parents=True)
    (atomic_dir / "atomic_error" / "error.json").write_text("{}", encoding="utf-8")

    states = categorize_sample_ids(
        sample_ids,
        output_dir,
        "head_keychain",
        atomic_dir,
        {"attempted"},
    )

    assert states == {
        "existing": ["existing"],
        "attempted": ["attempted"],
        "generation_errors": [],
        "ready": ["ready"],
        "atomic_errors": ["atomic_error"],
        "waiting": ["waiting"],
    }


def test_atomic_error_wins_over_stale_atomic_rules(tmp_path: Path):
    output_dir = tmp_path / "generated"
    atomic_dir = tmp_path / "atomic_rules"
    sample_dir = atomic_dir / "sample"
    sample_dir.mkdir(parents=True)
    (sample_dir / "atomic_rules.json").write_text(
        '{"schema_version":"atomic_rules.v1"}',
        encoding="utf-8",
    )
    (sample_dir / "error.json").write_text(
        '{"schema_version":"atomic_rules_error.v1"}',
        encoding="utf-8",
    )

    states = categorize_sample_ids(["sample"], output_dir, "plush", atomic_dir, set())

    assert states["ready"] == []
    assert states["atomic_errors"] == ["sample"]


def test_categorize_sample_ids_does_not_skip_corrupt_output(tmp_path: Path):
    output_dir = tmp_path / "generated"
    atomic_dir = tmp_path / "atomic_rules"
    (output_dir / "sample").mkdir(parents=True)
    (output_dir / "sample" / "sample_plush.png").write_bytes(b"corrupt")
    (atomic_dir / "sample").mkdir(parents=True)
    (atomic_dir / "sample" / "atomic_rules.json").write_text("{}", encoding="utf-8")

    states = categorize_sample_ids(
        ["sample"], output_dir, "plush", atomic_dir, set()
    )

    assert states["existing"] == []
    assert states["ready"] == ["sample"]


def test_generation_error_is_terminal_until_explicit_retry(tmp_path: Path):
    output_dir = tmp_path / "generated"
    atomic_dir = tmp_path / "atomic_rules"
    (output_dir / "sample").mkdir(parents=True)
    (output_dir / "sample" / "generation_error.json").write_text("{}", encoding="utf-8")
    (atomic_dir / "sample").mkdir(parents=True)
    (atomic_dir / "sample" / "atomic_rules.json").write_text("{}", encoding="utf-8")

    states = categorize_sample_ids(["sample"], output_dir, "plush", atomic_dir, set())
    retry_states = categorize_sample_ids(
        ["sample"],
        output_dir,
        "plush",
        atomic_dir,
        set(),
        retry_failed=True,
    )

    assert states["generation_errors"] == ["sample"]
    assert states["ready"] == []
    assert retry_states["generation_errors"] == []
    assert retry_states["ready"] == ["sample"]


def test_sample_failures_are_nonfatal_when_child_finished():
    assert is_nonfatal_sample_failure(
        1,
        {
            "status": "finished",
            "selected_samples": 28,
            "succeeded": 26,
            "failed": 2,
            "no_image_url_found": 0,
        },
    )


def test_crashed_child_without_finished_summary_is_fatal():
    assert not is_nonfatal_sample_failure(1, None)
    assert not is_nonfatal_sample_failure(1, {"status": "batch_started"})
