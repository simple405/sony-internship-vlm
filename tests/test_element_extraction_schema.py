import json

from vlm.scripts.dataset.element_extraction_schema import (
    ATOMIC_RULES_SCHEMA,
    elements_to_atomic_rules,
    normalize_model_response,
    prediction_elements,
)


def test_normalize_atomic_response_and_legacy_view():
    payload = normalize_model_response(
        json.dumps(
            {
                "code": "image",
                "atomic_rules": [
                    {"id": "hair", "value": "棕色双马尾", "bbox": [1, 2, 30, 40]},
                    {"id": "footwear_left", "value": "黑色平底鞋", "bbox": [3, 20, 12, 40]},
                ],
            },
            ensure_ascii=False,
        ),
        output_schema=ATOMIC_RULES_SCHEMA,
        code="sample-1",
    )

    assert payload["code"] == "sample-1"
    assert payload["atomic_rules"][0]["id"] == "hair"
    legacy = prediction_elements(payload)
    assert [item["element"] for item in legacy] == ["棕色双马尾", "黑色平底鞋"]
    assert legacy[1]["rule_id"] == "footwear_left"


def test_atomic_response_allows_empty_rules():
    payload = normalize_model_response(
        '{"code":"image","atomic_rules":[]}',
        output_schema=ATOMIC_RULES_SCHEMA,
        code="sample-2",
    )
    assert payload == {"code": "sample-2", "atomic_rules": []}


def test_gold_elements_can_be_converted_to_atomic_shape():
    rules = elements_to_atomic_rules(
        [
            {"element": "棕色皮鞋", "bbox": [1, 10, 20, 30]},
            {"element": "棕色皮鞋", "bbox": [30, 10, 50, 30]},
        ]
    )
    assert [rule["id"] for rule in rules] == ["footwear_left", "footwear_right"]
    assert all(set(rule) == {"id", "value", "bbox"} for rule in rules)
