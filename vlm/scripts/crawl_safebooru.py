"""Download Japanese-anime character references for Aniplex-style IP supervision."""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from PIL import Image, ImageStat
from tqdm import tqdm
from requests.exceptions import JSONDecodeError as RequestsJSONDecodeError


API_URL = "https://safebooru.org/index.php"
USER_AGENT = "Sony-Internship-VLM-Crawler/2.0 (+https://safebooru.org/)"
DEFAULT_OUTPUT_NAMES = {
    "japanese_anime_turnaround_strict": "japanese_anime_turnaround_180",
    "aniplex_supervision_strict": "aniplex_supervision_180",
}
MANIFEST_FIELDS = [
    "post_id",
    "character_signature",
    "crawl_label",
    "query_tags",
    "image_path",
    "download_status",
    "tags",
    "width",
    "height",
    "actual_width",
    "actual_height",
    "source",
    "rating",
    "score",
    "owner",
    "image_url",
    "sample_url",
    "file_url",
    "preview_url",
    "sat_mean",
    "colorfulness",
    "likely_color",
    "selection_notes",
]

SHEET_TAGS = {"character_sheet", "reference_sheet", "turnaround", "model_sheet"}
REQUIRED_TAGS = {"multiple_views", "solo"}
SUBJECT_TAGS = {"1girl", "1boy"}

NEGATIVE_TAGS = {
    "anthro",
    "chibi",
    "comic",
    "creature",
    "furry",
    "greyscale",
    "grayscale",
    "lineart",
    "monochrome",
    "monster",
    "monster_boy",
    "monster_girl",
    "photo",
    "photorealistic",
    "realistic",
    "rough_sketch",
    "sketch",
    "traditional_media",
    "western",
    "star_wars",
    "marvel",
    "dc_comics",
    "superhero",
}

SIGNATURE_FEATURE_TAGS = {
    "animal_ears",
    "cat_ears",
    "dog_ears",
    "fox_ears",
    "wolf_ears",
    "bunny_ears",
    "tail",
    "animal_tail",
    "cat_tail",
    "fox_tail",
    "wolf_tail",
    "horns",
    "wings",
    "pointy_ears",
    "elf",
    "elf_(dnd)",
    "demon_girl",
    "dragon_girl",
    "kemonomimi_mode",
}

STRICT_NON_HUMAN_TAGS = {
    "centaur",
    "fish_girl",
    "mermaid",
}

PARTIAL_VIEW_NEGATIVE_TAGS = {
    "upper_body",
    "cowboy_shot",
    "portrait",
    "head_focus",
    "head_shot",
    "headshot",
    "close-up",
    "close_up",
    "bust",
}

GENERIC_SIGNATURE_TAGS = {
    *SHEET_TAGS,
    *REQUIRED_TAGS,
    *SUBJECT_TAGS,
    "official_art",
    "profile",
    "from_side",
    "from_behind",
    "simple_background",
    "white_background",
    "highres",
    "absurdres",
    "standing",
    "looking_at_viewer",
    "smile",
}

VISUAL_SUFFIXES = (
    "_hair",
    "_eyes",
    "_dress",
    "_shirt",
    "_skirt",
    "_sleeves",
    "_sleeve",
    "_gloves",
    "_boots",
    "_shoes",
    "_legwear",
    "_background",
    "_hat",
    "_ribbon",
    "_bow",
    "_jacket",
    "_kimono",
    "_mouth",
    "_footwear",
)

