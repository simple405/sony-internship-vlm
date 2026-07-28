#!/usr/bin/env python3
"""Compare VLM element extraction output against human GT annotations.

Runs bge-m3 embedding-based semantic matching between qwen36-vl extracted
elements and human-annotated ground truth. Supports compound GT splitting:
elements like "金色长发与黑色蝴蝶结" are automatically split into sub-parts,
allowing multiple VLM predictions to collectively cover one compound GT element.

Key design decisions:
- MIN_SIMILARITY=0.6: filters ~31% of cascading false matches vs 0.5
- Compound splitting threshold: cosine_sim < 0.75 between sub-parts
- Relaxed precision: counts VLM preds with any-GT sim ≥ threshold,
  even if not selected by greedy matching (handles granularity mismatch)

Usage:
    PYTHONUNBUFFERED=1 /usr/bin/python3 vlm/experiment_vlm_analysis.py
"""

import os
import json
import time
import math
import numpy as np
from pathlib import Path

# Bypass HTTP proxy for local connections
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    os.environ.pop(key, None)

import requests


# === CONFIGURATION ===
DATA_DIR = "/home/intern/jsy/vlm/data/SN_6_3D_dataset"
OUTPUT_DIR = "/home/intern/jsy/vlm/experiment_results"
MODEL_NAME = "qwen36-vl:latest"
EMBED_MODEL_NAME = "bge-m3:latest"  # local ollama embedding model
MIN_SIMILARITY = 0.6  # reject matches below this threshold — 0.6 filters ~31% of cascading false matches
RELAXED_PRECISION_THRESHOLD = 0.6  # for relaxed precision: any-GT similarity above this counts

def load_ground_truth(char_dir: str) -> dict:
    """Load ground truth JSON for a character.

    Normalizes element dicts to always have 'name' and 'value' keys,
    handling known data quirks (typos like 'value:', duplicate entries).
    """
    char_name = os.path.basename(char_dir)
    json_path = os.path.join(char_dir, f"{char_name}.json")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Normalize elements: ensure each has 'name' + 'value' keys
    elements = data.get('elements', [])
    if isinstance(elements, list):
        normalized = []
        seen = set()
        for elem in elements:
            name = elem.get('name', '')
            # Handle typo key "value:" (with trailing colon)
            val = elem.get('value') or elem.get('value:') or ''
            dedup_key = f"{name}|{val}"
            if dedup_key not in seen:
                seen.add(dedup_key)
                normalized.append({'name': name, 'value': val})
        data['elements'] = normalized

    return data


def load_vlm_extraction(char_name: str) -> dict:
    """Load pre-extracted VLM elements from supervision_agent_output.

    Instead of re-running VLM inference (slow, deterministic), reads the
    already-extracted elements from the batch supervision output.
    """
    extraction_path = (
        f"/home/intern/jsy/vlm/tmp/supervision_agent_output/"
        f"{char_name}/extraction/{char_name}/extracted_elements.json"
    )
    with open(extraction_path, "r", encoding="utf-8") as f:
        return json.load(f)


