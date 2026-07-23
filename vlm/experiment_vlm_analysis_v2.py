#!/usr/bin/env python3
"""
VLM Image Analysis Experiment v2
=================================
Improvements over v1:
  1. Optimized prompt: role definition + few-shot examples + element grouping rules
  2. Hungarian algorithm for globally optimal matching (with greedy fallback)
  3. Similarity threshold to reject garbage matches
  4. Grid search over name/description weight ratios
  5. Standalone "description similarity" metric (name-independent)
  6. A/B comparison: runs both old prompt and new prompt, compares results

Usage:
  python3 experiment_vlm_analysis_v2.py          # Run full experiment
  python3 experiment_vlm_analysis_v2.py --ab     # Run A/B comparison (old vs new prompt)
  python3 experiment_vlm_analysis_v2.py --sample char_001  # Test on single sample
"""

import os
import sys
import json
import base64
import time
import re
import math
import argparse
import numpy as np
from pathlib import Path
from scipy.optimize import linear_sum_assignment

# Bypass HTTP proxy for local connections
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    os.environ.pop(key, None)

import ollama


# === CONFIGURATION ===
DATA_DIR = "/home/intern/jsy/vlm/data/SN_6期动漫数据标注"
OUTPUT_DIR = "/home/intern/jsy/vlm/experiment_results"
MODEL_NAME = "qwen36-vl:latest"
EMBED_MODEL_NAME = "bge-m3:latest"

# === PROMPTS ===

# V1 (original) prompt — kept for A/B comparison
VLM_PROMPT_V1 = """请仔细观察这张动漫角色图片，列出该角色的所有关键视觉元素。对于每个元素，给出元素名称和详细的视觉描述。

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

# V2 (optimized) prompt — addresses granularity misalignment
VLM_PROMPT_V2 = """你是一名专业的动漫角色设计标注专家。你需要仔细观察图片中的角色，提取关键视觉设计元素。

## 标注规则

### 1. 元素归并规则（重要）
将紧密相关的视觉特征合并为一个元素，而不是拆分成多个：
- 发色 + 发饰 → 合并（如"金色长发与黑色蝴蝶结"）
- 上衣 + 领口装饰 → 合并（如"白色衬衫与蓝色宝石领饰"）
- 外套 + 纹样装饰 → 合并（如"红色长外套与金色火焰纹饰"）
- 下装 + 腰部装饰 → 合并（如"黑色短裙与灰色腰带"）

### 2. 描述格式
对每个元素的描述必须包含：颜色、形状、位置、材质。末尾可以加一句质量提示（如"必须清晰绘制"、"不能遗漏"）。

### 3. 覆盖范围
从头部到脚部，按顺序检查：头面部 → 上装 → 下装 → 鞋/脚部 → 配件/特殊特征。4-7个元素为宜。

### 4. 只描述可见特征
只描述图中实际可见的视觉元素。不要添加设计建议或推测不可见部分。

## 标注示例

输入图片：一个穿着校服、金色双马尾、戴蓝色发夹的少女角色

正确输出：
```json
{
  "elements": [
    {"name": "金色双马尾与蓝色发夹", "value": "头发为亮金色，扎成两条长双马尾垂至胸前，刘海侧分；右侧刘海上夹有一个长方形蓝色发夹，是该角色标志性配饰，必须准确绘制。"},
    {"name": "蓝色眼睛", "value": "眼睛为深蓝色，瞳孔较大，眼神明亮，眼角微微上扬，睫毛纤细。"},
    {"name": "白色水手服与红色领巾", "value": "上身穿白色水手服，大翻领为深蓝色镶白边，胸前系红色三角领巾，领巾末端可见；领口和袖口有细白条纹装饰。"},
    {"name": "深蓝色百褶短裙", "value": "下身为深蓝色百褶短裙，裙摆高于膝盖，褶纹均匀清晰，腰部有调节扣细节。"},
    {"name": "黑色过膝袜与棕色皮鞋", "value": "腿穿黑色过膝长袜，袜口有白色细条纹；脚穿棕色圆头平底皮鞋，鞋面有金属扣装饰。"}
  ]
}
```

