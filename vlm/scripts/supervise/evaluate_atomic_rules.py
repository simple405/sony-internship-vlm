"""Evaluate atomic_rules_generated.json extractions against gold-standard elements.

Uses local Ollama bge-m3 embeddings for semantic similarity matching with
Hungarian algorithm for globally optimal one-to-one pairing.

Usage:
    python -m vlm.scripts.supervise.evaluate_atomic_rules           # all 34 samples
    python -m vlm.scripts.supervise.evaluate_atomic_rules --sample char_015  # single
    python -m vlm.scripts.supervise.evaluate_atomic_rules --no-embeddings     # keyword-only
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import requests
from scipy.optimize import linear_sum_assignment

DEFAULT_GOLD_ROOT = Path("vlm/data/SN_6_3D_dataset")
DEFAULT_PRED_ROOT = Path("vlm/tmp/supervision_agent_output")
DEFAULT_OUTPUT = Path("vlm/tmp/atomic_rules_eval_report.json")
OLLAMA_BASE = "http://127.0.0.1:11434"
EMBED_MODEL = "bge-m3:latest"

# Matching thresholds
SIMILARITY_THRESHOLD = 0.50   # minimum cosine sim to consider a match valid
GOOD_MATCH_THRESHOLD = 0.65   # above this, match is "good" vs "weak"


class OllamaEmbedder:
    """Local bge-m3 embedding via Ollama HTTP API with disk cache."""

    def __init__(
        self,
        base_url: str = OLLAMA_BASE,
        model: str = EMBED_MODEL,
        cache_path: Path | None = None,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self._cache: dict[str, list[float]] = {}
        self._cache_path = cache_path
        if cache_path and cache_path.exists():
            try:
                self._cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _save_cache(self) -> None:
        if self._cache_path:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False), encoding="utf-8"
            )

    def encode(self, texts: list[str]) -> np.ndarray:
        """Embed texts, using cache for seen strings. Returns (n, dim) array."""
        results: list[tuple[int, list[float]]] = []
        missing_texts: list[str] = []
        missing_indices: list[int] = []

        for i, text in enumerate(texts):
            key = text.strip()
            if key in self._cache:
                results.append((i, self._cache[key]))
            else:
                missing_texts.append(key)
                missing_indices.append(i)
                results.append((i, []))

        if missing_texts:
            # Batch embed — Ollama supports array of strings
            resp = requests.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": missing_texts},
                proxies={"http": None, "https": None},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            for idx, text in zip(missing_indices, missing_texts):
                emb = data["embeddings"][len(self._cache) % len(missing_texts)]
                self._cache[text] = emb
                results[idx] = (idx, emb)
            self._save_cache()

        # Reconstruct in original order
        vectors = []
        for _, emb in results:
            vectors.append(emb)
        return np.array(vectors, dtype=np.float32)

    def encode_single(self, text: str) -> np.ndarray:
        return self.encode([text])[0]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """Character-level Jaccard similarity (fallback when embeddings unavailable)."""
    # Strip punctuation/whitespace for clean comparison
    import re
    clean = lambda s: set(re.sub(r"[\s，。、""''：:；;,.!！?？/\\|（）()\[\]{}<>《》-]+", "", s))
    set_a = clean(text_a)
    set_b = clean(text_b)
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    jaccard = intersection / len(set_a | set_b)
    overlap = intersection / min(len(set_a), len(set_b))
    return max(jaccard, overlap)


def load_gold_elements(gold_root: Path, sample_id: str) -> list[dict[str, str]]:
    """Load gold-standard elements from SN_6_3D_dataset."""
    json_path = gold_root / sample_id / f"{sample_id}.json"
    if not json_path.exists():
        return []
    payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
    return [
        {"name": e.get("name", ""), "value": e.get("value", "")}
        for e in payload.get("elements", [])
    ]


def load_pred_elements(pred_root: Path, sample_id: str) -> list[dict[str, str]]:
    """Load atomic_rules as pred elements. Maps rule_id → name, value → value."""
    json_path = pred_root / sample_id / "atomic_rules_generated.json"
    if not json_path.exists():
        return []
    payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
    rules = payload.get("atomic_rules", [])
    return [
        {"name": r.get("rule_id", ""), "value": r.get("value", "")} for r in rules
    ]


def match_elements_hungarian(
    pred_elements: list[dict[str, str]],
    gold_elements: list[dict[str, str]],
    embedder: OllamaEmbedder | None,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> dict[str, Any]:
    """Hungarian algorithm for globally optimal one-to-one matching.

    Matches on full text (name + value) embeddings. Returns matches and
    unmatched elements on both sides.
    """
    if not pred_elements or not gold_elements:
        return {
            "matches": [],
            "unmatched_pred": list(pred_elements),
            "unmatched_gold": list(gold_elements),
        }

    n_pred = len(pred_elements)
    n_gold = len(gold_elements)

    # Atomic rules don't have a separate "name" concept — use full text
    pred_texts = [f"{e['value']}" for e in pred_elements]
    gold_texts = [f"{e['name']} {e['value']}" for e in gold_elements]

    if embedder is not None:
        pred_embs = embedder.encode(pred_texts)
        gold_embs = embedder.encode(gold_texts)
        use_embeddings = True
    else:
        use_embeddings = False

    # Build cost matrix (negate similarity for min-cost Hungarian)
    cost = np.zeros((n_pred, n_gold))
    for i in range(n_pred):
        for j in range(n_gold):
            if use_embeddings:
                cost[i, j] = -cosine_similarity(pred_embs[i], gold_embs[j])
            else:
                cost[i, j] = -jaccard_similarity(pred_texts[i], gold_texts[j])

    row_ind, col_ind = linear_sum_assignment(cost)

    matches = []
    matched_pred = set()
    matched_gold = set()

    for pi, gj in zip(row_ind, col_ind):
        sim = -cost[pi, gj]
        if sim >= similarity_threshold:
            matched_pred.add(pi)
            matched_gold.add(gj)
            matches.append({
                "pred_name": pred_elements[pi]["name"],
                "pred_value": pred_elements[pi]["value"],
                "gold_name": gold_elements[gj]["name"],
                "gold_value": gold_elements[gj]["value"],
                "similarity": round(sim, 4),
                "match_quality": "good" if sim >= GOOD_MATCH_THRESHOLD else "weak",
            })

    unmatched_pred = [pred_elements[i] for i in range(n_pred) if i not in matched_pred]
    unmatched_gold = [gold_elements[j] for j in range(n_gold) if j not in matched_gold]

    return {
        "matches": matches,
        "unmatched_pred": unmatched_pred,
        "unmatched_gold": unmatched_gold,
    }


def evaluate_sample(
    sample_id: str,
    gold_elements: list[dict[str, str]],
    pred_elements: list[dict[str, str]],
    embedder: OllamaEmbedder | None,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> dict[str, Any]:
    """Run matching + compute per-sample metrics."""
    result = match_elements_hungarian(
        pred_elements, gold_elements, embedder, similarity_threshold
    )

    matches = result["matches"]
    match_scores = [m["similarity"] for m in matches]
    good_matches = sum(1 for m in matches if m["match_quality"] == "good")
    weak_matches = len(matches) - good_matches

    n_gold = len(gold_elements)
    n_pred = len(pred_elements)

    coverage = round(len(matches) / n_gold, 4) if n_gold else 1.0
    precision = round(len(matches) / n_pred, 4) if n_pred else 1.0
    f1 = round(2 * coverage * precision / (coverage + precision), 4) if (coverage + precision) > 0 else 0.0
    avg_sim = round(float(np.mean(match_scores)), 4) if match_scores else 0.0

    return {
        "sample_id": sample_id,
        "gold_count": n_gold,
        "pred_count": n_pred,
        "matched_count": len(matches),
        "good_matches": good_matches,
        "weak_matches": weak_matches,
        "unmatched_pred_count": len(result["unmatched_pred"]),
        "unmatched_gold_count": len(result["unmatched_gold"]),
        "coverage": coverage,
        "precision": precision,
        "f1": f1,
        "avg_similarity": avg_sim,
        "count_diff": n_pred - n_gold,
        "matches": matches,
        "unmatched_pred": result["unmatched_pred"],
        "unmatched_gold": result["unmatched_gold"],
    }


def discover_available_samples(
    gold_root: Path, pred_root: Path
) -> list[tuple[str, list[dict], list[dict]]]:
    """Find samples that have both gold and prediction data."""
    available = []
    for gold_dir in sorted(gold_root.iterdir()):
        if not gold_dir.is_dir() or not gold_dir.name.startswith("char_"):
            continue
        sid = gold_dir.name
        gold = load_gold_elements(gold_root, sid)
        pred = load_pred_elements(pred_root, sid)
        if gold and pred:
            available.append((sid, gold, pred))
    return available


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate atomic_rules_generated.json extractions."
    )
    parser.add_argument("--gold-root", type=Path, default=DEFAULT_GOLD_ROOT)
    parser.add_argument("--pred-root", type=Path, default=DEFAULT_PRED_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample", type=str, help="Evaluate a single sample only.")
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=SIMILARITY_THRESHOLD,
        help="Minimum cosine similarity for a valid match.",
    )
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=Path("vlm/tmp/embedding_cache_local.json"),
    )
    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Skip embeddings — use Jaccard-only baseline.",
    )
    args = parser.parse_args()

    # Collect samples
    if args.sample:
        gold = load_gold_elements(args.gold_root, args.sample)
        pred = load_pred_elements(args.pred_root, args.sample)
        if not gold:
            raise SystemExit(f"No gold data for {args.sample}")
        if not pred:
            raise SystemExit(f"No atomic_rules for {args.sample}")
        samples = [(args.sample, gold, pred)]
    else:
        samples = discover_available_samples(args.gold_root, args.pred_root)
        if not samples:
            raise SystemExit("No samples found with both gold and prediction data.")

    print(f"Evaluating {len(samples)} samples...")

    # Init embedder
    embedder = OllamaEmbedder(cache_path=args.cache_path) if not args.no_embeddings else None

    # Precompute all embeddings in one batch (warm cache)
    if embedder is not None:
        all_texts: list[str] = []
        for _, gold, pred in samples:
            for e in gold:
                all_texts.append(f"{e['name']} {e['value']}")
            for e in pred:
                all_texts.append(e["value"])
        # Deduplicate
        unique_texts = list(dict.fromkeys(all_texts))
        print(f"Precomputing embeddings for {len(unique_texts)} unique texts...")
        embedder.encode(unique_texts)
        print("Embedding precompute done.")

    # Evaluate each sample
    per_sample = []
    for sid, gold, pred in samples:
        result = evaluate_sample(sid, gold, pred, embedder, args.similarity_threshold)
        per_sample.append(result)
        status = (
            f"cov={result['coverage']:.2%} prec={result['precision']:.2%} "
            f"f1={result['f1']:.3f} sim={result['avg_similarity']:.3f} "
            f"matched={result['matched_count']}/{result['gold_count']} "
            f"extra={result['unmatched_pred_count']} miss={result['unmatched_gold_count']}"
        )
        print(f"  {sid}: {status}")

    # Aggregate
    n = len(per_sample)
    avg_coverage = sum(s["coverage"] for s in per_sample) / n
    avg_precision = sum(s["precision"] for s in per_sample) / n
    avg_f1 = sum(s["f1"] for s in per_sample) / n
    avg_sim = sum(s["avg_similarity"] for s in per_sample) / n
    total_matched = sum(s["matched_count"] for s in per_sample)
    total_gold = sum(s["gold_count"] for s in per_sample)
    total_pred = sum(s["pred_count"] for s in per_sample)
    total_unmatched_pred = sum(s["unmatched_pred_count"] for s in per_sample)
    total_unmatched_gold = sum(s["unmatched_gold_count"] for s in per_sample)
    total_good = sum(s["good_matches"] for s in per_sample)
    total_weak = sum(s["weak_matches"] for s in per_sample)

    # Macro coverage/precision (sum of matches / sum of gold/pred)
    macro_coverage = round(total_matched / total_gold, 4) if total_gold else 0.0
    macro_precision = round(total_matched / total_pred, 4) if total_pred else 0.0
    macro_f1 = (
        round(2 * macro_coverage * macro_precision / (macro_coverage + macro_precision), 4)
        if (macro_coverage + macro_precision) > 0
        else 0.0
    )

    summary = {
        "evaluated_samples": n,
        "total_gold_elements": total_gold,
        "total_pred_elements": total_pred,
        "total_matches": total_matched,
        "good_matches": total_good,
        "weak_matches": total_weak,
        "total_unmatched_pred": total_unmatched_pred,
        "total_unmatched_gold": total_unmatched_gold,
        "macro_coverage": macro_coverage,
        "macro_precision": macro_precision,
        "macro_f1": macro_f1,
        "avg_coverage_per_sample": round(avg_coverage, 4),
        "avg_precision_per_sample": round(avg_precision, 4),
        "avg_f1_per_sample": round(avg_f1, 4),
        "avg_similarity": round(avg_sim, 4),
        "similarity_threshold": args.similarity_threshold,
    }

    report = {
        "schema_version": "atomic_rules_eval.v1",
        "summary": summary,
        "per_sample": per_sample,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Print summary
    print(f"\n{'='*60}")
    print(f"SUMMARY ({n} samples)")
    print(f"  Gold elements:     {total_gold}")
    print(f"  Pred elements:     {total_pred}")
    print(f"  Matched:           {total_matched} ({total_good} good, {total_weak} weak)")
    print(f"  Unmatched pred:    {total_unmatched_pred} (extra/misaligned)")
    print(f"  Unmatched gold:    {total_unmatched_gold} (missed)")
    print(f"  Macro Coverage:    {macro_coverage:.2%}")
    print(f"  Macro Precision:   {macro_precision:.2%}")
    print(f"  Macro F1:          {macro_f1:.4f}")
    print(f"  Avg Similarity:    {avg_sim:.4f}")
    print(f"\nReport saved to: {args.output}")


if __name__ == "__main__":
    main()