class OllamaEmbedder:
    """Thin wrapper around Ollama embedding API with caching for efficiency."""

    def __init__(self, model_name: str = "bge-m3:latest"):
        self.model_name = model_name
        self._cache = {}

    def encode(self, texts: list) -> np.ndarray:
        """Encode a list of texts and return embeddings as numpy array.

        Uses Ollama's /api/embed batch endpoint for efficiency — one HTTP
        round-trip per call instead of one per text.
        """
        results = [None] * len(texts)
        to_embed_indices = []
        to_embed_texts = []

        # Check cache first
        for i, text in enumerate(texts):
            if text in self._cache:
                results[i] = self._cache[text]
            else:
                to_embed_indices.append(i)
                to_embed_texts.append(text)

        if not to_embed_texts:
            return np.array(results, dtype=np.float32)

        # Batch embed all uncached texts in one request
        resp = requests.post(
            "http://127.0.0.1:11434/api/embed",
            json={"model": self.model_name, "input": to_embed_texts},
            proxies={"http": None, "https": None},
            timeout=120
        )
        resp.raise_for_status()
        embeddings = resp.json()['embeddings']

        for idx, emb in zip(to_embed_indices, embeddings):
            arr = np.array(emb, dtype=np.float32)
            self._cache[to_embed_texts[to_embed_indices.index(idx)]] = arr
            results[idx] = arr

        return np.array(results, dtype=np.float32)

    def encode_single(self, text: str) -> np.ndarray:
        """Encode a single text."""
        return self.encode([text])[0]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def split_compound_name(name: str, embedder: OllamaEmbedder) -> list:
    """Split compound element name if it contains semantic separator.

    Detects compound patterns like "A与B", "A及B", "A和B" and splits them
    only when the two parts are semantically distinct (cosine sim < 0.75).
    This avoids false splits like "黑色与金色拼接外套" (one item with two colors).

    Args:
        name: Element name to check for compound pattern
        embedder: Embedding model for semantic distance check

    Returns:
        List of sub-names if compound detected and split, otherwise [name]
    """
    for sep in ['与', '及', '和']:
        if sep not in name:
            continue
        parts = [p.strip() for p in name.split(sep, maxsplit=1)]
        if len(parts) == 2 and all(len(p) >= 2 for p in parts):
            # Semantic distance check: only split if parts are distinct elements
            embs = embedder.encode(parts)
            sim = cosine_similarity(embs[0], embs[1])
            if sim < 0.75:  # Threshold: below 0.75 = different elements
                return parts
    return [name]  # No split


def expand_gt_for_matching(gt_elements: list, embedder: OllamaEmbedder) -> tuple:
    """Expand GT elements into matching candidates (originals + virtual sub-elements).

    For compound GT elements like "金色长发与黑色蝴蝶结", creates:
    1. Original candidate: "金色长发与黑色蝴蝶结: {value}"
    2. Virtual sub-candidate 1: "金色长发: {value}"
    3. Virtual sub-candidate 2: "黑色蝴蝶结: {value}"

    Each candidate tracks which original GT element it belongs to, enabling
    many-to-one matching (multiple predictions can cover one compound GT).

    Args:
        gt_elements: Original GT elements list
        embedder: Embedding model for compound detection

    Returns:
        (matching_candidates, gt_element_map)
        - matching_candidates: Expanded list for matching (len >= len(gt_elements))
        - gt_element_map: Maps candidate_idx -> (original_gt_idx, is_virtual)
    """
    matching_candidates = []
    gt_element_map = []  # List of (gt_idx, is_virtual, sub_part_idx)

    for i, gt_elem in enumerate(gt_elements):
        # Always add the original full element
        matching_candidates.append({
            'name': gt_elem['name'],
            'value': gt_elem['value']
        })
        gt_element_map.append((i, False, None))  # (gt_idx, is_virtual, sub_idx)

        # Detect and add virtual sub-elements for compounds
        sub_names = split_compound_name(gt_elem['name'], embedder)
        if len(sub_names) > 1:
            for j, sub_name in enumerate(sub_names):
                matching_candidates.append({
                    'name': sub_name,
                    'value': gt_elem['value']  # Reuse full description
                })
                gt_element_map.append((i, True, j))  # Virtual sub-element

    return matching_candidates, gt_element_map


