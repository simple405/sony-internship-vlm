"""Tests for assign_merchandise_categories.py — score_row, candidate_categories, helpers."""

from collections import OrderedDict
from vlm.scripts.data.assign_merchandise_categories import (
    has,
    as_float,
    token_set,
    has_front_view,
    score_row,
    candidate_categories,
    key_tags,
    CATEGORIES,
)


# ---------------------------------------------------------------------------
# has / as_float / token_set / has_front_view
# ---------------------------------------------------------------------------

def test_has_present():
    assert has({"full_body", "solo"}, "full_body") is True

def test_has_absent():
    assert has({"full_body"}, "sitting") is False

def test_has_any_match():
    assert has({"standing"}, "sitting", "standing") is True

def test_as_float_valid():
    assert as_float("3.5") == 3.5

def test_as_float_int_string():
    assert as_float("42") == 42.0

def test_as_float_invalid():
    assert as_float("n/a") == 0.0

def test_as_float_none():
    assert as_float(None) == 0.0

def test_token_set_splits_on_space():
    row = {"tags": "full_body solo standing"}
    assert token_set(row) == {"full_body", "solo", "standing"}

def test_token_set_missing_tags():
    assert token_set({}) == set()

def test_has_front_view_true():
    assert has_front_view({"looking_at_viewer"}) is True

def test_has_front_view_false():
    assert has_front_view({"from_behind"}) is False


# ---------------------------------------------------------------------------
# score_row — representative tag combinations
# ---------------------------------------------------------------------------

def _row(**tags_dict):
    """Build a manifest row with the given tag booleans as a space-joined tags string."""
    tags = " ".join(k for k, v in tags_dict.items() if v)
    return {"tags": tags, "actual_width": "", "actual_height": "", "colorfulness": "0"}

def test_score_row_all_categories_present():
    scores, reasons = score_row(_row())
    assert set(scores.keys()) == set(CATEGORIES)

def test_score_row_sitting_boosts_qsit():
    scores_sitting, _ = score_row(_row(full_body=True, standing=False, sitting=True,
                                        looking_at_viewer=True))
    scores_standing, _ = score_row(_row(full_body=True, standing=True, sitting=False,
                                         looking_at_viewer=True))
    assert scores_sitting["dataset_QSitFigures"] > scores_standing["dataset_QSitFigures"]

def test_score_row_standing_boosts_plush():
    scores_standing, _ = score_row(_row(full_body=True, standing=True, looking_at_viewer=True))
    scores_not, _ = score_row(_row(full_body=True, standing=False, looking_at_viewer=True))
    assert scores_standing["plush"] > scores_not["plush"]

def test_score_row_weapon_boosts_figurine():
    scores_weapon, _ = score_row(_row(weapon=True, full_body=True, looking_at_viewer=True))
    scores_no_weapon, _ = score_row(_row(full_body=True, looking_at_viewer=True))
    assert scores_weapon["dataset_figurine"] > scores_no_weapon["dataset_figurine"]

def test_score_row_weapon_hurts_cake_roll():
    scores_weapon, _ = score_row(_row(weapon=True, full_body=True, looking_at_viewer=True))
    scores_no_weapon, _ = score_row(_row(full_body=True, looking_at_viewer=True))
    assert scores_weapon["cake_roll"] < scores_no_weapon["cake_roll"]

def test_score_row_not_full_body_forces_head_only():
    """Without full_body+front_view, full-body categories should be capped very low."""
    scores, reasons = score_row(_row(full_body=False, looking_at_viewer=False))
    # Full-body categories are capped to -100 when neither full_body nor front_view
    for cat in ("plush", "dataset_QSitFigures", "dataset_figurine"):
        assert scores[cat] <= -100

def test_score_row_simple_bg_boosts_cake_roll():
    scores_clean, _ = score_row(_row(simple_background=True))
    scores_complex, _ = score_row(_row(simple_background=False))
    assert scores_clean["cake_roll"] > scores_complex["cake_roll"]

def test_score_row_returns_reasons_list():
    _, reasons = score_row(_row(full_body=True, looking_at_viewer=True))
    assert isinstance(reasons, list)


# ---------------------------------------------------------------------------
# candidate_categories
# ---------------------------------------------------------------------------

def test_candidate_categories_returns_at_least_3():
    scores = OrderedDict((cat, 10) for cat in CATEGORIES)
    candidates = candidate_categories(scores)
    assert len(candidates) >= 3

def test_candidate_categories_max_4():
    scores = OrderedDict((cat, 100) for cat in CATEGORIES)
    candidates = candidate_categories(scores)
    assert len(candidates) <= 4

def test_candidate_categories_top_score_first():
    scores = OrderedDict(zip(CATEGORIES, [5, 200, 3, 4, 6, 7]))
    candidates = candidate_categories(scores)
    # The category with score 200 should be first
    highest = max(scores, key=lambda k: scores[k])
    assert candidates[0] == highest

def test_candidate_categories_all_zero_still_gives_3():
    scores = OrderedDict((cat, 0) for cat in CATEGORIES)
    candidates = candidate_categories(scores)
    assert len(candidates) == 3


# ---------------------------------------------------------------------------
# key_tags
# ---------------------------------------------------------------------------

def test_key_tags_includes_relevant_tags():
    row = {"tags": "full_body standing 1girl dress official_art"}
    result = key_tags(row)
    assert "full_body" in result
    assert "standing" in result
    assert "official_art" in result

def test_key_tags_excludes_irrelevant_tags():
    row = {"tags": "some_random_tag another_tag"}
    result = key_tags(row)
    # Should be empty or contain none of the useful tags
    useful = {"full_body", "standing", "sitting", "dress", "uniform"}
    assert not any(tag in result for tag in useful)
