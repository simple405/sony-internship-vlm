import json
from pathlib import Path

import pytest

from vlm.scripts.supervise.run_front_view_image_only_agent import (
    AgentPrompts,
    apply_head_only_scope_rules,
    build_comparison_prompt,
    build_extraction_prompt,
    build_multimodal_messages,
    profile_for_comparison,
    process_one,
    resolve_agent_output_dir,
    select_agent_jobs,
    validate_agent_rules,
    validate_visual_profile,
)
from vlm.scripts.supervise.run_paired_front_view_review import ReviewSample


def _write_sample(root: Path, sample_id: str = "sample-1") -> ReviewSample:
    sample_dir = root / "head_key_chain" / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    original = sample_dir / f"{sample_id}_original.png"
    generated = sample_dir / f"{sample_id}_head_keychain_front_view.png"
    gold = sample_dir / f"{sample_id}.json"
    original.write_bytes(b"fake-original")
    generated.write_bytes(b"fake-generated")
    gold.write_text("[]", encoding="utf-8")
    return ReviewSample(
        sample_id=sample_id,
        generated_image_path=generated,
        gold_path=gold,
        original_image_path=original,
        category="head_key_chain",
    )


def _prompts(tmp_path: Path) -> AgentPrompts:
    extract_path = tmp_path / "extract.txt"
    compare_path = tmp_path / "compare.txt"
    extract_path.write_text(
        "{{IMAGE_ROLE}} {{MERCHANDISE_CATEGORY}} {{CATEGORY_KEY}} {{CATEGORY_REQUIREMENTS}}",
        encoding="utf-8",
    )
    compare_path.write_text(
        "{{MERCHANDISE_CATEGORY}} {{CATEGORY_KEY}} {{CATEGORY_REQUIREMENTS}}\n"
        "{{SOURCE_VISUAL_JSON}}\n{{GENERATED_VISUAL_JSON}}",
        encoding="utf-8",
    )
    return AgentPrompts(extract_path, extract_path.read_text(), compare_path, compare_path.read_text())


def test_build_multimodal_messages_includes_two_images(tmp_path: Path):
    image_a = tmp_path / "a.png"
    image_b = tmp_path / "b.jpg"
    image_a.write_bytes(b"a")
    image_b.write_bytes(b"b")

    messages = build_multimodal_messages("prompt", [image_a, image_b])

    content = messages[0]["content"]
    assert content[0] == {"type": "text", "text": "prompt"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert len(content) == 3


def test_prompt_rendering_removes_placeholders():
    extract_prompt = build_extraction_prompt(
        "{{IMAGE_ROLE}} {{MERCHANDISE_CATEGORY}} {{CATEGORY_KEY}} {{CATEGORY_REQUIREMENTS}}",
        image_role="source_original",
        category="cake_roll",
    )
    compare_prompt = build_comparison_prompt(
        "{{MERCHANDISE_CATEGORY}} {{CATEGORY_KEY}} {{CATEGORY_REQUIREMENTS}} "
        "{{SOURCE_VISUAL_JSON}} {{GENERATED_VISUAL_JSON}}",
        source_visual={"elements": [{"element": "red eyes"}]},
        generated_visual={"elements": []},
        category="cake_roll",
    )

    assert "source_original" in extract_prompt
    assert "cake_roll" in extract_prompt
    assert "{{" not in extract_prompt
    assert "red eyes" in compare_prompt
    assert "{{" not in compare_prompt


def test_validate_visual_profile_normalizes_elements():
    profile, issues = validate_visual_profile(
        {
            "elements": [
                {
                    "element": "red eyes",
                    "location": "face",
                    "visibility": "clear",
                    "evidence_bbox": ["bad"],
                    "confidence": 2,
                }
            ],
            "global_notes": "notes",
        },
        image_role="source_original",
        category="head_key_chain",
    )

    assert profile["elements"][0]["element_id"] == "e1"
    assert profile["elements"][0]["location"] == ""
    assert profile["elements"][0]["visibility"] == "partial"
    assert profile["elements"][0]["evidence_bbox"] is None
    assert profile["elements"][0]["confidence"] == 1.0
    assert len(issues) == 3


def test_validate_agent_rules_repairs_invalid_results():
    rules, issues = validate_agent_rules(
        [{"element": "eyes", "result": "ok", "location": "head", "confidence": 0.9}]
    )

    assert rules[0]["rule_index"] == 1
    assert rules[0]["result"] == "review"
    assert rules[0]["location"] == "head"
    assert "invalid_result_at_index_1:ok" in issues


def test_profile_for_comparison_filters_not_evaluable_and_empty_elements():
    filtered = profile_for_comparison(
        {
            "elements": [
                {"element": "red eyes", "visibility": "visible"},
                {"element": "帽子", "visibility": "not_evaluable"},
                {"element": "", "visibility": "visible"},
            ]
        }
    )

    assert filtered["elements"] == [{"element": "red eyes", "visibility": "visible"}]


def test_apply_head_only_scope_rules_forces_body_out_of_scope():
    rules = apply_head_only_scope_rules(
        [
            {
                "element": "dress",
                "location": "body",
                "result": "fail",
                "issue_types": ["missing"],
                "confidence": 0.2,
            },
            {"element": "eyes", "location": "head", "result": "pass"},
        ],
        category="head_key_chain",
    )

    assert rules[0]["result"] == "out_of_scope"
    assert rules[0]["issue_types"] == []
    assert rules[0]["confidence"] == 1.0
    assert rules[1]["result"] == "pass"


def test_select_agent_jobs_accepts_category_sample_pairs(tmp_path: Path):
    sample = _write_sample(tmp_path)

    selected = select_agent_jobs(
        [sample],
        jobs=["head_key_chain/sample-1"],
        sample_manifest=None,
        requested_ids=[],
        limit=0,
        fallback_category="dataset_figurine",
    )

    assert selected == [sample]

    with pytest.raises(ValueError, match="category/sample_id"):
        select_agent_jobs(
            [sample],
            jobs=["sample-1"],
            sample_manifest=None,
            requested_ids=[],
            limit=0,
            fallback_category="dataset_figurine",
        )


def test_process_one_dry_run_writes_preview_without_gold_json(tmp_path: Path):
    sample = _write_sample(tmp_path / "input")
    prompts = _prompts(tmp_path)

    status = process_one(
        sample,
        prompts,
        tmp_path / "batch",
        dry_run=True,
        call_fn=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("network")),
    )

    assert status["status"] == "dry_run"
    output_dir = resolve_agent_output_dir(sample, "image_only_v0")
    preview = json.loads(
        (
            tmp_path
            / "batch"
            / "_sample_aux"
            / "image_only_v0"
            / "head_key_chain"
            / "sample-1"
            / "request_preview.json"
        ).read_text(encoding="utf-8")
    )
    assert preview["source_json_used_for_inference"] is False
    assert str(sample.gold_path) not in json.dumps(preview, ensure_ascii=False)
    assert (output_dir / "status.json").exists()


