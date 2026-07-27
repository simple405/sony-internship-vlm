"""Tests for align_human_findings_to_atomic_rules.py — tokenisation, scoring, candidate typing."""

from vlm.scripts.supervise.align_human_findings_to_atomic_rules import (
    tokens,
    finding_text,
    score_candidate,
    candidate_type,
    append_warning,
    align_rows,
    TOKEN_ALIASES,
    STOPWORDS,
)


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------

def test_tokens_basic():
    result = tokens("red hair")
    assert "red" in result
    assert "hair" in result

def test_tokens_removes_stopwords():
    result = tokens("the hair")
    assert "the" not in result
    assert "hair" in result

def test_tokens_alias_normalization():
    # "shoe" → "footwear"
    result = tokens("shoe")
    assert "footwear" in result
    assert "shoe" not in result

def test_tokens_alias_shoes_plural():
    result = tokens("shoes")
    assert "footwear" in result

def test_tokens_alias_colour():
    result = tokens("colour")
    assert "color" in result

def test_tokens_lowercases():
    result = tokens("RED")
    assert "red" in result

def test_tokens_empty():
    assert tokens("") == set()

def test_tokens_punctuation_as_separator():
    result = tokens("red,hair")
    assert "red" in result and "hair" in result

def test_tokens_all_stopwords():
    result = tokens("the a an is are of")
    assert result == set()


# ---------------------------------------------------------------------------
# finding_text
# ---------------------------------------------------------------------------

def test_finding_text_uses_all_fields():
    row = {"human_rule_name": "hair color", "element_name": "hair",
           "feature_key": "color", "attribute": "red",
           "expected_value": "dark red", "expected_from_2d": "",
           "observed_value": "pink", "observed_in_multiview": "pink",
           "issue_type": "wrong color"}
    text = finding_text(row)
    assert "hair color" in text
    assert "dark red" in text
    assert "wrong color" in text

def test_finding_text_skips_empty_fields():
    row = {"human_rule_name": "hair color", "element_name": "",
           "expected_value": "", "issue_type": "wrong color"}
    text = finding_text(row)
    assert "hair color" in text
    # Empty fields shouldn't produce double spaces that break matching
    assert "  " not in text.strip()


# ---------------------------------------------------------------------------
# score_candidate
# ---------------------------------------------------------------------------

def test_score_candidate_perfect_overlap():
    finding = {"human_rule_name": "hair color", "element_name": "hair",
                "feature_key": "color", "attribute": "",
                "expected_value": "red", "expected_from_2d": "",
                "observed_value": "", "observed_in_multiview": "", "issue_type": "wrong color"}
    rule = {"rule_id": "hair_color", "atomic_value": "red"}
    score, reason = score_candidate(finding, rule)
    # Strong overlap + value bonus → score should be high
    assert score > 0.5
    assert "value_bonus=0.15" in reason

def test_score_candidate_no_overlap():
    finding = {"human_rule_name": "shoe size", "element_name": "shoe",
                "feature_key": "size", "attribute": "",
                "expected_value": "large", "expected_from_2d": "",
                "observed_value": "", "observed_in_multiview": "", "issue_type": "wrong shape"}
    rule = {"rule_id": "hair_color", "atomic_value": "red"}
    score, reason = score_candidate(finding, rule)
    assert score < 0.3

def test_score_candidate_value_bonus_applied():
    finding = {"human_rule_name": "eye color", "element_name": "eye",
                "feature_key": "color", "attribute": "",
                "expected_value": "blue", "expected_from_2d": "",
                "observed_value": "", "observed_in_multiview": "", "issue_type": "wrong color"}
    rule = {"rule_id": "eye_color", "atomic_value": "deep blue"}
    score, reason = score_candidate(finding, rule)
    assert "value_bonus=0.15" in reason


# ---------------------------------------------------------------------------
# candidate_type
# ---------------------------------------------------------------------------

def test_candidate_type_exact_match():
    human = {"a", "b", "c"}
    rule = {"a", "b", "c"}
    assert candidate_type(0.90, human, rule) == "exact_match_candidate"

def test_candidate_type_semantic():
    human = {"hair", "red"}
    rule = {"hair", "color"}
    assert candidate_type(0.60, human, rule) == "semantic_equivalent_candidate"

def test_candidate_type_broader_or_narrower():
    # human is subset of rule
    human = {"hair"}
    rule = {"hair", "red", "long"}
    assert candidate_type(0.20, human, rule) == "broader_or_narrower_candidate"

def test_candidate_type_related():
    human = {"hair", "red"}
    rule = {"eye", "blue"}
    assert candidate_type(0.30, human, rule) == "related_candidate"

def test_candidate_type_low_confidence():
    human = {"hair", "red"}
    rule = {"eye", "blue"}
    assert candidate_type(0.10, human, rule) == "low_confidence_candidate"


# ---------------------------------------------------------------------------
# append_warning
# ---------------------------------------------------------------------------

def test_append_warning_first():
    assert append_warning("", "warning_a") == "warning_a"

def test_append_warning_adds_to_existing():
    result = append_warning("warning_a", "warning_b")
    assert "warning_a" in result
    assert "warning_b" in result

def test_append_warning_idempotent():
    result = append_warning("warning_a", "warning_a")
    assert result.count("warning_a") == 1

def test_append_warning_semicolon_separated():
    result = append_warning("a", "b")
    assert result == "a;b"


# ---------------------------------------------------------------------------
# align_rows — integration
# ---------------------------------------------------------------------------

def test_align_rows_no_rules_returns_no_match():
    findings = [{"sample_id": "s1", "category": "backpack", "finding_id": "f1",
                  "human_rule_name": "hair color", "element_name": "hair",
                  "feature_key": "color", "attribute": "",
                  "expected_value": "red", "expected_from_2d": "",
                  "observed_value": "", "observed_in_multiview": "", "issue_type": "wrong color"}]
    candidates, review_queue = align_rows(findings, {}, top_k=5, min_score=0.18)
    assert len(candidates) == 1
    assert candidates[0]["candidate_match_type"] == "no_match_candidate"

def test_align_rows_finds_candidates():
    findings = [{"sample_id": "s1", "category": "backpack", "finding_id": "f1",
                  "human_rule_name": "hair color", "element_name": "hair",
                  "feature_key": "color", "attribute": "",
                  "expected_value": "red", "expected_from_2d": "",
                  "observed_value": "", "observed_in_multiview": "", "issue_type": "wrong color"}]
    registry = {("backpack", "s1"): [{"rule_id": "hair_color", "atomic_value": "red"}]}
    candidates, review_queue = align_rows(findings, registry, top_k=5, min_score=0.0)
    assert len(candidates) >= 1
    assert candidates[0]["atomic_rule_id"] == "hair_color"
