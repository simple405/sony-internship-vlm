"""Tests for evaluator v2 relaxed matching and extra verification helpers."""

from pathlib import Path

from PIL import Image

from vlm.scripts.dataset.evaluate_element_extraction_predictions import evaluate_elements
from vlm.scripts.dataset.verify_extra_predictions_visual import make_bbox_crop, parse_verdict


def test_relaxed_any_gold_accepts_split_predictions_without_changing_strict():
    gold = [
        {
            "element": "白色短袖衬衫与红色领结",
            "description": "白色衬衫领口系有红色蝴蝶结领结。",
            "bbox": [0, 0, 100, 100],
        }
    ]
    predictions = [
        {
            "element": "白色短袖衬衫",
            "description": "角色穿着白色短袖衬衫。",
            "bbox": [0, 0, 100, 100],
        },
        {
            "element": "红色领结",
            "description": "衬衫领口有红色蝴蝶结领结。",
            "bbox": [35, 5, 65, 35],
        },
    ]

    result = evaluate_elements(gold, predictions)

    assert result["match_count"] == 1
    assert result["precision"] == 0.5
    assert result["relaxed_any_gold_match_count"] == 2
    assert result["relaxed_any_gold_unique_gold_count"] == 1
    assert result["relaxed_any_gold_precision"] == 1.0
    assert result["relaxed_any_gold_recall"] == 1.0
    assert all(match["gold_index"] == 0 for match in result["relaxed_any_gold_matches"])


def test_relaxed_any_gold_does_not_accept_unrelated_prediction():
    gold = [{"element": "蓝色眼睛", "description": "蓝色眼睛", "bbox": [0, 0, 20, 20]}]
    predictions = [
        {"element": "蓝色眼睛", "description": "蓝色眼睛", "bbox": [0, 0, 20, 20]},
        {"element": "红色鞋子", "description": "红色鞋子", "bbox": [80, 80, 100, 100]},
    ]

    result = evaluate_elements(gold, predictions)

    assert result["relaxed_any_gold_match_count"] == 1
    assert result["relaxed_any_gold_precision"] == 0.5


def test_parse_verdict_derives_accepted_extra():
    accepted = parse_verdict(
        '{"image_grounded":true,"description_correct":true,"duplicate":false,"conflict":false,"reason":"可见"}'
    )
    rejected = parse_verdict(
        '{"image_grounded":true,"description_correct":true,"duplicate":true,"conflict":false,"accepted_extra":true}'
    )

    assert accepted["accepted_extra"] is True
    assert rejected["accepted_extra"] is False


def test_make_bbox_crop_clamps_padding_to_image(tmp_path: Path):
    image_path = tmp_path / "source.png"
    crop_path = tmp_path / "crop.png"
    Image.new("RGB", (100, 80), "white").save(image_path)

    crop_box = make_bbox_crop(image_path, [0, 0, 20, 20], crop_path, padding_ratio=0.2)

    assert crop_box == [0, 0, 36, 36]
    assert Image.open(crop_path).size == (36, 36)