QUERY_BASE_NEGATIVES = "-chibi -creature -monster -furry -anthro -western -comic rating:safe"
ANIPLEX_SERIES_TAGS = (
    "fate_(series)",
    "fate/grand_order",
    "mahou_shoujo_madoka_magica",
    "kimetsu_no_yaiba",
    "sword_art_online",
    "lycoris_recoil",
    "bocchi_the_rock!",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl Japanese anime character references for atomic-rules supervision."
    )
    parser.add_argument(
        "--tags",
        default="",
        help='Custom Safebooru tag query, for example "character_sheet multiple_views full_body solo touhou".',
    )
    parser.add_argument(
        "--view-preset",
        choices=("japanese_anime_turnaround_strict", "aniplex_supervision_strict"),
        default="aniplex_supervision_strict",
        help="Use a built-in preset aligned with the atomic-rules workflow.",
    )
    parser.add_argument(
        "--output-name",
        default="",
        help="Override output folder name. Defaults depend on the selected preset.",
    )
    parser.add_argument("--limit", type=int, default=180, help="Target accepted image count.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("vlm") / "data" / "safebooru_2d",
        help="Base output directory.",
    )
    parser.add_argument(
        "--image-kind",
        choices=("sample", "file", "preview"),
        default="sample",
        help="Preferred image URL to download.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.3,
        help="Sleep seconds between accepted image downloads.",
    )
    parser.add_argument(
        "--request-sleep",
        type=float,
        default=0.0,
        help="Sleep seconds after each Safebooru API page request.",
    )
    parser.add_argument(
        "--max-pages-per-query",
        type=int,
        default=20,
        help="Maximum DAPI pages to scan per tag variant.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download files even when they already exist.",
    )
    parser.add_argument(
        "--existing-metadata",
        type=Path,
        help="Optional existing metadata.jsonl used to skip already collected posts and merge rows back on write.",
    )
    parser.add_argument(
        "--skip-post-ids",
        default="",
        help="Comma-separated Safebooru post IDs to skip even when they are not in existing metadata.",
    )
    parser.add_argument(
        "--incremental-write",
        action="store_true",
        help="Rewrite metadata.jsonl and manifest.csv after each accepted image so downstream workers can start early.",
    )
    return parser.parse_args()


def normalize_tags(tags: str) -> str:
    parts = tags.split()
    if not any(part.startswith("rating:") for part in parts):
        parts.append("rating:safe")
    return " ".join(parts)


