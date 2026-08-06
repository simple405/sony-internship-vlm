import json
from pathlib import Path

import pytest

from vlm.scripts.supervise.run_paired_front_view_review import (
    ReviewSample,
    apply_color_family_tolerance,
    build_batch_summary,
    build_messages,
    build_review_prompt,
    compute_aggregate_counts,
    compute_overall_decision,
    discover_samples,
    enforce_pilot_scale_guard,
    extract_json_object,
    load_gold_elements,
    process_one,
    request_preview,
    select_review_samples,
    validate_and_align_rules,
)

PROMPT_TEMPLATE_PATH = Path("vlm/prompts/supervision/paired_front_view_review_v1_cn.txt")


def _write_complete_sample(root: Path, sample_id: str) -> Path:
    sample_dir = root / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    (sample_dir / f"{sample_id}_q_front_view.png").write_bytes(b"fake-png")
    (sample_dir / f"{sample_id}_original.png").write_bytes(b"fake-original")
    (sample_dir / f"{sample_id}.json").write_text("[]", encoding="utf-8")
    return sample_dir


def test_prompt_template_exists_and_declares_contract():
    text = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8-sig")
    assert text.strip()
    assert "{{GOLD_COUNT}}" in text
    assert "{{GOLD_ELEMENTS}}" in text
    for keyword in (
        "rule_index",
        "evidence_bbox",
        "pass",
        "partial",
        "fail",
        "not_evaluable",
        "review",
        "extra_elements",
    ):
        assert keyword in text
    assert "微小细节" in text
    assert "粉红/玫红/紫红" in text


def test_discover_samples_finds_only_complete_three_file_dirs(tmp_path: Path):
    _write_complete_sample(tmp_path, "sample-b")
    _write_complete_sample(tmp_path, "sample-a")
    incomplete_dir = tmp_path / "sample-incomplete"
    incomplete_dir.mkdir()
    (incomplete_dir / "sample-incomplete_q_front_view.png").write_bytes(b"fake-png")
    metadata_dir = tmp_path / "_metadata"
    metadata_dir.mkdir()
    (metadata_dir / "sample-a").mkdir()

    samples = discover_samples(tmp_path)

    assert [sample.sample_id for sample in samples] == ["sample-a", "sample-b"]
    assert isinstance(samples[0], ReviewSample)
    assert samples[0].generated_image_path == tmp_path / "sample-a" / "sample-a_q_front_view.png"
    assert samples[0].gold_path == tmp_path / "sample-a" / "sample-a.json"
    assert samples[0].original_image_path == tmp_path / "sample-a" / "sample-a_original.png"


def test_discover_samples_returns_empty_for_missing_root(tmp_path: Path):
    assert discover_samples(tmp_path / "does-not-exist") == []


