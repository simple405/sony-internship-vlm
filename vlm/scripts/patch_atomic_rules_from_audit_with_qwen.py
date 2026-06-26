"""Patch missing color/detail atomic_rules from an audit CSV with Qwen-VL.

This script preserves each existing atomic_rules JSON and only appends new rules
that Qwen can verify from the image for the audit-listed gaps.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from dashscope import MultiModalConversation
from tqdm import tqdm

from atomic_rules_qwen_shared import (
    DEFAULT_SOURCE_TAG_HINTS,
    ensure_dashscope_api_key,
    extract_text,
    normalize_rule_entry,
    parse_json_text,
    response_to_dict,
)
from extract_atomic_rules_with_qwen import (
    DEFAULT_METADATA,
    DEFAULT_OUT_DIR,
    append_jsonl,
    is_transient_error,
    load_rows,
    qwen_image_ref,
    sample_code,
    source_tag_hints,
)


DEFAULT_AUDIT_CSV = Path(
    "vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/reports/"
    "atomic_rules_missing_color_or_detail_audit.csv"
)

SYSTEM_PROMPT = """You are an anime IP character atomic_rules repair assistant.
You inspect the provided 2D character image and existing atomic_rules.
Your task is only to add missing color/detail counterpart rules requested by the audit.
Return strict JSON only.
"""

PATCH_PROMPT_TEMPLATE = """Patch missing atomic_rules for this one sample.

Code: __CODE__

Existing atomic_rules:
__EXISTING_RULES_JSON__

Audit candidates that may need counterpart color/detail rules:
__AUDIT_CANDIDATES__

Task:
- Do NOT regenerate all atomic_rules.
- Do NOT remove, rename, or rewrite existing rules.
- Return only NEW atomic rules that should be appended to the existing JSON.
- Only add rules for audit-listed objects/features when the color, gradient, pattern, accent color, symbol color, or other visual detail is clearly visible in the 2D image.
- Use the old project's decomposable principle: separate object, color, pattern, structure, and decoration into independent rules.
- Do not infer colors from common sense. For example, do not assume a bell is gold/yellow unless the 2D image visibly shows that color.
- If an audit item already has a visible object rule such as `holding_item = bell`, add a visible counterpart such as `holding_item_color`, `bell_color`, `holding_item_gradient`, or `bell_pattern` only if supported by the image.
- If an audit item is `*_gradient = true` or `*_pattern` but lacks a base color, add the base `*_color` only if visible.
- Use English snake_case ids and short canonical labels. Boolean values are allowed only for true detail flags such as gradient/pattern existence.
- Do not output unknown, none, false, not_visible, or explanations.

Output schema:
{
  "code": "__CODE__",
  "new_atomic_rules": [
    {
      "id": "<english_snake_case_rule_id>",
      "value": "<short_label_or_true>"
    }
  ]
}

Source tag weak hints:
__SOURCE_TAG_HINTS__
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Append missing color/detail atomic_rules listed in an audit CSV."
    )
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--atomic-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--audit-csv", type=Path, default=DEFAULT_AUDIT_CSV)
    parser.add_argument("--model", default="qwen3.5-plus")
    parser.add_argument("--image-source", choices=("url", "local"), default="url")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-base-sleep", type=float, default=2.0)
    parser.add_argument("--limit-samples", type=int, default=0, help="0 means all audited samples.")
    parser.add_argument("--list-only", action="store_true", help="Print selected sample count without API calls.")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument(
        "--patch-log",
        type=Path,
        help="Optional JSONL patch log. Defaults to <atomic-dir>/../logs/qwen_patch_atomic_rules_<timestamp>.jsonl.",
    )
    return parser.parse_args()


