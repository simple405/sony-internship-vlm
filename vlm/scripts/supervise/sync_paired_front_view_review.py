"""Mirror paired front-view reviewer outputs into each sample directory.

The canonical reviewer batch remains under ``vlm/tmp``. This utility creates
an inspectable copy below each generated sample without changing the Phase A
top-level three-file deliverable contract.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from vlm.scripts._paths import VLM_ROOT
from vlm.scripts.generate.generate_paired_front_view import (
    DEFAULT_OUTPUT_ROOT as GENERATION_ROOT,
)
from vlm.scripts._validation import validate_path_component


DEFAULT_REVIEW_ROOT = VLM_ROOT / "tmp" / "paired_front_view_review_v1"
REVIEW_VERSION = "paired_front_view_review_v1"
HUMAN_SAMPLE_FILES = ("qc.csv",)
NOISY_SAMPLE_FILES = (
    "prediction.json",
    "review_prompt.txt",
    "request_preview.json",
    "raw_response.txt",
    "status.json",
    "sync_manifest.json",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def _replace_directory(staged: Path, destination: Path) -> None:
    """Replace a generated directory with rollback if the final rename fails."""
    backup = destination.with_name(destination.name + ".previous")
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        destination.replace(backup)
    try:
        staged.replace(destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def discover_review_ids(review_root: Path) -> list[str]:
    """Return reviewer sample IDs that have a prediction file."""
    sample_ids = sorted(
        validate_path_component(path.parent.name, "sample ID")
        for path in review_root.glob("*/prediction.json")
        if path.is_file()
    )
    return sample_ids


def sync_one(
    sample_id: str,
    review_root: Path,
    generation_root: Path,
    *,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Copy only human-facing review artifacts into one generated sample directory."""
    sample_id = validate_path_component(sample_id, "sample ID")
    source_dir = review_root / sample_id
    sample_dir = generation_root / sample_id
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Reviewer sample directory not found: {source_dir}")
    if not sample_dir.is_dir():
        raise FileNotFoundError(f"Generated sample directory not found: {sample_dir}")
    prediction_path = source_dir / "prediction.json"
    if not prediction_path.is_file():
        raise FileNotFoundError(f"Reviewer prediction not found: {prediction_path}")
    prediction = _read_json(prediction_path)
    required_sources = [source_dir / filename for filename in HUMAN_SAMPLE_FILES]
    missing_sources = [str(path) for path in required_sources if not path.is_file()]
    if missing_sources:
        raise FileNotFoundError(f"Reviewer artifacts not found: {missing_sources}")

    destination = sample_dir / "_review" / REVIEW_VERSION
    destination.mkdir(parents=True, exist_ok=True)

    for source in required_sources:
        target = destination / source.name
        if target.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite: {target}")
    for source in required_sources:
        target = destination / source.name
        temp = target.with_suffix(target.suffix + ".tmp")
        shutil.copy2(source, temp)
        temp.replace(target)

    # Older syncs mirrored every machine artifact into each sample.  Keep the
    # per-sample folder readable by removing those stale noisy files while
    # preserving the human-facing CSV.
    for filename in NOISY_SAMPLE_FILES:
        stale = destination / filename
        if stale.is_file():
            stale.unlink()

    copied = list(HUMAN_SAMPLE_FILES)
    manifest = {
        "schema_version": "paired_front_view_review_sample_sync.v2",
        "sample_id": sample_id,
        "canonical_review_dir": str(source_dir),
        "synced_files": copied,
        "sample_review_dir": str(destination),
        "central_review_dir": str(generation_root / "_review" / REVIEW_VERSION),
        "source_image_used": bool(
            prediction.get("inputs", {}).get("source_image_used", False)
        ),
        "overall_decision": prediction.get("overall_decision", "review"),
    }
    return manifest


