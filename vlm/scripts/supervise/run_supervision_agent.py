"""End-to-end VLM supervision agent: 2D original + product image → supervision report.

Takes a 2D character image and a merchandise design image, runs element extraction
internally to generate atomic_rules, then runs VLM supervision review to produce a
structured supervision report.

Pipeline:
    2D original image
      → Step 1: Element extraction (Qwen VL) → atomic_rules (generated internally)
      → Step 2: VLM supervision review (Qwen VL) → supervision report

Usage:
    python -m vlm.scripts.supervise.run_supervision_agent \\
        --source vlm/data/SN_6期动漫数据标注/char_001/char_001.png \\
        --product path/to/char_001_product.png \\
        --category backpack \\
        --sample-id char_001

    # Dry run (validates pipeline without API calls):
    python -m vlm.scripts.supervise.run_supervision_agent \\
        --source vlm/data/SN_6期动漫数据标注/char_001/char_001.png \\
        --product path/to/char_001_product.png \\
        --category backpack \\
        --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts.supervise.run_element_extraction import (
    DEFAULT_MODEL,
    DEFAULT_PROMPT_TEMPLATE,
    DEFAULT_QWEN_BASE_URL,
    load_env_file,
    run_sample,
)
from vlm.scripts.supervise.run_multicategory_supervision_review import run_one_sample

DEFAULT_ENV_FILE = Path("vlm/config/api.env")
DEFAULT_OUTPUT_ROOT = Path("vlm/tmp/supervision_agent_output")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the supervision agent.

    Returns:
        Parsed namespace with fields: source, product, category, sample_id,
        output_dir, env_file, model, temperature, max_tokens, timeout, dry_run.
    """
    parser = argparse.ArgumentParser(
        description="End-to-end VLM supervision agent: 2D original + product image → report."
    )
    parser.add_argument("--source", type=Path, required=True, help="Path to the 2D original character image.")
    parser.add_argument("--product", type=Path, required=True, help="Path to the merchandise design image.")
    parser.add_argument(
        "--category", required=True,
        choices=["backpack", "head_key_chain", "plush", "cake_roll", "dataset_figurine", "dataset_QSitFigures"],
        help="Product category for supervision prompt selection.",
    )
    parser.add_argument(
        "--sample-id", default="",
        help="Sample identifier. Defaults to the stem of --source (e.g. char_001).",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=32000, help="Max tokens for supervision review step. qwen36-vl thinking mode needs large budget.")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true", help="Build prompts without calling the API.")
    return parser.parse_args()


def elements_to_atomic_rules(extracted: dict[str, Any]) -> list[dict[str, str]]:
    """Convert element_extraction.v1 output to the atomic_rules list format.

    Maps element_id → rule_id and value → value. The supervision review script
    uses rule_id as the unique identifier for each rule across all three views.

    Args:
        extracted: Parsed extracted_elements.json (element_extraction.v1 schema).

    Returns:
        List of dicts with "rule_id" and "value" keys, one per extracted element.
    """
    return [
        {"rule_id": elem["element_id"], "value": elem["value"]}
        for elem in extracted.get("elements", [])
        if elem.get("element_id") and elem.get("value")
    ]


