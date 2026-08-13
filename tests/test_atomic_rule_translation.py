import json
from pathlib import Path

import pytest

from vlm.scripts.smoke_test_atomic_rule_translation import (
    SMOKE_RULES,
    select_smoke_cases,
    semantic_issues,
)
from vlm.scripts.translate_atomic_rules_xlsx import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    RulePair,
    parse_translation_response,
    translation_quality_issues,
)


def pair(rule_id: str, value: str) -> RulePair:
    return RulePair("key", rule_id, value, ("body",))


def test_prompt_explicitly_rejects_known_machine_phrases():
    assert PROMPT_VERSION == "atomic-rule-natural-cn-v4"
    assert "及大腿长度" in SYSTEM_PROMPT
    assert "及地长度" in SYSTEM_PROMPT
    assert "无可见鞋类" in SYSTEM_PROMPT
    assert "白色和深绿色双色" in SYSTEM_PROMPT
    assert "腰部是否有蝴蝶结" in SYSTEM_PROMPT
    assert "value_cn 中严禁出现顿号" in SYSTEM_PROMPT
    assert "严禁把下划线" in SYSTEM_PROMPT


@pytest.mark.parametrize(
    ("rule_id", "value", "rule_name_cn", "value_cn"),
    [
        ("skirt_length", "knee_length", "裙长", "及膝长度"),
        ("skirt_length", "floor_length", "裙长", "裙摆及地"),
        ("skirt_length", "thigh_length", "裙长", "裙摆至大腿中部"),
        ("legwear_type", "knee_high_socks", "腿部服饰", "及膝袜"),
        ("footwear_type", "none_visible", "鞋型", "未见鞋子"),
        ("has_bow_on_waist", "true", "腰部是否有蝴蝶结", "有"),
    ],
)
def test_natural_smoke_values_pass_quality_gate(
    rule_id: str,
    value: str,
    rule_name_cn: str,
    value_cn: str,
):
    candidate = pair(rule_id, value)
    assert translation_quality_issues(candidate, rule_name_cn, value_cn) == []
    assert semantic_issues(candidate, value_cn) == []


@pytest.mark.parametrize(
    ("rule_id", "value", "value_cn"),
    [
        ("skirt_length", "floor_length", "及地长度"),
        ("skirt_length", "thigh_length", "及大腿长度"),
        ("footwear_type", "none_visible", "无可见鞋类"),
    ],
)
def test_machine_like_values_are_rejected(rule_id: str, value: str, value_cn: str):
    assert translation_quality_issues(pair(rule_id, value), "属性", value_cn)


def test_mixed_color_construction_is_rejected():
    assert translation_quality_issues(
        pair("bag_color", "white_and_dark_green"),
        "包袋配色",
        "白色和深绿色双色",
    )


def test_value_with_dunhao_is_rejected():
    assert translation_quality_issues(
        pair("bag_color", "white_and_dark_green"),
        "包袋配色",
        "白色、深绿色",
    )


def test_has_on_rule_requires_natural_chinese_word_order():
    candidate = pair("has_bow_on_waist", "true")
    assert translation_quality_issues(candidate, "腰部是否有蝴蝶结", "有") == []
    assert translation_quality_issues(candidate, "是否有腰部蝴蝶结", "有")


def test_parser_rejects_machine_like_model_output():
    batch = [pair("skirt_length", "thigh_length")]
    response = json.dumps(
        {
            "translations": [
                {"index": 0, "rule_name_cn": "裙长", "value_cn": "及大腿长度"}
            ]
        },
        ensure_ascii=False,
    )
    with pytest.raises(ValueError, match="Machine-like Qwen translation"):
        parse_translation_response(response, batch)


def test_select_smoke_cases_reads_ten_real_rule_pairs(tmp_path: Path):
    atomic_root = tmp_path / "atomic_rules"
    for index, (rule_id, value) in enumerate(SMOKE_RULES):
        sample_dir = atomic_root / f"sample-{index}"
        sample_dir.mkdir(parents=True)
        (sample_dir / "atomic_rules.json").write_text(
            json.dumps(
                {
                    "atomic_rules": [
                        {"id": rule_id, "value": value, "location": "body"}
                    ]
                }
            ),
            encoding="utf-8",
        )
    selected = select_smoke_cases(atomic_root)
    assert [(case.pair.rule_id, case.pair.value) for case in selected] == list(SMOKE_RULES)
