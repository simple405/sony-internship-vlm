#!/usr/bin/env python3
"""
VLM Image Analysis Experiment
- Uses local qwen36-vl model (via Ollama) to analyze anime character images
- Compares model output with ground truth JSON annotations
- Computes semantic similarity using Ollama's bge-m3 embeddings (local)
- Generates a comprehensive comparison report
"""

import os
import sys
import json
import base64
import time
import re
import math
import numpy as np
from pathlib import Path

# Bypass HTTP proxy for local connections
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    os.environ.pop(key, None)

import ollama


# === CONFIGURATION ===
DATA_DIR = "/home/intern/jsy/vlm/data/SN_6期动漫数据标注"
OUTPUT_DIR = "/home/intern/jsy/vlm/experiment_results"
MODEL_NAME = "qwen36-vl:latest"
EMBED_MODEL_NAME = "bge-m3:latest"  # local ollama embedding model

VLM_PROMPT = """请仔细观察这张动漫角色图片，列出该角色的所有关键视觉元素。对于每个元素，给出元素名称和详细的视觉描述。

请严格按照以下JSON格式输出，只输出JSON，不要添加任何其他文字：
{
  "elements": [
    {"name": "元素名称", "value": "该元素的详细视觉描述"},
    {"name": "元素名称", "value": "该元素的详细视觉描述"}
  ]
}

要求：
- 必须包含：发型发色、眼睛颜色和形状、服装、配饰、特殊标志等
- 每个元素描述要具体详细，包括颜色、形状、位置等信息
- 至少列出5个元素
"""


def extract_json_from_response(text: str) -> dict:
    """Extract JSON object from model response (may contain markdown code fences)."""
    # Remove markdown code fences if present
    text = text.strip()
    # Try to find JSON between ```json and ``` markers
    match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', text)
    if match:
        text = match.group(1)
    # Try to parse as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object in the text
        match = re.search(r'\{[\s\S]*"elements"[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        print(f"  WARNING: Could not parse JSON from response. Raw:\n{text[:500]}")
        return {"elements": []}


def load_ground_truth(char_dir: str) -> dict:
    """Load ground truth JSON for a character."""
    char_name = os.path.basename(char_dir)
    json_path = os.path.join(char_dir, f"{char_name}.json")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_image(image_path: str) -> dict:
    """Send image to VLM and get element analysis."""
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{
            'role': 'user',
            'content': VLM_PROMPT,
            'images': [image_path]  # Pass file path directly
        }],
        options={'temperature': 0.1, 'num_predict': 2048}
    )

    raw_output = response['message']['content']
    parsed = extract_json_from_response(raw_output)
    parsed['_raw_output'] = raw_output
    return parsed


class OllamaEmbedder:
    """Thin wrapper around Ollama embedding API with caching for efficiency."""

    def __init__(self, model_name: str = "bge-m3:latest"):
        self.model_name = model_name
        self._cache = {}

    def encode(self, texts: list) -> np.ndarray:
        """Encode a list of texts and return embeddings as numpy array."""
        results = []
        to_embed = []
        to_embed_indices = []

        # Check cache first
        for i, text in enumerate(texts):
            if text in self._cache:
                results.append((i, self._cache[text]))
            else:
                to_embed.append(text)
                to_embed_indices.append(i)
                results.append((i, None))

        # Batch embed uncached texts one by one (ollama embed doesn't batch well)
        for idx, text in zip(to_embed_indices, to_embed):
            resp = ollama.embed(model=self.model_name, input=text)
            emb = np.array(resp['embeddings'][0], dtype=np.float32)
            self._cache[text] = emb
            results[idx] = (idx, emb)

        # Return in original order
        return np.array([emb for _, emb in results], dtype=np.float32)

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