def slugify_tags(tags: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", tags.strip())
    slug = re.sub(r"_+", "_", slug).strip("_.")
    return slug or "safebooru_query"


def split_counts(total: int, labels: list[str]) -> dict[str, int]:
    base = total // len(labels)
    remainder = total % len(labels)
    return {label: base + (1 if index < remainder else 0) for index, label in enumerate(labels)}


def load_jsonl_rows(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def strict_preset_query_groups() -> dict[str, list[str]]:
    return {
        "broad_turnaround_1girl": [
            f"turnaround multiple_views full_body solo 1girl {QUERY_BASE_NEGATIVES}",
            f"turnaround multiple_views solo 1girl {QUERY_BASE_NEGATIVES}",
        ],
        "broad_sheet_1girl": [
            f"character_sheet multiple_views solo 1girl {QUERY_BASE_NEGATIVES}",
            f"character_sheet multiple_views full_body solo 1girl {QUERY_BASE_NEGATIVES}",
        ],
        "broad_turnaround_1boy": [
            f"turnaround multiple_views full_body solo 1boy {QUERY_BASE_NEGATIVES}",
            f"turnaround multiple_views solo 1boy {QUERY_BASE_NEGATIVES}",
        ],
        "broad_sheet_1boy": [
            f"character_sheet multiple_views solo 1boy {QUERY_BASE_NEGATIVES}",
            f"character_sheet multiple_views full_body solo 1boy {QUERY_BASE_NEGATIVES}",
        ],
        "touhou_turnaround_human": [
            f"turnaround multiple_views solo touhou {QUERY_BASE_NEGATIVES}",
            f"character_sheet multiple_views solo touhou {QUERY_BASE_NEGATIVES}",
        ],
        "vocaloid_character_sheet_human": [
            f"character_sheet multiple_views solo vocaloid {QUERY_BASE_NEGATIVES}",
            f"reference_sheet multiple_views solo vocaloid {QUERY_BASE_NEGATIVES}",
        ],
        "anime_official_sheet_human": [
            f"character_sheet multiple_views solo official_art 1girl {QUERY_BASE_NEGATIVES}",
        ],
        "anime_official_sheet_boy_human": [
            f"character_sheet multiple_views solo official_art 1boy {QUERY_BASE_NEGATIVES}",
        ],
        "anime_turnaround_human": [
            f"turnaround multiple_views full_body solo 1girl {QUERY_BASE_NEGATIVES}",
        ],
        "anime_turnaround_boy_human": [
            f"turnaround multiple_views full_body solo 1boy {QUERY_BASE_NEGATIVES}",
        ],
        "fate_character_sheet_human": [
            f"character_sheet multiple_views solo fate_(series) {QUERY_BASE_NEGATIVES}",
            f"turnaround multiple_views solo fate_(series) {QUERY_BASE_NEGATIVES}",
        ],
    }


def aniplex_supervision_query_groups() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {
        "aniplex_broad_sheet_1girl": [
            f"character_sheet multiple_views solo 1girl {QUERY_BASE_NEGATIVES}",
            f"reference_sheet multiple_views solo 1girl {QUERY_BASE_NEGATIVES}",
            f"turnaround multiple_views solo 1girl {QUERY_BASE_NEGATIVES}",
        ],
        "aniplex_broad_sheet_1boy": [
            f"character_sheet multiple_views solo 1boy {QUERY_BASE_NEGATIVES}",
            f"reference_sheet multiple_views solo 1boy {QUERY_BASE_NEGATIVES}",
            f"turnaround multiple_views solo 1boy {QUERY_BASE_NEGATIVES}",
        ],
        "aniplex_official_full_body_1girl": [
            f"official_art full_body solo 1girl {QUERY_BASE_NEGATIVES}",
        ],
        "aniplex_official_full_body_1boy": [
            f"official_art full_body solo 1boy {QUERY_BASE_NEGATIVES}",
        ],
    }
    for series_tag in ANIPLEX_SERIES_TAGS:
        label = re.sub(r"[^A-Za-z0-9]+", "_", series_tag).strip("_")
        groups[f"aniplex_{label}_sheet"] = [
            f"character_sheet multiple_views solo {series_tag} {QUERY_BASE_NEGATIVES}",
            f"reference_sheet multiple_views solo {series_tag} {QUERY_BASE_NEGATIVES}",
            f"turnaround multiple_views solo {series_tag} {QUERY_BASE_NEGATIVES}",
        ]
        groups[f"aniplex_{label}_official_full_body"] = [
            f"official_art full_body solo {series_tag} {QUERY_BASE_NEGATIVES}",
        ]
    return groups


def preset_query_groups(preset: str) -> dict[str, list[str]]:
    if preset == "japanese_anime_turnaround_strict":
        return strict_preset_query_groups()
    if preset == "aniplex_supervision_strict":
        return aniplex_supervision_query_groups()
    raise ValueError(f"Unsupported view preset: {preset}")


def fetch_posts(session: requests.Session, tags: str, page: int, page_limit: int) -> list[dict[str, Any]]:
    params = {
        "page": "dapi",
        "s": "post",
        "q": "index",
        "tags": tags,
        "limit": page_limit,
        "pid": page,
        "json": "1",
    }
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = session.get(API_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                posts = data.get("post", [])
                if isinstance(posts, dict):
                    return [posts]
                return posts or []
            return data or []
        except (requests.RequestException, RequestsJSONDecodeError) as exc:
            last_error = exc
            time.sleep(1.0 + attempt * 1.5)
    if last_error:
        print(f"Warning: skipping page {page} for query [{tags}] after repeated fetch failures: {last_error}")
    return []


def choose_url(post: dict[str, Any], image_kind: str) -> str:
    keys_by_preference = {
        "sample": ("sample_url", "file_url", "preview_url"),
        "file": ("file_url", "sample_url", "preview_url"),
        "preview": ("preview_url", "sample_url", "file_url"),
    }
    for key in keys_by_preference[image_kind]:
        value = post.get(key)
        if value:
            return str(value)
    return ""


def extension_from_url(url: str, fallback_name: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix:
        return suffix
    fallback_suffix = Path(fallback_name).suffix.lower()
    return fallback_suffix or ".jpg"


def image_filename(post: dict[str, Any], url: str) -> str:
    post_id = str(post.get("id", "unknown"))
    image_hash = str(post.get("hash") or Path(str(post.get("image", "image"))).stem)
    ext = extension_from_url(url, str(post.get("image", "")))
    safe_hash = re.sub(r"[^A-Za-z0-9._-]+", "_", image_hash)
    return f"{post_id}_{safe_hash}{ext}"


def tag_set(post: dict[str, Any]) -> set[str]:
    return {tag.strip() for tag in str(post.get("tags", "")).split() if tag.strip()}


def has_single_subject(tags: set[str]) -> bool:
    if not (tags & SUBJECT_TAGS):
        return False
    for tag in tags:
        if re.fullmatch(r"\d+(girls|boys|people|persons)", tag):
            return False
        if tag in {"2girls", "2boys", "1girl_1boy", "duo", "trio", "group"}:
            return False
    return True


def normalized_source_key(source: Any) -> str:
    text = str(source or "").strip()
    if not text:
        return ""
    match = re.search(r"https?://\S+", text)
    if match:
        text = match.group(0)
    text = text.rstrip("/").lower()
    text = re.sub(r"[?#].*$", "", text)
    return text


def character_signature(post: dict[str, Any], crawl_label: str) -> str:
    return f"{crawl_label}:{post.get('id')}"


def allows_official_full_body(crawl_label: str, raw_tags: str) -> bool:
    return "official_full_body" in crawl_label or (
        "official_art" in raw_tags.split() and "full_body" in raw_tags.split()
    )


def prefilter_post(
    post: dict[str, Any],
    crawl_label: str,
    raw_tags: str,
    seen_ids: set[str],
    seen_signatures: set[str],
) -> tuple[bool, str, str]:
    post_id = str(post.get("id") or "")
    if not post_id or post_id in seen_ids:
        return False, "duplicate_post_id", ""

    tags = tag_set(post)
    allow_official_full_body = allows_official_full_body(crawl_label, raw_tags)
    if str(post.get("rating", "")).lower() != "safe":
        return False, "not_safe", ""
    if allow_official_full_body:
        if "official_art" not in tags:
            return False, "missing_official_art", ""
        if "full_body" not in tags:
            return False, "missing_full_body", ""
    else:
        if not (tags & SHEET_TAGS):
            return False, "missing_sheet_tag", ""
        missing_required = sorted(tag for tag in REQUIRED_TAGS if tag not in tags)
        if missing_required:
            return False, f"missing_required_tags:{','.join(missing_required)}", ""
    if not has_single_subject(tags):
        return False, "not_single_human_subject", ""
    if negative_hits := sorted(tags & NEGATIVE_TAGS):
        return False, f"negative_tags:{','.join(negative_hits)}", ""
    if non_human_hits := sorted(tags & STRICT_NON_HUMAN_TAGS):
        return False, f"non_human_tags:{','.join(non_human_hits)}", ""
    if partial_hits := sorted(tags & PARTIAL_VIEW_NEGATIVE_TAGS):
        return False, f"partial_view_tags:{','.join(partial_hits)}", ""

    raw_width = int(post.get("sample_width") or post.get("width") or 0)
    raw_height = int(post.get("sample_height") or post.get("height") or 0)
    if raw_width < 450 or raw_height < 450:
        return False, "too_small", ""

    signature = character_signature(post, crawl_label)

    if (
        not allow_official_full_body
        and "official_art" not in tags
        and "turnaround" not in tags
        and "character_sheet" not in tags
    ):
        return False, "weak_sheet_signal", signature

    query_terms = [term for term in raw_tags.split() if not term.startswith("-") and not term.startswith("rating:")]
    required_query_terms = [
        term
        for term in query_terms
        if term not in {"solo", "full_body", "multiple_views", "official_art", "1girl", "1boy"}
        and term not in SHEET_TAGS
    ]
    if required_query_terms and not any(term in tags for term in required_query_terms):
        return False, "missing_positive_series_tag", signature

    signature_hits = sorted(tags & SIGNATURE_FEATURE_TAGS)
    if signature_hits:
        return True, f"prefilter_pass;signature_features:{','.join(signature_hits)}", signature
    return True, "prefilter_pass", signature


def download_image(session: requests.Session, url: str, output_path: Path, overwrite: bool) -> str:
    if not url:
        return "missing_url"
    if output_path.exists() and output_path.stat().st_size > 0 and not overwrite:
        return "skipped_existing"

    tmp_path = output_path.with_suffix(output_path.suffix + ".part")
    try:
        with session.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        fh.write(chunk)
        tmp_path.replace(output_path)
        return "downloaded"
    except requests.RequestException as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        return f"failed:{exc.__class__.__name__}"


def image_metrics(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        sample = rgb.copy()
        sample.thumbnail((512, 512))
        hsv = sample.convert("HSV")
        saturation = list(hsv.getchannel("S").getdata())
        stat = ImageStat.Stat(sample)
        means = stat.mean
        stddev = stat.stddev

        width = rgb.width
        height = rgb.height

    sat_mean = statistics.fmean(saturation) / 255.0 if saturation else 0.0
    channel_spread = max(means) - min(means)
    colorfulness = sum(stddev) / 3.0 + channel_spread
    likely_color = sat_mean >= 0.08 and colorfulness >= 18.0
    return {
        "actual_width": width,
        "actual_height": height,
        "sat_mean": round(sat_mean, 4),
        "colorfulness": round(colorfulness, 4),
        "likely_color": likely_color,
    }


def metadata_row(
    post: dict[str, Any],
    tags_query: str,
    image_url: str,
    image_path: Path,
    status: str,
    crawl_label: str,
    signature: str,
    metrics: dict[str, Any],
    selection_notes: str,
) -> dict[str, Any]:
    return {
        "post_id": post.get("id"),
        "character_signature": signature,
        "crawl_label": crawl_label,
        "hash": post.get("hash"),
        "image_path": str(image_path.as_posix()),
        "download_status": status,
        "query_tags": tags_query,
        "tags": post.get("tags"),
        "width": post.get("width"),
        "height": post.get("height"),
        "actual_width": metrics.get("actual_width"),
        "actual_height": metrics.get("actual_height"),
        "source": post.get("source"),
        "rating": post.get("rating"),
        "score": post.get("score"),
        "owner": post.get("owner"),
        "image_url": image_url,
        "sample_url": post.get("sample_url"),
        "file_url": post.get("file_url"),
        "preview_url": post.get("preview_url"),
        "sat_mean": metrics.get("sat_mean"),
        "colorfulness": metrics.get("colorfulness"),
        "likely_color": metrics.get("likely_color"),
        "selection_notes": selection_notes,
    }


def write_outputs(rows: list[dict[str, Any]], metadata_path: Path, manifest_path: Path) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_tmp_path = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
    manifest_tmp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    with metadata_tmp_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    metadata_tmp_path.replace(metadata_path)

    with manifest_tmp_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in MANIFEST_FIELDS})
    manifest_tmp_path.replace(manifest_path)


def seed_seen_sets(existing_rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    seen_ids: set[str] = set()
    for row in existing_rows:
        post_id = str(row.get("post_id") or "").strip()
        if post_id:
            seen_ids.add(post_id)
    return seen_ids, set()


def add_explicit_skip_ids(seen_ids: set[str], skip_post_ids: str) -> None:
    for post_id in re.split(r"[,\s]+", skip_post_ids.strip()):
        if post_id:
            seen_ids.add(post_id)


def add_rejected_post_ids(seen_ids: set[str], output_dir: Path) -> None:
    path = output_dir / "rejected_post_ids.txt"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        post_id = line.split("#", 1)[0].strip()
        if post_id:
            seen_ids.add(post_id)


def crawl_query_variants(
    *,
    session: requests.Session,
    crawl_label: str,
    query_variants: list[str],
    target_count: int,
    images_dir: Path,
    image_kind: str,
    overwrite: bool,
    sleep_seconds: float,
    request_sleep_seconds: float,
    max_pages_per_query: int,
    seen_ids: set[str],
    seen_signatures: set[str],
    on_accept: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if target_count <= 0:
        return rows

    with tqdm(total=target_count, desc=f"Downloading {crawl_label}", unit="img") as progress:
        for raw_tags in query_variants:
            tags = normalize_tags(raw_tags)
            page = 0
            while len(rows) < target_count and page < max_pages_per_query:
                posts = fetch_posts(session, tags, page=page, page_limit=50)
                if request_sleep_seconds:
                    time.sleep(request_sleep_seconds)
                if not posts:
                    break

                for post in posts:
                    ok, prefilter_note, signature = prefilter_post(
                        post,
                        crawl_label,
                        tags,
                        seen_ids,
                        seen_signatures,
                    )
                    if not ok:
                        continue

                    image_url = choose_url(post, image_kind)
                    output_path = images_dir / image_filename(post, image_url)
                    status = download_image(session, image_url, output_path, overwrite)
                    if not status.startswith(("downloaded", "skipped_existing")):
                        continue

                    try:
                        metrics = image_metrics(output_path)
                    except Exception:
                        if output_path.exists():
                            output_path.unlink()
                        continue

                    if not metrics["likely_color"]:
                        if output_path.exists():
                            output_path.unlink()
                        continue

                    seen_ids.add(str(post.get("id")))
                    seen_signatures.add(signature)
                    row = metadata_row(
                        post=post,
                        tags_query=tags,
                        image_url=image_url,
                        image_path=output_path,
                        status=status,
                        crawl_label=crawl_label,
                        signature=signature,
                        metrics=metrics,
                        selection_notes=f"{prefilter_note};color_metric_pass",
                    )
                    rows.append(row)
                    if on_accept:
                        on_accept(row)
                    progress.update(1)

                    if len(rows) >= target_count:
                        break
                    if sleep_seconds:
                        time.sleep(sleep_seconds)

                page += 1
                if len(rows) >= target_count:
                    break

    return rows


def crawl_custom_tags(args: argparse.Namespace, session: requests.Session) -> tuple[Path, list[dict[str, Any]]]:
    tags = normalize_tags(args.tags)
    output_name = args.output_name or slugify_tags(args.tags)
    output_dir = args.out_dir / output_name
    existing_rows = load_jsonl_rows(args.existing_metadata)
    live_rows = list(existing_rows)
    metadata_path = output_dir / "metadata.jsonl"
    manifest_path = output_dir / "manifest.csv"

    def on_accept(row: dict[str, Any]) -> None:
        if not args.incremental_write:
            return
        live_rows.append(row)
        write_outputs(live_rows, metadata_path, manifest_path)

    seen_ids, seen_signatures = seed_seen_sets(existing_rows)
    add_rejected_post_ids(seen_ids, output_dir)
    add_explicit_skip_ids(seen_ids, args.skip_post_ids)
    rows = crawl_query_variants(
        session=session,
        crawl_label=output_name,
        query_variants=[tags],
        target_count=args.limit,
        images_dir=output_dir / "image",
        image_kind=args.image_kind,
        overwrite=args.overwrite,
        sleep_seconds=args.sleep,
        request_sleep_seconds=args.request_sleep,
        max_pages_per_query=args.max_pages_per_query,
        seen_ids=seen_ids,
        seen_signatures=seen_signatures,
        on_accept=on_accept,
    )
    return output_dir, [*existing_rows, *rows]


def crawl_preset(args: argparse.Namespace, session: requests.Session) -> tuple[Path, list[dict[str, Any]]]:
    query_groups = preset_query_groups(args.view_preset)
    output_name = args.output_name or DEFAULT_OUTPUT_NAMES[args.view_preset]
    output_dir = args.out_dir / output_name
    counts = split_counts(args.limit, list(query_groups))
    existing_rows = load_jsonl_rows(args.existing_metadata)
    rows: list[dict[str, Any]] = []
    metadata_path = output_dir / "metadata.jsonl"
    manifest_path = output_dir / "manifest.csv"

    def on_accept(row: dict[str, Any]) -> None:
        if not args.incremental_write:
            return
        rows.append(row)
        write_outputs([*existing_rows, *rows], metadata_path, manifest_path)

    seen_ids, seen_signatures = seed_seen_sets(existing_rows)
    add_rejected_post_ids(seen_ids, output_dir)
    add_explicit_skip_ids(seen_ids, args.skip_post_ids)

    for crawl_label, query_variants in query_groups.items():
        remaining_total = args.limit - len(rows)
        if remaining_total <= 0:
            break
        target_for_label = min(counts[crawl_label], remaining_total)
        group_rows = crawl_query_variants(
            session=session,
            crawl_label=crawl_label,
            query_variants=query_variants,
            target_count=target_for_label,
            images_dir=output_dir / "image",
            image_kind=args.image_kind,
            overwrite=args.overwrite,
            sleep_seconds=args.sleep,
            request_sleep_seconds=args.request_sleep,
            max_pages_per_query=args.max_pages_per_query,
            seen_ids=seen_ids,
            seen_signatures=seen_signatures,
            on_accept=on_accept,
        )
        if not args.incremental_write:
            rows.extend(group_rows)

    if len(rows) < args.limit:
        if args.view_preset == "aniplex_supervision_strict":
            backfill_variants = [
                f"official_art full_body solo 1girl {QUERY_BASE_NEGATIVES}",
                f"official_art full_body solo 1boy {QUERY_BASE_NEGATIVES}",
                f"character_sheet multiple_views solo official_art 1girl {QUERY_BASE_NEGATIVES}",
                f"character_sheet multiple_views solo official_art 1boy {QUERY_BASE_NEGATIVES}",
                f"character_sheet multiple_views solo fate_(series) {QUERY_BASE_NEGATIVES}",
                f"official_art full_body solo fate_(series) {QUERY_BASE_NEGATIVES}",
            ]
        else:
            backfill_variants = [
                f"turnaround multiple_views full_body solo 1girl {QUERY_BASE_NEGATIVES}",
                f"character_sheet multiple_views solo 1girl {QUERY_BASE_NEGATIVES}",
                f"turnaround multiple_views full_body solo 1boy {QUERY_BASE_NEGATIVES}",
                f"character_sheet multiple_views solo 1boy {QUERY_BASE_NEGATIVES}",
                f"character_sheet multiple_views solo official_art 1girl {QUERY_BASE_NEGATIVES}",
                f"character_sheet multiple_views solo official_art 1boy {QUERY_BASE_NEGATIVES}",
                f"character_sheet multiple_views solo vocaloid {QUERY_BASE_NEGATIVES}",
                f"turnaround multiple_views solo touhou {QUERY_BASE_NEGATIVES}",
                f"character_sheet multiple_views solo fate_(series) {QUERY_BASE_NEGATIVES}",
            ]
        backfill_rows = crawl_query_variants(
            session=session,
            crawl_label="strict_backfill",
            query_variants=backfill_variants,
            target_count=args.limit - len(rows),
            images_dir=output_dir / "image",
            image_kind=args.image_kind,
            overwrite=args.overwrite,
            sleep_seconds=args.sleep,
            request_sleep_seconds=args.request_sleep,
            max_pages_per_query=args.max_pages_per_query,
            seen_ids=seen_ids,
            seen_signatures=seen_signatures,
            on_accept=on_accept,
        )
        if not args.incremental_write:
            rows.extend(backfill_rows)

    return output_dir, [*existing_rows, *rows]


def crawl(args: argparse.Namespace) -> Path:
    if args.limit <= 0:
        raise ValueError("--limit must be greater than 0")
    if args.sleep < 0:
        raise ValueError("--sleep must not be negative")
    if args.request_sleep < 0:
        raise ValueError("--request-sleep must not be negative")
    if args.max_pages_per_query <= 0:
        raise ValueError("--max-pages-per-query must be greater than 0")
    if not args.tags and not args.view_preset:
        raise ValueError("Either --tags or --view-preset is required")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    if args.tags:
        output_dir, rows = crawl_custom_tags(args, session)
    else:
        output_dir, rows = crawl_preset(args, session)

    existing_count = len(load_jsonl_rows(args.existing_metadata))
    new_count = len(rows) - existing_count
    if new_count < args.limit:
        print(f"Warning: accepted {new_count} new images, below requested limit {args.limit}.")

    metadata_path = output_dir / "metadata.jsonl"
    manifest_path = output_dir / "manifest.csv"
    write_outputs(rows, metadata_path, manifest_path)
    return output_dir


def main() -> None:
    args = parse_args()
    output_dir = crawl(args)
    print(f"Saved Safebooru crawl to {output_dir}")


if __name__ == "__main__":
    main()
