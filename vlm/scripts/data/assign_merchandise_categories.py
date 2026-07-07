"""Assign Safebooru character images to merchandise generation categories."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


DEFAULT_DATASET = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20")

# Note 1: Keep category names stable because reports, sample lists, prompts, and
# generated output folders all use these strings as a shared data contract.
CATEGORIES = [
    "head_key_chain",
    "cake_roll",
    "backpack",
    "plush",
    "dataset_QSitFigures",
    "dataset_figurine",
]

HEAD_ONLY_CATEGORIES = ("head_key_chain", "cake_roll", "backpack")
FULL_BODY_CATEGORIES = ("plush", "dataset_QSitFigures", "dataset_figurine")
FRONT_VIEW_TAGS = ("looking_at_viewer", "facing_viewer", "front_view", "from_front")

GENERATED_CATEGORY_DIRS = {
    "head_key_chain": Path("runninghub/head_key_chain"),
    "backpack": Path("runninghub/backpack"),
    "cake_roll": Path("runninghub/cake_roll"),
    "plush": Path("runninghub/plush"),
    "dataset_figurine": Path("runninghub/dataset_figurine"),
    "dataset_QSitFigures": Path("runninghub/dataset_QSitFigures"),
}

# Note 2: CSV column order is declared once so downstream spreadsheet work and
# scripts can rely on predictable headers even if row assembly changes later.
OUTPUT_COLUMNS = [
    "sample_id",
    "primary_category",
    "candidate_categories",
    "already_generated_category",
    "assignment_source",
    "image_path",
    "crawl_label",
    "score_head_key_chain",
    "score_cake_roll",
    "score_backpack",
    "score_plush",
    "score_dataset_QSitFigures",
    "score_dataset_figurine",
    "primary_score",
    "reason",
    "key_tags",
    "width",
    "height",
    "colorfulness",
]


def parse_args() -> argparse.Namespace:
    # Note 3: Defaults are relative to the repository root; run this script from
    # the workspace root unless every path is passed explicitly.
    parser = argparse.ArgumentParser(description="Classify character images into merchandise categories.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_DATASET / "reports" / "merchandise_category_assignment",
    )
    parser.add_argument("--contact-sheet-limit", type=int, default=40)
    return parser.parse_args()


def read_manifest(path: Path) -> dict[str, dict[str, str]]:
    # Note 4: utf-8-sig tolerates CSV files opened and re-saved by Excel, which
    # may prepend a byte-order mark before the first header name.
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sample_id = str(row.get("post_id") or "").strip()
            if sample_id:
                rows[sample_id] = row
    return rows


def sample_id_from_image(path: Path) -> str:
    # Note 5: Safebooru image filenames start with the numeric post id; keeping
    # only that prefix lets generated assets and manifest rows join reliably.
    return path.name.split("_", 1)[0]


def discover_image_files(image_dir: Path) -> dict[str, Path]:
    # Note 6: setdefault keeps the first sorted file for duplicate ids, making
    # the choice deterministic instead of depending on filesystem order.
    images: dict[str, Path] = {}
    for path in sorted(image_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            images.setdefault(sample_id_from_image(path), path)
    return images


def discover_generated(dataset_dir: Path) -> dict[str, str]:
    # Note 7: Existing generated output wins over score-based assignment later,
    # so this scan protects completed samples from being moved between queues.
    generated_root = dataset_dir / "generated"
    generated: dict[str, str] = {}
    for category, rel_path in GENERATED_CATEGORY_DIRS.items():
        category_dir = generated_root / rel_path
        if not category_dir.exists():
            continue
        for child in category_dir.iterdir():
            if child.is_dir() and not child.name.startswith("_"):
                generated[child.name] = category
    return generated


def token_set(row: dict[str, str]) -> set[str]:
    # Note 8: Tags are stored as a whitespace-separated string in the manifest.
    # Converting to a set makes each heuristic a fast membership check.
    return set(str(row.get("tags") or "").split())


def has(tokens: set[str], *values: str) -> bool:
    # Note 9: The helper reads like a small rule language inside score_row,
    # which keeps the scoring section easier to audit than repeated any(...) calls.
    return any(value in tokens for value in values)


def as_float(value: Any) -> float:
    # Note 10: Metadata can be missing or string-typed; invalid values become 0
    # so later numeric heuristics can stay simple and non-crashing.
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def has_front_view(tokens: set[str]) -> bool:
    return has(tokens, *FRONT_VIEW_TAGS)


def score_row(row: dict[str, str]) -> tuple[OrderedDict[str, int], list[str]]:
    # Note 11: This function is intentionally heuristic rather than learned. It
    # should be easy for a maintainer to explain or tune one rule at a time.
    tokens = token_set(row)
    width = as_float(row.get("actual_width") or row.get("width"))
    height = as_float(row.get("actual_height") or row.get("height"))
    colorfulness = as_float(row.get("colorfulness"))

    # Note 12: Boolean feature flags separate "what the image contains" from
    # "how each merchandise category should react to that feature".
    full_body = has(tokens, "full_body")
    front_view = has_front_view(tokens)
    standing = has(tokens, "standing")
    sitting = has(tokens, "sitting", "kneeling", "crouching")
    multi_view = has(tokens, "multiple_views", "turnaround", "character_sheet", "from_side", "from_behind", "profile")
    simple_bg = has(tokens, "transparent_background", "simple_background", "white_background")
    weapon = has(tokens, "weapon", "holding_weapon", "sword", "gun", "rifle", "polearm", "spear", "scythe")
    armor = has(tokens, "armor", "armored_boots", "greaves", "helmet")
    appendage = has(tokens, "wings", "wing", "tail", "horns", "animal_ears", "pointy_ears")
    head_feature = has(
        tokens,
        "hat",
        "hair_ornament",
        "hair_ribbon",
        "hair_bow",
        "bow",
        "ribbon",
        "animal_ears",
        "horns",
        "pointy_ears",
        "twintails",
        "ponytail",
        "braid",
        "ahoge",
        "hair_flower",
        "crown",
    )
    outfit = has(tokens, "dress", "skirt", "jacket", "uniform", "kimono", "cape", "boots", "gloves", "shirt", "pants")
    cute = has(tokens, "smile", "chibi", "blush", "closed_mouth", "open_mouth")
    official = has(tokens, "official_art", "character_sheet", "tachi-e")
    text_noise = has(tokens, "speech_bubble", "text", "commentary", "translation_request")
    adult_risk = has(tokens, "large_breasts", "cleavage", "bikini", "swimsuit", "covered_nipples")

    # Note 13: Every category starts with the same small baseline so negative
    # penalties can demote poor fits without removing a category completely.
    scores: OrderedDict[str, int] = OrderedDict((category, 10) for category in CATEGORIES)
    reasons: list[str] = []

    if has(tokens, "solo"):
        # Note 14: Solo character images are useful for every product type
        # because there is less ambiguity about the target identity.
        for category in scores:
            scores[category] += 8
        reasons.append("solo")
    if simple_bg:
        # Note 15: Clean backgrounds make cutout-like products easier, with
        # cake_roll getting an extra boost because background clutter hurts it most.
        for category in scores:
            scores[category] += 5
        scores["cake_roll"] += 6
        reasons.append("clean_background")
    else:
        # Note 16: Non-simple backgrounds are not fatal, but they reduce product
        # types that need a clean silhouette or small readable character art.
        scores["cake_roll"] -= 25
        scores["backpack"] -= 8
        scores["plush"] -= 12
    if colorfulness >= 50:
        # Note 17: Colorful references tend to preserve identity better during
        # generation, so all categories get a small shared lift.
        for category in scores:
            scores[category] += 3
        reasons.append("color_reference")

    if full_body:
        # Note 18: Full-body references are especially important for products
        # where pose, legs, shoes, and outfit proportions must survive.
        for category in ("backpack", "plush", "dataset_QSitFigures", "dataset_figurine"):
            scores[category] += 18
        scores["head_key_chain"] += 4
        scores["cake_roll"] += 8
        reasons.append("full_body")
    else:
        # Note 19: Cropped or bust images are more suitable for head-focused
        # goods, while body-dependent outputs are penalized.
        for category in ("backpack", "plush", "dataset_QSitFigures", "dataset_figurine"):
            scores[category] -= 18
        scores["head_key_chain"] += 14
        scores["cake_roll"] += 12
        reasons.append("not_full_body")

    if standing:
        # Note 20: Standing poses are a strong plush signal because plush outputs
        # expect a readable front-facing body and stable feet.
        scores["plush"] += 18
        scores["dataset_figurine"] += 10
        scores["backpack"] += 8
        reasons.append("standing")
    elif full_body:
        # Note 21: A full body that is not standing may still work, but plush is
        # less likely to produce a clean upright product.
        scores["plush"] -= 15
    if sitting:
        # Note 22: Sitting and crouching poses are routed toward QSitFigures and
        # away from plush because the target product pose is different.
        scores["dataset_QSitFigures"] += 25
        scores["plush"] -= 25
        scores["dataset_figurine"] -= 8
        reasons.append("sitting_pose")
    if multi_view:
        # Note 23: Turnaround or character-sheet tags are valuable references for
        # almost every generation prompt, so the boost is broad.
        scores["plush"] += 14
        scores["head_key_chain"] += 12
        scores["backpack"] += 10
        scores["cake_roll"] += 10
        scores["dataset_figurine"] += 8
        scores["dataset_QSitFigures"] += 6
        reasons.append("multi_view_reference")
    if head_feature:
        # Note 24: Distinctive hair, hats, ears, horns, and ornaments help
        # head-focused products stay recognizable at small sizes.
        scores["head_key_chain"] += 20
        scores["cake_roll"] += 18
        scores["backpack"] += 10
        scores["plush"] += 8
        scores["dataset_QSitFigures"] += 5
        reasons.append("distinctive_head")
    if outfit:
        # Note 25: Outfit tags help products where the whole costume needs to
        # remain visible, especially backpack, plush, and figurine categories.
        scores["backpack"] += 18
        scores["plush"] += 10
        scores["dataset_figurine"] += 9
        scores["dataset_QSitFigures"] += 7
        reasons.append("outfit_reference")
    if weapon:
        # Note 26: Weapons and large props are treated as figurine-friendly but
        # risky for softer or compact goods.
        scores["dataset_figurine"] += 28
        scores["backpack"] -= 8
        scores["cake_roll"] -= 30
        scores["plush"] -= 12
        scores["dataset_QSitFigures"] -= 10
        reasons.append("weapon_or_prop")
    if armor or appendage:
        # Note 27: Armor, wings, tails, and horns are identity-heavy details; the
        # figurine prompt can usually preserve them better than compact goods.
        scores["dataset_figurine"] += 18
        scores["head_key_chain"] += 6
        scores["backpack"] -= 8
        scores["cake_roll"] -= 24
        scores["plush"] -= 6
        reasons.append("complex_identity_feature")
    if cute:
        # Note 28: Cute expressions often match sitting figure, cake roll, and
        # plush aesthetics, so this feature nudges those categories upward.
        scores["dataset_QSitFigures"] += 12
        scores["cake_roll"] += 10
        scores["head_key_chain"] += 6
        scores["plush"] += 7
        reasons.append("cute_expression")
    if official:
        # Note 29: Official art and character sheets tend to be cleaner reference
        # material, so body-dependent products receive a modest bonus.
        scores["dataset_figurine"] += 8
        scores["plush"] += 5
        scores["backpack"] += 5
        reasons.append("official_or_sheet")
    if not weapon and not armor and not appendage and head_feature and simple_bg:
        # Note 30: This compound rule captures simple head-goods candidates that
        # might not reach cake_roll through any single feature alone.
        scores["cake_roll"] += 16
        reasons.append("simple_head_goods_candidate")
    if has(tokens, "1boy", "male_focus"):
        scores["dataset_figurine"] += 4
        scores["plush"] += 2
    if adult_risk:
        # Note 31: Sensitive body-related tags make full-body products less
        # desirable; head-focused outputs are comparatively safer.
        scores["plush"] -= 8
        scores["dataset_QSitFigures"] -= 3
        scores["backpack"] -= 4
        scores["cake_roll"] -= 20
        reasons.append("prefer_head_goods_for_sensitive_body")
    if text_noise:
        # Note 32: Text and speech bubbles can be copied into generated images,
        # so all categories are penalized and cake_roll is penalized further.
        for category in scores:
            scores[category] -= 5
        scores["cake_roll"] -= 10
        reasons.append("text_noise")
    if width and height:
        # Note 33: Aspect ratio is a weak hint only. It nudges borderline cases
        # without overpowering semantic tags from the manifest.
        ratio = width / height
        if ratio > 1.35:
            scores["plush"] += 4
            scores["head_key_chain"] += 3
            scores["backpack"] += 3
        elif ratio < 0.85:
            scores["dataset_figurine"] += 4
            scores["dataset_QSitFigures"] += 3

    if not full_body or not front_view:
        # Note 34: Full-body product prompts need the whole body and a usable
        # front-facing reference. Cropped or side/back-only images are still
        # useful, but only for the head-only generation lane.
        for category in FULL_BODY_CATEGORIES:
            scores[category] = min(scores[category], -100)
        for category in HEAD_ONLY_CATEGORIES:
            scores[category] += 25
        reasons.append("head_only_only_not_full_body" if not full_body else "head_only_only_no_front_view")

    return scores, reasons


def key_tags(row: dict[str, str]) -> str:
    # Note 35: key_tags is a compact audit column; it records the tags most
    # likely to explain the category decision without copying the full tag list.
    tokens = token_set(row)
    useful = [
        "full_body",
        "looking_at_viewer",
        "facing_viewer",
        "front_view",
        "from_front",
        "standing",
        "sitting",
        "multiple_views",
        "turnaround",
        "character_sheet",
        "official_art",
        "transparent_background",
        "simple_background",
        "weapon",
        "armor",
        "wings",
        "tail",
        "horns",
        "animal_ears",
        "hat",
        "hair_ornament",
        "twintails",
        "ponytail",
        "braid",
        "dress",
        "uniform",
        "jacket",
        "1boy",
        "1girl",
    ]
    return " ".join(tag for tag in useful if tag in tokens)


def candidate_categories(scores: OrderedDict[str, int]) -> list[str]:
    # Note 35: Candidate categories provide fallback options for manual review or
    # future batching when the top category is blocked or already saturated.
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    candidates = [category for category, score in ranked if score >= 60]
    if len(candidates) < 3:
        # Note 36: Always keep at least three choices so spreadsheet review has
        # alternatives even when every score is below the confidence threshold.
        for category, _score in ranked:
            if category not in candidates:
                candidates.append(category)
            if len(candidates) >= 3:
                break
    return candidates[:4]


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    # Note 37: newline="" is the csv module's recommended mode; it avoids extra
    # blank lines on Windows when writing CSV files.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def make_contact_sheet(rows: list[dict[str, Any]], output_path: Path, limit: int) -> None:
    # Note 38: Contact sheets are lightweight visual QA. They let maintainers
    # spot bad assignments without opening hundreds of individual images.
    selected = rows[:limit]
    if not selected:
        return
    # Note 39: Fixed cell dimensions keep every sheet comparable across runs and
    # prevent one tall image from changing the whole grid layout.
    cell_w, cell_h = 220, 270
    cols = 5
    rows_count = (len(selected) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows_count * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, row in enumerate(selected):
        # Note 40: Each row has an image preview plus the assigned category and
        # score, which is enough context for quick manual triage.
        x = (index % cols) * cell_w
        y = (index // cols) * cell_h
        image_path = Path(str(row["image_path"]))
        try:
            # Note 41: thumbnail mutates the image in place while preserving
            # aspect ratio, so pasted previews never overflow the grid cell.
            with Image.open(image_path) as image:
                image = image.convert("RGB")
                image.thumbnail((cell_w - 16, cell_h - 44), Image.Resampling.LANCZOS)
                px = x + (cell_w - image.width) // 2
                py = y + 8
                sheet.paste(image, (px, py))
        except Exception:
            # Note 42: A red placeholder keeps the sheet generation resilient
            # even if a source image is missing or unreadable.
            draw.rectangle((x + 8, y + 8, x + cell_w - 8, y + cell_h - 44), outline="red")
        label = f"{row['sample_id']}  {row['primary_category']}"
        draw.text((x + 8, y + cell_h - 32), label[:34], fill="black", font=font)
        draw.text((x + 8, y + cell_h - 18), f"score {row['primary_score']}", fill="black", font=font)
        draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), outline="#cccccc")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=92)


def main() -> None:
    # Note 43: main coordinates three outputs: the full assignment CSV, per-
    # category sample lists, and visual contact sheets for review.
    # The function avoids hidden global mutation so it can be rerun safely.
    args = parse_args()
    dataset_dir = args.dataset_dir
    output_dir = args.output_dir
    manifest_rows = read_manifest(dataset_dir / "manifest.csv")
    image_files = discover_image_files(dataset_dir / "image")
    generated = discover_generated(dataset_dir)

    # Note 44: output_rows is the single in-memory table from which all report
    # artifacts are derived, keeping summaries and sample lists consistent.
    output_rows: list[dict[str, Any]] = []
    for sample_id in sorted(image_files):
        # Note 45: Sorting sample ids makes regenerated CSVs stable and easier
        # to diff after a scoring-rule change.
        manifest = dict(manifest_rows.get(sample_id) or {})
        manifest.setdefault("post_id", sample_id)
        manifest.setdefault("image_path", str(image_files[sample_id]).replace("\\", "/"))
        if Path(manifest["image_path"]).is_absolute():
            image_path = Path(manifest["image_path"])
        else:
            image_path = Path(manifest["image_path"])
        scores, reasons = score_row(manifest)
        generated_category = generated.get(sample_id, "")
        # Note 46: Existing generated assets override the heuristic category so
        # finished work is not accidentally re-queued somewhere else.
        primary_category = generated_category or max(scores, key=lambda category: scores[category])
        assignment_source = "existing_generated_output" if generated_category else "rule_score"
        candidates = candidate_categories(scores)
        if primary_category not in candidates:
            candidates.insert(0, primary_category)
        primary_score = scores[primary_category]
        output_rows.append(
            {
                "sample_id": sample_id,
                "primary_category": primary_category,
                "candidate_categories": "|".join(candidates),
                "already_generated_category": generated_category,
                "assignment_source": assignment_source,
                "image_path": str(image_path),
                "crawl_label": manifest.get("crawl_label", ""),
                "score_head_key_chain": scores["head_key_chain"],
                "score_cake_roll": scores["cake_roll"],
                "score_backpack": scores["backpack"],
                "score_plush": scores["plush"],
                "score_dataset_QSitFigures": scores["dataset_QSitFigures"],
                "score_dataset_figurine": scores["dataset_figurine"],
                "reason": ";".join(reasons),
                "key_tags": key_tags(manifest),
                "width": manifest.get("actual_width") or manifest.get("width", ""),
                "height": manifest.get("actual_height") or manifest.get("height", ""),
                "colorfulness": manifest.get("colorfulness", ""),
                "primary_score": primary_score,
            }
        )

    output_rows.sort(key=lambda row: (row["primary_category"], -int(row["primary_score"]), row["sample_id"]))
    # Note 47: Sorting by category then score puts the strongest pending samples
    # near the top of each list and contact sheet.
    write_csv(output_dir / "merchandise_category_assignments.csv", output_rows, OUTPUT_COLUMNS)

    summary_rows = []
    category_counts = Counter(row["primary_category"] for row in output_rows)
    generated_counts = Counter(row["already_generated_category"] for row in output_rows if row["already_generated_category"])
    for category in CATEGORIES:
        # Note 48: Sample lists intentionally contain only rows without existing
        # generated output, so batch scripts can treat them as pending queues.
        category_rows = [row for row in output_rows if row["primary_category"] == category]
        ungenerated_rows = [row for row in category_rows if not row["already_generated_category"]]
        list_dir = output_dir / "sample_lists"
        list_dir.mkdir(parents=True, exist_ok=True)
        (list_dir / f"{category}.txt").write_text(
            # Note 49: One id per line keeps the list easy for PowerShell, Python,
            # and manual editing. A trailing newline is added when the file is non-empty.
            "\n".join(str(row["sample_id"]) for row in ungenerated_rows) + ("\n" if ungenerated_rows else ""),
            encoding="utf-8",
        )
        make_contact_sheet(
            ungenerated_rows,
            output_dir / "contact_sheets" / f"{category}_top_{args.contact_sheet_limit}.jpg",
            args.contact_sheet_limit,
        )
        summary_rows.append(
            # Note 50: The summary links each category to both its machine queue
            # and its visual contact sheet, which helps future handoffs.
            {
                "category": category,
                "primary_total": category_counts[category],
                "already_generated": generated_counts[category],
                "remaining_to_generate": len(ungenerated_rows),
                "sample_list": str(list_dir / f"{category}.txt"),
                "contact_sheet": str(output_dir / "contact_sheets" / f"{category}_top_{args.contact_sheet_limit}.jpg"),
            }
        )
    write_csv(
        output_dir / "category_summary.csv",
        summary_rows,
        ["category", "primary_total", "already_generated", "remaining_to_generate", "sample_list", "contact_sheet"],
    )
    print(json.dumps({"status": "ok", "rows": len(output_rows), "output_dir": str(output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
