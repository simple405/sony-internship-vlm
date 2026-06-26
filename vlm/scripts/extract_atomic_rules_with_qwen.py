"""Build minimal one-folder-per-image atomic_rules data with Qwen-VL.

The output structure follows vlm/data/raw_trials style:
- <sample_id>_original.<ext>
- <sample_id>_atomic_rules.json

This is the canonical Safebooru smoke-test extraction script.
No metadata, raw model response, evidence, confidence, or audit sidecar files are
written by this script.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from tqdm import tqdm

from atomic_rules_qwen_shared import (
    DEFAULT_SOURCE_TAG_HINTS,
    call_qwen_atomic_rules,
    normalize_rule_doc,
)


DEFAULT_METADATA = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/metadata.jsonl")
DEFAULT_OUT_DIR = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/atomic_rules")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create raw_trials-style folders and extract minimal atomic_rules with Qwen-VL."
    )
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--model", default="qwen3.5-plus")
    parser.add_argument("--limit", type=int, default=20, help="0 means all rows after --offset.")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--sample-ids-file",
        type=Path,
        help="Optional newline or CSV file of sample IDs to process after metadata/offset/limit filtering.",
    )
    parser.add_argument(
        "--audit-csv",
        type=Path,
        help="Optional CSV audit report with sample_id/rule_id/value columns. Also adds per-sample repair guidance.",
    )
    parser.add_argument(
        "--image-source",
        choices=("url", "local"),
        default="url",
        help="Use remote image URL for Qwen by default to avoid local Unicode path upload issues.",
    )
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--workers", type=int, default=1, help="Concurrent Qwen requests. Start with 3 or 4.")
    parser.add_argument("--retries", type=int, default=2, help="Retries per image for transient API failures.")
    parser.add_argument("--retry-base-sleep", type=float, default=2.0)
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep polling metadata.jsonl and process newly crawled rows until stopped.",
    )
    parser.add_argument("--poll-interval", type=float, default=10.0, help="Seconds between metadata polls in watch mode.")
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=0.0,
        help="Exit watch mode after this many seconds without pending work. 0 means run until interrupted.",
    )
    parser.add_argument(
        "--error-log",
        type=Path,
        help="Optional JSONL error log. Defaults to <out-dir>/../logs/qwen_extract_errors_<timestamp>.jsonl.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help="Only create folders and copy images.")
    parser.add_argument("--guidance-file", type=Path, help="Optional prompt guidance file.")
    parser.add_argument(
        "--force-continue",
        action="store_true",
        help="Continue extracting visible rules for non-ideal but usable images instead of returning an empty array.",
    )
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args()


def load_guidance(path: Path | None) -> str:
    if not path:
        return ""
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return ""
    return text


def load_rows(path: Path, offset: int, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if offset < 0:
        raise ValueError("--offset must not be negative")
    if limit < 0:
        raise ValueError("--limit must not be negative")
    if limit == 0:
        return rows[offset:]
    return rows[offset : offset + limit]


def sample_code(row: dict[str, Any]) -> str:
    return str(row.get("post_id") or row.get("code") or "unknown")


def load_sample_ids_file(path: Path | None) -> set[str]:
    if not path:
        return set()
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return set()
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            ids: set[str] = set()
            for row in reader:
                sample_id = row.get("sample_id") or row.get("post_id") or row.get("code")
                if sample_id:
                    ids.add(str(sample_id).strip())
            return {sample_id for sample_id in ids if sample_id}
    ids = re.split(r"[\s,]+", text)
    return {sample_id.strip() for sample_id in ids if sample_id.strip()}


def load_audit_guidance(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    if not path.exists():
        raise FileNotFoundError(path)
    grouped: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            sample_id = str(row.get("sample_id") or "").strip()
            if not sample_id:
                continue
            rule_id = str(row.get("rule_id") or "").strip()
            value = str(row.get("value") or "").strip()
            missing = str(row.get("missing_expected_detail") or "").strip()
            issue = str(row.get("issue_type") or "").strip()
            if not rule_id:
                continue
            grouped.setdefault(sample_id, []).append(
                f"- {rule_id}={value}; issue={issue}; expected_detail_candidates={missing}"
            )

    guidance_by_code: dict[str, str] = {}
    for sample_id, lines in grouped.items():
        selected = lines[:30]
        guidance_by_code[sample_id] = "\n".join(
            [
                "A previous structural audit selected this sample because some object/accessory/held-item/detail rules are missing color or visual-detail counterparts.",
                "Re-inspect the image and output a complete atomic_rules JSON. Preserve visible core rules, and add missing *_color, *_gradient, *_pattern, or accent-color rules only when the detail is visible in the image.",
                "Do not infer colors from common sense; use the 2D image only.",
                "Audit candidates:",
                *selected,
            ]
        )
    return guidance_by_code


def filter_rows_by_sample_ids(rows: list[dict[str, Any]], sample_ids: set[str]) -> list[dict[str, Any]]:
    if not sample_ids:
        return rows
    return [row for row in rows if sample_code(row) in sample_ids]


def local_image_path(row: dict[str, Any]) -> Path:
    path = Path(str(row.get("image_path", "")))
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def qwen_image_ref(row: dict[str, Any], image_path: Path, image_source: str) -> str:
    if image_source == "url":
        url = str(row.get("image_url") or row.get("sample_url") or row.get("file_url") or "").strip()
        if url:
            return url
    return image_path.resolve().as_uri()


def source_tag_hints(row: dict[str, Any]) -> str:
    tags_value = row.get("tags") or row.get("tag_string") or row.get("query_tags") or ""
    if isinstance(tags_value, list):
        tags = [str(tag) for tag in tags_value]
    else:
        tags = re.split(r"\s+", str(tags_value).strip())
    tags = [tag.strip() for tag in tags if tag and len(tag.strip()) <= 64]
    if not tags:
        return "No source tags are available."

    priority_keywords = {
        "fan",
        "folding_fan",
        "book",
        "staff",
        "wand",
        "umbrella",
        "bag",
        "backpack",
        "weapon",
        "sword",
        "ribbon",
        "bow",
        "hair_ribbon",
        "yin_yang",
        "boots",
        "shoes",
        "gloves",
        "tail",
        "wings",
        "horns",
        "braid",
        "ponytail",
        "twintails",
        "dark_skin",
        "tan",
    }
    priority_tags = [
        tag
        for tag in tags
        if tag in priority_keywords or any(keyword in tag for keyword in priority_keywords)
    ]
    selected: list[str] = []
    seen: set[str] = set()
    for tag in [*priority_tags, *tags]:
        if tag not in seen:
            selected.append(tag)
            seen.add(tag)
        if len(selected) >= 40:
            break
    return "These source tags are weak hints only. Verify visually: " + " ".join(selected)


def copy_original_image(row: dict[str, Any], sample_dir: Path, code: str) -> Path:
    src = local_image_path(row)
    suffix = src.suffix.lower() or ".jpg"
    dst = sample_dir / f"{code}_original{suffix}"
    if not dst.exists() or dst.stat().st_size == 0:
        shutil.copy2(src, dst)
    return dst


def atomic_output_path(row: dict[str, Any], out_dir: Path) -> Path:
    code = sample_code(row)
    return out_dir / code / f"{code}_atomic_rules.json"


def pending_rows(rows: list[dict[str, Any]], out_dir: Path, overwrite: bool) -> list[dict[str, Any]]:
    if overwrite:
        return rows
    pending: list[dict[str, Any]] = []
    for row in rows:
        path = atomic_output_path(row, out_dir)
        if not path.exists() or path.stat().st_size == 0:
            pending.append(row)
    return pending


def default_error_log(out_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = out_dir.parent / "logs"
    return log_dir / f"qwen_extract_errors_{stamp}.jsonl"


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def is_transient_error(exc: Exception) -> bool:
    message = str(exc).lower()
    transient_markers = (
        "429",
        "500",
        "502",
        "503",
        "504",
        "timeout",
        "temporarily",
        "connection",
        "rate limit",
        "too many requests",
    )
    return any(marker in message for marker in transient_markers)


def process_row(row: dict[str, Any], args: argparse.Namespace, guidance: str) -> dict[str, Any]:
    code = sample_code(row)
    sample_dir = args.out_dir / code
    sample_dir.mkdir(parents=True, exist_ok=True)
    atomic_path = sample_dir / f"{code}_atomic_rules.json"
    row_guidance_parts = [part for part in [guidance.strip()] if part]
    audit_guidance = getattr(args, "audit_guidance_by_code", {}).get(code, "")
    if audit_guidance:
        row_guidance_parts.append(audit_guidance)
    row_guidance = "\n\n".join(row_guidance_parts)

    try:
        image_file = copy_original_image(row, sample_dir, code)

        if args.prepare_only:
            return {"status": "prepared", "code": code}
        if atomic_path.exists() and atomic_path.stat().st_size > 0 and not args.overwrite:
            return {"status": "skipped", "code": code}

        last_exc: Exception | None = None
        for attempt in range(args.retries + 1):
            try:
                parsed, _ = call_qwen_atomic_rules(
                    qwen_image_ref(row, image_file, args.image_source),
                    code,
                    args.model,
                    source_tag_hints=source_tag_hints(row) or DEFAULT_SOURCE_TAG_HINTS,
                    guidance=row_guidance,
                    force_continue=args.force_continue,
                )
                doc = normalize_rule_doc(parsed, code)
                tmp_path = atomic_path.with_suffix(atomic_path.suffix + ".tmp")
                tmp_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp_path.replace(atomic_path)
                if args.sleep:
                    time.sleep(args.sleep)
                return {"status": "written", "code": code}
            except Exception as exc:
                last_exc = exc
                if attempt >= args.retries or not is_transient_error(exc):
                    break
                delay = args.retry_base_sleep * (2**attempt) + random.uniform(0, 0.5)
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc
    except Exception as exc:
        return {
            "status": "error",
            "code": code,
            "image_path": str(row.get("image_path", "")),
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        }


def run_rows(
    rows: list[dict[str, Any]],
    args: argparse.Namespace,
    guidance: str,
    error_log: Path,
) -> dict[str, int]:
    written = 0
    skipped = 0
    prepared = 0
    errors: list[dict[str, Any]] = []
    if args.workers == 1:
        iterator = (process_row(row, args, guidance) for row in rows)
        for result in tqdm(iterator, total=len(rows), desc="atomic_rules", unit="img"):
            if result["status"] == "written":
                written += 1
            elif result["status"] == "skipped":
                skipped += 1
            elif result["status"] == "prepared":
                prepared += 1
            else:
                errors.append(result)
                append_jsonl(error_log, result)
                if args.stop_on_error:
                    raise RuntimeError(json.dumps(result, ensure_ascii=False))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(process_row, row, args, guidance) for row in rows]
            for future in tqdm(as_completed(futures), total=len(futures), desc="atomic_rules", unit="img"):
                result = future.result()
                if result["status"] == "written":
                    written += 1
                elif result["status"] == "skipped":
                    skipped += 1
                elif result["status"] == "prepared":
                    prepared += 1
                else:
                    errors.append(result)
                    append_jsonl(error_log, result)
                    if args.stop_on_error:
                        raise RuntimeError(json.dumps(result, ensure_ascii=False))

    print(f"Output dataset folder: {args.out_dir}")
    print(
        f"Wrote atomic_rules: {written}; skipped: {skipped}; "
        f"prepared: {prepared}; errors: {len(errors)}"
    )
    if errors:
        print(f"Error log: {error_log}")
        print("First errors:")
        for error in errors[:5]:
            print(json.dumps(error, ensure_ascii=False))
    return {"written": written, "skipped": skipped, "prepared": prepared, "errors": len(errors)}


def run_once(args: argparse.Namespace, guidance: str, error_log: Path) -> dict[str, int]:
    rows = load_rows(args.metadata, args.offset, args.limit)
    rows = filter_rows_by_sample_ids(rows, getattr(args, "sample_ids", set()))
    if getattr(args, "sample_ids", set()):
        print(f"Selected rows by sample IDs: {len(rows)}")
    return run_rows(rows, args, guidance, error_log)


def run_watch(args: argparse.Namespace, guidance: str, error_log: Path) -> None:
    if args.overwrite:
        raise ValueError("--watch cannot be combined with --overwrite because it would reprocess every poll.")
    last_work_time = time.monotonic()
    totals = {"written": 0, "skipped": 0, "prepared": 0, "errors": 0}
    print(f"Watching metadata: {args.metadata}")
    print(f"Output dataset folder: {args.out_dir}")

    try:
        while True:
            rows = load_rows(args.metadata, args.offset, args.limit)
            rows = filter_rows_by_sample_ids(rows, getattr(args, "sample_ids", set()))
            work = pending_rows(rows, args.out_dir, overwrite=False)
            if work:
                print(f"Found pending rows: {len(work)} / metadata rows: {len(rows)}")
                result = run_rows(work, args, guidance, error_log)
                for key, value in result.items():
                    totals[key] += value
                last_work_time = time.monotonic()
                print(
                    "Watch totals: "
                    f"written={totals['written']} skipped={totals['skipped']} "
                    f"prepared={totals['prepared']} errors={totals['errors']}"
                )
                continue

            if args.idle_timeout and time.monotonic() - last_work_time >= args.idle_timeout:
                print(f"No pending work for {args.idle_timeout:.0f}s; exiting watch mode.")
                break
            time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        print("Interrupted watch mode.")


def main() -> None:
    args = parse_args()
    if args.workers <= 0:
        raise ValueError("--workers must be greater than 0")
    if args.retries < 0:
        raise ValueError("--retries must not be negative")
    if args.sleep < 0:
        raise ValueError("--sleep must not be negative")
    if args.retry_base_sleep < 0:
        raise ValueError("--retry-base-sleep must not be negative")
    if args.poll_interval <= 0:
        raise ValueError("--poll-interval must be greater than 0")
    if args.idle_timeout < 0:
        raise ValueError("--idle-timeout must not be negative")
    if not args.prepare_only and not os.environ.get("DASHSCOPE_API_KEY"):
        raise SystemExit("DASHSCOPE_API_KEY is not set in this process.")

    guidance = load_guidance(args.guidance_file)
    audit_guidance_by_code = load_audit_guidance(args.audit_csv)
    sample_ids = load_sample_ids_file(args.sample_ids_file)
    sample_ids.update(audit_guidance_by_code)
    args.sample_ids = sample_ids
    args.audit_guidance_by_code = audit_guidance_by_code
    args.out_dir.mkdir(parents=True, exist_ok=True)
    error_log = args.error_log or default_error_log(args.out_dir)
    if args.watch:
        run_watch(args, guidance, error_log)
    else:
        run_once(args, guidance, error_log)


if __name__ == "__main__":
    main()
