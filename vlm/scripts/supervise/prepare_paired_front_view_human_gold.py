"""Prepare a human-gold annotation package for paired front-view reviews.

The Qwen reviewer output is a proposal, not gold. This script creates an
Excel-friendly package from the pilot results, keeping the model columns
separate from blank human-decision columns. By default it selects every
sample with a rule-level fail, partial, review, or not_evaluable result.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts._paths import VLM_ROOT
from vlm.scripts.generate.generate_paired_front_view import (
    DEFAULT_OUTPUT_ROOT as GENERATION_ROOT,
)
from vlm.scripts.generate.runninghub_client import IMAGE_SUFFIXES
from vlm.scripts._validation import validate_path_component


DEFAULT_REVIEW_ROOT = VLM_ROOT / "tmp" / "paired_front_view_review_v1"
DEFAULT_OUTPUT_ROOT = VLM_ROOT / "tmp" / "paired_front_view_human_gold_v1"
BAD_RESULTS = {"fail", "partial", "review", "not_evaluable"}
HUMAN_RESULTS = {"", "pass", "partial", "fail", "not_evaluable", "review"}
EXTRA_RESULTS = {"", "accept_extra", "reject_extra", "review"}

RULE_COLUMNS = [
    "sample_id",
    "rule_index",
    "element",
    "gold_description",
    "generated_image",
    "original_image",
    "model_result",
    "model_confidence",
    "model_issue_types",
    "model_observed_description",
    "model_reason",
    "human_result",
    "human_issue_types",
    "human_observed_description",
    "human_reason",
    "human_confidence",
    "annotator_id",
    "annotation_batch",
]

EXTRA_COLUMNS = [
    "sample_id",
    "extra_index",
    "element",
    "generated_image",
    "original_image",
    "model_confidence",
    "model_issue_types",
    "model_observed_description",
    "model_reason",
    "human_result",
    "human_reason",
    "annotator_id",
    "annotation_batch",
]

MANIFEST_COLUMNS = [
    "sample_id",
    "generated_image",
    "original_image",
    "gold_json",
    "model_overall_decision",
    "queue_reason",
    "rule_count",
    "extra_count",
    "annotation_status",
]
PACKAGE_OUTPUT_FILES = (
    "human_gold_rules.csv",
    "human_gold_extras.csv",
    "sample_manifest.csv",
    "source_vs_generated_queue.jpg",
    "README.md",
    "batch_summary.json",
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _display_path(path: Path, repo_root: Path) -> str:
    """Prefer workspace-relative paths so the CSV remains portable."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def load_review_queue(
    review_root: Path,
    generation_root: Path,
    requested_ids: list[str] | None = None,
    include_pass: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load predictions and select samples needing human gold.

    Selection is rule-level based. This intentionally catches partial-only
    samples that are absent from the reviewer batch's sample-level fail queue.
    """
    summary_path = review_root / "batch_summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"Reviewer batch summary not found: {summary_path}")
    summary = _read_json(summary_path)
    selected = requested_ids or list(summary.get("selected_sample_ids", []))
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    for sample_id in selected:
        sample_id = validate_path_component(sample_id, "sample ID")
        prediction_path = review_root / sample_id / "prediction.json"
        sample_dir = generation_root / sample_id
        gold_path = sample_dir / f"{sample_id}.json"
        generated_path = next(
            (
                sample_dir / f"{sample_id}_q_front_view{suffix}"
                for suffix in IMAGE_SUFFIXES
                if (sample_dir / f"{sample_id}_q_front_view{suffix}").is_file()
            ),
            None,
        )
        original_candidates = sorted(
            path
            for path in sample_dir.glob(f"{sample_id}_original.*")
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        )
        if (
            not prediction_path.is_file()
            or generated_path is None
            or not gold_path.is_file()
            or not original_candidates
        ):
            missing.append(sample_id)
            continue
        prediction = _read_json(prediction_path)
        bad_rules = [
            rule for rule in prediction.get("rules", [])
            if rule.get("result") in BAD_RESULTS
        ]
        if not include_pass and not bad_rules and prediction.get("overall_decision") == "pass":
            continue
        queue_reason = ";".join(
            sorted({str(rule.get("result")) for rule in bad_rules if rule.get("result")})
        ) or (
            "baseline_pass_calibration"
            if prediction.get("overall_decision") == "pass"
            else "sample_overall_review"
        )
        records.append(
            {
                "sample_id": sample_id,
                "prediction": prediction,
                "gold": _read_json(gold_path),
                "generated_path": generated_path,
                "original_path": original_candidates[0],
                "gold_path": gold_path,
                "queue_reason": queue_reason,
            }
        )
    return records, missing


def build_rows(records: list[dict[str, Any]], repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build rule, extra-element, and sample-manifest rows."""
    rule_rows: list[dict[str, Any]] = []
    extra_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    for record in records:
        prediction = record["prediction"]
        gold = record["gold"]
        rules = prediction.get("rules", [])
        for index, gold_rule in enumerate(gold, start=1):
            model_rule = rules[index - 1] if index - 1 < len(rules) else {}
            rule_rows.append(
                {
                    "sample_id": record["sample_id"],
                    "rule_index": index,
                    "element": gold_rule.get("element", ""),
                    "gold_description": gold_rule.get("description", ""),
                    "generated_image": _display_path(record["generated_path"], repo_root),
                    "original_image": _display_path(record["original_path"], repo_root),
                    "model_result": model_rule.get("result", "review"),
                    "model_confidence": model_rule.get("confidence", ""),
                    "model_issue_types": json.dumps(model_rule.get("issue_types", []), ensure_ascii=False),
                    "model_observed_description": model_rule.get("observed_description", ""),
                    "model_reason": model_rule.get("reason", ""),
                    "human_result": "",
                    "human_issue_types": "",
                    "human_observed_description": "",
                    "human_reason": "",
                    "human_confidence": "",
                    "annotator_id": "",
                    "annotation_batch": "paired_front_view_human_gold_v1",
                }
            )
        for index, raw_extra in enumerate(prediction.get("extra_elements", []), start=1):
            # Qwen sometimes emits a concise string instead of the documented
            # object shape. Keep the candidate visible in the human queue rather
            # than crashing package generation.
            extra = (
                raw_extra
                if isinstance(raw_extra, dict)
                else {
                    "element": str(raw_extra),
                    "confidence": "",
                    "issue_types": ["extra"],
                    "observed_description": "",
                    "reason": "Model emitted a string extra-element candidate.",
                }
            )
            extra_rows.append(
                {
                    "sample_id": record["sample_id"],
                    "extra_index": index,
                    "element": extra.get("element", ""),
                    "generated_image": _display_path(record["generated_path"], repo_root),
                    "original_image": _display_path(record["original_path"], repo_root),
                    "model_confidence": extra.get("confidence", ""),
                    "model_issue_types": json.dumps(extra.get("issue_types", []), ensure_ascii=False),
                    "model_observed_description": extra.get("observed_description", ""),
                    "model_reason": extra.get("reason", ""),
                    "human_result": "",
                    "human_reason": "",
                    "annotator_id": "",
                    "annotation_batch": "paired_front_view_human_gold_v1",
                }
            )
        manifest_rows.append(
            {
                "sample_id": record["sample_id"],
                "generated_image": _display_path(record["generated_path"], repo_root),
                "original_image": _display_path(record["original_path"], repo_root),
                "gold_json": _display_path(record["gold_path"], repo_root),
                "model_overall_decision": prediction.get("overall_decision", "review"),
                "queue_reason": record["queue_reason"],
                "rule_count": len(gold),
                "extra_count": len(prediction.get("extra_elements", [])),
                "annotation_status": "pending",
            }
        )
    return rule_rows, extra_rows, manifest_rows


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    """Write an Excel-compatible CSV atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        with temp.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def validate_rows(rows: list[dict[str, Any]], columns: list[str], *, extra: bool = False) -> list[str]:
    """Validate completed human rows without requiring every row to be filled."""
    issues: list[str] = []
    required = set(columns)
    if not required:
        issues.append("empty_schema")
    for row_number, row in enumerate(rows, start=2):
        if not row.get("sample_id"):
            issues.append(f"row_{row_number}:missing_sample_id")
        if extra:
            if row.get("human_result", "") not in EXTRA_RESULTS:
                issues.append(f"row_{row_number}:invalid_human_result")
        elif row.get("human_result", "") not in HUMAN_RESULTS:
            issues.append(f"row_{row_number}:invalid_human_result")
    return issues


def count_pending_rows(rows: list[dict[str, Any]]) -> int:
    """Count rows that still lack a human verdict."""
    return sum(not str(row.get("human_result", "")).strip() for row in rows)


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("msyh.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def crop_uniform_background(image: Image.Image, padding: int = 8) -> Image.Image:
    """Crop a mostly uniform corner-colored background around a subject."""
    rgb = image.convert("RGB")
    background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
    difference = ImageChops.difference(rgb, background).convert("L")
    difference = difference.point(lambda value: 255 if value > 12 else 0)
    bbox = difference.getbbox()
    if bbox is None:
        return rgb
    left, top, right, bottom = bbox
    return rgb.crop(
        (
            max(0, left - padding),
            max(0, top - padding),
            min(rgb.width, right + padding),
            min(rgb.height, bottom + padding),
        )
    )


def write_contact_sheet(records: list[dict[str, Any]], path: Path) -> None:
    """Write a labeled source/generated sheet for visual human review."""
    cell_w, cell_h, label_h = 480, 270, 34
    cols = 2
    rows = max(1, (len(records) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * cell_w, rows * (cell_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    label_font = _font(16)
    for index, record in enumerate(records):
        x = (index % cols) * cell_w
        y = (index // cols) * (cell_h + label_h)
        with Image.open(record["original_path"]) as image:
            source = crop_uniform_background(image)
        with Image.open(record["generated_path"]) as image:
            generated = crop_uniform_background(image)
        source.thumbnail((cell_w // 2 - 6, cell_h))
        generated.thumbnail((cell_w // 2 - 6, cell_h))
        sheet.paste(source, (x + 4, y + label_h))
        sheet.paste(generated, (x + cell_w // 2 + 2, y + label_h))
        draw.text((x + 6, y + 7), f"{record['sample_id']} [{record['queue_reason']}]", fill="black", font=label_font)
        draw.text((x + 8, y + label_h + cell_h - 20), "source", fill="black", font=_font(12))
        draw.text((x + cell_w // 2 + 8, y + label_h + cell_h - 20), "generated", fill="black", font=_font(12))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        sheet.save(temp, format="JPEG", quality=92)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def write_instructions(path: Path) -> None:
    """Write the human annotation instructions."""
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        "# Paired Front-View Human Gold v1\n\n"
        "这是人工 gold，不是 Qwen 预测。每行必须重新看图后填写。\n\n"
        "## 输入\n"
        "- `original_image`: 原始 2D 角色图，用于核对 gold 描述是否准确。\n"
        "- `generated_image`: RunningHub 生成的 PVC 正面图。\n"
        "- `gold_description`: 本次 reviewer 使用的预标注描述。\n\n"
        "## `human_gold_rules.csv`\n"
        "逐行填写 `human_result`：`pass`、`partial`、`fail`、`not_evaluable` 或 `review`。\n"
        "只记录可见证据；颜色、材质、形状明显不符时在 `human_issue_types` 填逗号分隔值，\n"
        "并在 `human_observed_description` / `human_reason` 写清实际观察。不要复制 model_result。\n\n"
        "## `human_gold_extras.csv`\n"
        "核对生成图中的额外元素：`accept_extra` 表示确实是 gold 未覆盖的显著新增元素，\n"
        "`reject_extra` 表示模型误报或其实已被 gold 覆盖，证据不足填 `review`。\n\n"
        "完成后运行：\n\n"
        "```powershell\n"
        ".\\.venv\\Scripts\\python.exe -m vlm.scripts.supervise.prepare_paired_front_view_human_gold --validate --output-root vlm/tmp/paired_front_view_human_gold_v1\n"
        "```\n\n"
        "未填写的行会被报告为 pending，校验命令返回非零；不要把空白标注直接用于训练。\n",
        encoding="utf-8",
    )
    temp.replace(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def parse_args() -> argparse.Namespace:
    """Parse human-gold package arguments."""
    parser = argparse.ArgumentParser(description="Prepare or validate paired front-view human gold.")
    parser.add_argument("--review-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    parser.add_argument("--generation-root", type=Path, default=GENERATION_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--include-pass", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly replace an existing generated work package.",
    )
    return parser.parse_args()


def main() -> None:
    """Create or validate the paired front-view human-gold package."""
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    if args.validate:
        problems: list[str] = []
        pending: dict[str, int] = {}
        for name, columns, is_extra in (
            ("human_gold_rules.csv", RULE_COLUMNS, False),
            ("human_gold_extras.csv", EXTRA_COLUMNS, True),
        ):
            path = args.output_root / name
            if not path.is_file():
                problems.append(f"missing:{name}")
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames != columns:
                    problems.append(f"schema:{name}")
                rows = list(reader)
                pending[name] = count_pending_rows(rows)
                problems.extend(f"{name}:{item}" for item in validate_rows(rows, columns, extra=is_extra))
        status = "invalid" if problems else ("pending" if any(pending.values()) else "complete")
        summary = {"status": status, "pending_rows": pending, "issues": problems}
        write_json(args.output_root / "validation_summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False))
        if problems or any(pending.values()):
            raise SystemExit(1)
        return

    existing = [
        args.output_root / name
        for name in PACKAGE_OUTPUT_FILES
        if (args.output_root / name).exists()
    ]
    if existing and not args.overwrite:
        raise SystemExit(
            "Human-gold work package already exists; refusing to overwrite possible "
            "manual annotations. Pass --overwrite only after preserving those edits."
        )

    records, missing = load_review_queue(
        args.review_root,
        args.generation_root,
        args.sample_id,
        include_pass=args.include_pass,
    )
    if not records:
        raise SystemExit("No samples need human gold")
    repo_root = Path(__file__).resolve().parents[3]
    rule_rows, extra_rows, manifest_rows = build_rows(records, repo_root)
    summary = {
        "schema_version": "paired_front_view_human_gold_batch.v1",
        "sample_count": len(records),
        "rule_row_count": len(rule_rows),
        "extra_row_count": len(extra_rows),
        "sample_ids": [record["sample_id"] for record in records],
        "missing_sample_ids": missing,
        "selection": (
            "explicit"
            if args.sample_id
            else "all_pilot_calibration" if args.include_pass else "rule_level_bad_results"
        ),
        "human_annotation_required": True,
    }
    args.output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".paired_front_view_human_gold.", dir=args.output_root.parent)
    )
    try:
        write_csv(staging / "human_gold_rules.csv", rule_rows, RULE_COLUMNS)
        write_csv(staging / "human_gold_extras.csv", extra_rows, EXTRA_COLUMNS)
        write_csv(staging / "sample_manifest.csv", manifest_rows, MANIFEST_COLUMNS)
        write_contact_sheet(records, staging / "source_vs_generated_queue.jpg")
        write_instructions(staging / "README.md")
        write_json(staging / "batch_summary.json", summary)
        args.output_root.mkdir(parents=True, exist_ok=True)
        for name in PACKAGE_OUTPUT_FILES:
            (staging / name).replace(args.output_root / name)
        (args.output_root / "validation_summary.json").unlink(missing_ok=True)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(json.dumps({"status": "created", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
