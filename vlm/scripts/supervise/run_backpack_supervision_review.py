"""Run Qwen VL supervision review on backpack samples with v3 schema.

Calls the Qwen vision API with a source 2D character image and a generated
multiview backpack design, using the v3 prompt template that includes
backpack view semantics (SECTION 3).

Usage:
    python -m vlm.scripts.supervise.run_backpack_supervision_review \
        --sample-config vlm/config/supervision/backpack_review_samples.json
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts._paths import API_ENV_FILE

DEFAULT_ENV_FILE = API_ENV_FILE
DEFAULT_PROMPT_TEMPLATE = Path(
    "vlm/prompts/supervision/qwen_prompt_v3_backpack.txt"
)
DEFAULT_OUTPUT_ROOT = Path("vlm/tmp/backpack_supervision_review_v3")
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.7-plus"

OUT_OF_SCOPE_RULE_IDS = [
    "skirt_type", "skirt_color", "skirt_length",
    "legwear_type", "legwear_color",
    "footwear_type", "footwear_color",
]
ERROR_STATUSES = {"wrong color", "wrong material", "wrong shape", "extra", "wrong invisible"}
VISIBLE_VALUES = {"visible", "invisible"}
VISIBLE_STATUS_VALUES = {"correct", "wrong color", "wrong material", "wrong shape", "extra"}
INVISIBLE_STATUS_VALUES = {"correct", "wrong invisible"}


# ── CLI ──────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Qwen VL supervision review on backpack samples."
    )
    parser.add_argument(
        "--sample-config", type=Path, required=True,
        help="JSON file with a list of sample configs (source_image, multiview_image, atomic_rules, sample_id).",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--prompt-template", type=Path, default=DEFAULT_PROMPT_TEMPLATE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--qwen-api-key", default="")
    parser.add_argument("--qwen-base-url", default=DEFAULT_QWEN_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true", help="Build prompt and payload but do not call the API.")
    return parser.parse_args()


# ── Helpers ──────────────────────────────────────────────────────────


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def require_key(value: str, env_name: str) -> str:
    key = value.strip() or os.environ.get(env_name, "").strip()
    if not key:
        raise SystemExit(
            f"{env_name} is required. Pass --qwen-api-key or set the environment variable."
        )
    return key


def media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"


def encode_image_data_url(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type(path)};base64,{data}"


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Qwen API ────────────────────────────────────────────────────────


def qwen_vl_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.0,
    max_tokens: int = 8000,
    timeout: int = 300,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload, ensure_ascii=False),
        timeout=timeout,
    )
    response.raise_for_status()
    result = response.json()
    try:
        return str(result["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Qwen response missing choices[0].message.content: {result}") from exc


# ── Prompt Building ──────────────────────────────────────────────────


def build_prompt_text(
    prompt_template: str,
    sample_id: str,
    category: str,
    atomic_rules: list[dict[str, str]],
) -> str:
    """Build the full prompt text by appending sample metadata and atomic rules.

    The prompt template already contains 6 sections (product scope, status
    convention, view semantics, out-of-scope, props, judgment procedure).
    We append the sample-specific atomic rules at the end.
    """
    rules_json = json.dumps(atomic_rules, ensure_ascii=False, indent=2)

    sample_block = f"""
样本：
sample_id: {sample_id}
category: {category}
product_type: {category}

Atomic rules（输入规则，封闭集合）：
{rules_json}

