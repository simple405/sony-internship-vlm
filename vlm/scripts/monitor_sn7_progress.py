"""Monitor SN-7 atomic-rules, RunningHub generation, and package progress."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from vlm.scripts._sn7_artifacts import (  # noqa: E402
    CATEGORIES,
    CATEGORY_OUTPUT_SUFFIXES as OUTPUT_SUFFIXES,
    IMAGE_SUFFIXES,
    find_generated_output,
    valid_image,
)
from vlm.scripts._dataset_manifest import (  # noqa: E402
    CONSOLIDATED_MANIFEST,
    SN7_DATASET_ROOT,
    SN7_DATASET_ID,
    read_manifest_rows,
)
from vlm.scripts.utils.atomic_rule_xlsx import (  # noqa: E402
    TRANSLATION_CACHE_RELATIVE_PATH,
)


DEFAULT_DATASET = Path("vlm/data/design_sheet_10610_smoke30")
PRODUCTION_DATASET = SN7_DATASET_ROOT
DEFAULT_RUN_DIR = Path("vlm/tmp/sn7_runninghub_smoke30")


def parse_args() -> argparse.Namespace:
    """Parse monitor arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--watch", type=int, default=0, help="Refresh every N seconds; 0 prints once.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of the compact text view.")
    parser.add_argument(
        "--processes",
        action="store_true",
        help="Try to include matching Python process command lines on Windows.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read an Excel-compatible CSV, returning an empty list when absent."""
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def has_atomic_rules(dataset_dir: Path, sample_id: str) -> bool:
    """Return whether Qwen produced a canonical atomic-rules file."""
    sample_dir = dataset_dir / "atomic_rules" / sample_id
    return (sample_dir / "atomic_rules.json").is_file()


def has_atomic_error(dataset_dir: Path, sample_id: str) -> bool:
    """Return whether Qwen recorded an extraction error."""
    return (dataset_dir / "atomic_rules" / sample_id / "error.json").is_file()


def generated_output(dataset_dir: Path, category: str, sample_id: str) -> Path | None:
    """Find a valid canonical RunningHub output for one sample."""
    sample_dir = dataset_dir / "generated" / category / sample_id
    suffix_name = OUTPUT_SUFFIXES[category]
    return find_generated_output(sample_dir, sample_id, suffix_name)


def package_complete(dataset_dir: Path, category: str, sample_id: str) -> bool:
    """Return whether the final deliverable folder has all required files."""
    sample_dir = dataset_dir / "deliverables" / category / sample_id
    if not sample_dir.is_dir():
        return False
    has_original = any(
        (sample_dir / f"2d_original{extension}").is_file()
        for extension in IMAGE_SUFFIXES
    )
    return all(
        [
            has_original,
            (sample_dir / "atomic_rules.json").is_file(),
            valid_image(sample_dir / "multiview_design.png"),
            (sample_dir / f"{sample_id}.xlsx").is_file(),
        ]
    )


def latest_run_dir(run_dir: Path) -> str:
    """Return the newest RunningHub run directory path if present."""
    if not run_dir.is_dir():
        return ""
    dirs = [path for path in run_dir.iterdir() if path.is_dir()]
    if not dirs:
        return ""
    return str(max(dirs, key=lambda path: path.stat().st_mtime))


def process_snapshot() -> list[dict[str, str]]:
    """Best-effort Windows process snapshot for relevant Python commands."""
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match 'python' -and "
        "($_.CommandLine -match 'extract_atomic_rules|translate_atomic_rules_xlsx|run_runninghub|generate_sn7_multiview') } | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"{type(exc).__name__}: {exc}"}]
    if completed.returncode != 0:
        return [{"error": completed.stderr.strip() or completed.stdout.strip()}]
    text = completed.stdout.strip()
    if not text:
        return []
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError:
        return [{"error": text}]
    if isinstance(parsed, dict):
        parsed = [parsed]
    return [
        {"pid": str(item.get("ProcessId", "")), "command": str(item.get("CommandLine", ""))}
        for item in parsed
        if isinstance(item, dict)
    ]


def build_report(dataset_dir: Path, run_dir: Path, include_processes: bool) -> dict[str, Any]:
    """Build a point-in-time progress report."""
    if dataset_dir.resolve() == PRODUCTION_DATASET.resolve() and CONSOLIDATED_MANIFEST.is_file():
        manifest = read_manifest_rows(CONSOLIDATED_MANIFEST, dataset_id=SN7_DATASET_ID)
    else:
        manifest = read_csv(dataset_dir / "manifest.csv")
    assignment = read_csv(
        dataset_dir
        / "reports"
        / "merchandise_category_assignment"
        / "merchandise_category_assignments.csv"
    )
    category_by_id = {row.get("sample_id", ""): row.get("primary_category", "") for row in assignment}
    generated_by_category: Counter[str] = Counter()
    packaged_by_category: Counter[str] = Counter()
    atomic_ok = 0
    atomic_errors = 0
    generated_ok = 0
    packaged_ok = 0
    atomic_xlsx = 0
    generated_xlsx = 0

    for row in manifest:
        sample_id = row.get("sample_id") or row.get("post_id") or ""
        category = category_by_id.get(sample_id, "")
        if has_atomic_rules(dataset_dir, sample_id):
            atomic_ok += 1
            if (dataset_dir / "atomic_rules" / sample_id / f"{sample_id}.xlsx").is_file():
                atomic_xlsx += 1
        elif has_atomic_error(dataset_dir, sample_id):
            atomic_errors += 1
        if category in CATEGORIES and generated_output(dataset_dir, category, sample_id) is not None:
            generated_ok += 1
            generated_by_category[category] += 1
            if (
                dataset_dir / "generated" / category / sample_id / f"{sample_id}.xlsx"
            ).is_file():
                generated_xlsx += 1
        if category in CATEGORIES and package_complete(dataset_dir, category, sample_id):
            packaged_ok += 1
            packaged_by_category[category] += 1

    total = len(manifest)
    translation_cache_path = dataset_dir / TRANSLATION_CACHE_RELATIVE_PATH
    translation: dict[str, Any] = {
        "status": "not_started",
        "translated": 0,
        "total": 0,
        "pending": 0,
        "cache_path": str(translation_cache_path),
    }
    if translation_cache_path.is_file():
        try:
            cache_payload = json.loads(
                translation_cache_path.read_text(encoding="utf-8-sig")
            )
            translated = int(cache_payload.get("translated_pair_count", 0))
            source_total = int(cache_payload.get("source_pair_count", 0))
            translation.update(
                {
                    "status": str(cache_payload.get("status", "unknown")),
                    "translated": translated,
                    "total": source_total,
                    "pending": max(0, source_total - translated),
                    "model": str(cache_payload.get("model", "")),
                }
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            translation.update({"status": "invalid_cache", "error": str(exc)})
    report: dict[str, Any] = {
        "status": "ok",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset_dir": str(dataset_dir),
        "total": total,
        "source_counts": dict(Counter(row.get("source_dataset", "") for row in manifest)),
        "category_counts": dict(Counter(category_by_id.values())),
        "atomic_rules": {
            "succeeded": atomic_ok,
            "errors": atomic_errors,
            "pending": max(0, total - atomic_ok - atomic_errors),
            "xlsx": atomic_xlsx,
        },
        "translation": translation,
        "runninghub": {
            "generated": generated_ok,
            "pending": max(0, total - generated_ok),
            "xlsx": generated_xlsx,
            "by_category": {category: generated_by_category[category] for category in CATEGORIES},
            "latest_run_dir": latest_run_dir(run_dir),
        },
        "deliverables": {
            "packaged": packaged_ok,
            "pending": max(0, total - packaged_ok),
            "by_category": {category: packaged_by_category[category] for category in CATEGORIES},
        },
    }
    if include_processes:
        report["processes"] = process_snapshot()
    return report


def print_text(report: dict[str, Any]) -> None:
    """Print a compact human-readable progress report."""
    total = report["total"]
    atomic = report["atomic_rules"]
    translation = report["translation"]
    runninghub = report["runninghub"]
    deliverables = report["deliverables"]
    print(f"[{report['timestamp']}] {report['dataset_dir']}")
    print(f"total: {total}")
    print(
        "atomic_rules: "
        f"{atomic['succeeded']}/{total} ok, {atomic['errors']} errors, "
        f"{atomic['pending']} pending, {atomic['xlsx']} xlsx"
    )
    print(
        "translation: "
        f"{translation['translated']}/{translation['total']} cached, "
        f"{translation['pending']} pending, status={translation['status']}"
    )
    print(
        f"runninghub: {runninghub['generated']}/{total} generated, "
        f"{runninghub['pending']} pending, {runninghub['xlsx']} xlsx"
    )
    print(f"deliverables: {deliverables['packaged']}/{total} packaged, {deliverables['pending']} pending")
    print(f"latest_run_dir: {runninghub['latest_run_dir'] or '-'}")
    print("runninghub_by_category:")
    for category, count in runninghub["by_category"].items():
        print(f"  {category}: {count}")
    if "processes" in report:
        print("processes:")
        for item in report["processes"]:
            print(f"  {item}")


def main() -> None:
    """Run the progress monitor."""
    args = parse_args()
    dataset_dir = args.dataset_dir.resolve()
    run_dir = args.run_dir.resolve()
    while True:
        report = build_report(dataset_dir, run_dir, args.processes)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        else:
            print_text(report)
        if args.watch <= 0:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
