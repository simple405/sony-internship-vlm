"""Tests for evaluate_element_extraction.py — pure scoring functions, no API calls."""

from vlm.scripts.supervise.evaluate_element_extraction import (
    compact_text,
    char_jaccard,
    split_composite_name,
    relation_score,
    conflict_audit,
    find_keyword_families,
    OBJECT_KEYWORDS,
    ATTRIBUTE_KEYWORDS,
)


# ---------------------------------------------------------------------------
# compact_text
# ---------------------------------------------------------------------------

def test_compact_text_strips_punctuation():
    assert "，" not in compact_text("红色，头发")

def test_compact_text_strips_ascii_words():
    # ASCII words like "accessory" should be removed
    result = compact_text("accessory 红色")
    assert "accessory" not in result
    assert "红色" in result or compact_text("红色") in result

def test_compact_text_lowercases():
    assert compact_text("RED") == compact_text("red")

def test_compact_text_empty():
    assert compact_text("") == ""


# ---------------------------------------------------------------------------
# char_jaccard
# ---------------------------------------------------------------------------

def test_char_jaccard_identical():
    assert char_jaccard("红色头发", "红色头发") == 1.0

def test_char_jaccard_disjoint():
    # "abc" vs "def" — completely disjoint char sets
    score = char_jaccard("abc", "def")
    assert score == 0.0

def test_char_jaccard_partial():
    # "红色头发" chars: {红,色,头,发}; "黑色眼睛" chars: {黑,色,眼,睛}
    # intersection={色}, jaccard=1/7≈0.14, overlap=1/4=0.25 → max=0.25
    score = char_jaccard("红色头发", "黑色眼睛")
    assert 0.0 < score < 1.0

def test_char_jaccard_subset_gets_high_overlap():
    # When one is a subset of the other, overlap / min_len = 1.0
    score = char_jaccard("红色", "红色头发")
    assert score > 0.5

def test_char_jaccard_empty_left():
    assert char_jaccard("", "something") == 0.0

def test_char_jaccard_empty_right():
    assert char_jaccard("something", "") == 0.0

def test_char_jaccard_symmetry():
    a, b = "红色头发", "黑色眼睛"
    assert abs(char_jaccard(a, b) - char_jaccard(b, a)) < 1e-9


# ---------------------------------------------------------------------------
# split_composite_name
# ---------------------------------------------------------------------------

def test_split_composite_simple():
    parts = split_composite_name("黑色腰带与金色链条")
    assert len(parts) == 2
    assert "黑色腰带" in parts
    assert "金色链条" in parts

def test_split_composite_no_separator():
    parts = split_composite_name("红色头发")
    assert parts == ["红色头发"]

def test_split_composite_multiple_separators():
    parts = split_composite_name("A与B与C")
    assert len(parts) == 3

def test_split_composite_strips_whitespace():
    parts = split_composite_name("A 与 B")
    assert all(p == p.strip() for p in parts)


# ---------------------------------------------------------------------------
# find_keyword_families
# ---------------------------------------------------------------------------

def test_find_keyword_families_hair():
    families = find_keyword_families("长发", OBJECT_KEYWORDS)
    assert "hair" in families

def test_find_keyword_families_boots():
    families = find_keyword_families("靴子", OBJECT_KEYWORDS)
    assert "boots" in families

def test_find_keyword_families_color_black():
    families = find_keyword_families("黑色外套", ATTRIBUTE_KEYWORDS["color"])
    assert "black" in families

def test_find_keyword_families_no_match():
    families = find_keyword_families("xyz unknown", OBJECT_KEYWORDS)
    # Should not crash, may return empty set
    assert isinstance(families, set)


# ---------------------------------------------------------------------------
# conflict_audit
# ---------------------------------------------------------------------------

def test_conflict_audit_no_conflict():
    notes, tolerated = conflict_audit("红色头发", "红色头发")
    assert notes == []

def test_conflict_audit_color_conflict():
    notes, tolerated = conflict_audit("红色外套", "蓝色外套")
    assert any("color conflict" in n for n in notes)

def test_conflict_audit_shape_conflict():
    # long vs short is a defined conflict pair
    notes, tolerated = conflict_audit("长发", "短发")
    assert any("shape conflict" in n for n in notes)

def test_conflict_audit_accessory_material_not_counted():
    # "金属搭扣" is an accessory detail, should be stripped before material check
    notes, tolerated = conflict_audit("布质腰带金属搭扣", "布质腰带")
    # After stripping accessory material context, no material conflict
    assert not any("material conflict" in n for n in notes)


# ---------------------------------------------------------------------------
# relation_score (no API — scorer=None)
# ---------------------------------------------------------------------------

def test_relation_score_identical_elements():
    el = {"name": "红色头发", "value": "长直发", "category": "hair", "attributes": {}}
    score = relation_score(el, el, scorer=None)
    assert score > 0.8

def test_relation_score_different_elements():
    gold = {"name": "红色头发", "value": "", "category": "hair", "attributes": {}}
    pred = {"name": "黑色靴子", "value": "", "category": "boots", "attributes": {}}
    score = relation_score(gold, pred, scorer=None)
    assert score < 0.5

def test_relation_score_nonnegative():
    gold = {"name": "A", "value": "", "category": "", "attributes": {}}
    pred = {"name": "B", "value": "", "category": "", "attributes": {}}
    assert relation_score(gold, pred, scorer=None) >= 0.0