请返回一个顶层 JSON object，必须包含：schema_version, task, sample_id, category, product_type, inputs, overall_decision, overall_reason, aggregate_counts, rules, metadata。
每个 rule object 必须包含：rule_id, value, front_visible, front_status, side_visible, side_status, back_visible, back_status, result, issue_type, confidence, reason, evidence。"""

    return prompt_template + sample_block


# ── QC Validation ───────────────────────────────────────────────────


def validate_rule(rule: dict[str, Any]) -> list[str]:
    """Validate a single rule against v3 schema constraints."""
    issues: list[str] = []
    required_fields = [
        "rule_id", "value",
        "front_visible", "front_status",
        "side_visible", "side_status",
        "back_visible", "back_status",
        "result",
    ]
    for field in required_fields:
        if field not in rule or not rule[field]:
            issues.append(f"missing_{field}")

    for view in ["front", "side", "back"]:
        visible = rule.get(f"{view}_visible", "")
        status = rule.get(f"{view}_status", "")
        if visible and visible not in VISIBLE_VALUES:
            issues.append(f"invalid_{view}_visible:{visible}")
        if visible == "visible" and status and status not in VISIBLE_STATUS_VALUES:
            issues.append(f"invalid_{view}_status_for_visible:{status}")
        if visible == "invisible" and status and status not in INVISIBLE_STATUS_VALUES:
            issues.append(f"invalid_{view}_status_for_invisible:{status}")

    status_values = [rule.get(f"{v}_status", "") for v in ["front", "side", "back"]]
    expected = "wrong" if any(s in ERROR_STATUSES for s in status_values) else "correct"
    result = rule.get("result", "")
    if result and result not in {"correct", "wrong"}:
        issues.append(f"invalid_result:{result}")
    elif result and result != expected:
        issues.append(f"result_mismatch_expected_{expected}")

    return issues


def run_qc(rules: list[dict[str, Any]], expected_rule_ids: list[str]) -> tuple[list[dict], dict]:
    """Run QC on all rules, return (qc_rows, summary_counts)."""
    qc_rows = []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    returned_ids = set()

    for rule in rules:
        rule_id = rule.get("rule_id", "UNKNOWN")
        returned_ids.add(rule_id)
        issues = validate_rule(rule)
        warnings = []
        if rule_id not in expected_rule_ids:
            warnings.append("rule_id_not_in_expected_set")
        status = "FAIL" if issues else ("WARN" if warnings else "PASS")
        counts[status] = counts.get(status, 0) + 1
        qc_rows.append({
            "rule_id": rule_id,
            "value": rule.get("value", ""),
            "qc_status": status,
            "issues": ";".join(issues),
            "warnings": ";".join(warnings),
        })

    missing = set(expected_rule_ids) - returned_ids
    if missing:
        for rid in sorted(missing):
            qc_rows.append({
                "rule_id": rid,
                "value": "",
                "qc_status": "FAIL",
                "issues": "missing_from_output",
                "warnings": "",
            })
            counts["FAIL"] = counts.get("FAIL", 0) + 1

    return qc_rows, counts


# ── Flattening ───────────────────────────────────────────────────────


def flatten_rules(sample_id: str, category: str, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten rules into CSV-friendly rows."""
    rows = []
    for rule in rules:
        rows.append({
            "sample_id": sample_id,
            "rule_id": rule.get("rule_id", ""),
            "value": rule.get("value", ""),
            "front_visible": rule.get("front_visible", ""),
            "front_status": rule.get("front_status", ""),
            "side_visible": rule.get("side_visible", ""),
            "side_status": rule.get("side_status", ""),
            "back_visible": rule.get("back_visible", ""),
            "back_status": rule.get("back_status", ""),
            "result": rule.get("result", ""),
            "issue_type": rule.get("issue_type", ""),
            "confidence": rule.get("confidence", ""),
            "reason": rule.get("reason", ""),
        })
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


# ── Main ─────────────────────────────────────────────────────────────


