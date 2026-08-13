"""Maintain a persistent SN-7 generation ledger.

The ledger is a small CSV used to keep sample IDs that were already submitted or
finished by RunningHub generation out of later queues.  It complements the
existing output-file resume guard: scan records completed/error artifacts that
already exist on disk, mark records one sample explicitly, and filter removes
ledgered IDs from a plain-text sample list.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts._sn7_artifacts import (
    CATEGORIES,
    CATEGORY_OUTPUT_SUFFIXES as OUTPUT_SUFFIXES,
    find_generated_output,
)
from vlm.scripts._validation import validate_path_component


DEFAULT_DATASET = Path("vlm/data/sn7_data_generation")
DEFAULT_SKIP_STATUSES = ("started", "succeeded", "no_image_url_found", "failed")
LEDGER_FIELDS = (
    "sample_id",
    "category",
    "status",
    "source",
    "artifact_path",
    "updated_at",
    "detail",
)
STATUS_PRIORITY = {
    "started": 10,
    "dry_run": 20,
    "failed": 30,
    "no_image_url_found": 40,
    "succeeded": 100,
}


def parse_args() -> argparse.Namespace:
    """Parse ledger commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=None,
        help="Default: <dataset-dir>/reports/runninghub_generation_ledger/used_samples.csv",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Scan generated outputs and errors into the ledger.")
    scan.add_argument("--replace", action="store_true", help="Replace the existing ledger instead of merging.")

    mark = subparsers.add_parser("mark", help="Upsert one sample into the ledger.")
    mark.add_argument("--sample-id", required=True)
    mark.add_argument("--category", required=True, choices=CATEGORIES)
    mark.add_argument(
        "--status",
        required=True,
        choices=("started", "succeeded", "failed", "no_image_url_found", "dry_run"),
    )
    mark.add_argument("--source", default="manual_mark")
    mark.add_argument("--artifact-path", default="")
    mark.add_argument("--detail", default="")

    filter_parser = subparsers.add_parser("filter", help="Remove ledgered IDs from a sample-list file.")
    filter_parser.add_argument("--sample-list", type=Path, required=True)
    filter_parser.add_argument("--category", required=True, choices=CATEGORIES)
    filter_parser.add_argument("--output", type=Path, default=None)
    filter_parser.add_argument(
        "--skip-status",
        action="append",
        default=[],
        choices=tuple(STATUS_PRIORITY),
        help="Status to skip. Repeatable. Default skips started/succeeded/no_image_url_found/failed.",
    )

    return parser.parse_args()


def default_ledger_path(dataset_dir: Path) -> Path:
    """Return the canonical ledger path for a dataset."""
    return dataset_dir / "reports" / "runninghub_generation_ledger" / "used_samples.csv"


def resolved_ledger_path(args: argparse.Namespace) -> Path:
    """Resolve the user-provided or default ledger path."""
    return args.ledger_path or default_ledger_path(args.dataset_dir)


def now_iso() -> str:
    """Return a timezone-aware timestamp for manual updates."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def file_mtime_iso(path: Path) -> str:
    """Return a timezone-aware timestamp from a file mtime."""
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def row_priority(row: dict[str, str]) -> int:
    """Return the merge priority for a ledger row."""
    return STATUS_PRIORITY.get(row.get("status", ""), 0)


def validate_row(row: dict[str, str]) -> dict[str, str]:
    """Normalize and validate one ledger row."""
    sample_id = validate_path_component(row.get("sample_id", ""), "sample ID")
    category = row.get("category", "")
    if category not in CATEGORIES:
        raise ValueError(f"Unsupported category for {sample_id}: {category!r}")
    status = row.get("status", "")
    if status not in STATUS_PRIORITY:
        raise ValueError(f"Unsupported status for {sample_id}: {status!r}")
    return {
        "sample_id": sample_id,
        "category": category,
        "status": status,
        "source": row.get("source", ""),
        "artifact_path": row.get("artifact_path", ""),
        "updated_at": row.get("updated_at", ""),
        "detail": row.get("detail", ""),
    }


def read_ledger(path: Path) -> dict[str, dict[str, str]]:
    """Read the ledger keyed by sample ID."""
    if not path.is_file():
        return {}
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            row = validate_row(raw)
            previous = rows.get(row["sample_id"])
            if previous is None or row_priority(row) >= row_priority(previous):
                rows[row["sample_id"]] = row
    return rows


def write_ledger(path: Path, rows: dict[str, dict[str, str]]) -> None:
    """Write the ledger atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    ordered = sorted(rows.values(), key=lambda row: (row["category"], row["sample_id"]))
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)
    temp.replace(path)


def upsert(rows: dict[str, dict[str, str]], row: dict[str, str]) -> None:
    """Insert or replace a ledger row if it is at least as authoritative."""
    normalized = validate_row(row)
    previous = rows.get(normalized["sample_id"])
    if previous is None or row_priority(normalized) >= row_priority(previous):
        rows[normalized["sample_id"]] = normalized


def valid_generated_output(sample_dir: Path, sample_id: str, output_suffix: str) -> Path | None:
    """Return the first valid canonical generated image for a sample."""
    return find_generated_output(sample_dir, sample_id, output_suffix)


