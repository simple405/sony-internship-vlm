import csv
from pathlib import Path

from PIL import Image

from vlm.scripts.generate.generate_paired_front_view import Sample
from vlm.scripts.supervise.prepare_five_category_supervision_manifest import (
    DEFAULT_CATEGORIES,
    build_selection_rows,
    discover_processed_sample_ids,
)


def _image(path: Path, size: tuple[int, int] = (32, 64)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path, format="PNG")


def test_build_selection_rows_excludes_processed_and_balances_categories(tmp_path: Path):
    samples = []
    for index in range(60):
        sample_id = f"sample-{index:02d}"
        image_path = tmp_path / "input" / f"{sample_id}.png"
        _image(image_path, size=(32 + index, 64))
        gold_path = image_path.with_suffix(".json")
        gold_path.write_text("[]", encoding="utf-8")
        samples.append(Sample(sample_id, image_path, ".png", image_path.stat().st_size, gold_path))

    rows = build_selection_rows(
        samples,
        processed_ids={"sample-00", "sample-01"},
        samples_per_category=10,
        output_root=tmp_path / "out",
        repo_root=tmp_path,
    )

    assert len(rows) == 50
    assert {row["category"] for row in rows} == set(DEFAULT_CATEGORIES)
    assert {row["sample_id"] for row in rows}.isdisjoint({"sample-00", "sample-01"})
    counts = {category: 0 for category in DEFAULT_CATEGORIES}
    for row in rows:
        counts[row["category"]] += 1
    assert set(counts.values()) == {10}


def test_discover_processed_sample_ids_reads_legacy_and_category_outputs(tmp_path: Path):
    legacy = tmp_path / "sample-old"
    _image(legacy / "sample-old_q_front_view.png")
    category = tmp_path / "head_key_chain" / "sample-new"
    _image(category / "sample-new_head_keychain_front_view.png")
    with (tmp_path / "batch_summary.json").open("w", encoding="utf-8", newline="") as handle:
        handle.write('{"selected": ["sample-summary"]}')

    processed = discover_processed_sample_ids(tmp_path)

    assert {"sample-old", "sample-new", "sample-summary"}.issubset(processed)
