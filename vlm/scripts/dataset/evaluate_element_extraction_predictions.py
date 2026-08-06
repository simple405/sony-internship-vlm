"""Evaluate paired-sample element predictions against human gold annotations.

The paired dataset stores gold annotations as a JSON list beside each source
image.  Predictions produced by ``run_qwen_element_extraction_smoke`` use a
small wrapper object with an ``elements`` list. This evaluator keeps the
comparison reproducible by combining Chinese character n-gram similarity,
optional Qwen text embeddings, greedy one-to-one matching, and bbox IoU.
The command-line evaluator enables embeddings by default.  Evaluator v2 also
reports a many-to-one ``relaxed_any_gold`` view so that predictions which split
one compound gold label into several valid sub-elements are not all counted as
false positives.  The original strict fields remain unchanged.

It is intentionally an offline metric.  A model judge may be useful for
borderline synonym cases later, but it must not replace a reproducible baseline.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from vlm.scripts._paths import API_ENV_FILE, load_api_env
from vlm.scripts.dataset.element_extraction_schema import prediction_elements
from vlm.scripts.supervise.embedding_scorer import EmbeddingScorer

PREDICTION_FILE = "qwen_element_prediction.json"
EVALUATION_FILE = "qwen_element_evaluation.json"
_TEXT_NOISE = re.compile(r"[\s，。、“”‘’：:；;,.!！?？/\\|（）()\[\]{}<>《》\-_]+")
COLOR_KEYWORDS = {
    "black": ("黑色", "黑"),
    "white_grey": ("白色", "米色", "灰色", "银色", "白/灰"),
    "brown": ("棕色", "褐色", "咖啡", "卡其"),
    "red": ("红色", "红"),
    "yellow_gold": ("黄色", "金色", "黄", "金"),
    "green": ("绿色", "绿"),
    "blue": ("蓝色", "青色", "蓝"),
    "purple": ("紫色", "紫"),
    "pink": ("粉色", "粉"),
    "orange": ("橙色", "橙"),
}
COLOR_COMPATIBLE_FAMILIES = {
    # Human labels for anime art often differ on adjacent hues and low-light
    # dark colors.  Treat these as compatible for color-conflict reporting; this
    # does not make unrelated objects match by itself.
    "black": {"blue", "brown", "white_grey"},
    "white_grey": {"black", "blue"},
    "brown": {"black", "red", "orange", "yellow_gold"},
    "red": {"brown", "orange", "pink"},
    "yellow_gold": {"brown", "orange", "green"},
    "green": {"yellow_gold", "blue"},
    "blue": {"black", "white_grey", "green", "purple"},
    "purple": {"blue", "pink"},
    "pink": {"red", "purple"},
    "orange": {"red", "yellow_gold", "brown"},
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def compact_text(value: Any) -> str:
    return _TEXT_NOISE.sub("", str(value or "").lower())


def character_ngrams(value: Any, n: int = 2) -> set[str]:
    text = compact_text(value)
    if not text:
        return set()
    if len(text) < n:
        return {text}
    return {text[index : index + n] for index in range(len(text) - n + 1)}


def text_similarity(left: Any, right: Any) -> float:
    """Return a conservative Dice score over Chinese character bigrams."""
    left_tokens = character_ngrams(left)
    right_tokens = character_ngrams(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return 2 * len(left_tokens & right_tokens) / (len(left_tokens) + len(right_tokens))


def normalize_bbox(raw: Any) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x1, y1, x2, y2)) or x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def bbox_iou(left: Any, right: Any) -> float | None:
    first = normalize_bbox(left)
    second = normalize_bbox(right)
    if first is None or second is None:
        return None
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / (first_area + second_area - intersection) if intersection else 0.0


def element_text(item: dict[str, Any]) -> str:
    return f"{item.get('element', '')} {item.get('description', '')}".strip()


def color_families(item: dict[str, Any]) -> set[str]:
    text = compact_text(element_text(item))
    return {family for family, keywords in COLOR_KEYWORDS.items() if any(keyword in text for keyword in keywords)}


def color_families_compatible(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    if not left.isdisjoint(right):
        return True
    return any(
        right_family in COLOR_COMPATIBLE_FAMILIES.get(left_family, set())
        or left_family in COLOR_COMPATIBLE_FAMILIES.get(right_family, set())
        for left_family in left
        for right_family in right
    )


def color_conflict(gold: dict[str, Any], prediction: dict[str, Any]) -> dict[str, list[str]] | None:
    gold_colors = color_families(gold)
    prediction_colors = color_families(prediction)
    if gold_colors and prediction_colors and not color_families_compatible(gold_colors, prediction_colors):
        return {"gold": sorted(gold_colors), "prediction": sorted(prediction_colors)}
    return None


def pair_score(
    gold: dict[str, Any], prediction: dict[str, Any], *, scorer: EmbeddingScorer | None = None
) -> tuple[float, float, float, float, float | None, float | None]:
    name_score = text_similarity(gold.get("element"), prediction.get("element"))
    description_score = text_similarity(gold.get("description"), prediction.get("description"))
    text_score = 0.65 * name_score + 0.35 * description_score
    iou = bbox_iou(gold.get("bbox"), prediction.get("bbox"))
    # Text decides semantic identity. IoU increases confidence but cannot turn an
    # unrelated item in the same region into a match.
    combined = text_score if iou is None else 0.7 * text_score + 0.3 * iou
    embedding_score = scorer.similarity(element_text(gold), element_text(prediction)) if scorer else None
    # Embeddings resolve alternate wording, but do not dominate the positional
    # and lexical evidence: generic character descriptions have high cosine
    # similarity even when they refer to distinct objects.
    if embedding_score is not None:
        combined = 0.75 * combined + 0.25 * embedding_score
    return combined, text_score, name_score, description_score, iou, embedding_score


def build_match_candidate(
    gold: dict[str, Any],
    prediction: dict[str, Any],
    *,
    gold_index: int,
    prediction_index: int,
    match_threshold: float,
    scorer: EmbeddingScorer | None,
    embedding_threshold: float,
) -> dict[str, Any] | None:
    """Return comparable pair evidence when a pair clears a match gate."""
    combined, text_score, name_score, description_score, iou, embedding_score = pair_score(
        gold, prediction, scorer=scorer
    )
    high_iou_textual_match = iou is not None and iou >= 0.5 and (
        name_score >= 0.25 or description_score >= 0.2
    )
    semantic_grounded_match = (
        embedding_score is not None
        and embedding_score >= embedding_threshold
        and (max(name_score, description_score) >= 0.18 or (iou is not None and iou >= 0.55))
    )
    if not (text_score >= match_threshold or high_iou_textual_match or semantic_grounded_match):
        return None
    if text_score >= match_threshold:
        match_method = "lexical"
    elif high_iou_textual_match:
        match_method = "bbox_grounded"
    else:
        match_method = "embedding_grounded"
    return {
        "gold_index": gold_index,
        "prediction_index": prediction_index,
        "score": round(combined, 4),
        "text_score": round(text_score, 4),
        "name_score": round(name_score, 4),
        "description_score": round(description_score, 4),
        "bbox_iou": round(iou, 4) if iou is not None else None,
        "embedding_similarity": round(embedding_score, 4) if embedding_score is not None else None,
        "match_method": match_method,
        "color_conflict": color_conflict(gold, prediction),
    }


def evaluate_elements(
    gold_elements: list[dict[str, Any]],
    predicted_elements: list[dict[str, Any]],
    *,
    match_threshold: float = 0.35,
    scorer: EmbeddingScorer | None = None,
    embedding_threshold: float = 0.9,
) -> dict[str, Any]:
    """Return strict one-to-one and relaxed prediction-to-any-gold metrics."""
    candidates: list[dict[str, Any]] = []
    for gold_index, gold in enumerate(gold_elements):
        for prediction_index, prediction in enumerate(predicted_elements):
            candidate = build_match_candidate(
                gold,
                prediction,
                gold_index=gold_index,
                prediction_index=prediction_index,
                match_threshold=match_threshold,
                scorer=scorer,
                embedding_threshold=embedding_threshold,
            )
            if candidate is not None:
                candidates.append(candidate)

    used_gold: set[int] = set()
    used_predictions: set[int] = set()
    matches: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        gold_index = candidate["gold_index"]
        prediction_index = candidate["prediction_index"]
        if gold_index in used_gold or prediction_index in used_predictions:
            continue
        used_gold.add(gold_index)
        used_predictions.add(prediction_index)
        matches.append(
            {
                **candidate,
                "gold": gold_elements[gold_index],
                "prediction": predicted_elements[prediction_index],
            }
        )

    missed_gold = [item for index, item in enumerate(gold_elements) if index not in used_gold]
    extra_predictions = [item for index, item in enumerate(predicted_elements) if index not in used_predictions]
    match_count = len(matches)
    precision = match_count / len(predicted_elements) if predicted_elements else 1.0
    recall = match_count / len(gold_elements) if gold_elements else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    ious = [match["bbox_iou"] for match in matches if match["bbox_iou"] is not None]
    color_conflicts = [match for match in matches if match["color_conflict"] is not None]
    embeddings = [match["embedding_similarity"] for match in matches if match["embedding_similarity"] is not None]

    # Relax only the gold-side exclusivity.  Each prediction chooses its best
    # eligible gold, while multiple predictions may choose the same compound
    # gold.  This intentionally does not deduplicate predictions; duplicate and
    # visually unsupported extras are separate v2 diagnostics.
    strict_by_prediction = {match["prediction_index"]: match for match in matches}
    best_by_prediction: dict[int, dict[str, Any]] = {
        prediction_index: {
            key: value
            for key, value in match.items()
            if key not in {"gold", "prediction"}
        }
        for prediction_index, match in strict_by_prediction.items()
    }
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        if candidate["prediction_index"] in strict_by_prediction:
            continue
        best_by_prediction.setdefault(candidate["prediction_index"], candidate)
    relaxed_matches = [
        {
            **candidate,
            "gold": gold_elements[candidate["gold_index"]],
            "prediction": predicted_elements[prediction_index],
            "also_strict_match": prediction_index in used_predictions,
        }
        for prediction_index, candidate in sorted(best_by_prediction.items())
    ]
    relaxed_match_count = len(relaxed_matches)
    relaxed_unique_gold_count = len({match["gold_index"] for match in relaxed_matches})
    relaxed_precision = relaxed_match_count / len(predicted_elements) if predicted_elements else 1.0
    relaxed_recall = relaxed_unique_gold_count / len(gold_elements) if gold_elements else 1.0
    relaxed_f1 = (
        2 * relaxed_precision * relaxed_recall / (relaxed_precision + relaxed_recall)
        if relaxed_precision + relaxed_recall
        else 0.0
    )
    return {
        "gold_element_count": len(gold_elements),
        "prediction_element_count": len(predicted_elements),
        "match_count": match_count,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "matched_bbox_iou_mean": round(sum(ious) / len(ious), 4) if ious else None,
        "matched_bbox_iou_count": len(ious),
        "color_conflict_count": len(color_conflicts),
        "color_conflicts": color_conflicts,
        "matched_embedding_similarity_mean": round(sum(embeddings) / len(embeddings), 4) if embeddings else None,
        "matched_embedding_similarity_count": len(embeddings),
        "matches": matches,
        "missed_gold": missed_gold,
        "extra_predictions": extra_predictions,
        "relaxed_any_gold_match_count": relaxed_match_count,
        "relaxed_any_gold_unique_gold_count": relaxed_unique_gold_count,
        "relaxed_any_gold_precision": round(relaxed_precision, 4),
        "relaxed_any_gold_recall": round(relaxed_recall, 4),
        "relaxed_any_gold_f1": round(relaxed_f1, 4),
        "relaxed_any_gold_matches": relaxed_matches,
    }


def evaluate_sample_dir(
    sample_dir: Path,
    *,
    prediction_file: str = PREDICTION_FILE,
    match_threshold: float = 0.35,
    scorer: EmbeddingScorer | None = None,
    embedding_threshold: float = 0.9,
) -> dict[str, Any]:
    gold_path = sample_dir / f"{sample_dir.name}.json"
    prediction_path = sample_dir / prediction_file
    gold = read_json(gold_path)
    if not isinstance(gold, list):
        raise ValueError(f"{gold_path}: human gold must be a JSON list")
    prediction = read_json(prediction_path)
    result = evaluate_elements(
        gold,
        prediction_elements(prediction),
        match_threshold=match_threshold,
        scorer=scorer,
        embedding_threshold=embedding_threshold,
    )
    return {
        "schema_version": "element_extraction_evaluation.v2",
        "sample_id": sample_dir.name,
        "gold_path": gold_path.name,
        "prediction_path": prediction_path.name,
        "match_threshold": match_threshold,
        "embedding_model": scorer.model if scorer else None,
        "embedding_threshold": embedding_threshold if scorer else None,
        **result,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate paired image element predictions against human gold JSON.")
    parser.add_argument("--paired-root", type=Path, default=Path("vlm/data/1-动漫标注结果导出_paired_samples"))
    parser.add_argument("--sample-id", action="append", default=[], help="May be passed more than once. Defaults to all prediction folders.")
    parser.add_argument("--prediction-file", default=PREDICTION_FILE)
    parser.add_argument("--match-threshold", type=float, default=0.35)
    parser.add_argument("--evaluation-file", default=EVALUATION_FILE)
    embedding_group = parser.add_mutually_exclusive_group()
    embedding_group.add_argument(
        "--use-embeddings",
        dest="use_embeddings",
        action="store_true",
        help="Use Qwen text-embedding-v3 as a grounded semantic match signal (default).",
    )
    embedding_group.add_argument(
        "--no-embeddings",
        dest="use_embeddings",
        action="store_false",
        help="Disable embedding matching and use lexical/bbox scoring only.",
    )
    parser.set_defaults(use_embeddings=True)
    parser.add_argument("--embedding-model", default="text-embedding-v3")
    parser.add_argument("--embedding-threshold", type=float, default=0.9)
    parser.add_argument("--embedding-cache-path", type=Path, default=Path("vlm/tmp/qwen_element_embedding_cache.json"))
    parser.add_argument("--env-file", type=Path, default=API_ENV_FILE)
    parser.add_argument("--summary-path", type=Path, default=Path("vlm/data/1-动漫标注结果导出_paired_samples/qwen_element_evaluation_summary.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paired_root = args.paired_root.resolve()
    if not paired_root.exists():
        raise SystemExit(f"paired root not found: {paired_root}")
    sample_dirs = [paired_root / sample_id for sample_id in args.sample_id] if args.sample_id else sorted(
        path for path in paired_root.iterdir() if path.is_dir() and (path / args.prediction_file).exists()
    )
    scorer = None
    if args.use_embeddings:
        load_api_env(args.env_file)
        api_key = os.environ.get("QWEN_API_KEY", "").strip()
        if not api_key:
            raise SystemExit("QWEN_API_KEY is required for --use-embeddings")
        base_url = os.environ.get("QWEN_BASE_URL", "").strip()
        scorer = EmbeddingScorer(api_key=api_key, base_url=base_url, model=args.embedding_model, cache_path=args.embedding_cache_path)
        embedding_texts: list[str] = []
        for sample_dir in sample_dirs:
            gold = read_json(sample_dir / f"{sample_dir.name}.json")
            prediction = read_json(sample_dir / args.prediction_file)
            embedding_texts.extend(element_text(item) for item in gold if isinstance(item, dict))
            embedding_texts.extend(element_text(item) for item in prediction_elements(prediction))
        scorer.precompute(embedding_texts)

    results = []
    for sample_dir in sample_dirs:
        if not sample_dir.exists():
            raise SystemExit(f"sample folder not found: {sample_dir}")
        result = evaluate_sample_dir(
            sample_dir,
            prediction_file=args.prediction_file,
            match_threshold=args.match_threshold,
            scorer=scorer,
            embedding_threshold=args.embedding_threshold,
        )
        write_json(sample_dir / args.evaluation_file, result)
        results.append(result)

    total_matches = sum(result["match_count"] for result in results)
    total_gold = sum(result["gold_element_count"] for result in results)
    total_predictions = sum(result["prediction_element_count"] for result in results)
    precision = total_matches / total_predictions if total_predictions else 1.0
    recall = total_matches / total_gold if total_gold else 1.0
    relaxed_matches = sum(result["relaxed_any_gold_match_count"] for result in results)
    relaxed_unique_gold = sum(result["relaxed_any_gold_unique_gold_count"] for result in results)
    relaxed_precision = relaxed_matches / total_predictions if total_predictions else 1.0
    relaxed_recall = relaxed_unique_gold / total_gold if total_gold else 1.0
    summary = {
        "schema_version": "element_extraction_evaluation_summary.v2",
        "sample_count": len(results),
        "embedding_model": scorer.model if scorer else None,
        "embedding_threshold": args.embedding_threshold if scorer else None,
        "micro_precision": round(precision, 4),
        "micro_recall": round(recall, 4),
        "micro_f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "total_gold_elements": total_gold,
        "total_prediction_elements": total_predictions,
        "total_matches": total_matches,
        "relaxed_any_gold_micro_precision": round(relaxed_precision, 4),
        "relaxed_any_gold_micro_recall": round(relaxed_recall, 4),
        "relaxed_any_gold_micro_f1": round(
            2 * relaxed_precision * relaxed_recall / (relaxed_precision + relaxed_recall), 4
        )
        if relaxed_precision + relaxed_recall
        else 0.0,
        "relaxed_any_gold_total_matches": relaxed_matches,
        "relaxed_any_gold_total_unique_gold": relaxed_unique_gold,
        "samples": results,
    }
    write_json(args.summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