def test_load_gold_elements_returns_raw_list(tmp_path: Path):
    gold_path = tmp_path / "sample-1.json"
    gold_path.write_text(
        json.dumps(
            [{"element": "红色眼睛", "description": "鲜艳的红色", "bbox": [1, 2, 3, 4]}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    elements = load_gold_elements(gold_path)

    assert elements == [{"element": "红色眼睛", "description": "鲜艳的红色", "bbox": [1, 2, 3, 4]}]


def test_build_review_prompt_numbers_elements_and_fills_count():
    template = "COUNT={{GOLD_COUNT}}\nELEMENTS:\n{{GOLD_ELEMENTS}}\nEND"
    gold_elements = [
        {"element": "金色长发", "description": "飘逸的金色长发"},
        {"element": "红色眼睛", "description": "鲜艳的红色"},
    ]

    prompt = build_review_prompt(template, gold_elements)

    assert "COUNT=2" in prompt
    assert "1. element: 金色长发" in prompt
    assert "2. element: 红色眼睛" in prompt
    assert prompt.index("1. element: 金色长发") < prompt.index("2. element: 红色眼睛")
    assert "{{GOLD_COUNT}}" not in prompt
    assert "{{GOLD_ELEMENTS}}" not in prompt


def test_build_review_prompt_adds_micro_detail_hints():
    template = "{{GOLD_COUNT}}\n{{GOLD_ELEMENTS}}"
    gold_elements = [
        {
            "element": "白色衬衫与蓝色宝石领饰",
            "description": "领口处有黑色小领结和一枚镶嵌蓝色宝石的圆形领饰。",
        }
    ]

    prompt = build_review_prompt(template, gold_elements)

    assert "micro_detail_hints:" in prompt
    assert "宝石" in prompt
    assert "领饰" in prompt


def test_request_preview_references_only_generated_image_never_original(tmp_path: Path):
    sample_dir = _write_complete_sample(tmp_path, "sample-1")
    sample = ReviewSample(
        sample_id="sample-1",
        generated_image_path=sample_dir / "sample-1_q_front_view.png",
        gold_path=sample_dir / "sample-1.json",
        original_image_path=sample_dir / "sample-1_original.png",
    )
    prompt_text = "rendered prompt text mentioning gold description"

    preview = request_preview(
        sample,
        tmp_path / "prompt.txt",
        prompt_text,
        gold_element_count=3,
        output_dir=tmp_path / "out",
    )

    serialized = json.dumps(preview, ensure_ascii=False)
    assert str(sample.original_image_path) not in serialized
    assert preview["request"]["image_path"] == str(sample.generated_image_path)
    assert preview["request"]["image_count"] == 1
    assert preview["gold_element_count"] == 3
    assert preview["request"]["prompt"] == prompt_text


def test_validate_and_align_rules_forces_rule_index_and_element_from_gold():
    gold_elements = [{"element": "金色长发"}, {"element": "红色眼睛"}]
    raw_rules = [
        {"rule_index": 99, "element": "wrong-name", "result": "pass", "confidence": 0.9},
        {"rule_index": 1, "result": "fail", "confidence": 0.8},
    ]

    aligned, issues = validate_and_align_rules(raw_rules, gold_elements)

    assert [rule["rule_index"] for rule in aligned] == [1, 2]
    assert [rule["element"] for rule in aligned] == ["金色长发", "红色眼睛"]
    assert aligned[0]["result"] == "pass"
    assert aligned[1]["result"] == "fail"
    assert issues == []


def test_validate_and_align_rules_repairs_missing_and_invalid_entries():
    gold_elements = [{"element": "金色长发"}, {"element": "红色眼睛"}]
    raw_rules = [{"rule_index": 1, "result": "not-a-real-result", "confidence": 0.9}]

    aligned, issues = validate_and_align_rules(raw_rules, gold_elements)

    assert len(aligned) == 2
    assert aligned[0]["result"] == "review"
    assert aligned[1]["result"] == "review"
    assert any("missing_rule_index_2" in issue for issue in issues)
    assert any("invalid_result_at_index_1" in issue for issue in issues)


def test_validate_and_align_rules_rejects_non_list_input():
    aligned, issues = validate_and_align_rules("not a list", [{"element": "金色长发"}])

    assert len(aligned) == 1
    assert aligned[0]["result"] == "review"
    assert "rules_not_a_list" in issues


def test_apply_color_family_tolerance_downgrades_pink_vs_purple_red_only():
    gold_elements = [
        {"element": "紫红色蝴蝶结", "description": "胸前有一个紫红色蝴蝶结。"},
        {"element": "蓝色裙子", "description": "裙子为蓝色。"},
    ]
    rules = [
        {
            "result": "fail",
            "description_correct": False,
            "issue_types": ["color"],
            "observed_description": "图中蝴蝶结呈粉红色。",
            "reason": "粉红色与紫红色不一致。",
        },
        {
            "result": "fail",
            "description_correct": False,
            "issue_types": ["color", "structure"],
            "observed_description": "裙子偏青蓝且结构不同。",
            "reason": "颜色和结构均不一致。",
        },
    ]

    adjusted = apply_color_family_tolerance(rules, gold_elements)

    assert adjusted[0]["result"] == "pass"
    assert adjusted[0]["issue_types"] == []
    assert adjusted[0]["postprocess"]["color_family_tolerated"] is True
    assert adjusted[0]["postprocess"]["matched_color_families"] == ["pink", "purple_red"]
    assert adjusted[1]["result"] == "fail"
    assert adjusted[1]["issue_types"] == ["structure"]


def test_compute_aggregate_counts_tallies_by_result():
    rules = [{"result": "pass"}, {"result": "pass"}, {"result": "fail"}, {"result": "review"}]

    counts = compute_aggregate_counts(rules)

    assert counts == {"fail": 1, "not_evaluable": 0, "partial": 0, "pass": 2, "review": 1}


def test_compute_overall_decision_prioritizes_fail_then_review_then_pass():
    assert compute_overall_decision([{"result": "fail", "confidence": 0.9}], []) == "fail"
    assert compute_overall_decision([{"result": "pass", "confidence": 0.9}], ["some_qc_issue"]) == "review"
    assert compute_overall_decision([{"result": "review", "confidence": 0.9}], []) == "review"
    assert compute_overall_decision([{"result": "pass", "confidence": 0.4}], []) == "review"
    assert compute_overall_decision([{"result": "pass", "confidence": 0.9}], []) == "pass"


def test_build_messages_has_exactly_one_text_and_one_image_block(tmp_path: Path):
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"fake-png-bytes")

    messages = build_messages("the prompt text", image_path)

    assert len(messages) == 1
    content = messages[0]["content"]
    assert content[0] == {"type": "text", "text": "the prompt text"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert len(content) == 2


def test_extract_json_object_handles_markdown_fence():
    text = '```json\n{"rules": [], "extra_elements": []}\n```'

    result = extract_json_object(text)

    assert result == {"rules": [], "extra_elements": []}


def test_extract_json_object_handles_bare_json():
    assert extract_json_object('{"rules": []}') == {"rules": []}


def test_process_one_dry_run_writes_preview_and_never_calls_network(tmp_path: Path):
    sample_dir = _write_complete_sample(tmp_path / "input", "sample-1")
    (sample_dir / "sample-1.json").write_text(
        json.dumps([{"element": "红色眼睛", "description": "鲜艳的红色"}], ensure_ascii=False),
        encoding="utf-8",
    )
    sample = ReviewSample(
        sample_id="sample-1",
        generated_image_path=sample_dir / "sample-1_q_front_view.png",
        gold_path=sample_dir / "sample-1.json",
        original_image_path=sample_dir / "sample-1_original.png",
    )
    gold_elements = load_gold_elements(sample.gold_path)

    def _fail_if_called(**_kwargs):
        raise AssertionError("call_fn must not be invoked during a dry run")

    status = process_one(
        sample,
        gold_elements,
        tmp_path / "prompt.txt",
        "COUNT={{GOLD_COUNT}}\n{{GOLD_ELEMENTS}}",
        tmp_path / "output",
        dry_run=True,
        call_fn=_fail_if_called,
    )

    assert status["status"] == "dry_run"
    output_dir = tmp_path / "output" / "sample-1"
    preview = json.loads((output_dir / "request_preview.json").read_text(encoding="utf-8"))
    assert preview["request"]["image_path"] == str(sample.generated_image_path)
    assert str(sample.original_image_path) not in json.dumps(preview, ensure_ascii=False)
    assert (output_dir / "review_prompt.txt").read_text(encoding="utf-8").startswith("COUNT=1")
    assert not (output_dir / "prediction.json").exists()


def test_process_one_real_call_writes_aligned_prediction(tmp_path: Path):
    sample_dir = _write_complete_sample(tmp_path / "input", "sample-1")
    (sample_dir / "sample-1.json").write_text(
        json.dumps([{"element": "红色眼睛", "description": "鲜艳的红色"}], ensure_ascii=False),
        encoding="utf-8",
    )
    sample = ReviewSample(
        sample_id="sample-1",
        generated_image_path=sample_dir / "sample-1_q_front_view.png",
        gold_path=sample_dir / "sample-1.json",
        original_image_path=sample_dir / "sample-1_original.png",
    )
    gold_elements = load_gold_elements(sample.gold_path)
    canned_response = json.dumps(
        {
            "rules": [
                {
                    "rule_index": 1,
                    "result": "pass",
                    "confidence": 0.95,
                    "image_grounded": True,
                    "description_correct": True,
                    "issue_types": [],
                    "observed_description": "可见红色眼睛",
                    "evidence_bbox": [10, 20, 30, 40],
                    "reason": "颜色一致",
                }
            ],
            "extra_elements": [],
        },
        ensure_ascii=False,
    )

    status = process_one(
        sample,
        gold_elements,
        tmp_path / "prompt.txt",
        "COUNT={{GOLD_COUNT}}\n{{GOLD_ELEMENTS}}",
        tmp_path / "output",
        dry_run=False,
        api_key="unused",
        base_url="unused",
        model="qwen-vl-max",
        call_fn=lambda **_kwargs: canned_response,
    )

    assert status["status"] == "succeeded"
    assert status["overall_decision"] == "pass"
    assert status["aggregate_counts"]["pass"] == 1
    output_dir = tmp_path / "output" / "sample-1"
    prediction = json.loads((output_dir / "prediction.json").read_text(encoding="utf-8"))
    assert prediction["inputs"]["source_image_used"] is False
    assert prediction["rules"][0]["rule_index"] == 1
    assert prediction["rules"][0]["element"] == "红色眼睛"
    assert (output_dir / "qc.csv").exists()


def test_enforce_pilot_scale_guard_blocks_large_limit_without_explicit_ids():
    with pytest.raises(SystemExit):
        enforce_pilot_scale_guard(requested_ids=[], limit=6901)


def test_enforce_pilot_scale_guard_allows_default_pilot_limit():
    enforce_pilot_scale_guard(requested_ids=[], limit=20)


def test_enforce_pilot_scale_guard_allows_large_limit_with_explicit_ids():
    enforce_pilot_scale_guard(requested_ids=["sample-1", "sample-2"], limit=6901)


def test_select_review_samples_filters_by_explicit_ids_or_limit():
    samples = [
        ReviewSample(sample_id, Path(f"{sample_id}.png"), Path(f"{sample_id}.json"), Path(f"{sample_id}_o.png"))
        for sample_id in ("a", "b", "c")
    ]

    assert [sample.sample_id for sample in select_review_samples(samples, [], 2)] == ["a", "b"]
    assert [sample.sample_id for sample in select_review_samples(samples, ["c", "a"], 0)] == ["c", "a"]

    with pytest.raises(ValueError, match="Unknown sample_id"):
        select_review_samples(samples, ["missing"], 0)


def test_build_batch_summary_aggregates_verdicts_and_queues():
    statuses = [
        {
            "sample_id": "a",
            "status": "succeeded",
            "overall_decision": "pass",
            "aggregate_counts": {"pass": 1, "partial": 0, "fail": 0, "not_evaluable": 0, "review": 0},
        },
        {
            "sample_id": "b",
            "status": "succeeded",
            "overall_decision": "fail",
            "aggregate_counts": {"pass": 0, "partial": 0, "fail": 1, "not_evaluable": 0, "review": 0},
        },
        {"sample_id": "c", "status": "failed", "error": "boom"},
    ]

    summary = build_batch_summary(statuses)

    assert summary["sample_count"] == 3
    assert summary["overall_decision_distribution"]["pass"] == 1
    assert summary["overall_decision_distribution"]["fail"] == 1
    assert summary["fail_or_review_sample_ids"] == ["b"]
    assert summary["parse_failures"] == ["c"]
    assert summary["verdict_distribution"]["pass"] == 1
    assert summary["verdict_distribution"]["fail"] == 1