def match_elements(pred_elements: list, gt_elements: list, embedder: OllamaEmbedder) -> tuple:
    """
    Match predicted elements to ground truth elements based on semantic similarity.
    Uses greedy matching: best match for each prediction, then next best for remaining.

    Returns: (matches, unmatched_pred, unmatched_gt)
    """
    matches = []

    if not pred_elements or not gt_elements:
        return matches, list(pred_elements), list(gt_elements)

    # Build combined text for matching: name + ": " + description
    pred_texts = [f"{e['name']}: {e['value']}" for e in pred_elements]
    gt_texts = [f"{e['name']}: {e['value']}" for e in gt_elements]
    pred_names = [e['name'] for e in pred_elements]
    gt_names = [e['name'] for e in gt_elements]

    # Encode all at once (uses cache internally)
    pred_embs = embedder.encode(pred_texts)
    gt_embs = embedder.encode(gt_texts)
    pred_name_embs = embedder.encode(pred_names)
    gt_name_embs = embedder.encode(gt_names)

    # Greedy matching: for each prediction, find best unmatched GT
    matched_gt_indices = set()
    matched_pred_indices = set()

    for i in range(len(pred_elements)):
        best_score = 0.0
        best_gt_idx = -1
        for j in range(len(gt_elements)):
            if j in matched_gt_indices:
                continue
            # Combined text similarity
            text_sim = cosine_similarity(pred_embs[i], gt_embs[j])
            # Name-only similarity
            name_sim = cosine_similarity(pred_name_embs[i], gt_name_embs[j])
            # Weighted: 30% name + 70% full text
            combined = 0.3 * name_sim + 0.7 * text_sim
            if combined > best_score:
                best_score = combined
                best_gt_idx = j

        if best_gt_idx >= 0:
            matched_gt_indices.add(best_gt_idx)
            matched_pred_indices.add(i)
            matches.append({
                'pred_name': pred_elements[i]['name'],
                'pred_value': pred_elements[i]['value'],
                'gt_name': gt_elements[best_gt_idx]['name'],
                'gt_value': gt_elements[best_gt_idx]['value'],
                'similarity': round(best_score, 4)
            })

    # Unmatched predictions (model found extra)
    unmatched_pred = [pred_elements[i] for i in range(len(pred_elements))
                      if i not in matched_pred_indices]

    # Unmatched GT (model missed)
    unmatched_gt = [gt_elements[j] for j in range(len(gt_elements))
                    if j not in matched_gt_indices]

    return matches, unmatched_pred, unmatched_gt


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

        # Analyze with VLM
        try:
            pred = analyze_image(str(image_path))
        except Exception as e:
            print(f"  ERROR during VLM inference: {e}")
            pred = {"elements": [], "_raw_output": f"ERROR: {e}"}

        pred_elements = pred.get('elements', [])
        gt_elements = gt.get('elements', [])

        print(f"  Model found {len(pred_elements)} elements, GT has {len(gt_elements)} elements")

        # Match and compute similarities
        matches, unmatched_pred, unmatched_gt = match_elements(
            pred_elements, gt_elements, embedder
        )

        # Compute per-sample metrics
        match_scores = [m['similarity'] for m in matches]
        avg_similarity = round(sum(match_scores) / len(match_scores), 4) if match_scores else 0.0

        # Coverage: how many GT elements were matched
        coverage = round(len(matches) / len(gt_elements), 4) if gt_elements else 1.0

        # Precision: how many predictions matched GT
        precision = round(len(matches) / len(pred_elements), 4) if pred_elements else 1.0

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
            'matches': matches,
            'unmatched_pred': [{'name': e['name'], 'value': e['value']} for e in unmatched_pred],
            'unmatched_gt': [{'name': e['name'], 'value': e['value']} for e in unmatched_gt],
            'pred_elements': [{'name': e['name'], 'value': e['value']} for e in pred_elements],
            'gt_elements': gt_elements,
            '_raw_model_output': pred.get('_raw_output', ''),
            '_inference_time_s': round(time.time() - t_start, 1)
        }
        all_results.append(result)

        print(f"  Matched: {len(matches)}, Unmatched pred: {len(unmatched_pred)}, "
              f"Unmatched GT: {len(unmatched_gt)}")
        print(f"  Avg Similarity: {avg_similarity}, Coverage: {coverage}, Precision: {precision}")
        print(f"  Time: {result['_inference_time_s']}s")

    total_time = round(time.time() - total_start, 1)

    # === AGGREGATE METRICS ===
    print("\n" + "=" * 70)
    print("AGGREGATE RESULTS")
    print("=" * 70)

    all_avg_sim = [r['avg_similarity'] for r in all_results if r['matched_count'] > 0]
    all_coverage = [r['coverage'] for r in all_results]
    all_precision = [r['precision'] for r in all_results]
    total_gt = sum(r['gt_element_count'] for r in all_results)
    total_pred = sum(r['pred_element_count'] for r in all_results)
    total_matched = sum(r['matched_count'] for r in all_results)
    total_unmatched_pred = sum(r['unmatched_pred_count'] for r in all_results)
    total_unmatched_gt = sum(r['unmatched_gt_count'] for r in all_results)

    summary = {
        'experiment': 'VLM Anime Character Element Extraction',
        'model': MODEL_NAME,
        'embedding_model': EMBED_MODEL_NAME + " (via Ollama)",
        'total_samples': len(all_results),
        'total_time_s': total_time,
        'aggregate_metrics': {
            'avg_similarity_mean': round(sum(all_avg_sim) / len(all_avg_sim), 4) if all_avg_sim else 0,
            'avg_similarity_min': round(min(all_avg_sim), 4) if all_avg_sim else 0,
            'avg_similarity_max': round(max(all_avg_sim), 4) if all_avg_sim else 0,
            'coverage_mean': round(sum(all_coverage) / len(all_coverage), 4) if all_coverage else 0,
            'precision_mean': round(sum(all_precision) / len(all_precision), 4) if all_precision else 0,
            'total_gt_elements': total_gt,
            'total_pred_elements': total_pred,
            'total_matched': total_matched,
            'total_unmatched_pred': total_unmatched_pred,
            'total_unmatched_gt': total_unmatched_gt,
            'overall_coverage': round(total_matched / total_gt, 4) if total_gt else 0,
            'overall_precision': round(total_matched / total_pred, 4) if total_pred else 0,
        },
        'per_sample': all_results
    }

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
    print(f"Avg Semantic Similarity: {summary['aggregate_metrics']['avg_similarity_mean']}")
    print(f"Avg Coverage (GT matched): {summary['aggregate_metrics']['coverage_mean']}")
    print(f"Avg Precision (Pred matched): {summary['aggregate_metrics']['precision_mean']}")
    print(f"Total GT elements: {total_gt}, Matched: {total_matched}")
    print(f"Total Pred elements: {total_pred}, Matched: {total_matched}")
    print(f"Unmatched predictions (model extra): {total_unmatched_pred}")
    print(f"Unmatched GT (model missed): {total_unmatched_gt}")

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
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Avg Semantic Similarity | {m['avg_similarity_mean']} |")
    lines.append(f"| Min Similarity | {m['avg_similarity_min']} |")
    lines.append(f"| Max Similarity | {m['avg_similarity_max']} |")
    lines.append(f"| Avg Coverage (GT recall) | {m['coverage_mean']} |")
    lines.append(f"| Avg Precision | {m['precision_mean']} |")
    lines.append(f"| Total GT Elements | {m['total_gt_elements']} |")
    lines.append(f"| Total Predicted Elements | {m['total_pred_elements']} |")
    lines.append(f"| Total Matched | {m['total_matched']} |")
    lines.append(f"| Total Unmatched (extra predictions) | {m['total_unmatched_pred']} |")
    lines.append(f"| Total Unmatched (missed GT) | {m['total_unmatched_gt']} |")
    lines.append(f"| Overall Coverage | {m['overall_coverage']} |")
    lines.append(f"| Overall Precision | {m['overall_precision']} |")
    lines.append("")

    lines.append("## Per-Sample Details")
    lines.append("")
    for r in summary['per_sample']:
        lines.append(f"### {r['sample_id']}")
        lines.append(f"")
        lines.append(f"- **GT elements**: {r['gt_element_count']}, **Pred elements**: {r['pred_element_count']}")
        lines.append(f"- **Matched**: {r['matched_count']}, **Avg Similarity**: {r['avg_similarity']}")
        lines.append(f"- **Coverage**: {r['coverage']}, **Precision**: {r['precision']}")
        lines.append(f"- **Inference time**: {r['_inference_time_s']}s")
        lines.append("")

        if r['matches']:
            lines.append("#### Matched Pairs (Prediction ↔ Ground Truth)")
            lines.append("")
            lines.append("| # | Predicted Element | GT Element | Similarity |")
            lines.append("|---|-------------------|------------|------------|")
            for i, m in enumerate(r['matches'], 1):
                pred_short = m['pred_name'][:40]
                gt_short = m['gt_name'][:40]
                lines.append(f"| {i} | {pred_short} | {gt_short} | {m['similarity']} |")
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
