#!/usr/bin/env python3
"""Batch review all RunningHub generated front-view images with local Ollama Qwen-VL."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse the review module's core functions
from vlm.scripts.supervise.review_local_comfyui_output import (
    build_review_prompt,
    call_local_ollama,
    extract_json,
    normalize_review,
    atomic_json,
    atomic_text,
)

PROJECT_ROOT = Path("/home/intern/jsy")
DATA_ROOT = PROJECT_ROOT / "vlm/data/SN_6期动漫数据标注"
OUTPUT_ROOT = PROJECT_ROOT / "vlm/data/smoke_test"
BATCH_SUMMARY_PATH = OUTPUT_ROOT / "batch_review_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch review RunningHub generation outputs.")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen36-vl:latest")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--identity-threshold", type=float, default=0.85)
    parser.add_argument("--start-from", default=None, help="Resume from a specific sample_id (e.g. char_005)")
    parser.add_argument("--dry-run", action="store_true", help="List samples without running.")
    return parser.parse_args()


def discover_samples() -> list[tuple[str, Path, Path, dict[str, Any]]]:
    """Find all samples with both source annotation and generated output."""
    samples = []
    for anno_dir in sorted(DATA_ROOT.iterdir()):
        if not anno_dir.is_dir() or not anno_dir.name.startswith("char_"):
            continue
        sample_id = anno_dir.name

        # Source: annotation JSON + source image
        annotations = sorted(anno_dir.glob("*.json"))
        if len(annotations) != 1:
            print(f"  [SKIP] {sample_id}: expected 1 annotation JSON, found {len(annotations)}")
            continue
        annotation = json.loads(annotations[0].read_text(encoding="utf-8"))
        source = anno_dir / str(annotation["source_image"])
        if not source.is_file():
            print(f"  [SKIP] {sample_id}: source image not found: {source}")
            continue

        # Generated output
        generated = OUTPUT_ROOT / sample_id / f"{sample_id}_front_view.png"
        if not generated.is_file():
            print(f"  [SKIP] {sample_id}: generated image not found: {generated}")
            continue

        samples.append((sample_id, source, generated, annotation))
    return samples


def review_one(
    sample_id: str,
    source: Path,
    generated: Path,
    annotation: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Run a single review and return the normalized result."""
    prompt = build_review_prompt(annotation)

    output_dir = generated.parent
    stem = generated.stem
    review_path = output_dir / f"{stem}_review.json"
    raw_path = output_dir / f"{stem}_review_raw.txt"
    request_path = output_dir / f"{stem}_review_request.json"

    for proxy_name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(proxy_name, None)
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"

    atomic_json(
        request_path,
        {
            "base_url": args.base_url,
            "model": args.model,
            "image_paths": [str(source), str(generated)],
            "annotation_path": str(source.parent),
            "prompt_chars": len(prompt),
            "note": "Image bytes are local and omitted from this audit preview.",
        },
    )

    try:
        text = call_local_ollama(args.base_url, args.model, prompt, [source, generated], args.timeout)
    except Exception as exc:
        return {
            "reviewed_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "error": str(exc),
            "decision": "error",
            "sample_id": sample_id,
        }

    atomic_text(raw_path, text.rstrip() + "\n")

    try:
        review = normalize_review(extract_json(text), annotation, args.identity_threshold)
    except Exception as exc:
        return {
            "reviewed_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "error": f"JSON parse error: {exc}",
            "raw_response": text[:500],
            "decision": "error",
            "sample_id": sample_id,
        }

    review["model"] = args.model
    review["source_image"] = str(source)
    review["generated_image"] = str(generated)
    review["sample_id"] = sample_id
    atomic_json(review_path, review)
    return review