def write_json(path: Path, payload: Any) -> None:
    """Write payload as pretty-printed UTF-8 JSON to path, creating parents.

    Args:
        path: Destination file path.
        payload: Any JSON-serialisable value.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def require_api_key(env_name: str) -> str:
    """Read API key from environment, raising SystemExit if absent.

    Args:
        env_name: Name of the environment variable to read.

    Returns:
        Non-empty API key string.

    Raises:
        SystemExit: If the environment variable is not set or empty.
    """
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise SystemExit(f"{env_name} is required. Set it in vlm/config/api.env.")
    return key


def main() -> None:
    """Run the end-to-end supervision agent pipeline.

    Step 1: element extraction on the 2D source image.
    Step 2: convert extracted elements to atomic_rules format.
    Step 3: VLM supervision review using the generated atomic_rules.

    Exits with code 1 if either step fails.
    """
    args = parse_args()
    load_env_file(args.env_file)

    source = args.source.resolve()
    product = args.product.resolve()
    sample_id = args.sample_id.strip() or source.stem

    if not source.exists():
        raise SystemExit(f"Source image not found: {source}")
    if not product.exists():
        raise SystemExit(f"Product image not found: {product}")

    api_key = "" if args.dry_run else require_api_key("QWEN_API_KEY")
    base_url = os.environ.get("QWEN_BASE_URL", DEFAULT_QWEN_BASE_URL).strip() or DEFAULT_QWEN_BASE_URL

    output_dir = args.output_dir / sample_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: element extraction ────────────────────────────────────
    print(f"[{sample_id}] Step 1: extracting elements from {source.name}...", flush=True)

    extraction_output_root = output_dir / "extraction"
    sample_dict: dict[str, Any] = {
        "sample_id": sample_id,
        "json_path": source.parent / f"{sample_id}.json",
        "source_image": source.name,
        "image_path": source,
    }

    extraction_result = run_sample(
        sample=sample_dict,
        prompt_template=DEFAULT_PROMPT_TEMPLATE,
        output_root=extraction_output_root,
        api_key=api_key,
        base_url=base_url,
        model=args.model,
        temperature=args.temperature,
        max_tokens=32000,  # qwen36-vl thinking mode needs large token budget
        timeout=args.timeout,
        dry_run=args.dry_run,
    )

    if extraction_result.get("status") == "error":
        raise SystemExit(f"Element extraction failed: {extraction_result.get('error')}")

    if args.dry_run:
        print(json.dumps({"status": "dry_run", "step": "extraction", "result": extraction_result}, ensure_ascii=False, indent=2))
        print(f"[{sample_id}] Dry run complete — no API calls made.")
        return

    # ── Step 2: convert elements → atomic_rules ───────────────────────
    result_path = Path(extraction_result["result_path"])
    extracted = json.loads(result_path.read_text(encoding="utf-8"))
    atomic_rules = elements_to_atomic_rules(extracted)

    if not atomic_rules:
        raise SystemExit(f"Element extraction returned 0 elements for {sample_id}. Cannot run supervision review.")

    atomic_rules_path = output_dir / "atomic_rules_generated.json"
    write_json(atomic_rules_path, {"atomic_rules": atomic_rules})
    print(f"[{sample_id}] Step 2: {len(atomic_rules)} elements → {atomic_rules_path.name}", flush=True)

    # ── Step 3: VLM supervision review ───────────────────────────────
    print(f"[{sample_id}] Step 3: running supervision review ({args.category})...", flush=True)

    sample_config: dict[str, Any] = {
        "sample_id": sample_id,
        "category": args.category,
        "source_image": str(source),
        "multiview_image": str(product),
        "atomic_rules": str(atomic_rules_path),
    }

    review_result = run_one_sample(
        sample_config,
        prompt_template_override=None,
        api_key=api_key,
        base_url=base_url,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
        output_dir=output_dir / "review",
        dry_run=args.dry_run,
    )

    prediction_path = Path(review_result["output_dir"]) / "qwen_prediction_v3.json"
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))

    final_summary = {
        "status": "ok",
        "sample_id": sample_id,
        "category": args.category,
        "element_count": len(atomic_rules),
        "billable_annotation_issue_count": review_result.get("billable_annotation_issue_count", 0),
        "design_quality_note_count": review_result.get("design_quality_note_count", 0),
        "human_review_required": review_result.get("human_review_required", False),
        "overall_decision": prediction.get("overall_decision", ""),
        "review_output_dir": review_result.get("output_dir", ""),
    }
    write_json(output_dir / "agent_summary.json", final_summary)
    print(json.dumps(final_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
