"""Tests for compare_predictions.py — event matching, metrics, and confidence parsing."""

from vlm.scripts.supervise.compare_predictions import (
    _parse_confidence,
    _infer_attribute,
    event_key,
    compute_metrics,
    match_events,
    extract_prediction_events,
    extract_gold_events,
    ACCEPTANCE_ISSUE_TYPES,
)


# ---------------------------------------------------------------------------
# _parse_confidence
# ---------------------------------------------------------------------------

def test_parse_confidence_float():
    assert _parse_confidence(0.8) == 0.8

def test_parse_confidence_int():
    assert _parse_confidence(1) == 1.0

def test_parse_confidence_string_high():
    assert _parse_confidence("high") == 0.95

def test_parse_confidence_string_very_high():
    assert _parse_confidence("very_high") == 0.95

def test_parse_confidence_string_medium():
    assert _parse_confidence("medium") == 0.75

def test_parse_confidence_string_low():
    assert _parse_confidence("low") == 0.5

def test_parse_confidence_unknown_string():
    assert _parse_confidence("excellent") == 1.0

def test_parse_confidence_none():
    assert _parse_confidence(None) == 1.0


# ---------------------------------------------------------------------------
# _infer_attribute
# ---------------------------------------------------------------------------

def test_infer_attribute_wrong_color():
    assert _infer_attribute("anything", "wrong color") == "color"

def test_infer_attribute_wrong_material():
    assert _infer_attribute("anything", "wrong material") == "material"

def test_infer_attribute_wrong_shape():
    assert _infer_attribute("anything", "wrong shape") == "shape"

def test_infer_attribute_color_in_rule_id():
    assert _infer_attribute("hair_color", "paired box completion") == "color"

def test_infer_attribute_material_in_rule_id():
    assert _infer_attribute("fabric_material", "paired box completion") == "material"

def test_infer_attribute_other():
    assert _infer_attribute("unknown_rule", "paired box completion") == "other"


# ---------------------------------------------------------------------------
# event_key
# ---------------------------------------------------------------------------

def _make_event(**kwargs):
    base = {"sample_id": "s1", "category": "backpack", "issue_type": "wrong color",
            "rule_id": "hair_color", "view": "front", "element_name": "hair_color"}
    base.update(kwargs)
    return base

def test_event_key_strict_includes_view_and_rule():
    e = _make_event()
    key = event_key(e, strict=True)
    assert key == ("s1", "backpack", "wrong color", "hair_color", "front")

def test_event_key_relaxed_drops_view_and_rule():
    e = _make_event()
    key = event_key(e, strict=False)
    assert key == ("s1", "backpack", "wrong color", "hair_color")

def test_event_key_different_view_differs_in_strict():
    e1 = _make_event(view="front")
    e2 = _make_event(view="side")
    assert event_key(e1, strict=True) != event_key(e2, strict=True)

def test_event_key_different_view_same_in_relaxed():
    e1 = _make_event(view="front")
    e2 = _make_event(view="side")
    assert event_key(e1, strict=False) == event_key(e2, strict=False)


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

def test_compute_metrics_perfect():
    matched = [("p", "g"), ("p2", "g2")]
    result = compute_metrics(matched, [], [])
    assert result["tp"] == 2
    assert result["fp"] == 0
    assert result["fn"] == 0
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["f1"] == 1.0

def test_compute_metrics_all_fp():
    result = compute_metrics([], [{"a": 1}, {"b": 2}], [])
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0
    assert result["f1"] == 0.0

def test_compute_metrics_all_fn():
    result = compute_metrics([], [], [{"a": 1}])
    assert result["recall"] == 0.0
    assert result["precision"] == 0.0

def test_compute_metrics_mixed():
    # TP=1, FP=1, FN=1
    result = compute_metrics([("p", "g")], [{"x": 1}], [{"y": 1}])
    assert result["tp"] == 1
    assert result["fp"] == 1
    assert result["fn"] == 1
    assert abs(result["precision"] - 0.5) < 1e-9
    assert abs(result["recall"] - 0.5) < 1e-9
    assert abs(result["f1"] - 0.5) < 1e-9

