from pathlib import Path

from PIL import Image

from vlm.scripts.orchestrate.run_runninghub_merchandise_full_batch import categorize_sample_ids


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
        "ready": ["ready"],
        "atomic_errors": ["atomic_error"],
        "waiting": ["waiting"],
    }


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