请严格按照以上格式输出JSON，只输出JSON，不要添加任何其他文字：
```json
{
  "elements": [
    {"name": "元素名称", "value": "该元素的详细视觉描述"},
    {"name": "元素名称", "value": "该元素的详细视觉描述"}
  ]
}
```
"""


# === UTILS ===

def extract_json_from_response(text: str) -> dict:
    """Extract JSON object from model response (may contain markdown code fences)."""
    text = text.strip()

    # Step 1: Remove markdown code fences (robust multi-line)
    fence_match = re.search(r'```(?:json)?\s*\n(.*?)\n\s*```', text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    elif text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

    # Step 2: Try direct JSON parse
    try:
        parsed = json.loads(text)
        return _normalize_element_keys(parsed)
    except json.JSONDecodeError:
        pass

    # Step 3: Find JSON object with "elements" key
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end+1]
        try:
            parsed = json.loads(candidate)
            return _normalize_element_keys(parsed)
        except json.JSONDecodeError:
            pass

    # Step 4: Fallback regex for element keys
    for key_pattern in [r'"elements"', r'"visual_elements"', r'"element_list"']:
        match = re.search(r'\{[^{}]*' + key_pattern + r'\s*:\s*\[.*?\]\s*[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return _normalize_element_keys(parsed)
            except json.JSONDecodeError:
                pass

    print(f"  WARNING: Could not parse JSON. Raw (first 500 chars):\n{text[:500]}")
    return {"elements": []}


def _normalize_element_keys(parsed: dict) -> dict:
    """Normalize variant JSON keys to standard {'elements': [{'name':..., 'value':...}]} format."""
    # Find the element list under any common variant key
    elements = None
    for key in ['elements', 'visual_elements', 'element_list', 'items']:
        if key in parsed:
            elements = parsed[key]
            break
    if elements is None:
        return parsed

    normalized = []
    for elem in elements:
        if not isinstance(elem, dict):
            continue
        name = elem.get('name') or elem.get('element_name') or elem.get('label') or ''
        value = elem.get('value') or elem.get('description') or elem.get('desc') or elem.get('text') or ''
        normalized.append({'name': str(name), 'value': str(value)})

    return {'elements': normalized, '_raw_parsed': parsed}


def load_ground_truth(char_dir: str) -> dict:
    char_name = os.path.basename(char_dir)
    json_path = os.path.join(char_dir, f"{char_name}.json")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_image(image_path: str, prompt: str) -> dict:
    """Send image to VLM and get element analysis."""
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{
            'role': 'user',
            'content': prompt,
            'images': [image_path]
        }],
        options={'temperature': 0.1, 'num_predict': 4096}
    )
    raw_output = response['message']['content']
    parsed = extract_json_from_response(raw_output)
    parsed['_raw_output'] = raw_output
    return parsed


class OllamaEmbedder:
    """Thin wrapper around Ollama embedding API with caching."""

    def __init__(self, model_name: str = "bge-m3:latest"):
        self.model_name = model_name
        self._cache = {}

    def encode(self, texts: list) -> np.ndarray:
        results = []
        to_embed = []
        to_embed_indices = []
        for i, text in enumerate(texts):
            if text in self._cache:
                results.append((i, self._cache[text]))
            else:
                to_embed.append(text)
                to_embed_indices.append(i)
                results.append((i, None))
        for idx, text in zip(to_embed_indices, to_embed):
            resp = ollama.embed(model=self.model_name, input=text)
            emb = np.array(resp['embeddings'][0], dtype=np.float32)
            self._cache[text] = emb
            results[idx] = (idx, emb)
        return np.array([emb for _, emb in results], dtype=np.float32)

    def encode_single(self, text: str) -> np.ndarray:
        return self.encode([text])[0]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


# === MATCHING ALGORITHMS ===

def match_elements_hungarian(
    pred_elements: list,
    gt_elements: list,
    embedder: OllamaEmbedder,
    name_weight: float = 0.3,
    similarity_threshold: float = 0.50,
) -> tuple:
    """
    Hungarian algorithm for globally optimal one-to-one matching.
    Finds the assignment that maximizes total weighted similarity.

    Returns: (matches, unmatched_pred, unmatched_gt)
    """
    if not pred_elements or not gt_elements:
        return [], list(pred_elements), list(gt_elements)

    n_pred = len(pred_elements)
    n_gt = len(gt_elements)

    # Build combined texts
    pred_texts = [f"{e['name']}: {e['value']}" for e in pred_elements]
    gt_texts = [f"{e['name']}: {e['value']}" for e in gt_elements]
    pred_names = [e['name'] for e in pred_elements]
    gt_names = [e['name'] for e in gt_elements]

    # Encode all
    pred_embs = embedder.encode(pred_texts)
    gt_embs = embedder.encode(gt_texts)
    pred_name_embs = embedder.encode(pred_names)
    gt_name_embs = embedder.encode(gt_names)

    # Build cost matrix (we want to MAXIMIZE similarity, so negate for min-cost assignment)
    cost_matrix = np.zeros((n_pred, n_gt))
    for i in range(n_pred):
        for j in range(n_gt):
            text_sim = cosine_similarity(pred_embs[i], gt_embs[j])
            name_sim = cosine_similarity(pred_name_embs[i], gt_name_embs[j])
            combined = name_weight * name_sim + (1.0 - name_weight) * text_sim
            cost_matrix[i, j] = -combined  # negate for Hungarian (minimizes cost)

    # Hungarian algorithm
    row_ind, col_ind = linear_sum_assignment(cost_matrix)

    matches = []
    matched_pred_indices = set()
    matched_gt_indices = set()

    for pi, gj in zip(row_ind, col_ind):
        similarity = -cost_matrix[pi, gj]
        if similarity >= similarity_threshold:
            matched_pred_indices.add(pi)
            matched_gt_indices.add(gj)
            matches.append({
                'pred_name': pred_elements[pi]['name'],
                'pred_value': pred_elements[pi]['value'],
                'gt_name': gt_elements[gj]['name'],
                'gt_value': gt_elements[gj]['value'],
                'similarity': round(similarity, 4),
                'match_quality': 'good' if similarity >= 0.65 else 'weak'
            })
        # Below-threshold matches are rejected — treated as unmatched on both sides

    unmatched_pred = [pred_elements[i] for i in range(n_pred)
                      if i not in matched_pred_indices]
    unmatched_gt = [gt_elements[j] for j in range(n_gt)
                    if j not in matched_gt_indices]

    return matches, unmatched_pred, unmatched_gt


def match_elements_greedy(
    pred_elements: list,
    gt_elements: list,
    embedder: OllamaEmbedder,
    name_weight: float = 0.3,
    similarity_threshold: float = 0.50,
) -> tuple:
    """
    Greedy matching with similarity threshold.
    Each prediction takes its best unmatched GT. Below-threshold matches are rejected.
    """
    if not pred_elements or not gt_elements:
        return [], list(pred_elements), list(gt_elements)

    pred_texts = [f"{e['name']}: {e['value']}" for e in pred_elements]
    gt_texts = [f"{e['name']}: {e['value']}" for e in gt_elements]
    pred_names = [e['name'] for e in pred_elements]
    gt_names = [e['name'] for e in gt_elements]

    pred_embs = embedder.encode(pred_texts)
    gt_embs = embedder.encode(gt_texts)
    pred_name_embs = embedder.encode(pred_names)
    gt_name_embs = embedder.encode(gt_names)

    matches = []
    matched_gt_indices = set()
    matched_pred_indices = set()

    for i in range(len(pred_elements)):
        best_score = 0.0
        best_gt_idx = -1
        for j in range(len(gt_elements)):
            if j in matched_gt_indices:
                continue
            text_sim = cosine_similarity(pred_embs[i], gt_embs[j])
            name_sim = cosine_similarity(pred_name_embs[i], gt_name_embs[j])
            combined = name_weight * name_sim + (1.0 - name_weight) * text_sim
            if combined > best_score:
                best_score = combined
                best_gt_idx = j

        if best_gt_idx >= 0 and best_score >= similarity_threshold:
            matched_gt_indices.add(best_gt_idx)
            matched_pred_indices.add(i)
            matches.append({
                'pred_name': pred_elements[i]['name'],
                'pred_value': pred_elements[i]['value'],
                'gt_name': gt_elements[best_gt_idx]['name'],
                'gt_value': gt_elements[best_gt_idx]['value'],
                'similarity': round(best_score, 4),
                'match_quality': 'good' if best_score >= 0.65 else 'weak'
            })

    unmatched_pred = [pred_elements[i] for i in range(len(pred_elements))
                      if i not in matched_pred_indices]
    unmatched_gt = [gt_elements[j] for j in range(len(gt_elements))
                    if j not in matched_gt_indices]

    return matches, unmatched_pred, unmatched_gt


# === METRICS ===

def compute_description_similarity(
    pred_elements: list,
    gt_elements: list,
    embedder: OllamaEmbedder,
) -> dict:
    """
    Compute description-only similarity.
    Strips element names, compares only the 'value' (description) field.
    Uses Hungarian matching on description text alone — this measures
    whether the model describes the same things, regardless of naming style.
    """
    if not pred_elements or not gt_elements:
        return {
            'description_similarity': 0.0,
            'description_matches': 0,
            'description_total': 0,
        }

    pred_descs = [e['value'] for e in pred_elements]
    gt_descs = [e['value'] for e in gt_elements]

    pred_embs = embedder.encode(pred_descs)
    gt_embs = embedder.encode(gt_descs)

    # Hungarian on description-only similarity
    n_pred, n_gt = len(pred_descs), len(gt_descs)
    cost_matrix = np.zeros((n_pred, n_gt))
    for i in range(n_pred):
        for j in range(n_gt):
            cost_matrix[i, j] = -cosine_similarity(pred_embs[i], gt_embs[j])

    row_ind, col_ind = linear_sum_assignment(cost_matrix)

    desc_sims = []
    desc_matches = 0
    for pi, gj in zip(row_ind, col_ind):
        sim = -cost_matrix[pi, gj]
        if sim >= 0.50:
            desc_sims.append(sim)
            desc_matches += 1

    n = max(n_pred, n_gt)
    return {
        'description_similarity': round(np.mean(desc_sims), 4) if desc_sims else 0.0,
        'description_matches': desc_matches,
        'description_total': n,
        'description_all_sims': [round(s, 4) for s in desc_sims],
    }


def compute_per_sample_metrics(
    pred_elements: list,
    gt_elements: list,
    embedder: OllamaEmbedder,
    name_weight: float = 0.3,
    similarity_threshold: float = 0.50,
    algorithm: str = 'hungarian',
) -> dict:
    """Compute all metrics for one sample."""

    match_fn = match_elements_hungarian if algorithm == 'hungarian' else match_elements_greedy

    matches, unmatched_pred, unmatched_gt = match_fn(
        pred_elements, gt_elements, embedder,
        name_weight=name_weight,
        similarity_threshold=similarity_threshold,
    )

    # Basic metrics
    match_scores = [m['similarity'] for m in matches]
    good_matches = [m for m in matches if m['match_quality'] == 'good']
    weak_matches = [m for m in matches if m['match_quality'] == 'weak']

    avg_similarity = round(np.mean(match_scores), 4) if match_scores else 0.0
    coverage = round(len(matches) / len(gt_elements), 4) if gt_elements else 1.0
    precision = round(len(matches) / len(pred_elements), 4) if pred_elements else 1.0

    # Description-only metric (independent of name similarity)
    desc_metrics = compute_description_similarity(pred_elements, gt_elements, embedder)

    # Element count balance
    count_diff = len(pred_elements) - len(gt_elements)

    return {
        'matched_count': len(matches),
        'good_matches': len(good_matches),
        'weak_matches': len(weak_matches),
        'unmatched_pred_count': len(unmatched_pred),
        'unmatched_gt_count': len(unmatched_gt),
        'avg_similarity': avg_similarity,
        'coverage': coverage,
        'precision': precision,
        'count_diff': count_diff,
        'matches': matches,
        'unmatched_pred': [{'name': e['name'], 'value': e['value']} for e in unmatched_pred],
        'unmatched_gt': [{'name': e['name'], 'value': e['value']} for e in unmatched_gt],
        'description_similarity': desc_metrics['description_similarity'],
        'description_matches': desc_metrics['description_matches'],
        'description_total': desc_metrics['description_total'],
    }


# === MAIN EXPERIMENT ===

def run_experiment(
    prompt: str = None,
    prompt_label: str = "optimized",
    name_weight: float = 0.3,
    similarity_threshold: float = 0.50,
    algorithm: str = 'hungarian',
    sample_filter: str = None,
) -> dict:
    """Run the full experiment."""
    if prompt is None:
        prompt = VLM_PROMPT_V2

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 70)
    print(f"Experiment: VLM Anime Character Element Extraction v2")
    print(f"Prompt: {prompt_label}")
    print(f"Algorithm: {algorithm}")
    print(f"Name weight: {name_weight}, Threshold: {similarity_threshold}")
    print("=" * 70)

    # Init embedder
    print("\nInitializing bge-m3 embedding model...")
    embedder = OllamaEmbedder(EMBED_MODEL_NAME)
    test_emb = embedder.encode_single("测试文本")
    print(f"  Dim={len(test_emb)}, cache enabled")

    # Collect samples
    char_dirs = sorted([
        d for d in Path(DATA_DIR).iterdir()
        if d.is_dir() and d.name.startswith('char_')
    ])
    if sample_filter:
        char_dirs = [d for d in char_dirs if d.name == sample_filter]
        if not char_dirs:
            print(f"ERROR: sample {sample_filter} not found")
            return {}

    print(f"\nProcessing {len(char_dirs)} samples...\n")

    all_results = []
    total_start = time.time()

    for idx, char_dir in enumerate(char_dirs):
        char_name = char_dir.name
        image_path = char_dir / f"{char_name}.png"

        if not image_path.exists():
            print(f"[{idx+1}/{len(char_dirs)}] {char_name}: SKIP (no image)")
            continue

        print(f"[{idx+1}/{len(char_dirs)}] {char_name}...", end=" ", flush=True)
        t_start = time.time()

        gt = load_ground_truth(str(char_dir))

        try:
            pred = analyze_image(str(image_path), prompt)
        except Exception as e:
            print(f"ERROR: {e}")
            pred = {"elements": [], "_raw_output": f"ERROR: {e}"}

        pred_elements = pred.get('elements', [])
        gt_elements = gt.get('elements', [])

        metrics = compute_per_sample_metrics(
            pred_elements, gt_elements, embedder,
            name_weight=name_weight,
            similarity_threshold=similarity_threshold,
            algorithm=algorithm,
        )

        elapsed = round(time.time() - t_start, 1)
        print(f"pred={len(pred_elements)} gt={len(gt_elements)} "
              f"matched={metrics['matched_count']} "
              f"sim={metrics['avg_similarity']} "
              f"desc_sim={metrics['description_similarity']} "
              f"cov={metrics['coverage']} prec={metrics['precision']} "
              f"({elapsed}s)")

        result = {
            'sample_id': char_name,
            'gt_element_count': len(gt_elements),
            'pred_element_count': len(pred_elements),
            **metrics,
            'pred_elements': [{'name': e['name'], 'value': e['value']} for e in pred_elements],
            'gt_elements': gt_elements,
            '_raw_model_output': pred.get('_raw_output', ''),
            '_inference_time_s': elapsed,
        }
        all_results.append(result)

    total_time = round(time.time() - total_start, 1)

    # Aggregate
    all_avg_sim = [r['avg_similarity'] for r in all_results if r['matched_count'] > 0]
    all_desc_sim = [r['description_similarity'] for r in all_results]
    all_coverage = [r['coverage'] for r in all_results]
    all_precision = [r['precision'] for r in all_results]
    total_gt = sum(r['gt_element_count'] for r in all_results)
    total_pred = sum(r['pred_element_count'] for r in all_results)
    total_matched = sum(r['matched_count'] for r in all_results)
    total_good = sum(r['good_matches'] for r in all_results)
    total_weak = sum(r['weak_matches'] for r in all_results)
    total_unmatched_pred = sum(r['unmatched_pred_count'] for r in all_results)
    total_unmatched_gt = sum(r['unmatched_gt_count'] for r in all_results)

    summary = {
        'experiment': 'VLM Anime Character Element Extraction v2',
        'prompt_label': prompt_label,
        'prompt': prompt,
        'algorithm': algorithm,
        'name_weight': name_weight,
        'similarity_threshold': similarity_threshold,
        'model': MODEL_NAME,
        'embedding_model': EMBED_MODEL_NAME,
        'total_samples': len(all_results),
        'total_time_s': total_time,
        'aggregate_metrics': {
            'avg_similarity_mean': round(np.mean(all_avg_sim), 4) if all_avg_sim else 0,
            'avg_similarity_std': round(np.std(all_avg_sim), 4) if all_avg_sim else 0,
            'avg_similarity_min': round(min(all_avg_sim), 4) if all_avg_sim else 0,
            'avg_similarity_max': round(max(all_avg_sim), 4) if all_avg_sim else 0,
            'avg_description_similarity': round(np.mean(all_desc_sim), 4) if all_desc_sim else 0,
            'coverage_mean': round(np.mean(all_coverage), 4) if all_coverage else 0,
            'precision_mean': round(np.mean(all_precision), 4) if all_precision else 0,
            'total_gt_elements': total_gt,
            'total_pred_elements': total_pred,
            'total_matched': total_matched,
            'total_good_matches': total_good,
            'total_weak_matches': total_weak,
            'total_unmatched_pred': total_unmatched_pred,
            'total_unmatched_gt': total_unmatched_gt,
            'overall_coverage': round(total_matched / total_gt, 4) if total_gt else 0,
            'overall_precision': round(total_matched / total_pred, 4) if total_pred else 0,
            'good_match_ratio': round(total_good / total_matched, 4) if total_matched else 0,
        },
        'per_sample': all_results
    }

    # Save
    suffix = f"_{prompt_label}" if prompt_label else ""
    output_json = os.path.join(OUTPUT_DIR, f'experiment_results_v2{suffix}.json')
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {output_json}")

    output_md = os.path.join(OUTPUT_DIR, f'experiment_report_v2{suffix}.md')
    generate_report(summary, output_md)
    print(f"Report saved to: {output_md}")

    # Print summary
    m = summary['aggregate_metrics']
    print(f"\n{'='*70}")
    print("RESULTS SUMMARY")
    print(f"{'='*70}")
    print(f"  Avg Combined Similarity:  {m['avg_similarity_mean']} ± {m['avg_similarity_std']}")
    print(f"  Avg Description Similarity: {m['avg_description_similarity']}  <-- 描述准确率")
    print(f"  Avg Coverage (recall):    {m['coverage_mean']}")
    print(f"  Avg Precision:            {m['precision_mean']}")
    print(f"  Good matches: {total_good}/{total_matched} ({m['good_match_ratio']})")
    print(f"  Weak matches: {total_weak}/{total_matched}")
    print(f"  Unmatched pred: {total_unmatched_pred}, Unmatched GT: {total_unmatched_gt}")
    print(f"  Total time: {total_time}s")

    return summary


def run_ab_comparison(sample_filter: str = None):
    """Run A/B comparison: V1 prompt vs V2 prompt on the same samples."""
    print("=" * 70)
    print("A/B COMPARISON: Old Prompt vs Optimized Prompt")
    print("=" * 70)

    results_a = run_experiment(
        prompt=VLM_PROMPT_V1,
        prompt_label="v1_original",
        algorithm='hungarian',
        similarity_threshold=0.50,
        sample_filter=sample_filter,
    )
    results_b = run_experiment(
        prompt=VLM_PROMPT_V2,
        prompt_label="v2_optimized",
        algorithm='hungarian',
        similarity_threshold=0.50,
        sample_filter=sample_filter,
    )

    # Comparison summary
    if results_a and results_b:
        ma = results_a['aggregate_metrics']
        mb = results_b['aggregate_metrics']
        print(f"\n{'='*70}")
        print("A/B COMPARISON SUMMARY")
        print(f"{'='*70}")
        print(f"{'Metric':<35} {'V1 (Original)':<15} {'V2 (Optimized)':<15} {'Delta':<10}")
        print("-" * 75)
        metrics_to_compare = [
            ('avg_similarity_mean', 'Avg Combined Similarity'),
            ('avg_description_similarity', 'Avg Description Similarity'),
            ('coverage_mean', 'Avg Coverage'),
            ('precision_mean', 'Avg Precision'),
            ('good_match_ratio', 'Good Match Ratio'),
            ('overall_coverage', 'Overall Coverage'),
            ('overall_precision', 'Overall Precision'),
        ]
        for key, label in metrics_to_compare:
            v1 = ma.get(key, 0)
            v2 = mb.get(key, 0)
            delta = round(v2 - v1, 4)
            direction = "↑" if delta > 0 else "↓" if delta < 0 else "="
            print(f"{label:<35} {v1:<15} {v2:<15} {direction} {delta:+.4f}")

        # Save comparison
        comparison = {
            'v1_original': {'prompt_label': 'v1_original', 'aggregate_metrics': ma},
            'v2_optimized': {'prompt_label': 'v2_optimized', 'aggregate_metrics': mb},
        }
        comp_path = os.path.join(OUTPUT_DIR, 'experiment_ab_comparison.json')
        with open(comp_path, 'w', encoding='utf-8') as f:
            json.dump(comparison, f, ensure_ascii=False, indent=2)
        print(f"\nA/B comparison saved to: {comp_path}")


def run_weight_search(sample_filter: str = None):
    """Grid search over name_weight to find optimal ratio."""
    print("=" * 70)
    print("WEIGHT GRID SEARCH: Finding optimal name/description weight ratio")
    print("=" * 70)

    weights = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    best_weight = None
    best_similarity = 0

    for w in weights:
        print(f"\n--- Weight: name={w:.1f}, description={1-w:.1f} ---")
        results = run_experiment(
            prompt=VLM_PROMPT_V2,
            prompt_label=f"weight_search_name{w:.1f}",
            name_weight=w,
            algorithm='hungarian',
            similarity_threshold=0.50,
            sample_filter=sample_filter,
        )
        if results:
            sim = results['aggregate_metrics']['avg_similarity_mean']
            desc_sim = results['aggregate_metrics']['avg_description_similarity']
            print(f"  → Combined={sim}, Description={desc_sim}")
            if sim > best_similarity:
                best_similarity = sim
                best_weight = w

    print(f"\n{'='*70}")
    print(f"BEST: name_weight={best_weight:.1f} → similarity={best_similarity}")
    print(f"{'='*70}")


# === REPORT GENERATION ===

def generate_report(summary: dict, output_path: str):
    """Generate a detailed markdown report."""
    lines = []
    lines.append("# VLM Element Extraction Experiment Report v2")
    lines.append("")
    lines.append(f"**Prompt**: {summary['prompt_label']}")
    lines.append(f"**Algorithm**: {summary['algorithm']} (threshold={summary['similarity_threshold']})")
    lines.append(f"**Name/Desc Weight**: {summary['name_weight']:.1f}/{1-summary['name_weight']:.1f}")
    lines.append(f"**Model**: {summary['model']}")
    lines.append(f"**Embedding**: {summary['embedding_model']}")
    lines.append(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Samples**: {summary['total_samples']}")
    lines.append(f"**Total Time**: {summary['total_time_s']}s")
    lines.append("")

    m = summary['aggregate_metrics']
    lines.append("## Aggregate Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Avg Combined Similarity (name+desc) | {m['avg_similarity_mean']} ± {m['avg_similarity_std']} |")
    lines.append(f"| **Avg Description Similarity** | **{m['avg_description_similarity']}** |")
    lines.append(f"| Min / Max Similarity | {m['avg_similarity_min']} / {m['avg_similarity_max']} |")
    lines.append(f"| Avg Coverage (GT recall) | {m['coverage_mean']} |")
    lines.append(f"| Avg Precision | {m['precision_mean']} |")
    lines.append(f"| Overall Coverage | {m['overall_coverage']} |")
    lines.append(f"| Overall Precision | {m['overall_precision']} |")
    lines.append(f"| Total GT / Pred / Matched | {m['total_gt_elements']} / {m['total_pred_elements']} / {m['total_matched']} |")
    lines.append(f"| Good / Weak Matches | {m['total_good_matches']} / {m['total_weak_matches']} |")
    lines.append(f"| Good Match Ratio | {m['good_match_ratio']} |")
    lines.append(f"| Unmatched Pred / GT | {m['total_unmatched_pred']} / {m['total_unmatched_gt']} |")
    lines.append("")

    # Per-sample table
    lines.append("## Per-Sample Summary")
    lines.append("")
    lines.append("| Sample | GT | Pred | Matched | Good | Weak | Combined | Desc Sim | Cov | Prec | Time(s) |")
    lines.append("|--------|-----|------|---------|------|------|----------|----------|-----|------|---------|")
    for r in summary['per_sample']:
        lines.append(
            f"| {r['sample_id']} | {r['gt_element_count']} | {r['pred_element_count']} | "
            f"{r['matched_count']} | {r['good_matches']} | {r['weak_matches']} | "
            f"{r['avg_similarity']} | {r['description_similarity']} | "
            f"{r['coverage']} | {r['precision']} | {r['_inference_time_s']} |"
        )
    lines.append("")

    # Per-sample details
    lines.append("## Per-Sample Details")
    lines.append("")
    for r in summary['per_sample']:
        lines.append(f"### {r['sample_id']}")
        lines.append("")
        lines.append(f"- GT: {r['gt_element_count']}, Pred: {r['pred_element_count']}, "
                     f"Matched: {r['matched_count']}, "
                     f"Combined Sim: {r['avg_similarity']}, "
                     f"**Desc Sim: {r['description_similarity']}**")
        lines.append(f"- Coverage: {r['coverage']}, Precision: {r['precision']}")
        lines.append("")

        if r['matches']:
            lines.append("| # | Quality | Pred Name | GT Name | Similarity |")
            lines.append("|---|---------|-----------|---------|------------|")
            for i, m in enumerate(r['matches'], 1):
                quality_icon = "✅" if m['match_quality'] == 'good' else "⚠️"
                lines.append(f"| {i} | {quality_icon} | {m['pred_name'][:35]} | {m['gt_name'][:35]} | {m['similarity']} |")
            lines.append("")

        if r['unmatched_pred']:
            lines.append("**Extra Predictions:**")
            for e in r['unmatched_pred']:
                lines.append(f"- **{e['name']}**: {e['value'][:100]}")
            lines.append("")

        if r['unmatched_gt']:
            lines.append("**Missed GT:**")
            for e in r['unmatched_gt']:
                lines.append(f"- **{e['name']}**: {e['value'][:100]}")
            lines.append("")

        lines.append("---")
        lines.append("")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


# === CLI ===

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="VLM Element Extraction Experiment v2")
    parser.add_argument('--ab', action='store_true', help='Run A/B comparison (old vs new prompt)')
    parser.add_argument('--weight-search', action='store_true', help='Grid search optimal name/description weight')
    parser.add_argument('--sample', type=str, help='Run on a single sample (e.g. char_001)')
    parser.add_argument('--algorithm', type=str, default='hungarian',
                        choices=['hungarian', 'greedy'], help='Matching algorithm')
    parser.add_argument('--threshold', type=float, default=0.50,
                        help='Similarity threshold for matching')
    parser.add_argument('--name-weight', type=float, default=0.3,
                        help='Weight for element name similarity (0-1)')
    args = parser.parse_args()

    if args.ab:
        run_ab_comparison(sample_filter=args.sample)
    elif args.weight_search:
        run_weight_search(sample_filter=args.sample)
    else:
        run_experiment(
            prompt=VLM_PROMPT_V2,
            prompt_label="v2_optimized",
            name_weight=args.name_weight,
            similarity_threshold=args.threshold,
            algorithm=args.algorithm,
            sample_filter=args.sample,
        )