def scan_dataset(dataset_dir: Path) -> dict[str, dict[str, str]]:
    """Scan generated outputs and generation_error.json files into rows."""
    scanned: dict[str, dict[str, str]] = {}
    generated_root = dataset_dir / "generated"
    for category in CATEGORIES:
        category_dir = generated_root / category
        if not category_dir.is_dir():
            continue
        output_suffix = OUTPUT_SUFFIXES[category]
        for sample_dir in sorted(category_dir.iterdir()):
            if not sample_dir.is_dir() or sample_dir.name.startswith("_"):
                continue
            sample_id = validate_path_component(sample_dir.name, "sample ID")
            output_path = valid_generated_output(sample_dir, sample_id, output_suffix)
            if output_path is not None:
                upsert(
                    scanned,
                    {
                        "sample_id": sample_id,
                        "category": category,
                        "status": "succeeded",
                        "source": "scan_generated_output",
                        "artifact_path": output_path.relative_to(dataset_dir).as_posix(),
                        "updated_at": file_mtime_iso(output_path),
                        "detail": "",
                    },
                )
                continue

            error_path = sample_dir / "generation_error.json"
            if not error_path.is_file():
                continue
            status = "failed"
            detail = ""
            try:
                payload: dict[str, Any] = json.loads(error_path.read_text(encoding="utf-8"))
                status = str(payload.get("status") or "failed")
                if status not in STATUS_PRIORITY:
                    status = "failed"
                detail = str(payload.get("rejection_type") or payload.get("error_type") or "")
            except Exception as exc:  # noqa: BLE001
                detail = f"{type(exc).__name__}: {exc}"
            upsert(
                scanned,
                {
                    "sample_id": sample_id,
                    "category": category,
                    "status": status,
                    "source": "scan_generation_error",
                    "artifact_path": error_path.relative_to(dataset_dir).as_posix(),
                    "updated_at": file_mtime_iso(error_path),
                    "detail": detail,
                },
            )
    return scanned


def read_sample_list(path: Path) -> list[str]:
    """Read, validate, and deduplicate a plain-text sample list."""
    sample_ids = [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    for sample_id in sample_ids:
        validate_path_component(sample_id, "sample ID")
    return list(dict.fromkeys(sample_ids))


def write_sample_list(path: Path, sample_ids: list[str]) -> None:
    """Write a plain-text sample list."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sample_ids) + ("\n" if sample_ids else ""), encoding="utf-8")


def filter_sample_ids(
    sample_ids: list[str],
    ledger: dict[str, dict[str, str]],
    skip_statuses: set[str],
) -> tuple[list[str], list[str]]:
    """Return pending and skipped sample IDs."""
    pending: list[str] = []
    skipped: list[str] = []
    for sample_id in sample_ids:
        row = ledger.get(sample_id)
        if row and row.get("status") in skip_statuses:
            skipped.append(sample_id)
        else:
            pending.append(sample_id)
    return pending, skipped


def main() -> None:
    """Run the selected ledger command."""
    args = parse_args()
    dataset_dir = args.dataset_dir.resolve()
    ledger_path = resolved_ledger_path(args).resolve()

    if args.command == "scan":
        rows = {} if args.replace else read_ledger(ledger_path)
        scanned = scan_dataset(dataset_dir)
        for row in scanned.values():
            upsert(rows, row)
        write_ledger(ledger_path, rows)
        print(
            json.dumps(
                {
                    "status": "ledger_scanned",
                    "ledger_path": str(ledger_path),
                    "scanned": len(scanned),
                    "total": len(rows),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return

    if args.command == "mark":
        rows = read_ledger(ledger_path)
        artifact_path = args.artifact_path
        if artifact_path:
            artifact_path = Path(artifact_path).as_posix()
        upsert(
            rows,
            {
                "sample_id": args.sample_id,
                "category": args.category,
                "status": args.status,
                "source": args.source,
                "artifact_path": artifact_path,
                "updated_at": now_iso(),
                "detail": args.detail,
            },
        )
        write_ledger(ledger_path, rows)
        print(
            json.dumps(
                {
                    "status": "ledger_marked",
                    "ledger_path": str(ledger_path),
                    "sample_id": args.sample_id,
                    "sample_status": args.status,
                    "total": len(rows),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return

    if args.command == "filter":
        skip_statuses = set(args.skip_status or DEFAULT_SKIP_STATUSES)
        ledger = read_ledger(ledger_path)
        sample_ids = read_sample_list(args.sample_list)
        pending, skipped = filter_sample_ids(sample_ids, ledger, skip_statuses)
        if args.output is not None:
            write_sample_list(args.output, pending)
        print(
            json.dumps(
                {
                    "status": "sample_list_filtered",
                    "ledger_path": str(ledger_path),
                    "sample_list": str(args.sample_list),
                    "output": str(args.output) if args.output else "",
                    "category": args.category,
                    "input_samples": len(sample_ids),
                    "skipped": len(skipped),
                    "pending": len(pending),
                    "skip_statuses": sorted(skip_statuses),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return

    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