def summarize(results: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """Produce batch-level statistics."""
    total = len(results)
    passed = sum(1 for r in results if r.get("decision") == "pass")
    failed = sum(1 for r in results if r.get("decision") == "fail")
    errors = sum(1 for r in results if r.get("decision") == "error")

    identity_scores = [r["identity_match"] for r in results if "identity_match" in r]
    visual_scores = [r["visual_quality"] for r in results if "visual_quality" in r]

    # Count element-level issues
    element_issue_counts: dict[str, int] = {}
    for r in results:
        for elem in r.get("elements", []):
            if elem.get("status") != "preserved":
                name = elem.get("name", "unknown")
                element_issue_counts[name] = element_issue_counts.get(name, 0) + 1

    # Count gate failures
    gate_fail_counts: dict[str, int] = {}
    for r in results:
        for gate_name, gate_val in r.get("gates", {}).items():
            if gate_val is not True:
                gate_fail_counts[gate_name] = gate_fail_counts.get(gate_name, 0) + 1

    return {
        "reviewed_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "pass_rate": round(passed / total, 3) if total > 0 else 0,
        "identity_threshold": threshold,
        "identity_match": {
            "mean": round(sum(identity_scores) / len(identity_scores), 3) if identity_scores else 0,
            "min": round(min(identity_scores), 3) if identity_scores else 0,
            "max": round(max(identity_scores), 3) if identity_scores else 0,
        },
        "visual_quality": {
            "mean": round(sum(visual_scores) / len(visual_scores), 3) if visual_scores else 0,
            "min": round(min(visual_scores), 3) if visual_scores else 0,
            "max": round(max(visual_scores), 3) if visual_scores else 0,
        },
        "top_element_issues": sorted(
            [{"name": k, "failure_count": v} for k, v in element_issue_counts.items()],
            key=lambda x: -x["failure_count"],
        ),
        "gate_failures": [
            {"gate": k, "failure_count": v} for k, v in gate_fail_counts.items()
        ],
        "results": results,
    }


def main() -> None:
    args = parse_args()
    samples = discover_samples()
    print(f"Found {len(samples)} samples with both source and generated images.")

    if args.dry_run:
        for sid, src, gen, _ in samples:
            print(f"  {sid}: {gen}")
        return

    # Resume support
    if args.start_from:
        skip = True
        filtered = []
        for s in samples:
            if s[0] == args.start_from:
                skip = False
            if not skip:
                filtered.append(s)
            else:
                print(f"  [RESUME-SKIP] {s[0]}")
        samples = filtered
        print(f"Resuming from {args.start_from}, {len(samples)} remaining.")

    results = []
    for i, (sample_id, source, generated, annotation) in enumerate(samples, 1):
        print(f"[{i}/{len(samples)}] Reviewing {sample_id} ... ", end="", flush=True)
        review = review_one(sample_id, source, generated, annotation, args)
        decision = review.get("decision", "error")
        identity = review.get("identity_match", "N/A")
        print(f"{decision} (identity={identity})")
        results.append(review)

    summary = summarize(results, args.identity_threshold)
    atomic_json(BATCH_SUMMARY_PATH, summary)
    print(f"\nBatch review complete. Summary saved to {BATCH_SUMMARY_PATH}")
    print(f"  Total: {summary['total']} | Pass: {summary['passed']} | Fail: {summary['failed']} | Error: {summary['errors']}")
    print(f"  Pass Rate: {summary['pass_rate']:.1%}")
    print(f"  Identity Match: mean={summary['identity_match']['mean']:.3f}, range=[{summary['identity_match']['min']:.3f}, {summary['identity_match']['max']:.3f}]")
    print(f"  Visual Quality: mean={summary['visual_quality']['mean']:.3f}, range=[{summary['visual_quality']['min']:.3f}, {summary['visual_quality']['max']:.3f}]")
    if summary["top_element_issues"]:
        print("  Top Element Issues:")
        for item in summary["top_element_issues"][:5]:
            print(f"    - {item['name']}: {item['failure_count']}/{summary['total']} failures")
    if summary["gate_failures"]:
        print("  Gate Failures:")
        for item in summary["gate_failures"]:
            print(f"    - {item['gate']}: {item['failure_count']}/{summary['total']}")


if __name__ == "__main__":
    main()
