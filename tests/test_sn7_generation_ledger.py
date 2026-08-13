import csv
from pathlib import Path

from PIL import Image

from vlm.scripts.generate.sn7_generation_ledger import (
    filter_sample_ids,
    read_ledger,
    scan_dataset,
    upsert,
    write_ledger,
)


def test_scan_dataset_records_valid_outputs_and_generation_errors(tmp_path: Path):
    dataset = tmp_path / "dataset"
    success_dir = dataset / "generated" / "head_key_chain" / "cs_1"
    success_dir.mkdir(parents=True)
    Image.new("RGB", (8, 8), "white").save(success_dir / "cs_1_head_keychain.png")

    error_dir = dataset / "generated" / "backpack" / "cd_1"
    error_dir.mkdir(parents=True)
    (error_dir / "generation_error.json").write_text(
        '{"status": "no_image_url_found", "error_type": "empty"}',
        encoding="utf-8",
    )

    rows = scan_dataset(dataset)

    assert rows["cs_1"]["status"] == "succeeded"
    assert rows["cs_1"]["category"] == "head_key_chain"
    assert rows["cs_1"]["artifact_path"] == "generated/head_key_chain/cs_1/cs_1_head_keychain.png"
    assert rows["cd_1"]["status"] == "no_image_url_found"
    assert rows["cd_1"]["category"] == "backpack"


def test_scan_dataset_ignores_corrupt_generated_output(tmp_path: Path):
    dataset = tmp_path / "dataset"
    corrupt_dir = dataset / "generated" / "plush" / "cs_bad"
    corrupt_dir.mkdir(parents=True)
    (corrupt_dir / "cs_bad_plush.png").write_bytes(b"not an image")

    rows = scan_dataset(dataset)

    assert "cs_bad" not in rows


def test_ledger_write_read_and_filter_skip_processed_samples(tmp_path: Path):
    ledger_path = tmp_path / "used_samples.csv"
    rows = {}
    upsert(
        rows,
        {
            "sample_id": "cs_1",
            "category": "head_key_chain",
            "status": "started",
            "source": "test",
            "artifact_path": "",
            "updated_at": "2026-08-11T00:00:00+08:00",
            "detail": "",
        },
    )
    upsert(
        rows,
        {
            "sample_id": "cs_2",
            "category": "head_key_chain",
            "status": "succeeded",
            "source": "test",
            "artifact_path": "generated/head_key_chain/cs_2/cs_2_head_keychain.png",
            "updated_at": "2026-08-11T00:00:01+08:00",
            "detail": "",
        },
    )
    write_ledger(ledger_path, rows)

    loaded = read_ledger(ledger_path)
    pending, skipped = filter_sample_ids(
        ["cs_1", "cs_2", "cs_3"],
        loaded,
        {"started", "succeeded"},
    )

    assert skipped == ["cs_1", "cs_2"]
    assert pending == ["cs_3"]

    with ledger_path.open("r", encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 2