def run_one_sample(
    sample_config: dict[str, Any],
    *,
    prompt_template: str,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    output_dir: Path,
    dry_run: bool,
) -> dict[str, Any]:
    sample_id = str(sample_config["sample_id"])
    category = sample_config.get("category", "backpack")
    source_image = Path(sample_config["source_image"])
    multiview_image = Path(sample_config["multiview_image"])
    atomic_rules_path = Path(sample_config["atomic_rules"])

    # Load atomic rules
    atomic_data = json.loads(atomic_rules_path.read_text(encoding="utf-8"))
    raw_rules = atomic_data.get("atomic_rules", atomic_data)
    # Normalize: the source file uses "id" as the key; prompt expects "rule_id".
    # Also convert non-string values (e.g. bool true) to strings for the prompt.
    atomic_rules = []
    for r in raw_rules:
        rule_id = r.get("rule_id") or r.get("id", "")
        value = r.get("value", "")
        if isinstance(value, bool):
            value = str(value)
        atomic_rules.append({"rule_id": rule_id, "value": value})
    expected_rule_ids = [r["rule_id"] for r in atomic_rules]

    # Build prompt
    prompt_text = build_prompt_text(prompt_template, sample_id, category, atomic_rules)

    # Setup output dir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sample_dir = output_dir / f"{sample_id}_v3_view_semantics_{timestamp}"
    sample_dir.mkdir(parents=True, exist_ok=True)

    # Save prompt
    (sample_dir / "prompt_v3_final_backpack.txt").write_text(prompt_text, encoding="utf-8")

    # Build messages
    messages = [
        {"role": "system", "content": "你只能输出合法 JSON，并严格遵守所有硬性覆盖规则。"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": encode_image_data_url(source_image)}},
                {"type": "image_url", "image_url": {"url": encode_image_data_url(multiview_image)}},
            ],
        },
    ]

    # Redacted payload for provenance
    redacted_payload = {
        "model": model,
        "messages": [
            {"role": m["role"], "content": m["content"] if isinstance(m["content"], str) else "[redacted_multimodal]"}
            for m in messages
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    write_json(sample_dir / "request_payload_redacted.json", redacted_payload)

    if dry_run:
        print(json.dumps({
            "status": "dry_run",
            "sample_id": sample_id,
            "prompt_chars": len(prompt_text),
            "atomic_rule_count": len(atomic_rules),
            "output_dir": str(sample_dir),
        }, ensure_ascii=False))
        return {"status": "dry_run", "output_dir": str(sample_dir)}

    # Diagnostic: print message structure before calling API
    print(f"Messages structure: {len(messages)} messages", flush=True)
    for i, msg in enumerate(messages):
        role = msg["role"]
        content = msg["content"]
        if isinstance(content, str):
            print(f"  [{i}] role={role}, content=string({len(content)} chars)", flush=True)
        elif isinstance(content, list):
            print(f"  [{i}] role={role}, content=list({len(content)} blocks):", flush=True)
            for j, block in enumerate(content):
                btype = block.get("type", "MISSING")
                if btype == "text":
                    print(f"    block[{j}]: type={btype}, text={len(block.get('text', ''))} chars", flush=True)
                elif btype == "image_url":
                    url = block.get("image_url", {}).get("url", "")
                    url_preview = url[:60] + "..." if len(url) > 60 else url
                    print(f"    block[{j}]: type={btype}, url={url_preview} ({len(url)} chars)", flush=True)
                else:
                    print(f"    block[{j}]: type={btype} ← UNEXPECTED TYPE!", flush=True)
                    print(f"    block[{j}] keys: {list(block.keys())}", flush=True)

    # Call Qwen API
    print(f"Calling Qwen {model} for sample {sample_id}...", flush=True)
    start_time = time.time()
    try:
        raw_text = qwen_vl_chat(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
    except requests.exceptions.HTTPError as e:
        print(f"\n=== API ERROR ===", flush=True)
        print(f"Status: {e.response.status_code}", flush=True)
        print(f"Response: {e.response.text}", flush=True)
        # Dump the exact payload for debugging (redact base64)
        debug_payload = {
            "model": model,
            "messages": [],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        for m in messages:
            if isinstance(m["content"], str):
                debug_payload["messages"].append({"role": m["role"], "content": m["content"][:200] + "..."})
            elif isinstance(m["content"], list):
                debug_blocks = []
                for b in m["content"]:
                    if b.get("type") == "image_url":
                        debug_blocks.append({"type": "image_url", "image_url": {"url": b["image_url"]["url"][:80] + "..."}})
                    else:
                        debug_blocks.append(b)
                debug_payload["messages"].append({"role": m["role"], "content": debug_blocks})
        (sample_dir / "debug_request_payload.json").write_text(
            json.dumps(debug_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Debug payload saved to {sample_dir / 'debug_request_payload.json'}", flush=True)
        raise
    elapsed = round(time.time() - start_time, 2)

    # Save raw response
    (sample_dir / f"raw_response_{model}.txt").write_text(raw_text, encoding="utf-8")

    # Parse JSON
    prediction = extract_json_object(raw_text)
    write_json(sample_dir / "qwen_prediction_v3.json", prediction)

    # Extract and flatten rules
    rules = prediction.get("rules", [])
    flat_rows = flatten_rules(sample_id, category, rules)
    write_csv(sample_dir / "qwen_prediction_flattened_v3.csv", flat_rows)

    # Also write JSONL
    jsonl_path = sample_dir / "qwen_prediction_flattened_v3.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in flat_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # QC
    qc_rows, qc_counts = run_qc(rules, expected_rule_ids)
    write_csv(sample_dir / "qwen_prediction_qc_report_v3.csv", qc_rows)

    # Summary
    correct_count = sum(1 for r in rules if r.get("result") == "correct")
    wrong_count = sum(1 for r in rules if r.get("result") == "wrong")
    summary = {
        "created_at": datetime.now().astimezone().isoformat(),
        "sample_id": sample_id,
        "category": category,
        "model_name": model,
        "elapsed_seconds": elapsed,
        "requested_rule_count": len(expected_rule_ids),
        "returned_rule_count": len(rules),
        "aggregate_counts": {
            "total_rules": len(rules),
            "correct_rules": correct_count,
            "wrong_rules": wrong_count,
        },
        "qc_counts": qc_counts,
        "output_dir": str(sample_dir),
    }
    write_json(sample_dir / "summary.json", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)
    qwen_key = "" if args.dry_run else require_key(args.qwen_api_key, "QWEN_API_KEY")

    # Load prompt template
    if not args.prompt_template.exists():
        raise SystemExit(f"Prompt template not found: {args.prompt_template}")
    prompt_template = args.prompt_template.read_text(encoding="utf-8")

    # Load sample configs
    config_data = json.loads(args.sample_config.read_text(encoding="utf-8"))
    samples = config_data if isinstance(config_data, list) else config_data.get("samples", [])

    results = []
    for sample_config in samples:
        result = run_one_sample(
            sample_config,
            prompt_template=prompt_template,
            api_key=qwen_key,
            base_url=args.qwen_base_url,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
        )
        results.append(result)

    print(json.dumps({"status": "finished", "sample_count": len(results), "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