def default_patch_log(atomic_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return atomic_dir.parent / "logs" / f"qwen_patch_atomic_rules_{stamp}.jsonl"


def load_audit_rows(path: Path) -> dict[str, list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            sample_id = str(row.get("sample_id") or "").strip()
            rule_id = str(row.get("rule_id") or "").strip()
            if not sample_id or not rule_id:
                continue
            grouped[sample_id].append(
                {
                    "rule_id": rule_id,
                    "value": str(row.get("value") or "").strip(),
                    "issue_type": str(row.get("issue_type") or "").strip(),
                    "missing_expected_detail": str(row.get("missing_expected_detail") or "").strip(),
                    "existing_related_rules": str(row.get("existing_related_rules") or "").strip(),
                }
            )
    return dict(grouped)


def atomic_path(atomic_dir: Path, code: str) -> Path:
    return atomic_dir / code / f"{code}_atomic_rules.json"


def load_existing_doc(atomic_dir: Path, code: str) -> dict[str, Any]:
    path = atomic_path(atomic_dir, code)
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def compact_existing_rules(doc: dict[str, Any]) -> list[dict[str, Any]]:
    rules = doc.get("atomic_rules", [])
    if not isinstance(rules, list):
        return []
    compact: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_id = rule.get("id") or rule.get("rule_id")
        if not rule_id or "value" not in rule:
            continue
        compact.append({"id": rule_id, "value": rule.get("value")})
    return compact


def audit_candidates_text(rows: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for row in rows[:40]:
        lines.append(
            "- "
            f"rule_id={row['rule_id']}; "
            f"value={row['value']}; "
            f"issue={row['issue_type']}; "
            f"expected_detail_candidates={row['missing_expected_detail']}; "
            f"existing_related_rules={row['existing_related_rules']}"
        )
    return "\n".join(lines) if lines else "- No audit candidates."


def build_patch_prompt(code: str, existing_rules: list[dict[str, Any]], audit_rows: list[dict[str, str]], tags: str) -> str:
    return (
        PATCH_PROMPT_TEMPLATE.replace("__CODE__", code)
        .replace("__EXISTING_RULES_JSON__", json.dumps(existing_rules, ensure_ascii=False, indent=2))
        .replace("__AUDIT_CANDIDATES__", audit_candidates_text(audit_rows))
        .replace("__SOURCE_TAG_HINTS__", tags or DEFAULT_SOURCE_TAG_HINTS)
    )


def call_qwen_patch(
    image_ref: str,
    code: str,
    existing_rules: list[dict[str, Any]],
    audit_rows: list[dict[str, str]],
    model: str,
    tags: str,
) -> dict[str, Any]:
    api_key = ensure_dashscope_api_key()
    response = MultiModalConversation.call(
        model=model,
        messages=[
            {"role": "system", "content": [{"text": SYSTEM_PROMPT}]},
            {
                "role": "user",
                "content": [
                    {"image": image_ref},
                    {"text": build_patch_prompt(code, existing_rules, audit_rows, tags)},
                ],
            },
        ],
        api_key=api_key,
        result_format="message",
        temperature=0.0,
    )
    response_dict = response_to_dict(response)
    status_code = response_dict.get("status_code")
    if status_code and int(status_code) >= 400:
        raise RuntimeError(f"DashScope error {status_code}: {response_dict}")
    return parse_json_text(extract_text(response_dict))


def normalize_new_rules(doc: dict[str, Any]) -> list[dict[str, Any]]:
    rules = doc.get("new_atomic_rules", [])
    if not isinstance(rules, list):
        rules = doc.get("atomic_rules", [])
    if not isinstance(rules, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in rules:
        item = normalize_rule_entry(rule)
        if not item:
            continue
        key = json.dumps([item["id"], item["value"]], ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    return normalized


def merge_rules(existing_doc: dict[str, Any], additions: list[dict[str, Any]], code: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    existing_rules = compact_existing_rules(existing_doc)
    existing_keys = {
        json.dumps([rule["id"], rule["value"]], ensure_ascii=False, sort_keys=True)
        for rule in existing_rules
    }
    kept: list[dict[str, Any]] = []
    for rule in additions:
        key = json.dumps([rule["id"], rule["value"]], ensure_ascii=False, sort_keys=True)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        kept.append(rule)
    return {"code": code, "atomic_rules": [*existing_rules, *kept]}, kept


def local_image_path_from_row(row: dict[str, Any]) -> Path:
    path = Path(str(row.get("image_path", "")))
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def process_sample(
    row: dict[str, Any],
    audit_rows: list[dict[str, str]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    code = sample_code(row)
    try:
        existing_doc = load_existing_doc(args.atomic_dir, code)
        existing_rules = compact_existing_rules(existing_doc)
        image_path = local_image_path_from_row(row)
        image_ref = qwen_image_ref(row, image_path, args.image_source)
        tags = source_tag_hints(row) or DEFAULT_SOURCE_TAG_HINTS

        last_exc: Exception | None = None
        parsed: dict[str, Any] | None = None
        for attempt in range(args.retries + 1):
            try:
                parsed = call_qwen_patch(image_ref, code, existing_rules, audit_rows, args.model, tags)
                break
            except Exception as exc:
                last_exc = exc
                if attempt >= args.retries or not is_transient_error(exc):
                    break
                delay = args.retry_base_sleep * (2**attempt) + random.uniform(0, 0.5)
                time.sleep(delay)
        if parsed is None:
            assert last_exc is not None
            raise last_exc

        additions = normalize_new_rules(parsed)
        merged_doc, kept = merge_rules(existing_doc, additions, code)
        path = atomic_path(args.atomic_dir, code)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(merged_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
        if args.sleep:
            time.sleep(args.sleep)
        return {
            "status": "patched",
            "code": code,
            "audit_issue_count": len(audit_rows),
            "model_rule_count": len(additions),
            "added_rule_count": len(kept),
            "added_rules": kept,
        }
    except Exception as exc:
        return {
            "status": "error",
            "code": code,
            "audit_issue_count": len(audit_rows),
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        }


def select_work(args: argparse.Namespace) -> list[tuple[dict[str, Any], list[dict[str, str]]]]:
    audit_by_code = load_audit_rows(args.audit_csv)
    rows_by_code = {sample_code(row): row for row in load_rows(args.metadata, 0, 0)}
    work: list[tuple[dict[str, Any], list[dict[str, str]]]] = []
    for code in sorted(audit_by_code):
        row = rows_by_code.get(code)
        if not row:
            continue
        work.append((row, audit_by_code[code]))
    if args.limit_samples > 0:
        work = work[: args.limit_samples]
    return work


def run(args: argparse.Namespace) -> None:
    if args.workers <= 0:
        raise ValueError("--workers must be greater than 0")
    if args.retries < 0:
        raise ValueError("--retries must not be negative")
    if args.sleep < 0:
        raise ValueError("--sleep must not be negative")
    if args.retry_base_sleep < 0:
        raise ValueError("--retry-base-sleep must not be negative")
    if not args.list_only and not os.environ.get("DASHSCOPE_API_KEY"):
        raise SystemExit("DASHSCOPE_API_KEY is not set in this process.")

    work = select_work(args)
    print(f"Selected audited samples: {len(work)}")
    print(f"Audit CSV: {args.audit_csv}")
    print(f"Atomic dir: {args.atomic_dir}")
    if args.list_only:
        return

    patch_log = args.patch_log or default_patch_log(args.atomic_dir)
    patched = 0
    errors = 0
    added = 0

    if args.workers == 1:
        iterator = (process_sample(row, audit_rows, args) for row, audit_rows in work)
        for result in tqdm(iterator, total=len(work), desc="patch_atomic_rules", unit="img"):
            append_jsonl(patch_log, result)
            if result["status"] == "patched":
                patched += 1
                added += int(result["added_rule_count"])
            else:
                errors += 1
                if args.stop_on_error:
                    raise RuntimeError(json.dumps(result, ensure_ascii=False))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(process_sample, row, audit_rows, args) for row, audit_rows in work]
            for future in tqdm(as_completed(futures), total=len(futures), desc="patch_atomic_rules", unit="img"):
                result = future.result()
                append_jsonl(patch_log, result)
                if result["status"] == "patched":
                    patched += 1
                    added += int(result["added_rule_count"])
                else:
                    errors += 1
                    if args.stop_on_error:
                        raise RuntimeError(json.dumps(result, ensure_ascii=False))

    print(f"Patched samples: {patched}; added rules: {added}; errors: {errors}")
    print(f"Patch log: {patch_log}")


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