def test_compute_metrics_empty():
    result = compute_metrics([], [], [])
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0
    assert result["f1"] == 0.0


# ---------------------------------------------------------------------------
# match_events
# ---------------------------------------------------------------------------

def test_match_events_exact_match():
    pred = [_make_event()]
    gold = [_make_event()]
    matched, fp, fn = match_events(pred, gold, strict=True)
    assert len(matched) == 1
    assert len(fp) == 0
    assert len(fn) == 0

def test_match_events_surplus_prediction_is_fp():
    pred = [_make_event(), _make_event()]
    gold = [_make_event()]
    matched, fp, fn = match_events(pred, gold, strict=True)
    assert len(matched) == 1
    assert len(fp) == 1
    assert len(fn) == 0

def test_match_events_surplus_gold_is_fn():
    pred = [_make_event()]
    gold = [_make_event(), _make_event()]
    matched, fp, fn = match_events(pred, gold, strict=True)
    assert len(matched) == 1
    assert len(fp) == 0
    assert len(fn) == 1

def test_match_events_no_overlap():
    pred = [_make_event(rule_id="hair_color")]
    gold = [_make_event(rule_id="eye_color")]
    matched, fp, fn = match_events(pred, gold, strict=True)
    assert len(matched) == 0
    assert len(fp) == 1
    assert len(fn) == 1

def test_match_events_empty_inputs():
    matched, fp, fn = match_events([], [], strict=True)
    assert matched == [] and fp == [] and fn == []


# ---------------------------------------------------------------------------
# extract_prediction_events (Lane A filtering)
# ---------------------------------------------------------------------------

def test_extract_prediction_events_only_acceptance_issues():
    pred_rows = [{
        "rule_id": "hair_color",
        "value": "red",
        "front_status": "wrong color",
        "side_status": "correct",
        "back_status": "correct",
        "confidence": "high",
        "reason": "",
    }]
    events = extract_prediction_events(pred_rows, "s1", "backpack")
    assert len(events) == 1
    assert events[0]["view"] == "front"
    assert events[0]["issue_type"] == "wrong color"

def test_extract_prediction_events_filters_correct():
    pred_rows = [{
        "rule_id": "eye_color",
        "value": "blue",
        "front_status": "correct",
        "side_status": "correct",
        "back_status": "correct",
        "confidence": 1.0,
        "reason": "",
    }]
    events = extract_prediction_events(pred_rows, "s1", "backpack")
    assert len(events) == 0

def test_extract_prediction_events_multi_view():
    pred_rows = [{
        "rule_id": "outfit_color",
        "value": "blue",
        "front_status": "wrong color",
        "side_status": "wrong shape",
        "back_status": "correct",
        "confidence": "medium",
        "reason": "mismatch",
    }]
    events = extract_prediction_events(pred_rows, "s1", "plush")
    assert len(events) == 2
    views = {e["view"] for e in events}
    assert views == {"front", "side"}


# ---------------------------------------------------------------------------
# extract_gold_events (Lane A filtering + sample filtering)
# ---------------------------------------------------------------------------

def _gold_row(sample_id="s1", category="backpack", issue_type="wrong color",
              rule_id="r1", view="front"):
    return {"sample_id": sample_id, "category": category,
            "issue_type": issue_type, "rule_id": rule_id, "view": view,
            "attribute": "", "element_name": rule_id, "confidence": "1.0", "reason": ""}

def test_extract_gold_events_filters_by_sample():
    gold = [_gold_row("s1"), _gold_row("s2")]
    events = extract_gold_events(gold, "s1", "backpack")
    assert len(events) == 1
    assert events[0]["sample_id"] == "s1"

def test_extract_gold_events_filters_lane_b():
    gold = [_gold_row(issue_type="missing")]
    events = extract_gold_events(gold, "s1", "backpack")
    assert len(events) == 0

def test_extract_gold_events_all_acceptance_types():
    gold = [_gold_row(issue_type=t) for t in ACCEPTANCE_ISSUE_TYPES]
    events = extract_gold_events(gold, "s1", "backpack")
    assert len(events) == len(ACCEPTANCE_ISSUE_TYPES)

