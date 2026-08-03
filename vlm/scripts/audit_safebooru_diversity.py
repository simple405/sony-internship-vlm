"""Audit Safebooru images for duplicates, repeated identities, and element diversity."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from PIL import Image


DEFAULT_ROOT = Path("vlm/data/safebooru_2d")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
IDENTITY_RULE_PREFIXES = (
    "hair_",
    "eye_",
    "headwear_",
    "head_accessory",
    "horn_",
    "mouth_",
    "expression",
    "top_",
    "bottom_",
    "dress_",
    "skirt_",
    "pants_",
    "coat_",
    "jacket_",
    "outfit_",
    "footwear_",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Safebooru dataset diversity and duplicate risk.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--image-root", type=Path, default=None)
    parser.add_argument("--atomic-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--near-threshold", type=int, default=5, help="dHash Hamming distance threshold for near duplicates.")
    parser.add_argument("--max-near-pairs", type=int, default=5000)
    parser.add_argument("--contact-sheet-limit", type=int, default=80)
    return parser.parse_args()


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle) if row.get("post_id")]


def sample_id_from_image(path: Path) -> str:
    return path.stem.split("_", 1)[0]


def discover_images(image_root: Path) -> dict[str, Path]:
    return {
        sample_id_from_image(path): path
        for path in sorted(image_root.iterdir())
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    }


def resolve_image(row: dict[str, str], image_root: Path, image_by_id: dict[str, Path]) -> Path | None:
    sample_id = str(row["post_id"])
    candidate = Path(row.get("image_path", ""))
    if candidate and not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if candidate.exists():
        return candidate
    fallback = image_root / candidate.name
    if fallback.exists():
        return fallback
    return image_by_id.get(sample_id)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dhash(path: Path) -> int:
    with Image.open(path) as image:
        gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(gray.getdata())
    value = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            value = (value << 1) | int(left > right)
    return value


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def atomic_path(atomic_root: Path, sample_id: str) -> Path | None:
    sample_dir = atomic_root / sample_id
    current = sample_dir / "atomic_rules.json"
    if current.exists():
        return current
    legacy = sample_dir / f"{sample_id}_atomic_rules.json"
    return legacy if legacy.exists() else None


def load_atomic_rules(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rules = data.get("atomic_rules", [])
    return [rule for rule in rules if isinstance(rule, dict)]


def identity_signature_from_rules(rules: list[dict[str, Any]]) -> str:
    pairs = []
    for rule in rules:
        rule_id = str(rule.get("id", ""))
        if rule_id == "expression" or rule_id.startswith(IDENTITY_RULE_PREFIXES):
            value = str(rule.get("value", "")).strip()
            if value:
                pairs.append(f"{rule_id}={value}")
    return "|".join(sorted(pairs))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def make_near_duplicate_contact_sheet(
    near_rows: list[dict[str, Any]],
    records_by_id: dict[str, dict[str, Any]],
    output_path: Path,
    limit: int,
) -> None:
    if not near_rows or limit <= 0:
        return
    selected = near_rows[:limit]
    cell_w, cell_h = 360, 190
    cols = 2
    rows = (len(selected) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    from PIL import ImageDraw, ImageFont

    drawer = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, pair in enumerate(selected):
        x = (index % cols) * cell_w
        y = (index // cols) * cell_h
        sample_ids = [str(pair["sample_a"]), str(pair["sample_b"])]
        for offset, sample_id in enumerate(sample_ids):
            record = records_by_id.get(sample_id)
            if not record:
                continue
            image_path = Path(str(record["image_path"]))
            try:
                with Image.open(image_path) as image:
                    image = image.convert("RGB")
                    image.thumbnail((155, 145), Image.Resampling.LANCZOS)
                    px = x + 12 + offset * 170 + (155 - image.width) // 2
                    py = y + 8 + (145 - image.height) // 2
                    sheet.paste(image, (px, py))
            except Exception:  # noqa: BLE001
                drawer.rectangle((x + 12 + offset * 170, y + 8, x + 167 + offset * 170, y + 153), outline="red")
            drawer.text((x + 12 + offset * 170, y + 158), sample_id, fill="black", font=font)
        drawer.text((x + 12, y + 174), f"dHash distance: {pair['hamming_distance']}", fill="black", font=font)
        drawer.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), outline="#cccccc")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=92)


def main() -> None:
    args = parse_args()
    root = args.root
    manifest_path = args.manifest or root / "manifest.csv"
    image_root = args.image_root or root / "image"
    atomic_root = args.atomic_root or root / "atomic_rules"
    output_dir = args.output_dir or root / "reports" / "diversity_audit"
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = read_manifest(manifest_path)
    image_by_id = discover_images(image_root)

    records: list[dict[str, Any]] = []
    exact_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dhashes: list[tuple[str, int]] = []
    signature_groups: dict[str, list[str]] = defaultdict(list)
    atomic_signature_groups: dict[str, list[str]] = defaultdict(list)
    tag_counter: Counter[str] = Counter()
    rule_counter: Counter[str] = Counter()
    rule_value_counter: Counter[tuple[str, str]] = Counter()
    missing_images: list[str] = []

    for row in rows:
        sample_id = str(row["post_id"])
        image_path = resolve_image(row, image_root, image_by_id)
        if image_path is None:
            missing_images.append(sample_id)
            continue
        image_hash = sha256(image_path)
        exact_groups[image_hash].append({"sample_id": sample_id, "image_path": str(image_path)})
        try:
            image_dhash = dhash(image_path)
            dhashes.append((sample_id, image_dhash))
        except Exception:  # noqa: BLE001
            image_dhash = None

        tags = [tag for tag in str(row.get("tags", "")).split() if tag]
        tag_counter.update(tags)
        character_signature = str(row.get("character_signature", "")).strip()
        if character_signature:
            signature_groups[character_signature].append(sample_id)

        rules = load_atomic_rules(atomic_path(atomic_root, sample_id))
        for rule in rules:
            rule_id = str(rule.get("id", ""))
            value = str(rule.get("value", ""))
            if rule_id:
                rule_counter[rule_id] += 1
                rule_value_counter[(rule_id, value)] += 1
        atomic_signature = identity_signature_from_rules(rules)
        if atomic_signature:
            atomic_signature_groups[atomic_signature].append(sample_id)

        records.append({
            "sample_id": sample_id,
            "image_path": str(image_path),
            "sha256": image_hash,
            "dhash": f"{image_dhash:016x}" if image_dhash is not None else "",
            "character_signature": character_signature,
            "tag_count": len(tags),
            "atomic_rule_count": len(rules),
        })

    duplicate_rows = []
    for group_id, (digest, items) in enumerate((item for item in exact_groups.items() if len(item[1]) > 1), start=1):
        for item in items:
            duplicate_rows.append({"group_id": group_id, "sha256": digest, **item})

    near_rows = []
    for index, (sample_a, hash_a) in enumerate(dhashes):
        for sample_b, hash_b in dhashes[index + 1:]:
            distance = hamming(hash_a, hash_b)
            if distance <= args.near_threshold:
                near_rows.append({"sample_a": sample_a, "sample_b": sample_b, "hamming_distance": distance})
                if len(near_rows) >= args.max_near_pairs:
                    break
        if len(near_rows) >= args.max_near_pairs:
            break

    signature_rows = [
        {"signature_type": "manifest_character_signature", "signature": signature, "sample_count": len(sample_ids), "sample_ids": " ".join(sample_ids[:50])}
        for signature, sample_ids in sorted(signature_groups.items(), key=lambda item: (-len(item[1]), item[0]))
        if len(sample_ids) > 1
    ]
    atomic_signature_rows = [
        {"signature_type": "atomic_identity_signature", "signature": signature[:500], "sample_count": len(sample_ids), "sample_ids": " ".join(sample_ids[:50])}
        for signature, sample_ids in sorted(atomic_signature_groups.items(), key=lambda item: (-len(item[1]), item[0]))
        if len(sample_ids) > 1
    ]

    write_csv(output_dir / "sample_image_audit.csv", records, ["sample_id", "image_path", "sha256", "dhash", "character_signature", "tag_count", "atomic_rule_count"])
    write_csv(output_dir / "exact_duplicate_groups.csv", duplicate_rows, ["group_id", "sha256", "sample_id", "image_path"])
    write_csv(output_dir / "near_duplicate_pairs.csv", near_rows, ["sample_a", "sample_b", "hamming_distance"])
    write_csv(output_dir / "same_identity_signature_groups.csv", signature_rows + atomic_signature_rows, ["signature_type", "signature", "sample_count", "sample_ids"])
    write_csv(
        output_dir / "element_frequency.csv",
        [
            {"rule_id": rule_id, "value": value, "count": count}
            for (rule_id, value), count in rule_value_counter.most_common()
        ],
        ["rule_id", "value", "count"],
    )
    write_csv(
        output_dir / "tag_frequency.csv",
        [{"tag": tag, "count": count} for tag, count in tag_counter.most_common()],
        ["tag", "count"],
    )
    contact_sheet = output_dir / "near_duplicate_contact_sheet.jpg"
    make_near_duplicate_contact_sheet(
        near_rows,
        {str(record["sample_id"]): record for record in records},
        contact_sheet,
        args.contact_sheet_limit,
    )

    summary = {
        "schema_version": "safebooru_diversity_audit.v1",
        "sample_count": len(rows),
        "resolved_images": len(records),
        "missing_images": len(missing_images),
        "exact_duplicate_groups": sum(1 for items in exact_groups.values() if len(items) > 1),
        "exact_duplicate_samples": len(duplicate_rows),
        "near_duplicate_pairs": len(near_rows),
        "near_duplicate_threshold": args.near_threshold,
        "same_manifest_signature_groups": len(signature_rows),
        "same_atomic_identity_signature_groups": len(atomic_signature_rows),
        "unique_tags": len(tag_counter),
        "unique_rule_ids": len(rule_counter),
        "atomic_rule_samples": sum(1 for record in records if record["atomic_rule_count"] > 0),
        "outputs": {
            "sample_image_audit": str(output_dir / "sample_image_audit.csv"),
            "exact_duplicate_groups": str(output_dir / "exact_duplicate_groups.csv"),
            "near_duplicate_pairs": str(output_dir / "near_duplicate_pairs.csv"),
            "same_identity_signature_groups": str(output_dir / "same_identity_signature_groups.csv"),
            "element_frequency": str(output_dir / "element_frequency.csv"),
            "tag_frequency": str(output_dir / "tag_frequency.csv"),
            "near_duplicate_contact_sheet": str(contact_sheet),
        },
    }
    (output_dir / "diversity_audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