def test_process_one_can_write_review_v1_directory(tmp_path: Path):
    sample = _write_sample(tmp_path / "input")
    prompts = _prompts(tmp_path)

    status = process_one(
        sample,
        prompts,
        tmp_path / "batch",
        dry_run=True,
        sample_agent_root_name="review_v1",
        sample_output_parent="_review",
        call_fn=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("network")),
    )

    output_dir = resolve_agent_output_dir(
        sample,
        "review_v1",
        sample_output_parent="_review",
    )
    assert status["status"] == "dry_run"
    assert output_dir == sample.generated_image_path.parent / "_review" / "review_v1"
    assert (output_dir / "status.json").exists()
    assert not (sample.generated_image_path.parent / "_agent" / "review_v1").exists()


def test_process_one_real_call_writes_image_only_prediction(tmp_path: Path):
    sample = _write_sample(tmp_path / "input")
    prompts = _prompts(tmp_path)
    responses = iter(
        [
            json.dumps(
                {
                    "elements": [
                        {
                            "element_id": "s1",
                            "element": "red eyes",
                            "location": "head",
                            "visibility": "visible",
                            "confidence": 0.9,
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "elements": [
                        {
                            "element_id": "g1",
                            "element": "red eyes",
                            "location": "head",
                            "visibility": "visible",
                            "confidence": 0.9,
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "rules": [
                        {
                            "source_element_id": "s1",
                            "generated_element_id": "g1",
                            "element": "red eyes",
                            "location": "head",
                            "image_grounded": True,
                            "description_correct": True,
                            "issue_types": [],
                            "observed_description": "eyes preserved",
                            "confidence": 0.95,
                            "result": "pass",
                        }
                    ],
                    "extra_elements": [],
                }
            ),
        ]
    )

    status = process_one(
        sample,
        prompts,
        tmp_path / "batch",
        dry_run=False,
        api_key="unused",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-vl-max",
        call_fn=lambda **_kwargs: next(responses),
    )

    output_dir = resolve_agent_output_dir(sample, "image_only_v0")
    prediction = json.loads((output_dir / "prediction.json").read_text(encoding="utf-8"))
    assert status["status"] == "succeeded"
    assert prediction["inputs"]["source_json_used_for_inference"] is False
    assert prediction["overall_decision"] == "pass"
    assert (output_dir / "source_visual.json").exists()
    assert (output_dir / "generated_visual.json").exists()
    assert (output_dir / "qc.csv").exists()
