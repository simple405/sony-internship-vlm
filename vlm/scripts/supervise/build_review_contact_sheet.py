"""Build local contact sheets for manual supervision review."""

from __future__ import annotations

import argparse
import csv
import json
from math import ceil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps


DEFAULT_REPORT_ROOT = Path(
    "vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/reports/supervision_review/runs"
)
THUMB_SIZE = (260, 260)
CELL_WIDTH = 600
CELL_HEIGHT = 360
LABEL_HEIGHT = 70
PADDING = 18
GAP = 16


def parse_args() -> argparse.Namespace:
    # Note 1: This script is local-only. It reads image paths already present in
    # CSV reports and writes a JPEG/PNG contact sheet; it never calls generation,
    # VLM, or RunningHub APIs.
    parser = argparse.ArgumentParser(description="Build a source/generated image contact sheet for review.")
    parser.add_argument("--review-csv", type=Path, help="Path to human_review_queue.csv or review_summary.csv.")
    parser.add_argument("--run-dir", type=Path, help="Run directory containing tables/*.csv.")
    parser.add_argument("--output", type=Path, help="Output image path. Defaults to run_dir/contact_sheets/review_contact_sheet.jpg.")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--columns", type=int, default=2)
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--decision", action="append", default=[])
    return parser.parse_args()


def resolve_input(args: argparse.Namespace) -> Path:
    # Note 2: Prefer human_review_queue because it reflects the samples a person
    # needs to inspect. review_summary remains supported for broader overview
    # sheets or future model-completed runs.
    if args.review_csv:
        return args.review_csv
    if args.run_dir:
        queue = args.run_dir / "tables" / "human_review_queue.csv"
        if queue.exists():
            return queue
        return args.run_dir / "tables" / "review_summary.csv"
    candidates = sorted(
        DEFAULT_REPORT_ROOT.glob("*/tables/human_review_queue.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise SystemExit("No review CSV found. Pass --review-csv or --run-dir.")
    return candidates[0]


def resolve_output(args: argparse.Namespace, input_path: Path) -> Path:
    if args.output:
        return args.output
    run_dir = input_path.parent.parent
    return run_dir / "contact_sheets" / "review_contact_sheet.jpg"


def read_csv(path: Path) -> list[dict[str, str]]:
    # Note 3: utf-8-sig keeps Excel-edited CSVs readable, and DictReader keeps
    # this script independent of column ordering.
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def normalize_filter(values: list[str]) -> set[str]:
    return {value.strip() for value in values if value.strip()}


def filter_rows(rows: list[dict[str, str]], *, categories: set[str], decisions: set[str], limit: int) -> list[dict[str, str]]:
    # Note 4: Filtering is intentionally simple and exact-match. The CSV already
    # contains normalized category and decision fields from the report writer.
    selected: list[dict[str, str]] = []
    for row in rows:
        if categories and row.get("category", "") not in categories:
            continue
        if decisions and row.get("decision", "") not in decisions:
            continue
        if not row.get("source_image_path") or not row.get("generated_image_path"):
            continue
        selected.append(row)
        if limit > 0 and len(selected) >= limit:
            break
    return selected


def resolve_image_path(raw_path: str, base_dir: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return base_dir / path


def open_thumbnail(path: Path) -> Image.Image:
    # Note 5: ImageOps.contain preserves aspect ratio inside a fixed box. The
    # surrounding white canvas keeps cell sizes stable even for very different
    # source and generated image aspect ratios.
    canvas = Image.new("RGB", THUMB_SIZE, "white")
    with Image.open(path) as image:
        thumbnail = ImageOps.contain(image.convert("RGB"), THUMB_SIZE)
    x = (THUMB_SIZE[0] - thumbnail.width) // 2
    y = (THUMB_SIZE[1] - thumbnail.height) // 2
    canvas.paste(thumbnail, (x, y))
    return canvas


def missing_thumbnail(label: str) -> Image.Image:
    canvas = Image.new("RGB", THUMB_SIZE, "#f5f5f5")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, THUMB_SIZE[0] - 1, THUMB_SIZE[1] - 1), outline="#cc3333", width=3)
    draw.text((12, 16), "missing image", fill="#cc3333")
    draw.text((12, 40), label[:34], fill="#333333")
    return canvas


def draw_wrapped_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, max_chars: int, line_height: int) -> None:
    # Note 6: PIL's default font is reliable but basic. Keeping labels ASCII and
    # wrapping by character count avoids font-dependent width calculations.
    x, y = xy
    chunks = [text[index : index + max_chars] for index in range(0, len(text), max_chars)]
    for chunk in chunks[:3]:
        draw.text((x, y), chunk, fill="#111111")
        y += line_height


