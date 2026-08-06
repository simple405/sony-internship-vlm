"""Mirror paired front-view reviewer outputs into each sample directory.

The canonical reviewer batch remains under ``vlm/tmp``. This utility creates
an inspectable copy below each generated sample without changing the Phase A
top-level three-file deliverable contract.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from vlm.scripts._paths import VLM_ROOT
from vlm.scripts.generate.generate_paired_front_view import (
    DEFAULT_OUTPUT_ROOT as GENERATION_ROOT,
)


DEFAULT_REVIEW_ROOT = VLM_ROOT / "tmp" / "paired_front_view_review_v1"
REVIEW_FILES = (
    "prediction.json",
    "qc.csv",
    "review_prompt.txt",
    "request_preview.json",
    "raw_response.txt",
    "status.json",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def discover_review_ids(review_root: Path) -> list[str]:
    """Return reviewer sample IDs that have a prediction file."""
    return sorted(
        path.parent.name
        for path in review_root.glob("*/prediction.json")
        if path.is_file()
    )


def sync_one(
    sample_id: str,
    review_root: Path,
    generation_root: Path,
    *,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Copy available review artifacts into one generated sample directory."""
    source_dir = review_root / sample_id
    sample_dir = generation_root / sample_id
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Reviewer sample directory not found: {source_dir}")
    if not sample_dir.is_dir():
        raise FileNotFoundError(f"Generated sample directory not found: {sample_dir}")
    prediction_path = source_dir / "prediction.json"
    if not prediction_path.is_file():
        raise FileNotFoundError(f"Reviewer prediction not found: {prediction_path}")

    destination = sample_dir / "_review" / "paired_front_view_review_v1"
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for filename in REVIEW_FILES:
        source = source_dir / filename
        if not source.is_file():
            continue
        target = destination / filename
        if target.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite: {target}")
        shutil.copy2(source, target)
        copied.append(filename)

    prediction = _read_json(prediction_path)
    manifest = {
        "schema_version": "paired_front_view_review_sync.v1",
        "sample_id": sample_id,
        "canonical_review_dir": str(source_dir),
        "synced_files": copied,
        "source_image_used": bool(
            prediction.get("inputs", {}).get("source_image_used", False)
        ),
        "overall_decision": prediction.get("overall_decision", "review"),
    }
    (destination / "sync_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mirror paired reviewer outputs into generated sample directories."
    )
    parser.add_argument("--review-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    parser.add_argument("--generation-root", type=Path, default=GENERATION_ROOT)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--no-overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
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

    summary = {
        "schema_version": "paired_front_view_review_sync_batch.v1",
        "sample_count": len(sample_ids),
        "synced_count": len(manifests),
        "failed_count": len(failures),
        "sample_ids": sample_ids,
        "failures": failures,
    }
    (args.review_root / "sync_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