def match_elements(pred_elements: list, gt_elements: list, embedder: OllamaEmbedder) -> tuple:
    """
    Match predicted elements to ground truth elements with compound-aware matching.

    Supports many-to-one matching: multiple predictions can match different sub-parts
    of a compound GT element (e.g., "金色长发" and "黑色蝴蝶结" both match
    "金色长发与黑色蝴蝶结").

    Uses greedy matching: best match for each prediction against all GT candidates
    (originals + virtual sub-elements from compound expansion).

    Returns: (matches, unmatched_pred, unmatched_gt, coverage_info)
        - matches: List of matched (pred, gt_candidate) pairs
        - unmatched_pred: Predictions that didn't match any GT candidate
        - unmatched_gt: Original GT elements with no matches (direct or via sub-parts)
        - coverage_info: Dict with compound-aware coverage statistics
    """
    matches = []

    if not pred_elements or not gt_elements:
        return matches, list(pred_elements), list(gt_elements), {}

    # Expand GT elements: original + virtual sub-elements for compounds
    gt_candidates, gt_element_map = expand_gt_for_matching(gt_elements, embedder)

    # Build combined text for matching: name + ": " + description
    pred_texts = [f"{e['name']}: {e['value']}" for e in pred_elements]
    cand_texts = [f"{c['name']}: {c['value']}" for c in gt_candidates]
    pred_names = [e['name'] for e in pred_elements]
    cand_names = [c['name'] for c in gt_candidates]

    # Encode all at once (uses cache internally)
    pred_embs = embedder.encode(pred_texts)
    cand_embs = embedder.encode(cand_texts)
    pred_name_embs = embedder.encode(pred_names)
    cand_name_embs = embedder.encode(cand_names)

    # Greedy matching: for each prediction, find best unmatched GT candidate
    matched_cand_indices = set()
    matched_pred_indices = set()

    for i in range(len(pred_elements)):
        best_score = 0.0
        best_cand_idx = -1
        for j in range(len(gt_candidates)):
            if j in matched_cand_indices:
                continue
            # Combined text similarity
            text_sim = cosine_similarity(pred_embs[i], cand_embs[j])
            # Name-only similarity
            name_sim = cosine_similarity(pred_name_embs[i], cand_name_embs[j])
            # Weighted: 30% name + 70% full text
            combined = 0.3 * name_sim + 0.7 * text_sim
            if combined > best_score:
                best_score = combined
                best_cand_idx = j

        if best_cand_idx >= 0 and best_score >= MIN_SIMILARITY:
            matched_cand_indices.add(best_cand_idx)
            matched_pred_indices.add(i)

            # Get original GT element info via map
            orig_gt_idx, is_virtual, sub_idx = gt_element_map[best_cand_idx]
            matched_gt_name = gt_candidates[best_cand_idx]['name']
            matched_gt_value = gt_candidates[best_cand_idx]['value']

            matches.append({
                'pred_name': pred_elements[i]['name'],
                'pred_value': pred_elements[i]['value'],
                'pred_category': pred_elements[i].get('category', 'unknown'),
                'gt_name': matched_gt_name,
                'gt_value': matched_gt_value,
                'similarity': round(best_score, 4),
                'matched_original_gt': gt_elements[orig_gt_idx]['name'],
                'is_virtual_match': is_virtual,
                'original_gt_idx': orig_gt_idx
            })

    # Compute coverage at original GT element level
    covered_gt_indices = set(m['original_gt_idx'] for m in matches)

    # Partial coverage: a compound GT with 2 sub-parts where only 1 matched
    # gets 0.5 credit, not 1.0. Keeps the compound annotation meaningful
    # instead of letting a single sub-part match satisfy the whole element.
    sub_part_totals = {}  # gt_idx -> number of virtual sub-parts
    for cand_idx, (gt_idx, is_virtual, _) in enumerate(gt_element_map):
        if is_virtual:
            sub_part_totals[gt_idx] = sub_part_totals.get(gt_idx, 0) + 1

    coverage_scores = []
    for j in range(len(gt_elements)):
        j_matches = [m for m in matches if m['original_gt_idx'] == j]
        if not j_matches:
            coverage_scores.append(0.0)
        elif any(not m['is_virtual_match'] for m in j_matches):
            coverage_scores.append(1.0)  # direct match on the full compound
        else:
            # Only sub-parts matched — credit the fraction covered
            n_total = sub_part_totals.get(j, 1)
            coverage_scores.append(min(1.0, len(j_matches) / n_total))

    # Unmatched predictions (model found extra)
    unmatched_pred = [pred_elements[i] for i in range(len(pred_elements))
                      if i not in matched_pred_indices]

    # Unmatched original GT elements (no direct or virtual matches)
    unmatched_gt = [gt_elements[j] for j in range(len(gt_elements))
                    if j not in covered_gt_indices]

    # Partially covered compounds — worth surfacing separately from full misses
    partial_gt = [
        {'name': gt_elements[j]['name'], 'coverage': round(coverage_scores[j], 4)}
        for j in range(len(gt_elements))
        if 0.0 < coverage_scores[j] < 1.0
    ]

    # Coverage info for reporting
    coverage_info = {
        'total_gt_candidates': len(gt_candidates),
        'total_original_gt': len(gt_elements),
        'covered_original_gt': len(covered_gt_indices),
        'weighted_coverage_sum': round(sum(coverage_scores), 4),
        'partially_covered_gt': partial_gt,
        'virtual_matches': sum(1 for m in matches if m['is_virtual_match']),
        'direct_matches': sum(1 for m in matches if not m['is_virtual_match'])
    }

    return matches, unmatched_pred, unmatched_gt, coverage_info


