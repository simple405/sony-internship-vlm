"""Audit source-2D element extraction against the small human pilot set.

The Stage 1 research target is not exact element-count matching. A useful
extraction may split one human element into multiple visible parts, but it must:

1. cover every human gold element,
2. avoid obvious color/material/shape conflicts, and
3. flag extra details that need human visibility review.

Example:
    python -m vlm.scripts.supervise.evaluate_element_extraction
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from vlm.scripts.supervise.embedding_scorer import EmbeddingScorer
from vlm.scripts.supervise.postprocess_color_family_verdicts import (
    RULE_NAME as COLOR_FAMILY_RULE_NAME,
    TOLERATED_COLOR_GROUPS,
    extract_color_families,
)


DEFAULT_GOLD_ROOT = Path("vlm/data/SN_6期动漫数据标注")
DEFAULT_PRED_ROOT = Path("vlm/data/element_extraction_results")
DEFAULT_REPORT_PATH = Path("vlm/data/element_extraction_results/evaluation_report.json")
DEFAULT_EMBED_CACHE_PATH = Path("vlm/tmp/embedding_cache.json")
from vlm.scripts._paths import API_ENV_FILE, load_api_env

DEFAULT_ENV_FILE = API_ENV_FILE

# Cosine similarity above this counts as "semantically the same real-world detail"
# when deciding whether an extra prediction is a hallucination vs. a valid split
# of a composite gold name (e.g. gold "黑色过膝袜与棕色靴子" vs pred "黑色过膝袜").
EMBED_SUPPORTED_THRESHOLD = 0.75


OBJECT_KEYWORDS = {
    "skin": ["皮肤", "肤色", "身体"],
    "hair": ["头发", "发型", "发色", "长发", "短发", "卷发", "直发", "马尾"],
    "eyes": ["眼睛", "眼部", "瞳孔"],
    "ears": ["耳朵", "尖耳"],
    "headwear": ["头巾", "帽子", "便帽", "头饰", "头上戴", "发饰"],
    "coat": ["外衣", "外套", "长外套", "开襟"],
    "shirt": ["内衬", "内搭", "衬衫", "上衣"],
    "belt": ["腰带", "背带", "肩带"],
    "pants": ["裤子", "长裤", "下装", "裤脚", "短裤"],
    "leg_wraps": ["绑腿", "腿部绑带", "小腿处", "小腿"],
    "boots": ["靴子", "短靴", "鞋靴"],
    "wrist_guard": ["护腕", "手臂绑带", "前臂", "双臂"],
    "fur_trim": ["毛皮", "毛绒", "毛边", "包边", "滚边"],
    # --- algo-v2 additions: common item types previously missing object-family coverage ---
    "gloves": ["手套"],
    "shoes": ["皮鞋", "鞋子", "运动鞋", "高跟鞋", "凉鞋", "球鞋", "布鞋", "鞋"],
    "bracelet": ["手环", "手镯", "手链", "手腕饰"],
    "necklace": ["项链", "项圈", "颈链"],
    "glasses": ["眼镜", "墨镜", "太阳镜"],
    "tail": ["尾巴", "猫尾", "兽尾", "狐狸尾", "龙尾"],
    "claws": ["爪子", "爪足", "趾甲", "兽爪", "脚爪"],
    # --- algo-v3 additions: high-frequency anime item categories missing from prior versions ---
    "skirt": ["裙子", "短裙", "长裙", "百褶裙", "蓬蓬裙", "半身裙", "连衣裙", "洋装"],
    "necktie": ["领结", "领带", "领饰", "蝴蝶结领"],
    "wing": ["翅膀", "羽翼", "双翼", "天使翅"],
    "horn": ["兽角", "犄角", "头角"],
    "weapon": ["武器", "剑", "刀", "弓", "法杖", "魔杖", "长枪"],
    "cloak": ["斗篷", "披风", "披肩", "披巾"],
}

ATTRIBUTE_KEYWORDS = {
    "color": {
        "black": ["黑色", "黑"],
        "blue": ["蓝色", "蓝"],
        "brown_tan": ["棕色", "棕", "褐色", "咖啡", "卡其", "驼色", "浅棕", "深棕", "黄褐", "土黄", "米色", "米白", "杏色"],
        "green": ["绿色", "绿"],
        "grey": ["灰色", "灰"],
        "pink": ["粉色", "粉"],
        "purple": ["紫色", "紫"],
        "red": ["红色", "红"],
        "white": ["白色", "白", "米白"],
        "yellow": ["黄色", "金色", "黄", "金"],
    },
    "material": {
        "cloth": ["布", "布质", "织物", "棉", "衬衫"],
        "fur": ["毛皮", "毛绒", "皮毛"],
        "leather": ["皮革", "皮靴", "软皮"],
        "metal": ["金属", "铁", "银", "铜"],
    },
    "shape": {
        # Use explicit compound words — bare "长"/"短" cause false positives in measurement
        # phrases like "长度在膝盖以上" (length above knee) or "短暂" (brief).
        "long": ["长款", "长裤", "长外套", "长发", "长袖", "长裙", "长靴", "长筒", "长辫"],
        "short": ["短款", "短靴", "短发", "短裙", "短裤", "短袖", "短外套"],
        "wide": ["宽松", "宽"],
        "narrow": ["窄款", "修身", "紧身", "贴身"],
        "pointed": ["尖", "尖耳"],
        "round": ["圆形", "圆润"],
        "wrapped": ["缠绕", "包裹", "包边", "滚边", "绑带"],
    },
}
SHAPE_CONFLICT_PAIRS = {
    frozenset(("long", "short")),
    frozenset(("wide", "narrow")),
    frozenset(("pointed", "round")),
}
DETAIL_OBJECTS = {"fur_trim", "leg_wraps"}


def is_workflow_tolerated_color_set(families: set[str]) -> bool:
    """Use the pilot color-family groups, but in the Stage 1 audit as a loose review gate."""
    if len(families) < 2:
        return False
    return any(families.issubset(group) for group in TOLERATED_COLOR_GROUPS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit extracted elements against human pilot elements.")
    parser.add_argument("--gold-root", type=Path, default=DEFAULT_GOLD_ROOT)
    parser.add_argument("--pred-root", type=Path, default=DEFAULT_PRED_ROOT)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--coverage-threshold", type=float, default=0.32)
    parser.add_argument(
        "--match-threshold",
        type=float,
        dest="coverage_threshold",
        help="Backward-compatible alias for --coverage-threshold.",
    )
    parser.add_argument(
        "--use-embeddings",
        action="store_true",
        default=True,
        help="Boost relation_score with DashScope text-embedding-v3 cosine similarity.",
    )
    parser.add_argument(
        "--embed-cache-path",
        type=Path,
        default=DEFAULT_EMBED_CACHE_PATH,
        help="Path to the embedding disk cache JSON (avoids re-calling the API).",
    )
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


_ASCII_RE = re.compile(r'[a-zA-Z]+')
_COMPOSITE_SEPARATOR = re.compile(r'\s*与\s*')


def compact_text(value: str) -> str:
    # Strip English category strings (e.g. "accessory", "footwear") that appear in
    # structured pred JSON but never in human gold text — they would pollute the
    # character-level Jaccard intersection and lower scores spuriously.
    value = _ASCII_RE.sub("", value)
    return re.sub(r"[\s，。、""''：:；;,.!！?？/\\|（）()\[\]{}<>《》-]+", "", value.lower())


def char_jaccard(left: str, right: str) -> float:
    left_set = set(compact_text(left))
    right_set = set(compact_text(right))
    if not left_set or not right_set:
        return 0.0
    intersection = len(left_set & right_set)
    jaccard = intersection / len(left_set | right_set)
    overlap = intersection / min(len(left_set), len(right_set))
    return max(jaccard, overlap)


def element_text(element: dict[str, Any]) -> str:
    attributes = element.get("attributes")
    attr_text = ""
    if isinstance(attributes, dict):
        attr_text = " ".join(str(value) for value in attributes.values())
    return f"{element.get('name', '')} {element.get('value', '')} {element.get('category', '')} {attr_text}"


def element_name(element: dict[str, Any]) -> str:
    return str(element.get("name", ""))


def split_composite_name(name: str) -> list[str]:
    """Split '黑色短裙与腰带' → ['黑色短裙', '腰带']."""
    parts = _COMPOSITE_SEPARATOR.split(name)
    return [p.strip() for p in parts if p.strip()]


def embed_text(element: dict[str, Any]) -> str:
    parts = [str(element.get("name", "")), str(element.get("value", ""))]
    return " ".join(p for p in parts if p).strip()


def find_keyword_families(text: str, mapping: dict[str, list[str]]) -> set[str]:
    compacted = compact_text(text)
    families = set()
    for family, keywords in mapping.items():
        if any(compact_text(keyword) in compacted for keyword in keywords):
            families.add(family)
    return families


def extract_attributes(text: str) -> dict[str, set[str]]:
    return {
        attr_type: find_keyword_families(text, family_map)
        for attr_type, family_map in ATTRIBUTE_KEYWORDS.items()
    }


def object_info(element: dict[str, Any], *, include_detail_from_full_text: bool) -> dict[str, set[str]]:
    primary = find_keyword_families(element_name(element), OBJECT_KEYWORDS)
    full = find_keyword_families(element_text(element), OBJECT_KEYWORDS)
    if include_detail_from_full_text:
        primary = primary | (full & DETAIL_OBJECTS)
    objects = primary or full
    return {
        "primary": primary,
        "secondary": full - primary,
        "all": objects,
    }


def relation_score(gold: dict[str, Any], pred: dict[str, Any], *, scorer: EmbeddingScorer | None = None) -> float:
    gold_text = element_text(gold)
    pred_text = element_text(pred)
    score = char_jaccard(gold_text, pred_text)
    # Name similarity as an independent floor: verbose value fields can dilute the
    # full-text Jaccard even when names are near-identical.  A strong name match
    # (e.g. gold="白色手套" vs pred="白色手套") should always qualify, regardless of
    # how much description text each side carries.
    # Guard: require at least 2 shared chars so a single common character (e.g. "短"
    # shared by "短裤" and "绿色百褶短裙") cannot produce a spurious high name-score.
    gold_name_chars = set(compact_text(element_name(gold)))
    pred_name_chars = set(compact_text(element_name(pred)))
    if len(gold_name_chars & pred_name_chars) >= 2:
        name_score = char_jaccard(element_name(gold), element_name(pred))
        score = max(score, name_score)
    gold_objects = object_info(gold, include_detail_from_full_text=False)["all"]
    pred_objects = object_info(pred, include_detail_from_full_text=True)
    primary_shared = gold_objects & pred_objects["primary"]
    secondary_shared = gold_objects & pred_objects["secondary"]
    if primary_shared:
        score = max(score, min(0.9, 0.62 + len(primary_shared) * 0.08))
    elif secondary_shared:
        score = max(score, min(0.72, 0.5 + len(secondary_shared) * 0.06))
    if scorer is not None:
        embed_sim = scorer.similarity(embed_text(gold), embed_text(pred))
        score = max(score, embed_sim)
    return score


def load_gold_samples(root: Path) -> list[dict[str, Any]]:
    samples = []
    for sample_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        json_path = sample_dir / f"{sample_dir.name}.json"
        if not json_path.exists():
            continue
        payload = read_json(json_path)
        samples.append({
            "sample_id": sample_dir.name,
            "path": json_path,
            "elements": payload.get("elements", []),
        })
    return samples


def load_prediction(pred_root: Path, sample_id: str) -> dict[str, Any] | None:
    path = pred_root / sample_id / "extracted_elements.json"
    if not path.exists():
        return None
    return read_json(path)


def object_coverage_status(gold_objects: set[str], candidate_objects: set[str]) -> tuple[bool, list[str]]:
    if not gold_objects:
        return False, []
    missing = sorted(gold_objects - candidate_objects)
    return not missing, missing


# Material keyword patterns that describe only a minor accessory detail (e.g. a buckle or
# clasp) rather than the primary material of the item.  Stripping these before conflict
# detection avoids false positives like "gold=metal (from 金属搭扣) vs pred=cloth".
_ACCESSORY_DETAIL_MATERIAL_RE = re.compile(
    r"[金银铜铁](?:属)?搭扣"
    r"|金属扣[环圈]?"
    r"|[金银铜](?:属)?纽扣"
    r"|拉链头"
    r"|金属扣件"
)


def _strip_accessory_material_context(text: str) -> str:
    """Remove minor-detail material phrases before attribute extraction."""
    return _ACCESSORY_DETAIL_MATERIAL_RE.sub("", text)


def conflict_audit(gold_text: str, pred_text: str) -> tuple[list[str], list[dict[str, Any]]]:
    # Strip accessory-detail material phrases so a metal buckle on a cloth belt does
    # not produce a spurious material conflict.
    gold_text_attrs = _strip_accessory_material_context(gold_text)
    pred_text_attrs = _strip_accessory_material_context(pred_text)
    gold_attrs = extract_attributes(gold_text_attrs)
    pred_attrs = extract_attributes(pred_text_attrs)
    notes = []
    tolerated = []
    for attr_type in ("color", "material", "shape"):
        gold_values = gold_attrs[attr_type]
        pred_values = pred_attrs[attr_type]
        if attr_type == "shape":
            has_shape_conflict = any(
                frozenset((gold_value, pred_value)) in SHAPE_CONFLICT_PAIRS
                for gold_value in gold_values
                for pred_value in pred_values
            )
            if has_shape_conflict:
                notes.append(
                    f"{attr_type} conflict: gold={sorted(gold_values)}, pred={sorted(pred_values)}"
                )
        elif gold_values and pred_values and gold_values.isdisjoint(pred_values):
            color_families = extract_color_families(f"{gold_text} {pred_text}") if attr_type == "color" else set()
            gold_color_families = extract_color_families(gold_text) if attr_type == "color" else set()
            pred_color_families = extract_color_families(pred_text) if attr_type == "color" else set()
            tolerated_color_families = [
                pred_color_families | {gold_family}
                for gold_family in gold_color_families
                if is_workflow_tolerated_color_set(pred_color_families | {gold_family})
            ]
            if attr_type == "color" and (is_workflow_tolerated_color_set(color_families) or tolerated_color_families):
                matched = set().union(*tolerated_color_families) if tolerated_color_families else color_families
                tolerated.append({
                    "rule": COLOR_FAMILY_RULE_NAME,
                    "matched_color_families": sorted(matched),
                })
                continue
            notes.append(
                f"{attr_type} conflict: gold={sorted(gold_values)}, pred={sorted(pred_values)}"
            )
    return notes, tolerated


def audit_composite_gold_element(
    gold_index: int,
    gold: dict[str, Any],
    sub_names: list[str],
    pred_elements: list[dict[str, Any]],
    threshold: float,
    *,
    scorer: EmbeddingScorer | None = None,
) -> dict[str, Any]:
    """Evaluate a composite gold element (name contains '与') by matching each sub-name
    against ALL pred elements independently (no exclusion).  A single pred may cover
    multiple sub-names — this handles both 'feature' composites (e.g. '礼服与燕尾设计',
    where the design detail lives in the pred's value) and 'paired-item' composites
    (e.g. '腰带与剑鞘', where both may be described in one pred).  Gold is covered when
    all sub-names score >= threshold against some pred.  Conflict detection runs at
    sub-name level to avoid false positives from mixed composite attributes."""
    sub_results: list[dict[str, Any]] = []
    all_conflicts: list[dict[str, Any]] = []
    all_tolerated: list[dict[str, Any]] = []
    covering_pred_indexes: list[int] = []
    conflict_checked_preds: set[int] = set()
    best_score_overall = 0.0

    for sub_name in sub_names:
        # Minimal sub-gold keyed only on sub-name: avoids cross-contamination from the full
        # composite value text (e.g. "腰带" should not inherit the skirt's color from value).
        sub_gold: dict[str, Any] = {"name": sub_name, "value": "", "category": "", "attributes": {}}

        best_idx: int | None = None
        best_score = 0.0
        best_pred: dict[str, Any] | None = None
        for pred_index, pred in enumerate(pred_elements):
            score = relation_score(sub_gold, pred, scorer=scorer)
            if score > best_score:
                best_score = score
                best_idx = pred_index
                best_pred = pred

        best_score_overall = max(best_score_overall, best_score)
        sub_covered = best_idx is not None and best_score >= threshold

        if sub_covered and best_idx is not None and best_pred is not None:
            if best_idx + 1 not in covering_pred_indexes:
                covering_pred_indexes.append(best_idx + 1)
            # Only run conflict_audit once per (sub_name, pred) pair even if the same pred
            # is later re-selected for another sub_name.
            check_key = best_idx + 1
            if check_key not in conflict_checked_preds:
                notes, tolerated = conflict_audit(sub_name, element_text(best_pred))
                if notes:
                    all_conflicts.append({
                        "pred_index": best_idx + 1,
                        "pred_name": best_pred.get("name", ""),
                        "sub_name": sub_name,
                        "notes": notes,
                    })
                for t in tolerated:
                    all_tolerated.append({"pred_index": best_idx + 1, "pred_name": best_pred.get("name", ""), **t})
                conflict_checked_preds.add(check_key)

        sub_results.append({
            "sub_name": sub_name,
            "covered": sub_covered,
            "pred_index": best_idx + 1 if best_idx is not None else None,
            "pred_name": best_pred.get("name", "") if best_pred is not None else None,
            "score": round(best_score, 3),
        })

    covered = all(r["covered"] for r in sub_results)
    gold_objects = find_keyword_families(element_name(gold), OBJECT_KEYWORDS)
    covered_sub_objects: set[str] = set()
    for r in sub_results:
        if r["covered"]:
            covered_sub_objects |= find_keyword_families(r["sub_name"], OBJECT_KEYWORDS)
    missing_objects = sorted(gold_objects - covered_sub_objects)

    return {
        "gold_index": gold_index + 1,
        "gold_name": gold.get("name", ""),
        "covered": covered,
        "covering_pred_indexes": covering_pred_indexes,
        "best_score": round(best_score_overall, 3),
        "gold_object_families": sorted(gold_objects),
        "missing_object_families": missing_objects,
        "possible_conflict": bool(all_conflicts),
        "conflict_notes": all_conflicts,
        "color_family_tolerated": bool(all_tolerated),
        "color_family_tolerated_notes": all_tolerated,
        "candidate_predictions": sub_results,
        "composite_sub_results": sub_results,
    }


def audit_gold_element(
    gold_index: int,
    gold: dict[str, Any],
    pred_elements: list[dict[str, Any]],
    threshold: float,
    *,
    scorer: EmbeddingScorer | None = None,
) -> dict[str, Any]:
    # Composite gold elements (name contains '与') are evaluated by matching each
    # sub-name to a separate pred element.  Routing here keeps the original logic
    # intact for simple (non-composite) gold names.
    sub_names = split_composite_name(element_name(gold))
    if len(sub_names) > 1:
        return audit_composite_gold_element(gold_index, gold, sub_names, pred_elements, threshold, scorer=scorer)

    # Coverage requirement: use name-only object families for the gold element.
    # Falling back to the full value text would inject false requirements —
    # e.g. gold "灰色马甲与金色链条" whose value mentions "内搭" would require
    # preds to carry a "shirt" family even when the pred name "金色链条" is
    # clearly correct.  Scoring (relation_score) still uses the full-text path.
    gold_objects = find_keyword_families(element_name(gold), OBJECT_KEYWORDS)
    candidates = []
    candidate_objects: set[str] = set()
    conflicts = []
    color_family_tolerated = []

    for pred_index, pred in enumerate(pred_elements):
        pred_objects = object_info(pred, include_detail_from_full_text=True)
        score = relation_score(gold, pred, scorer=scorer)
        primary_shared = gold_objects & pred_objects["primary"]
        secondary_shared = gold_objects & pred_objects["secondary"]
        shared_objects = primary_shared | secondary_shared
        is_candidate = score >= threshold or bool(shared_objects)
        if not is_candidate:
            continue

        candidates.append({
            "pred_index": pred_index + 1,
            "pred_name": pred.get("name", ""),
            "score": round(score, 3),
            "shared_objects": sorted(shared_objects),
            "primary_shared_objects": sorted(primary_shared),
            "secondary_shared_objects": sorted(secondary_shared),
            "_primary_shared": primary_shared,
            "_secondary_shared": secondary_shared,
            "_pred": pred,
        })

    candidates.sort(
        key=lambda item: (
            bool(item["_primary_shared"]),
            len(item["_primary_shared"]),
            len(item["_secondary_shared"]),
            item["score"],
        ),
        reverse=True,
    )
    selected_by_index: dict[int, dict[str, Any]] = {}
    for gold_object in gold_objects:
        object_candidates = [
            item for item in candidates
            if gold_object in item["_primary_shared"] or gold_object in item["_secondary_shared"]
        ]
        if not object_candidates:
            continue
        object_candidates.sort(
            key=lambda item: (
                gold_object in item["_primary_shared"],
                item["score"],
            ),
            reverse=True,
        )
        selected = object_candidates[0]
        selected_by_index[int(selected["pred_index"])] = selected
        candidate_objects.add(gold_object)

    score_only_fallback = False
    if not selected_by_index and candidates and candidates[0]["score"] >= threshold:
        selected_by_index[int(candidates[0]["pred_index"])] = candidates[0]
        score_only_fallback = True

    selected_predictions = sorted(
        selected_by_index.values(),
        key=lambda item: item["score"],
        reverse=True,
    )
    best_score = candidates[0]["score"] if candidates else 0.0
    object_covered, missing_objects = object_coverage_status(gold_objects, candidate_objects)
    if score_only_fallback:
        # No family path matched any gold_object, but the best candidate clears the score
        # threshold — treat as covered.  The gold element likely uses a compound name whose
        # keywords don't appear verbatim in the pred (e.g. gold="腰带与剑鞘", pred="背带"),
        # so family matching fails even when the semantic match is strong enough.
        covered = True
        missing_objects = []
    else:
        covered = object_covered if gold_objects else best_score >= threshold
    for item in selected_predictions:
        pred = item["_pred"]
        notes, tolerated = conflict_audit(element_text(gold), element_text(pred))
        for tolerated_item in tolerated:
            color_family_tolerated.append({
                "pred_index": item["pred_index"],
                "pred_name": item["pred_name"],
                **tolerated_item,
            })
        if notes:
            conflicts.append({
                "pred_index": item["pred_index"],
                "pred_name": item["pred_name"],
                "shared_objects": item["shared_objects"],
                "notes": notes,
            })

    return {
        "gold_index": gold_index + 1,
        "gold_name": gold.get("name", ""),
        "covered": covered,
        "covering_pred_indexes": [item["pred_index"] for item in selected_predictions],
        "best_score": best_score,
        "gold_object_families": sorted(gold_objects),
        "missing_object_families": missing_objects,
        "possible_conflict": bool(conflicts),
        "conflict_notes": conflicts,
        "color_family_tolerated": bool(color_family_tolerated),
        "color_family_tolerated_notes": color_family_tolerated,
        "candidate_predictions": [
            {key: value for key, value in item.items() if not key.startswith("_")}
            for item in candidates
        ],
    }


def classify_extra_prediction(
    pred_index: int,
    pred: dict[str, Any],
    gold_elements: list[dict[str, Any]],
    threshold: float,
    *,
    scorer: EmbeddingScorer | None = None,
) -> dict[str, Any]:
    best_score = 0.0
    best_gold_index = -1
    best_primary_shared: set[str] = set()
    for gold_index, gold in enumerate(gold_elements):
        score = relation_score(gold, pred, scorer=scorer)
        primary_shared = (
            object_info(gold, include_detail_from_full_text=False)["all"]
            & object_info(pred, include_detail_from_full_text=True)["primary"]
        )
        if score > best_score:
            best_score = score
            best_gold_index = gold_index
            best_primary_shared = primary_shared

    embed_sim_to_best = 0.0
    if scorer is not None and best_gold_index >= 0:
        embed_sim_to_best = scorer.similarity(
            embed_text(pred), embed_text(gold_elements[best_gold_index])
        )

    classification = "needs_review"
    reason = "not referenced by human gold; inspect whether the detail is visible and useful"
    if best_score >= threshold and best_gold_index >= 0 and (best_primary_shared or embed_sim_to_best >= EMBED_SUPPORTED_THRESHOLD):
        classification = "supported_extra"
        reason = "related to a human gold element but not required for coverage"
    elif best_score >= threshold and best_gold_index >= 0:
        classification = "unsupported_extra"
        reason = (
            f"scores {round(best_score, 3):.3f} near gold #{best_gold_index + 1} "
            "but shares no primary object family; possible hallucinated detail"
        )

    result: dict[str, Any] = {
        "pred_index": pred_index + 1,
        "pred_name": pred.get("name", ""),
        "classification": classification,
        "best_gold_index": best_gold_index + 1 if best_gold_index >= 0 else None,
        "best_score": round(best_score, 3),
        "reason": reason,
    }
    if scorer is not None:
        result["embed_sim_to_best"] = round(embed_sim_to_best, 3)
    return result


def audit_sample(
    gold_elements: list[dict[str, Any]],
    pred_elements: list[dict[str, Any]],
    threshold: float,
    *,
    scorer: EmbeddingScorer | None = None,
) -> dict[str, Any]:
    gold_audits = [
        audit_gold_element(index, gold, pred_elements, threshold, scorer=scorer)
        for index, gold in enumerate(gold_elements)
    ]
    used_pred_indexes = {
        pred_index
        for audit in gold_audits
        for pred_index in audit["covering_pred_indexes"]
    }
    extra_audits = [
        classify_extra_prediction(pred_index, pred, gold_elements, threshold, scorer=scorer)
        for pred_index, pred in enumerate(pred_elements)
        if pred_index + 1 not in used_pred_indexes
    ]

    covered_count = sum(1 for item in gold_audits if item["covered"])
    conflict_count = sum(1 for item in gold_audits if item["possible_conflict"])
    color_family_tolerated_count = sum(1 for item in gold_audits if item["color_family_tolerated"])
    unsupported_extra_count = sum(1 for item in extra_audits if item["classification"] == "unsupported_extra")
    needs_review_extra_count = sum(1 for item in extra_audits if item["classification"] == "needs_review")
    return {
        "gold_count": len(gold_elements),
        "pred_count": len(pred_elements),
        "covered_gold_count": covered_count,
        "uncovered_gold_count": len(gold_elements) - covered_count,
        "gold_coverage_rate": round(covered_count / len(gold_elements), 4) if gold_elements else 0.0,
        "conflict_count": conflict_count,
        "color_family_tolerated_count": color_family_tolerated_count,
        "unsupported_extra_count": unsupported_extra_count,
        "needs_review_extra_count": needs_review_extra_count,
        "gold_audit": gold_audits,
        "extra_audit": extra_audits,
    }


def main() -> None:
    args = parse_args()
    if not args.gold_root.exists():
        raise SystemExit(f"Gold root not found: {args.gold_root}")

    gold_samples = load_gold_samples(args.gold_root)

    scorer: EmbeddingScorer | None = None
    if args.use_embeddings:
        load_api_env()
        api_key = os.environ.get("QWEN_API_KEY", "")
        if not api_key:
            raise SystemExit("QWEN_API_KEY is required for --use-embeddings. Set it in vlm/config/api.env.")
        scorer = EmbeddingScorer(api_key=api_key, cache_path=args.embed_cache_path)
        all_texts: list[str] = []
        for gs in gold_samples:
            all_texts.extend(embed_text(e) for e in gs["elements"])
        for gs in gold_samples:
            pred = load_prediction(args.pred_root, gs["sample_id"])
            if pred:
                all_texts.extend(embed_text(e) for e in pred.get("elements", []))
        scorer.precompute(all_texts)
        print(json.dumps({"embedding_precompute": "ok", "cache_path": str(args.embed_cache_path)}, ensure_ascii=False))

    sample_reports = []
    missing_prediction_count = 0
    totals = {
        "gold_count": 0,
        "evaluated_gold_count": 0,
        "pred_count": 0,
        "covered_gold_count": 0,
        "uncovered_gold_count": 0,
        "conflict_count": 0,
        "color_family_tolerated_count": 0,
        "unsupported_extra_count": 0,
        "needs_review_extra_count": 0,
    }

    for gold_sample in gold_samples:
        sample_id = gold_sample["sample_id"]
        gold_elements = gold_sample["elements"]
        totals["gold_count"] += len(gold_elements)
        prediction = load_prediction(args.pred_root, sample_id)
        if prediction is None:
            missing_prediction_count += 1
            sample_reports.append({
                "sample_id": sample_id,
                "status": "missing_prediction",
                "gold_count": len(gold_elements),
            })
            continue

        sample_report = audit_sample(
            gold_elements,
            prediction.get("elements", []),
            args.coverage_threshold,
            scorer=scorer,
        )
        sample_report["sample_id"] = sample_id
        sample_report["status"] = "ok"
        sample_reports.append(sample_report)
        for key in totals:
            if key == "gold_count":
                continue
            if key == "evaluated_gold_count":
                totals[key] += int(sample_report.get("gold_count", 0))
            else:
                totals[key] += int(sample_report.get(key, 0))

    evaluated_coverage = (
        totals["covered_gold_count"] / totals["evaluated_gold_count"]
        if totals["evaluated_gold_count"]
        else 0.0
    )
    all_gold_coverage = totals["covered_gold_count"] / totals["gold_count"] if totals["gold_count"] else 0.0
    report = {
        "schema_version": "element_extraction_eval.v2",
        "gold_root": str(args.gold_root),
        "pred_root": str(args.pred_root),
        "coverage_threshold": args.coverage_threshold,
        "summary": {
            **totals,
            "sample_count": len(sample_reports),
            "evaluated_sample_count": len(sample_reports) - missing_prediction_count,
            "missing_prediction_count": missing_prediction_count,
            "gold_coverage_rate_evaluated": round(evaluated_coverage, 4),
            "gold_coverage_rate_all_gold": round(all_gold_coverage, 4),
        },
        "notes": [
            "Coverage allows one human gold element to be represented by multiple extracted elements.",
            f"Color-only conflicts inside tolerated adjacent color families are downgraded with {COLOR_FAMILY_RULE_NAME}.",
            "Remaining conflict checks are deterministic color/material/shape keyword diagnostics, not a substitute for visual review.",
            "Extra predictions marked needs_review are not counted as wrong unless a reviewer confirms they are unsupported.",
        ],
        "samples": sample_reports,
    }
    write_json(args.report_path, report)
    print(json.dumps({
        "status": "ok",
        "report_path": str(args.report_path),
        "summary": report["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