def build_central_review_summary(
    review_root: Path,
    generation_root: Path,
    sample_ids: list[str],
    sync_manifests: list[dict[str, Any]],
    failures: list[dict[str, str]],
) -> dict[str, Any]:
    """Write one central, machine-readable review bundle outside sample folders."""
    sample_ids = [validate_path_component(value, "sample ID") for value in sample_ids]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("Duplicate sample IDs are not allowed")
    for sample_id in sample_ids:
        sample_review_dir = review_root / sample_id
        _read_json(sample_review_dir / "prediction.json")
        qc_path = sample_review_dir / "qc.csv"
        if not qc_path.is_file():
            raise FileNotFoundError(f"Reviewer QC file not found: {qc_path}")
        with qc_path.open("r", encoding="utf-8-sig", newline="") as handle:
            if csv.DictReader(handle).fieldnames is None:
                raise ValueError(f"Reviewer QC header is missing: {qc_path}")
        preview_path = sample_review_dir / "request_preview.json"
        if preview_path.is_file():
            _read_json(preview_path)

    central_destination = generation_root / "_review" / REVIEW_VERSION
    central_destination.parent.mkdir(parents=True, exist_ok=True)
    central_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{REVIEW_VERSION}.", dir=central_destination.parent
        )
    )

    qc_rows: list[dict[str, str]] = []
    qc_fields: list[str] = []
    prediction_summary_rows: list[dict[str, Any]] = []
    request_audit_rows: list[dict[str, Any]] = []

    predictions_jsonl = central_dir / "predictions.jsonl"
    with predictions_jsonl.open("w", encoding="utf-8") as predictions_handle:
        for sample_id in sample_ids:
            sample_review_dir = review_root / sample_id
            prediction_path = sample_review_dir / "prediction.json"
            if prediction_path.is_file():
                prediction = _read_json(prediction_path)
                predictions_handle.write(
                    json.dumps(prediction, ensure_ascii=False) + "\n"
                )
                counts = prediction.get("aggregate_counts", {})
                prediction_summary_rows.append(
                    {
                        "sample_id": sample_id,
                        "overall_decision": prediction.get(
                            "overall_decision", "review"
                        ),
                        "pass": counts.get("pass", 0),
                        "partial": counts.get("partial", 0),
                        "fail": counts.get("fail", 0),
                        "not_evaluable": counts.get("not_evaluable", 0),
                        "review": counts.get("review", 0),
                        "source_image_used": bool(
                            prediction.get("inputs", {}).get(
                                "source_image_used", False
                            )
                        ),
                    }
                )

            qc_path = sample_review_dir / "qc.csv"
            if qc_path.is_file():
                with qc_path.open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    if reader.fieldnames and not qc_fields:
                        qc_fields = list(reader.fieldnames)
                    for row in reader:
                        qc_rows.append({"sample_id": sample_id, **row})

            request_preview_path = sample_review_dir / "request_preview.json"
            if request_preview_path.is_file():
                preview = _read_json(request_preview_path)
                request = preview.get("request", {})
                request_audit_rows.append(
                    {
                        "sample_id": sample_id,
                        "generated_image_sha256": preview.get(
                            "generated_image_sha256", ""
                        ),
                        "prompt_sha256": preview.get("prompt_sha256", ""),
                        "gold_element_count": preview.get("gold_element_count", ""),
                        "image_count": request.get("image_count", ""),
                        "source_image_used": bool(
                            preview.get("source_image_used", False)
                        ),
                    }
                )

    qc_all_path = central_dir / "qc_all.csv"
    with qc_all_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["sample_id", *qc_fields] if qc_fields else ["sample_id"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(qc_rows)

    prediction_summary_path = central_dir / "prediction_summary.csv"
    with prediction_summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "sample_id",
            "overall_decision",
            "pass",
            "partial",
            "fail",
            "not_evaluable",
            "review",
            "source_image_used",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(prediction_summary_rows)

    request_audit_path = central_dir / "request_audit.csv"
    with request_audit_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "sample_id",
            "generated_image_sha256",
            "prompt_sha256",
            "gold_element_count",
            "image_count",
            "source_image_used",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(request_audit_rows)

    batch_summary_source = review_root / "batch_summary.json"
    if batch_summary_source.is_file():
        _read_json(batch_summary_source)
        shutil.copy2(batch_summary_source, central_dir / "batch_summary.json")

    summary = {
        "schema_version": "paired_front_view_review_central_sync.v1",
        "sample_count": len(sample_ids),
        "synced_count": len(sync_manifests),
        "failed_count": len(failures),
        "sample_ids": sample_ids,
        "human_sample_files": list(HUMAN_SAMPLE_FILES),
        "central_files": [
            "qc_all.csv",
            "prediction_summary.csv",
            "predictions.jsonl",
            "request_audit.csv",
            *(
                ["batch_summary.json"]
                if (central_dir / "batch_summary.json").is_file()
                else []
            ),
        ],
        "failures": failures,
    }
    _write_json_atomic(central_dir / "sync_summary.json", summary)
    _replace_directory(central_dir, central_destination)
    return summary


def parse_args() -> argparse.Namespace:
    """Parse paired review synchronization arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Copy human-facing reviewer CSVs into sample directories and write "
            "machine artifacts as one central summary bundle."
        )
    )
    parser.add_argument("--review-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    parser.add_argument("--generation-root", type=Path, default=GENERATION_ROOT)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--no-overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    """Synchronize human CSVs and publish the central review bundle."""
    args = parse_args()
    if not args.review_root.is_dir():
        raise SystemExit(f"Reviewer root not found: {args.review_root}")
    sample_ids = args.sample_id or discover_review_ids(args.review_root)
    if not sample_ids:
        raise SystemExit("No reviewer predictions found")

    manifests: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for sample_id in sample_ids:
        try:
            manifest = sync_one(
                sample_id,
                args.review_root,
                args.generation_root,
                overwrite=not args.no_overwrite,
            )
            manifests.append(manifest)
            print(json.dumps({"status": "synced", **manifest}, ensure_ascii=False), flush=True)
        except Exception as exc:
            failures.append(
                {"sample_id": sample_id, "error_type": type(exc).__name__, "error": str(exc)}
            )
            print(json.dumps({"status": "failed", **failures[-1]}, ensure_ascii=False), flush=True)

    synced_ids = [str(manifest["sample_id"]) for manifest in manifests]
    if failures:
        summary = {
            "schema_version": "paired_front_view_review_central_sync.v1",
            "sample_count": len(sample_ids),
            "synced_count": len(manifests),
            "failed_count": len(failures),
            "requested_sample_ids": sample_ids,
            "central_review_updated": False,
            "failures": failures,
        }
        _write_json_atomic(args.review_root / "sync_summary.json", summary)
        raise SystemExit(1)

    summary = build_central_review_summary(
        args.review_root,
        args.generation_root,
        synced_ids,
        manifests,
        failures,
    )
    summary["requested_sample_ids"] = sample_ids
    _write_json_atomic(args.review_root / "sync_summary.json", summary)


if __name__ == "__main__":
    main()