def build_cell(row: dict[str, str], base_dir: Path) -> Image.Image:
    cell = Image.new("RGB", (CELL_WIDTH, CELL_HEIGHT), "white")
    draw = ImageDraw.Draw(cell)
    draw.rectangle((0, 0, CELL_WIDTH - 1, CELL_HEIGHT - 1), outline="#d8d8d8")

    source_path = resolve_image_path(row.get("source_image_path", ""), base_dir)
    generated_path = resolve_image_path(row.get("generated_image_path", ""), base_dir)
    try:
        source_thumb = open_thumbnail(source_path)
    except Exception:  # noqa: BLE001
        source_thumb = missing_thumbnail("source")
    try:
        generated_thumb = open_thumbnail(generated_path)
    except Exception:  # noqa: BLE001
        generated_thumb = missing_thumbnail("generated")

    cell.paste(source_thumb, (PADDING, PADDING + LABEL_HEIGHT))
    cell.paste(generated_thumb, (PADDING + THUMB_SIZE[0] + GAP, PADDING + LABEL_HEIGHT))
    draw.text((PADDING, PADDING + LABEL_HEIGHT - 18), "source", fill="#555555")
    draw.text((PADDING + THUMB_SIZE[0] + GAP, PADDING + LABEL_HEIGHT - 18), "generated", fill="#555555")

    label = (
        f"{row.get('sample_id', '')} | {row.get('category', '')} | "
        f"decision={row.get('decision', '')} | expected={row.get('expected_decision', '')}"
    )
    draw_wrapped_text(draw, (PADDING, PADDING), label, max_chars=76, line_height=16)
    return cell


def build_sheet(rows: list[dict[str, str]], base_dir: Path, columns: int) -> Image.Image:
    if not rows:
        sheet = Image.new("RGB", (CELL_WIDTH, 120), "white")
        ImageDraw.Draw(sheet).text((PADDING, PADDING), "No rows selected.", fill="#111111")
        return sheet
    columns = max(1, columns)
    row_count = ceil(len(rows) / columns)
    sheet = Image.new("RGB", (columns * CELL_WIDTH, row_count * CELL_HEIGHT), "#eeeeee")
    for index, row in enumerate(rows):
        cell = build_cell(row, base_dir)
        x = (index % columns) * CELL_WIDTH
        y = (index // columns) * CELL_HEIGHT
        sheet.paste(cell, (x, y))
    return sheet


def main() -> None:
    args = parse_args()
    input_path = resolve_input(args)
    if not input_path.exists():
        raise SystemExit(f"review CSV does not exist: {input_path}")
    rows = read_csv(input_path)
    selected = filter_rows(
        rows,
        categories=normalize_filter(args.category),
        decisions=normalize_filter(args.decision),
        limit=args.limit,
    )
    output_path = resolve_output(args, input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet = build_sheet(selected, Path.cwd(), args.columns)
    sheet.save(output_path)
    print(
        json.dumps(
            {
                "status": "finished",
                "input": str(input_path),
                "output": str(output_path),
                "selected_rows": len(selected),
                "columns": max(1, args.columns),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