def run_experiment():
    """Main experiment loop."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Initialize Ollama embedder for semantic comparison
    print("=" * 70)
    print("Initializing embedding model for semantic comparison...")
    embedder = OllamaEmbedder(EMBED_MODEL_NAME)
    # Warm up with a test embedding
    test_emb = embedder.encode_single("测试文本")
    print(f"  Using {EMBED_MODEL_NAME} via Ollama (dim={len(test_emb)})")
    print(f"  Embedding cache enabled for efficiency")

    # Collect all character directories
    char_dirs = sorted([
        d for d in Path(DATA_DIR).iterdir()
        if d.is_dir() and d.name.startswith('char_')
    ])
    print(f"\nFound {len(char_dirs)} character directories to analyze.")
    print("=" * 70)

    all_results = []
    total_start = time.time()

    for idx, char_dir in enumerate(char_dirs):
        char_name = char_dir.name
        image_path = char_dir / f"{char_name}.png"
        json_path = char_dir / f"{char_name}.json"

        if not image_path.exists():
            print(f"\n[{idx+1}/{len(char_dirs)}] {char_name}: SKIP (no image)")
            continue
        if not json_path.exists():
            print(f"\n[{idx+1}/{len(char_dirs)}] {char_name}: SKIP (no ground truth)")
            continue

        print(f"\n[{idx+1}/{len(char_dirs)}] Analyzing {char_name}...")
        t_start = time.time()

        # Load ground truth
        gt = load_ground_truth(str(char_dir))

        # Load pre-extracted VLM elements
        try:
            pred = load_vlm_extraction(char_name)
        except Exception as e:
            print(f"  ERROR loading VLM extraction: {e}")
            pred = {"elements": [], "_raw_output": f"ERROR: {e}"}

        pred_elements = pred.get('elements', [])
        gt_elements = gt.get('elements', [])

        print(f"  Model found {len(pred_elements)} elements, GT has {len(gt_elements)} elements")

        # Match and compute similarities (compound-aware matching)
        matches, unmatched_pred, unmatched_gt, coverage_info = match_elements(
            pred_elements, gt_elements, embedder
        )

        # Compute per-sample metrics
        match_scores = [m['similarity'] for m in matches]
        avg_similarity = round(sum(match_scores) / len(match_scores), 4) if match_scores else 0.0

        # Coverage: weighted by partial compound coverage
        # Full direct match = 1.0, partial compound (1/2 sub-parts) = 0.5
        coverage = round(coverage_info['weighted_coverage_sum'] / len(gt_elements), 4) if gt_elements else 1.0

        # Precision (strict): how many predictions matched any GT candidate
        precision = round(len(matches) / len(pred_elements), 4) if pred_elements else 1.0

        # Relaxed precision: predictions with high similarity to ANY GT (even if not "best match")
        # This gives credit for correct extractions that lost in greedy competition
        relaxed_matched = 0
        if pred_elements and gt_elements:
            # Quick check: for unmatched predictions, check if they have ANY GT with sim > threshold
            for pred_elem in unmatched_pred:
                pred_text = f"{pred_elem['name']}: {pred_elem['value']}"
                pred_emb = embedder.encode([pred_text])[0]
                # Check against all original GT elements
                for gt_elem in gt_elements:
                    gt_text = f"{gt_elem['name']}: {gt_elem['value']}"
                    gt_emb = embedder.encode([gt_text])[0]
                    if cosine_similarity(pred_emb, gt_emb) >= RELAXED_PRECISION_THRESHOLD:
                        relaxed_matched += 1
                        break  # Count this pred once
        relaxed_precision = round((len(matches) + relaxed_matched) / len(pred_elements), 4) if pred_elements else 1.0

        result = {
            'sample_id': char_name,
            'gt_element_count': len(gt_elements),
            'pred_element_count': len(pred_elements),
            'matched_count': len(matches),
            'unmatched_pred_count': len(unmatched_pred),
            'unmatched_gt_count': len(unmatched_gt),
            'avg_similarity': avg_similarity,
            'coverage': coverage,
            'precision': precision,
            'relaxed_precision': relaxed_precision,
            'matches': matches,
            'unmatched_pred': [{'name': e['name'], 'value': e['value'], 'category': e.get('category', 'unknown')} for e in unmatched_pred],
            'unmatched_gt': [{'name': e['name'], 'value': e['value']} for e in unmatched_gt],
            'pred_elements': [{'name': e['name'], 'value': e['value'], 'category': e.get('category', 'unknown')} for e in pred_elements],
            'gt_elements': gt_elements,
            'coverage_info': coverage_info,
            '_raw_model_output': pred.get('_raw_output', ''),
            '_inference_time_s': round(time.time() - t_start, 1)
        }
        all_results.append(result)

        print(f"  Matched: {len(matches)} ({coverage_info.get('virtual_matches',0)} via sub-parts), "
              f"Unmatched pred: {len(unmatched_pred)}, Unmatched GT: {len(unmatched_gt)}")
        print(f"  Avg Similarity: {avg_similarity}, Coverage: {coverage}, "
              f"Precision: {precision}, Relaxed Prec: {relaxed_precision}")
        print(f"  Time: {result['_inference_time_s']}s")

    total_time = round(time.time() - total_start, 1)

    # === AGGREGATE METRICS ===
    print("\n" + "=" * 70)
    print("AGGREGATE RESULTS")
    print("=" * 70)

    all_avg_sim = [r['avg_similarity'] for r in all_results if r['matched_count'] > 0]
    all_coverage = [r['coverage'] for r in all_results]
    all_precision = [r['precision'] for r in all_results]
    all_relaxed_precision = [r['relaxed_precision'] for r in all_results]
    total_gt = sum(r['gt_element_count'] for r in all_results)
    total_pred = sum(r['pred_element_count'] for r in all_results)
    total_matched = sum(r['matched_count'] for r in all_results)
    total_unmatched_pred = sum(r['unmatched_pred_count'] for r in all_results)
    total_unmatched_gt = sum(r['unmatched_gt_count'] for r in all_results)
    total_virtual_matches = sum(r.get('coverage_info', {}).get('virtual_matches', 0) for r in all_results)
    total_direct_matches = sum(r.get('coverage_info', {}).get('direct_matches', 0) for r in all_results)

    summary = {
        'experiment': 'VLM Anime Character Element Extraction (compound-aware matching)',
        'model': MODEL_NAME,
        'embedding_model': EMBED_MODEL_NAME + " (via Ollama)",
        'min_similarity_threshold': MIN_SIMILARITY,
        'relaxed_precision_threshold': RELAXED_PRECISION_THRESHOLD,
        'total_samples': len(all_results),
        'total_time_s': total_time,
        'aggregate_metrics': {
            'avg_similarity_mean': round(sum(all_avg_sim) / len(all_avg_sim), 4) if all_avg_sim else 0,
            'avg_similarity_min': round(min(all_avg_sim), 4) if all_avg_sim else 0,
            'avg_similarity_max': round(max(all_avg_sim), 4) if all_avg_sim else 0,
            'coverage_mean': round(sum(all_coverage) / len(all_coverage), 4) if all_coverage else 0,
            'precision_mean': round(sum(all_precision) / len(all_precision), 4) if all_precision else 0,
            'relaxed_precision_mean': round(sum(all_relaxed_precision) / len(all_relaxed_precision), 4) if all_relaxed_precision else 0,
            'total_gt_elements': total_gt,
            'total_pred_elements': total_pred,
            'total_matched': total_matched,
            'total_direct_matches': total_direct_matches,
            'total_virtual_matches': total_virtual_matches,  # matches via compound sub-parts
            'total_unmatched_pred': total_unmatched_pred,
            'total_unmatched_gt': total_unmatched_gt,
            'overall_coverage': round(total_matched / total_gt, 4) if total_gt else 0,
            'overall_precision': round(total_matched / total_pred, 4) if total_pred else 0,
        },
        'per_sample': all_results
    }

    # === PER-CATEGORY METRICS ===
    # Aggregate by VLM category (hair, face, clothing, accessory, headwear, etc.)
    cat_matched = {}
    cat_total = {}
    cat_similarities = {}
    for r in all_results:
        for m in r['matches']:
            cat = m.get('pred_category', 'unknown')
            cat_matched[cat] = cat_matched.get(cat, 0) + 1
            cat_similarities.setdefault(cat, []).append(m['similarity'])
        for e in r['pred_elements']:
            cat = e.get('category', 'unknown')
            cat_total[cat] = cat_total.get(cat, 0) + 1

    category_metrics = {}
    for cat in sorted(set(list(cat_matched.keys()) + list(cat_total.keys()))):
        matched = cat_matched.get(cat, 0)
        total = cat_total.get(cat, 0)
        sims = cat_similarities.get(cat, [])
        category_metrics[cat] = {
            'total_pred': total,
            'matched': matched,
            'unmatched': total - matched,
            'precision': round(matched / total, 4) if total > 0 else 0,
            'avg_similarity': round(sum(sims) / len(sims), 4) if sims else 0,
        }

    summary['category_metrics'] = category_metrics

    # Save detailed results
    output_path = os.path.join(OUTPUT_DIR, 'experiment_results.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed results saved to: {output_path}")

    # Save human-readable report
    report_path = os.path.join(OUTPUT_DIR, 'experiment_report.md')
    generate_report(summary, report_path)
    print(f"Report saved to: {report_path}")

    # Print summary
    print(f"\n{'='*70}")
    print("EXPERIMENT SUMMARY")
    print(f"{'='*70}")
    print(f"Samples processed: {len(all_results)}")
    print(f"Total time: {total_time}s")
    m_agg = summary['aggregate_metrics']
    print(f"Avg Semantic Similarity: {m_agg['avg_similarity_mean']}")
    print(f"Avg Coverage (GT recall):  {m_agg['coverage_mean']}")
    print(f"Avg Precision (strict):    {m_agg['precision_mean']}")
    print(f"Avg Precision (relaxed):   {m_agg['relaxed_precision_mean']}")
    print(f"Total GT elements: {total_gt}, Matched: {total_matched} "
          f"({total_virtual_matches} via compound sub-parts)")
    print(f"Total Pred elements: {total_pred}")
    print(f"Unmatched predictions (model extra): {total_unmatched_pred}")
    print(f"Unmatched GT (model missed): {total_unmatched_gt}")
    print(f"\nPer-Category Breakdown:")
    for cat in sorted(category_metrics.keys()):
        cm = category_metrics[cat]
        print(f"  {cat}: precision={cm['precision']}, matched={cm['matched']}/{cm['total_pred']}, "
              f"avg_sim={cm['avg_similarity']}")

    return summary


def generate_report(summary: dict, output_path: str):
    """Generate a human-readable markdown report."""
    lines = []
    lines.append("# VLM Image Analysis Experiment Report")
    lines.append("")
    lines.append(f"**Model**: {summary['model']}")
    lines.append(f"**Embedding Model**: {summary['embedding_model']}")
    lines.append(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Total Samples**: {summary['total_samples']}")
    lines.append(f"**Total Time**: {summary['total_time_s']}s")
    lines.append("")

    m = summary['aggregate_metrics']
    lines.append("## Aggregate Metrics")
    lines.append("")
    lines.append(f"> Matching threshold: `MIN_SIMILARITY={summary.get('min_similarity_threshold', 0.6)}`  ")
    lines.append(f"> Compound GT splitting enabled — multiple predictions can match sub-parts of a compound GT element.")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Avg Semantic Similarity | {m['avg_similarity_mean']} |")
    lines.append(f"| Min Similarity | {m['avg_similarity_min']} |")
    lines.append(f"| Max Similarity | {m['avg_similarity_max']} |")
    lines.append(f"| Avg Coverage (GT recall, compound-aware) | {m['coverage_mean']} |")
    lines.append(f"| Avg Precision (strict, pred→GT) | {m['precision_mean']} |")
    lines.append(f"| Avg Precision (relaxed, any-GT≥{summary.get('relaxed_precision_threshold', 0.6)}) | {m['relaxed_precision_mean']} |")
    lines.append(f"| Total GT Elements | {m['total_gt_elements']} |")
    lines.append(f"| Total Predicted Elements | {m['total_pred_elements']} |")
    lines.append(f"| Total Matched | {m['total_matched']} ({m.get('total_virtual_matches', 0)} via compound sub-parts) |")
    lines.append(f"| Total Unmatched (extra predictions) | {m['total_unmatched_pred']} |")
    lines.append(f"| Total Unmatched (missed GT) | {m['total_unmatched_gt']} |")
    lines.append(f"| Overall Coverage | {m['overall_coverage']} |")
    lines.append(f"| Overall Precision | {m['overall_precision']} |")
    lines.append("")

    # Per-Category Breakdown
    if summary.get('category_metrics'):
        lines.append("## Per-Category Breakdown")
        lines.append("")
        lines.append("| Category | Precision | Matched / Total | Avg Similarity |")
        lines.append("|----------|-----------|-----------------|----------------|")
        for cat in sorted(summary['category_metrics'].keys()):
            cm = summary['category_metrics'][cat]
            lines.append(f"| {cat} | {cm['precision']} | {cm['matched']}/{cm['total_pred']} | {cm['avg_similarity']} |")
        lines.append("")

    lines.append("## Per-Sample Details")
    lines.append("")
    for r in summary['per_sample']:
        cov_info = r.get('coverage_info', {})
        virtual = cov_info.get('virtual_matches', 0)
        virtual_note = f" ({virtual} via sub-parts)" if virtual > 0 else ""

        lines.append(f"### {r['sample_id']}")
        lines.append(f"")
        lines.append(f"- **GT elements**: {r['gt_element_count']}, **Pred elements**: {r['pred_element_count']}")
        lines.append(f"- **Matched**: {r['matched_count']}{virtual_note}, **Avg Similarity**: {r['avg_similarity']}")
        lines.append(f"- **Coverage**: {r['coverage']}, **Precision (strict)**: {r['precision']}, "
                     f"**Precision (relaxed)**: {r.get('relaxed_precision', '-')}")
        lines.append(f"- **Inference time**: {r['_inference_time_s']}s")
        lines.append("")

        if r['matches']:
            lines.append("#### Matched Pairs (Prediction ↔ Ground Truth)")
            lines.append("")
            lines.append("| # | Predicted Element | GT Element | Similarity | Via Sub-part? |")
            lines.append("|---|-------------------|------------|------------|---------------|")
            for i, m in enumerate(r['matches'], 1):
                pred_short = m['pred_name'][:40]
                gt_short = m['gt_name'][:40]
                orig_gt = m.get('matched_original_gt', '')
                is_virtual = m.get('is_virtual_match', False)
                virtual_flag = f"✓ ({orig_gt[:30]})" if is_virtual else ""
                lines.append(f"| {i} | {pred_short} | {gt_short} | {m['similarity']} | {virtual_flag} |")
            lines.append("")

        if r['unmatched_pred']:
            lines.append("#### Extra Predictions (model found, not in GT)")
            lines.append("")
            for e in r['unmatched_pred']:
                lines.append(f"- **{e['name']}**: {e['value']}")
            lines.append("")

        if r['unmatched_gt']:
            lines.append("#### Missed Elements (in GT, model didn't find)")
            lines.append("")
            for e in r['unmatched_gt']:
                lines.append(f"- **{e['name']}**: {e['value']}")
            lines.append("")

        lines.append("---")
        lines.append("")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


if __name__ == '__main__':
    run_experiment()
