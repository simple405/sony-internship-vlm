"""Run offline supervision review in dry-run mode."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts.supervise.report_writer import write_run_reports  # noqa: E402
from vlm.scripts.supervise.review_schemas import (  # noqa: E402
    ReviewPair,
    ReviewResult,
    RunSummary,
    result_from_dict,
    to_jsonable,
)
from vlm.scripts.supervise.vlm_client import run_vlm_json  # noqa: E402


DEFAULT_DATASET = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20")
DEFAULT_PAIRS = DEFAULT_DATASET / "reports" / "supervision_review" / "latest" / "review_pairs.jsonl"
DEFAULT_PROMPT_DIR = Path("vlm/prompts/supervision")
DEFAULT_REPORT_ROOT = DEFAULT_DATASET / "reports" / "supervision_review" / "runs"


def parse_args() -> argparse.Namespace:
    # Note 1: --pair-json is kept as an alias because the development plan used
    # that name in examples. Internally we normalize both spellings to args.pairs.
    parser = argparse.ArgumentParser(description="Run offline supervision review.")
    parser.add_argument("--pairs", "--pair-json", dest="pairs", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument("--sample-id")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prompt-dir", type=Path, default=DEFAULT_PROMPT_DIR)
    parser.add_argument("--workers", type=int, default=1, help="Accepted for CLI stability; v1 runs sequentially.")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    # Note 2: This reader is strict by design. A malformed pair file means the
    # run would be non-reproducible, so it is better to fail before producing a
    # partial report.
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def read_optional_jsonl(path: Path) -> list[dict[str, Any]]:
    # Note 3: skipped_pairs.jsonl is a companion artifact from collection time.
    # It should enrich reports when present, but older pair files should still
    # run if the skipped file was not generated.
    if not path.exists():
        return []
    return read_jsonl(path)


def load_prompt(prompt_dir: Path, name: str) -> str:
    # Note 4: Prompts are optional for dry-run because no model is called. Real
    # provider mode should probably make missing prompts a hard error.
    path = prompt_dir / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def validate_image(path: Path) -> tuple[bool, str]:
    # Note 5: Image.verify checks that the file can be parsed without loading all
    # pixels into memory. This catches corrupt inputs early while staying cheap
    # enough for batch preflight.
    if not path.exists():
        return False, "missing"
    try:
        with Image.open(path) as image:
            image.verify()
    except Exception as exc:  # noqa: BLE001
        return False, f"open_failed: {exc}"
    return True, ""


def result_path(output_dir: Path, pair: ReviewPair) -> Path:
    # Note 6: Results are nested by category then sample_id so repeated product
    # reviews for the same original do not overwrite one another.
    return output_dir / "results" / pair.category / pair.sample_id / "result.json"


def load_existing_result(path: Path) -> ReviewResult | None:
    # Note 7: Resume mode should be forgiving. If an old result cannot be parsed,
    # the caller will skip adding it to the report rather than crashing the whole
    # run while trying to summarize previous output.
    try:
        return result_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    # Note 8: All result artifacts use pretty JSON because these files are meant
    # for human debugging as well as machine parsing.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_dry_run_result(pair: ReviewPair, output_dir: Path) -> ReviewResult:
    # Note 9: Dry-run keeps seed expectations in metadata but sets the actual
    # decision to not_reviewed. This prevents historical labels from being
    # mistaken for an agent's visual judgment.
    seed_case = pair.seed_case or {}
    expected_decision = seed_case.get("expected_decision", "")
    expected_findings = seed_case.get("expected_findings", [])
    summary = "dry-run 占位结果：未调用真实 VLM，未进行视觉判断。"
    if expected_decision:
        summary += f" seed expected_decision={expected_decision} 仅供人工确认。"
    return ReviewResult(
        sample_id=pair.sample_id,
        category=pair.category,
        decision="not_reviewed",
        score=0,
        risk_level="unreviewed",
        confidence=0.0,
        requires_human_review=True,
        review_status="dry_run_placeholder",
        summary_cn=summary,
        findings=[],
        positive_points=[],
        source_evidence={},
        generated_evidence={},
        metadata={
            # Note 10: Provenance paths are copied into every result so a single
            # result.json remains useful even if moved away from review_pairs.
            "source_image_path": pair.source_image_path,
            "generated_image_path": pair.generated_image_path,
            "generated_candidates": pair.generated_candidates,
            "atomic_rules_path": pair.atomic_rules_path,
            "manifest_row": pair.manifest_row,
            "seed_case": seed_case,
            "expected_findings": expected_findings,
            "result_json_path": str(result_path(output_dir, pair)),
            "dry_run_notice_cn": "该结果不是正式监修结论。",
        },
    )


def run_one(pair: ReviewPair, output_dir: Path, prompt_dir: Path, dry_run: bool) -> ReviewResult:
    # Note 11: run_one is intentionally linear: validate files, run the three
    # conceptual VLM stages, then write one result. Keeping this sequence simple
    # makes it easier to replace dry-run with real provider calls later.
    sample_dir = output_dir / "results" / pair.category / pair.sample_id
    debug_dir = sample_dir / "debug"
    source_path = Path(pair.source_image_path)
    generated_path = Path(pair.generated_image_path)

    for label, image_path in (("source_image", source_path), ("generated_image", generated_path)):
        # Note 12: File validation happens before any VLM call. In real provider
        # mode this avoids spending API budget on samples that cannot be opened.
        ok, reason = validate_image(image_path)
        if not ok:
            raise RuntimeError(f"{label} invalid: {reason}: {image_path}")

    original_prompt = load_prompt(prompt_dir, "original_feature_extractor_cn.txt")
    generated_prompt = load_prompt(prompt_dir, "generated_sheet_parser_cn.txt")
    compare_prompt = load_prompt(prompt_dir, "supervision_compare_cn.txt")
    # Note 13: The three calls mirror the intended agent design: source feature
    # extraction, generated sheet parsing, and pairwise comparison. Dry-run writes
    # placeholders for each stage so the output tree is already stable.
    original_features = run_vlm_json(
        prompt=original_prompt,
        image_paths=[source_path],
        expected_schema_name="original_feature_extraction",
        output_path=sample_dir / "original_features.json",
        debug_dir=debug_dir,
        dry_run=dry_run,
    )
    generated_parse = run_vlm_json(
        prompt=generated_prompt,
        image_paths=[generated_path],
        expected_schema_name="generated_sheet_parsing",
        output_path=sample_dir / "generated_parse.json",
        debug_dir=debug_dir,
        dry_run=dry_run,
    )
    compare_payload = run_vlm_json(
        prompt=compare_prompt,
        image_paths=[source_path, generated_path],
        expected_schema_name="supervision_compare",
        output_path=sample_dir / "compare_findings.json",
        debug_dir=debug_dir,
        dry_run=dry_run,
    )
    result = build_dry_run_result(pair, output_dir)
    result.source_evidence = original_features
    result.generated_evidence = generated_parse
    result.metadata["compare_payload"] = compare_payload
    write_json(result_path(output_dir, pair), to_jsonable(result))
    return result


def main() -> None:
    args = parse_args()
    if args.workers != 1:
        # Note 14: The argument exists so future real-VLM batching can add
        # concurrency without changing command lines. For now, sequential runs
        # keep debug files deterministic.
        print(json.dumps({"status": "warning", "message": "v1 runs sequentially; --workers is ignored"}, ensure_ascii=False))
    if not args.dry_run:
        # Note 15: This is the second hard safety guard, paired with vlm_client.
        # A caller must explicitly implement and approve real provider mode.
        raise SystemExit("v1 only supports --dry-run. Real VLM calls require separate approval and implementation.")
    if not args.pairs.exists():
        raise SystemExit(f"Pairs JSONL does not exist: {args.pairs}")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir or (DEFAULT_REPORT_ROOT / f"{run_id}_dry_run")
    pair_rows = read_jsonl(args.pairs)
    skipped_pairs = read_optional_jsonl(args.pairs.parent / "skipped_pairs.jsonl")
    pairs = [ReviewPair(**row) for row in pair_rows]
    if args.sample_id:
        # Note 16: Single-sample mode is the safest way to inspect a key case
        # such as 2027251 before running a larger seed batch.
        pairs = [pair for pair in pairs if pair.sample_id == args.sample_id]
        if not pairs:
            raise SystemExit(f"sample_id not found in pairs: {args.sample_id}")
    if args.limit > 0:
        pairs = pairs[: args.limit]

    results: list[ReviewResult] = []
    errors: list[dict[str, Any]] = []
    result_paths: dict[tuple[str, str], Path] = {}
    skipped_existing = 0

    for pair in pairs:
        path = result_path(output_dir, pair)
        result_paths[(pair.sample_id, pair.category)] = path
        if path.exists() and not args.force:
            # Note 17: Default resume behavior protects existing review artifacts.
            # Use --force only when intentionally refreshing a run directory.
            skipped_existing += 1
            existing = load_existing_result(path)
            if existing is not None:
                results.append(existing)
            continue
        try:
            results.append(run_one(pair, output_dir, args.prompt_dir, args.dry_run))
        except Exception as exc:  # noqa: BLE001
            # Note 18: Per-sample errors are written beside the expected result
            # location. One bad image should not hide the rest of a batch report.
            error = {
                "sample_id": pair.sample_id,
                "category": pair.category,
                "error": str(exc),
                "source_image_path": pair.source_image_path,
                "generated_image_path": pair.generated_image_path,
            }
            errors.append(error)
            write_json(output_dir / "results" / pair.category / pair.sample_id / "error.json", error)

    summary = RunSummary(
        # Note 19: The run summary is deliberately generated after per-sample
        # processing so it reflects skipped existing results and captured errors.
        run_id=output_dir.name,
        review_status="dry_run_placeholder",
        total_pairs=len(pairs),
        processed=len(results),
        skipped_existing=skipped_existing,
        errors=len(errors),
        output_dir=str(output_dir),
        skipped_pairs=len(skipped_pairs),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_run_reports(
        output_dir=output_dir,
        summary=summary,
        results=results,
        errors=errors,
        result_paths=result_paths,
        skipped_pairs=skipped_pairs,
    )
    print(json.dumps(to_jsonable(summary), ensure_ascii=False))


if __name__ == "__main__":
    main()
