"""Download Japanese-anime character references for Aniplex-style IP supervision.

This module crawls Safebooru (a safe-for-work anime image board) to collect high-quality
character reference sheets and turnaround images for merchandise supervision workflows.

Key Features:
    - Multi-query strategy: Uses multiple tag combinations to achieve target counts
    - Character deduplication: Prevents duplicate characters via signature matching
    - Quality filtering: Enforces minimum size (450px), color content, and safe ratings
    - Rate limiting: Configurable delays between API requests and downloads
    - Incremental updates: Supports resuming from existing metadata to add more images

Rate Limiting Strategy:
    - Default 0.3s sleep between accepted image downloads (--sleep)
    - Optional delay after each API page request (--request-sleep)
    - Exponential backoff on API failures (1.0s + attempt * 1.5s)
    - Page limit of 50 results per API call to balance speed and reliability

Output Format:
    - metadata.jsonl: One JSON object per line with full post metadata and metrics
    - manifest.csv: Same data in CSV format for Excel/spreadsheet analysis
    - image/: Downloaded images named as {post_id}_{hash}{ext}
    - rejected_post_ids.txt: Optional user-curated rejection list

Filtering Pipeline:
    1. API-level: Tag queries with rating:safe and negative tags
    2. Prefilter: Size, tags, subject count, existing post/character checks
    3. Download: Fetch image and verify actual dimensions
    4. Metrics: Calculate color saturation and colorfulness
    5. Color check: Reject grayscale/monochrome images (sat_mean < 0.08 or colorfulness < 18.0)

Typical Usage:
    python crawl_safebooru.py --view-preset aniplex_supervision_strict --limit 180
    python crawl_safebooru.py --tags "character_sheet multiple_views solo fate_(series)" --limit 50
"""

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
    "full_body",
    "official_art",
    "profile",
    "from_side",
    "from_behind",
    "from_above",
    "from_below",
    "simple_background",
    "white_background",
    "highres",
    "absurdres",
    "standing",
    "sitting",
    "kneeling",
    "crouching",
    "looking_at_viewer",
    "facing_viewer",
    "smile",
}

GENERIC_IDENTITY_TAGS = {
    "ahoge",
    "bangs",
    "bare_shoulders",
    "blush",
    "boots",
    "bow",
    "breasts",
    "cape",
    "closed_eyes",
    "closed_mouth",
    "collarbone",
    "dress",
    "earrings",
    "eyebrows_visible_through_hair",
    "female",
    "flower",
    "frills",
    "glasses",
    "gloves",
    "hair_between_eyes",
    "hair_ornament",
    "hat",
    "high_heels",
    "holding",
    "jacket",
    "jewelry",
    "long_hair",
    "long_sleeves",
    "medium_breasts",
    "medium_hair",
    "open_mouth",
    "pants",
    "ribbon",
    "shirt",
    "shoes",
    "short_hair",
    "short_sleeves",
    "skirt",
    "socks",
    "solo",
    "standing_on_one_leg",
    "swept_bangs",
    "thigh-highs",
    "translation_request",
    "very_long_hair",
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
    """Parse and validate command-line arguments for the Safebooru crawler.

    Returns:
        argparse.Namespace: Parsed arguments including:
            - tags: Custom Safebooru tag query string
            - view_preset: Named preset for turnaround/supervision workflows
            - output_name: Override for the output folder name
            - limit: Target number of accepted images to collect
            - out_dir: Base directory under which output subfolders are created
            - image_kind: Which URL to prefer when downloading (sample/file/preview)
            - sleep: Delay in seconds between image downloads (rate limiting)
            - request_sleep: Delay in seconds between API page requests
            - max_pages_per_query: Hard cap on pages scanned per tag query variant
            - overwrite: Whether to re-download already-existing files
            - existing_metadata: Path to a previous metadata.jsonl to resume from
            - skip_post_ids: Comma-separated post IDs to exclude from this run
            - incremental_write: Whether to flush metadata after each accepted image
    """
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
    """Ensure the tag query always includes a rating:safe filter.

    Safebooru supports multiple ratings (safe, questionable, explicit). Without an
    explicit rating filter the API returns posts across all ratings. This function
    appends ``rating:safe`` if the caller has not already included any rating: term.

    Args:
        tags: Raw tag query string, e.g. ``"character_sheet multiple_views solo"``.

    Returns:
        Tag query guaranteed to contain exactly one rating: term.
    """
    parts = tags.split()
    if not any(part.startswith("rating:") for part in parts):
        parts.append("rating:safe")
    return " ".join(parts)


def slugify_tags(tags: str) -> str:
    """Convert a tag query string into a safe filesystem folder name.

    Replaces all non-alphanumeric characters (except dots, underscores, dashes) with
    underscores, collapses multiple underscores, and trims leading/trailing underscores.

    Args:
        tags: Tag query string that may contain spaces, colons, special characters.

    Returns:
        Filesystem-safe slug, e.g. ``"character_sheet_multiple_views_solo_rating_safe"``.
    """
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", tags.strip())
    slug = re.sub(r"_+", "_", slug).strip("_.")
    return slug or "safebooru_query"


def split_counts(total: int, labels: list[str]) -> dict[str, int]:
    """Distribute a total count as evenly as possible across a list of labels.

    Uses integer division so the sum always equals ``total`` exactly.  Any remainder
    is distributed one unit at a time to the first labels in the list (round-robin).

    Example:
        split_counts(10, ["a", "b", "c"]) -> {"a": 4, "b": 3, "c": 3}

    Args:
        total: Total number of items to distribute.
        labels: Ordered list of label strings (typically crawl-group names).

    Returns:
        Dict mapping each label to its per-group target count.
    """
    base = total // len(labels)
    remainder = total % len(labels)
    # First `remainder` labels get one extra to absorb the integer-division leftover
    return {label: base + (1 if index < remainder else 0) for index, label in enumerate(labels)}


def load_jsonl_rows(path: Path | None) -> list[dict[str, Any]]:
    """Load all records from a newline-delimited JSON file into a list of dicts.

    Returns an empty list silently when *path* is None or does not exist, making
    it safe to call unconditionally when an existing-metadata file is optional.

    Args:
        path: Path to a ``.jsonl`` file, or None to skip loading.

    Returns:
        List of parsed JSON objects; empty list if the file is absent or empty.
    """
    if not path or not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def strict_preset_query_groups() -> dict[str, list[str]]:
    """Return query groups for the ``japanese_anime_turnaround_strict`` preset.

    This preset targets high-quality anime character turnarounds and sheets for
    general Japanese anime (not limited to specific series). Each group key is a
    crawl label used in metadata and folder names; each value is a list of tag
    query variants tried in order until the per-group target count is reached.

    Multi-variant strategy: The first variant in each list is the most restrictive
    (e.g. includes ``full_body``); subsequent variants relax one condition at a time.
    This ensures the highest-quality posts are collected first before falling back to
    more permissive queries.

    Returns:
        Dict of {crawl_label: [query_variant, ...]} for the strict turnaround preset.
    """
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
    """Return query groups for the ``aniplex_supervision_strict`` preset.

    This preset targets reference images suitable for Aniplex-style IP merchandise
    supervision, combining broad anime queries with series-specific queries for each
    franchise in ANIPLEX_SERIES_TAGS. The series-specific groups are auto-generated,
    so adding a new series tag to ANIPLEX_SERIES_TAGS automatically extends this preset.

    Group structure:
        - ``aniplex_broad_sheet_*``: Generic character sheets for 1girl/1boy
        - ``aniplex_official_full_body_*``: Official art with full-body view
        - ``aniplex_{series}_sheet``: Series-specific character sheets (auto-generated)
        - ``aniplex_{series}_official_full_body``: Series-specific official art (auto-generated)

    Returns:
        Dict of {crawl_label: [query_variant, ...]} for the Aniplex supervision preset.
    """
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
    """Dispatch to the appropriate query-group builder for the given preset name.

    Args:
        preset: One of ``"japanese_anime_turnaround_strict"`` or
                ``"aniplex_supervision_strict"``.

    Returns:
        Dict of {crawl_label: [query_variant, ...]} for the requested preset.

    Raises:
        ValueError: If ``preset`` is not a recognised preset name.
    """
    if preset == "japanese_anime_turnaround_strict":
        return strict_preset_query_groups()
    if preset == "aniplex_supervision_strict":
        return aniplex_supervision_query_groups()
    raise ValueError(f"Unsupported view preset: {preset}")


def fetch_posts(session: requests.Session, tags: str, page: int, page_limit: int) -> list[dict[str, Any]]:
    """Fetch one page of posts from the Safebooru DAPI (Data API).

    Uses the Safebooru JSON endpoint with automatic retry on network/parse errors.
    Exponential backoff prevents hammering the server when it is temporarily unhappy.

    The DAPI returns either a list of post dicts or a dict with a ``"post"`` key.
    Both shapes are normalised to a plain list here.

    Rate limiting note: page_limit=50 is the practical sweet spot — larger values
    (up to 100) increase per-request latency and risk timeouts; smaller values
    require more requests to scan the same result set.

    Args:
        session: A ``requests.Session`` with User-Agent already set.
        tags: Space-separated Safebooru tag query (should include ``rating:safe``).
        page: Zero-based page index (pid parameter in the DAPI).
        page_limit: Number of results per page; 50 is the default and recommended max.

    Returns:
        List of post dicts from the API; empty list on failure or no results.
    """
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
                # DAPI wraps a single post as a dict instead of a list
                if isinstance(posts, dict):
                    return [posts]
                return posts or []
            return data or []
        except (requests.RequestException, RequestsJSONDecodeError) as exc:
            last_error = exc
            # Exponential backoff: 1.0s, 2.5s, 4.0s between retries
            time.sleep(1.0 + attempt * 1.5)
    if last_error:
        print(f"Warning: skipping page {page} for query [{tags}] after repeated fetch failures: {last_error}")
    return []


def choose_url(post: dict[str, Any], image_kind: str) -> str:
    """Select the best available image URL from a post according to the preferred kind.

    Safebooru posts expose up to three image URLs at different resolutions:
        - ``sample_url``: Medium-resolution JPEG, usually 850px on the long edge
        - ``file_url``: Original full-resolution upload (may be very large)
        - ``preview_url``: Small thumbnail, typically 150px

    For supervision work the ``sample`` kind is the default — it is large enough for
    detailed visual analysis but avoids downloading multi-megabyte originals.

    Args:
        post: A Safebooru post dict as returned by ``fetch_posts``.
        image_kind: One of ``"sample"``, ``"file"``, or ``"preview"``.

    Returns:
        The first non-empty URL found in preference order, or empty string if none.
    """
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
    """Derive a file extension from a URL, with fallback to a filename or ``.jpg``.

    First tries to extract the extension from the URL path (e.g. ``/image.png`` -> ``.png``).
    If the URL has no discernible extension (e.g. CDN URLs with query strings stripping
    the suffix), falls back to the extension of ``fallback_name``, then to ``.jpg``.

    Args:
        url: Image URL string to parse.
        fallback_name: Original filename from the post (e.g. ``post.get("image")``).

    Returns:
        Lowercase extension including the leading dot, e.g. ``.jpg``, ``.png``.
    """
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix:
        return suffix
    fallback_suffix = Path(fallback_name).suffix.lower()
    return fallback_suffix or ".jpg"


def image_filename(post: dict[str, Any], url: str) -> str:
    """Build a deterministic, filesystem-safe filename for a downloaded post image.

    The filename format is ``{post_id}_{hash}{ext}``.  The post ID ensures uniqueness;
    the hash (or stem of the original filename) aids manual identification.
    All non-safe characters in the hash are replaced with underscores.

    Args:
        post: Safebooru post dict containing ``id``, ``hash``, and optionally ``image``.
        url: Resolved download URL used to determine the file extension.

    Returns:
        Safe filename string, e.g. ``"12345678_abc123def456.jpg"``.
    """
    post_id = str(post.get("id", "unknown"))
    image_hash = str(post.get("hash") or Path(str(post.get("image", "image"))).stem)
    ext = extension_from_url(url, str(post.get("image", "")))
    safe_hash = re.sub(r"[^A-Za-z0-9._-]+", "_", image_hash)
    return f"{post_id}_{safe_hash}{ext}"


def tag_set(post: dict[str, Any]) -> set[str]:
    """Extract the set of Safebooru tags from a post dict.

    The DAPI returns tags as a single space-separated string in the ``"tags"`` field.
    This helper parses that into a set for efficient membership testing.

    Args:
        post: Safebooru post dict.

    Returns:
        Set of tag strings, empty set if tags field is missing or empty.
    """
    return {tag.strip() for tag in str(post.get("tags", "")).split() if tag.strip()}


def has_single_subject(tags: set[str]) -> bool:
    """Return True only when the post depicts exactly one human-like character.

    The filter requires at least one of the SUBJECT_TAGS (``1girl`` / ``1boy``) to be
    present, then rejects anything that signals multiple subjects via numeric prefixes
    or explicit group/duo tags.  This guards against turnaround sheets that show a
    character together with a companion, which would confuse per-character supervision.

    Rejection patterns:
        - Tags matching ``r"\\d+(girls|boys|people|persons)"`` (e.g. ``2girls``, ``3people``)
        - Explicit multi-character tags: ``2girls``, ``2boys``, ``1girl_1boy``, ``duo``,
          ``trio``, ``group``

    Args:
        tags: Set of tags for a post, as returned by ``tag_set()``.

    Returns:
        True if exactly one human-type subject is present.
    """
    if not (tags & SUBJECT_TAGS):
        return False
    for tag in tags:
        if re.fullmatch(r"\d+(girls|boys|people|persons)", tag):
            return False
        if tag in {"2girls", "2boys", "1girl_1boy", "duo", "trio", "group"}:
            return False
    return True


def normalized_source_key(source: Any) -> str:
    """Extract and normalise the source URL from a post for deduplication purposes.

    Safebooru's ``source`` field may be a bare URL, a URL embedded in free text, or
    empty.  This function extracts the first HTTP(S) URL if present, then normalises
    it by lowercasing, stripping trailing slashes, and removing query/fragment strings.

    This normalisation ensures that ``https://pixiv.net/artworks/12345?lang=en`` and
    ``https://pixiv.net/artworks/12345/`` are treated as the same source.

    Args:
        source: Raw ``source`` field from a Safebooru post (may be str, None, etc.).

    Returns:
        Normalised URL string, or empty string if no valid URL was found.
    """
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
    """Build a compact identity string that represents a unique character across posts.

    This signature drives the per-character deduplication check: two posts with the
    same signature are assumed to depict the same character and only one is kept.

    Tag exclusion rationale:
        Tags in ``GENERIC_SIGNATURE_TAGS`` describe *context* (sheet type, framing,
        background) and are shared by every post in the crawl, so they carry no
        identity signal.

        Tags in ``GENERIC_IDENTITY_TAGS`` describe *common physical traits* such as
        ``long_hair`` or ``glasses`` that thousands of different characters share and
        therefore do not distinguish one character from another.

        Tags in ``NEGATIVE_TAGS``, ``STRICT_NON_HUMAN_TAGS``, and
        ``PARTIAL_VIEW_NEGATIVE_TAGS`` have already been screened out by
        ``prefilter_post``; excluding them here keeps the signature clean.

        Tags matching ``VISUAL_SUFFIXES`` (e.g. ``blonde_hair``, ``blue_eyes``) are
        colour/material descriptors that are useful for the VLM but not distinctive
        enough to reliably identify a specific named character.

        Tags matching ``r"\\d+(girl|boy|...)"`` are subject-count tags, not identifiers.

    Deduplication strategy:
        The function returns the *most specific* fingerprint available:
        1. Up to 5 character-specific tags (alphabetically sorted for stability),
           joined as ``character_tags:tag1|tag2|...``  — catches named characters.
        2. Normalised source URL as ``source:https://...``  — catches single-artwork
           uploads where no named-character tags are tagged.
        3. Post ID as ``post:{id}``  — last resort, every post is unique.

        Limiting to 5 tags prevents the signature from being so long that minor tag
        differences (e.g. one upload tagged more thoroughly) fragment the same
        character into multiple buckets.

    Args:
        post: Safebooru post dict.
        crawl_label: The crawl group label (currently unused in the signature logic
                     but kept for future group-aware deduplication).

    Returns:
        A stable, compact string that identifies the character depicted in the post.
    """
    tags = tag_set(post)
    # Aggregate all tag categories that carry no character-identity information
    ignored = (
        GENERIC_SIGNATURE_TAGS
        | GENERIC_IDENTITY_TAGS
        | NEGATIVE_TAGS
        | STRICT_NON_HUMAN_TAGS
        | PARTIAL_VIEW_NEGATIVE_TAGS
    )
    identity_tags = []
    for tag in sorted(tags):  # Sorted for deterministic output across Python runs
        if tag in ignored or tag.startswith("rating:"):
            continue
        # Visual colour/material descriptors (e.g. "red_hair") are too common to
        # distinguish characters reliably; skip them
        if tag.endswith(VISUAL_SUFFIXES):
            continue
        # Skip numeric subject-count tags (e.g. "1girl", "2boys")
        if re.fullmatch(r"\d+(girl|boy|girls|boys|people|persons)", tag):
            continue
        identity_tags.append(tag)
    if identity_tags:
        # Cap at 5 tags to avoid over-specificity from exhaustive tag lists
        return "character_tags:" + "|".join(identity_tags[:5])

    # Fallback 1: use the normalised source URL if tags are too generic
    source_key = normalized_source_key(post.get("source"))
    if source_key:
        return f"source:{source_key}"
    # Fallback 2: every post is unique by its ID — no deduplication, but safe
    return f"post:{post.get('id')}"


def allows_official_full_body(crawl_label: str, raw_tags: str) -> bool:
    """Check if this crawl group targets official_art + full_body posts instead of sheets.

    Some query groups in the Aniplex preset accept posts that have ``official_art``
    and ``full_body`` tags rather than requiring a turnaround/character_sheet tag.
    This allows the crawler to collect high-quality official illustrations when sheets
    are scarce for a given series.

    Args:
        crawl_label: The crawl group label (e.g. ``"aniplex_official_full_body_1girl"``).
        raw_tags: The tag query string used for this group.

    Returns:
        True if ``official_full_body`` appears in the label or both tags are present.
    """
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
    """Run all quality and relevance filters for a single Safebooru post.

    This is the central gate before downloading an image. Posts must pass every check
    in sequence; any failure returns immediately with a descriptive rejection reason so
    callers can log filtering statistics or adjust query strategies.

    Filter order (each check short-circuits the rest on failure):

    1.  **Post-ID deduplication**: Skips posts already seen in this run or in
        ``existing_metadata``. Prevents redundant downloads across page boundaries
        and resumed crawls.

    2.  **Safety rating**: Only ``rating:safe`` posts are accepted. Safebooru posts
        with ``rating:questionable`` or ``rating:explicit`` are always rejected.

    3.  **Sheet/official-art tag gate**: For normal groups the post must have at least
        one of SHEET_TAGS (``character_sheet``, ``reference_sheet``, ``turnaround``,
        ``model_sheet``) plus REQUIRED_TAGS (``multiple_views``, ``solo``). Official-
        full-body groups instead require ``official_art`` + ``full_body``.

    4.  **Single-subject check**: The post must depict exactly one ``1girl`` or ``1boy``
        with no multi-character tags (see ``has_single_subject``).

    5.  **Negative tag rejection**: Tags in NEGATIVE_TAGS disqualify the post because:
        - ``anthro``, ``furry``, ``creature``, ``monster*`` → non-human body proportions
          would not train supervision rules for standard anime characters.
        - ``chibi`` → exaggerated proportions incompatible with realistic merchandise.
        - ``comic`` → panel layouts break the full-body single-character assumption.
        - ``greyscale``, ``monochrome``, ``lineart``, ``sketch``, ``rough_sketch`` →
          colour accuracy is essential for fabric/paint supervision.
        - ``traditional_media`` → scanned art quality is too variable.
        - ``photo``, ``photorealistic``, ``realistic`` → non-anime style.
        - ``western``, ``star_wars``, ``marvel``, ``dc_comics``, ``superhero`` →
          non-Japanese IP, outside the scope of Aniplex-style supervision.

    6.  **Strict non-human rejection**: Tags in STRICT_NON_HUMAN_TAGS (``centaur``,
        ``mermaid``, ``fish_girl``) indicate body plans too different from human for
        standard merchandise patterns, even though they are anime-style.

    7.  **Partial-view rejection**: Tags like ``upper_body``, ``cowboy_shot``,
        ``portrait``, ``bust``, ``close-up`` indicate the image does not show the full
        figure. Merchandise supervision requires full-body reference views to check
        proportions, accessories, and footwear.

    8.  **Minimum resolution (450px)**: Both ``sample_width``/``sample_height`` (or
        fallback ``width``/``height``) must be at least 450px in each dimension.
        Why 450px: at that size a ~100px face region is still legible for facial-feature
        supervision, and garment details remain distinguishable. Smaller images produce
        noisy colour measurements and unreliable VLM outputs.

    9.  **Character-signature deduplication**: Posts with a signature already in
        ``seen_signatures`` are skipped, even if they are different posts of the same
        character. This keeps the dataset character-diverse rather than image-diverse.

    10. **Weak-sheet-signal check**: For non-official-full-body groups the post must
        have at least one of ``official_art``, ``turnaround``, or ``character_sheet``
        to confirm it is a proper reference sheet and not a casual illustration that
        accidentally matched the query.

    11. **Series-tag enforcement**: If the query contains series/franchise tags (any
        positive term that is not a generic layout tag), the post must have at least
        one of them. This prevents off-series posts from polluting a series-specific
        group when Safebooru's boolean AND has edge cases.

    Args:
        post: Safebooru post dict from ``fetch_posts``.
        crawl_label: Crawl group label for context-sensitive checks.
        raw_tags: The normalised tag query used to fetch this post.
        seen_ids: Set of post IDs already accepted or explicitly skipped this run.
        seen_signatures: Set of character signatures already accepted this run.

    Returns:
        Tuple of (accepted: bool, reason: str, signature: str).
        ``reason`` describes the result (pass or the first failing filter).
        ``signature`` is the character identity string (empty on early rejections).
    """
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
        # Normal groups require a sheet/turnaround tag to confirm reference-quality
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

    # 450px minimum: small images degrade VLM accuracy and produce unreliable
    # colour metrics; sample_width/height is preferred because that is the resolution
    # of the image we will actually download (sample_url)
    raw_width = int(post.get("sample_width") or post.get("width") or 0)
    raw_height = int(post.get("sample_height") or post.get("height") or 0)
    if raw_width < 450 or raw_height < 450:
        return False, "too_small", ""

    signature = character_signature(post, crawl_label)
    if signature in seen_signatures:
        return False, "duplicate_character_signature", signature

    if (
        not allow_official_full_body
        and "official_art" not in tags
        and "turnaround" not in tags
        and "character_sheet" not in tags
    ):
        return False, "weak_sheet_signal", signature

    # Build the list of meaningful positive query terms (strip negatives and layout
    # terms that are too generic to distinguish the target series/character)
    query_terms = [term for term in raw_tags.split() if not term.startswith("-") and not term.startswith("rating:")]
    required_query_terms = [
        term
        for term in query_terms
        if term not in {"solo", "full_body", "multiple_views", "official_art", "1girl", "1boy"}
        and term not in SHEET_TAGS
    ]
    # Enforce that at least one series/character term from the query actually appears
    # in the post's tags — this catches borderline results where Safebooru's boolean
    # AND returned a post missing the franchise tag due to incomplete tagging
    if required_query_terms and not any(term in tags for term in required_query_terms):
        return False, "missing_positive_series_tag", signature

    # Record any distinctive anatomical signature features for the selection notes
    signature_hits = sorted(tags & SIGNATURE_FEATURE_TAGS)
    if signature_hits:
        return True, f"prefilter_pass;signature_features:{','.join(signature_hits)}", signature
    return True, "prefilter_pass", signature


def download_image(session: requests.Session, url: str, output_path: Path, overwrite: bool) -> str:
    """Download an image file from a URL with partial-download protection.

    Uses a temporary ``.part`` file during download so interrupted transfers do not
    leave corrupted files on disk. The temporary file is atomically renamed to the
    final path only when the download completes successfully.

    Args:
        session: A ``requests.Session`` with User-Agent already set.
        url: Image URL to download.
        output_path: Target file path; parent directories are created if missing.
        overwrite: If False and ``output_path`` already exists with non-zero size,
                   skip the download and return ``"skipped_existing"``.

    Returns:
        Status string: ``"downloaded"``, ``"skipped_existing"``, ``"missing_url"``,
        or ``"failed:{ExceptionClassName}"`` on network/IO errors.
    """
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
                # 256KB chunks balance memory usage and disk-write overhead
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
    """Compute colour quality metrics for a downloaded image file.

    The image is resized to at most 512x512 before analysis to keep computation fast
    and consistent across files of varying resolution.

    Metrics computed:
        - ``actual_width`` / ``actual_height``: True pixel dimensions of the original.
        - ``sat_mean``: Mean HSV saturation across all pixels, normalised to [0, 1].
          Values below ~0.08 indicate near-greyscale images.
        - ``colorfulness``: Sum of per-channel RGB standard deviation divided by 3,
          plus the max-minus-min channel mean spread.  This captures both inter-pixel
          colour variation and cross-channel colour imbalance.
          Threshold for acceptance: >= 18.0 (empirically chosen to reject monochrome
          and very pale sketch-style images while keeping pastel-toned anime art).
        - ``likely_color``: True when both sat_mean >= 0.08 AND colorfulness >= 18.0.
          Acts as the final colour gate before a post is accepted.

    The dual threshold (saturation AND colorfulness) is intentional:
        - Saturation alone misses highly-desaturated cyan/magenta schemes.
        - Colorfulness alone passes near-white backgrounds with one vivid accent.
        Together they reject greyscale/lineart that slipped past the tag filter.

    Args:
        path: Absolute path to a successfully downloaded image file.

    Returns:
        Dict with keys: ``actual_width``, ``actual_height``, ``sat_mean``,
        ``colorfulness``, ``likely_color``.

    Raises:
        Exception: PIL may raise ``UnidentifiedImageError`` or ``OSError`` for
                   corrupt/unsupported files; callers should catch broadly.
    """
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        sample = rgb.copy()
        # Downsample to 512px for fast per-pixel saturation scan
        sample.thumbnail((512, 512))
        hsv = sample.convert("HSV")
        saturation = list(hsv.getchannel("S").getdata())
        stat = ImageStat.Stat(sample)
        means = stat.mean    # Per-channel RGB mean brightness [0, 255]
        stddev = stat.stddev  # Per-channel RGB standard deviation

        width = rgb.width
        height = rgb.height

    # Normalise saturation from [0, 255] to [0, 1]
    sat_mean = statistics.fmean(saturation) / 255.0 if saturation else 0.0
    # Channel spread = how different the R/G/B average brightnesses are (0 = grey)
    channel_spread = max(means) - min(means)
    # Colorfulness = average per-channel variation + cross-channel spread
    colorfulness = sum(stddev) / 3.0 + channel_spread
    # Combined gate: image must be both saturated AND colourful
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
    """Assemble a complete metadata record for one accepted image.

    Combines Safebooru post fields with crawl context (query, label, signature) and
    computed image metrics into a flat dict that can be written to metadata.jsonl or
    manifest.csv.

    Args:
        post: Raw Safebooru post dict from the API.
        tags_query: The normalised tag query that retrieved this post.
        image_url: The URL that was actually downloaded (sample/file/preview).
        image_path: Local filesystem path where the image was saved.
        status: Download status string (``"downloaded"`` or ``"skipped_existing"``).
        crawl_label: Crawl group label for traceability.
        signature: Character signature from ``character_signature()``.
        metrics: Colour metrics dict from ``image_metrics()``.
        selection_notes: Semicolon-separated notes from prefilter and colour check.

    Returns:
        Flat dict matching the schema defined by MANIFEST_FIELDS.
    """
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
    """Atomically write all accepted rows to metadata.jsonl and manifest.csv.

    Both files are written via a ``.tmp`` temporary file that is renamed to the final
    path only after a complete, successful write. This prevents partial/corrupt files
    if the process is interrupted mid-write.

    Args:
        rows: List of metadata dicts (all accepted images so far, including pre-existing
              rows from ``existing_metadata`` that were merged in by the caller).
        metadata_path: Target ``.jsonl`` file path.
        manifest_path: Target ``.csv`` file path.
    """
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_tmp_path = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
    manifest_tmp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    # Write JSONL first: full fidelity including non-manifest fields like "hash"
    with metadata_tmp_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    metadata_tmp_path.replace(metadata_path)

    # Write CSV with only the declared MANIFEST_FIELDS columns for spreadsheet use
    with manifest_tmp_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in MANIFEST_FIELDS})
    manifest_tmp_path.replace(manifest_path)


def seed_seen_sets(existing_rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """Build the initial deduplication sets from a previously collected metadata file.

    Called at the start of a crawl session to initialise ``seen_ids`` and
    ``seen_signatures`` from any rows loaded via ``--existing-metadata``.  This ensures
    that a resumed or incremental crawl never re-downloads a post or re-accepts a
    character that was already accepted in a prior run.

    Args:
        existing_rows: List of previously accepted metadata dicts, as returned by
                       ``load_jsonl_rows(args.existing_metadata)``.

    Returns:
        Tuple of (seen_ids: set[str], seen_signatures: set[str]).
    """
    seen_ids: set[str] = set()
    seen_signatures: set[str] = set()
    for row in existing_rows:
        post_id = str(row.get("post_id") or "").strip()
        if post_id:
            seen_ids.add(post_id)
        signature = str(row.get("character_signature") or "").strip()
        if signature:
            seen_signatures.add(signature)
    return seen_ids, seen_signatures


def add_explicit_skip_ids(seen_ids: set[str], skip_post_ids: str) -> None:
    """Add manually specified post IDs to the seen-IDs set to force-skip them.

    Provides a command-line escape hatch (``--skip-post-ids``) to exclude specific
    posts without editing any file, useful when a post passed all automated filters
    but should be excluded for manual quality reasons.

    Args:
        seen_ids: Mutable set of post IDs; modified in place.
        skip_post_ids: Comma- or whitespace-separated string of post IDs to skip.
                       Silently ignores empty tokens.
    """
    for post_id in re.split(r"[,\s]+", skip_post_ids.strip()):
        if post_id:
            seen_ids.add(post_id)


def add_rejected_post_ids(seen_ids: set[str], output_dir: Path) -> None:
    """Load a user-curated rejection list and add those post IDs to the seen-IDs set.

    The file ``rejected_post_ids.txt`` in the output directory is an optional manual
    curation tool: one post ID per line, with anything after a ``#`` treated as a
    comment.  This allows users to maintain a persistent rejection list alongside the
    dataset without modifying ``metadata.jsonl`` or re-running the crawler with
    ``--skip-post-ids`` every time.

    Args:
        seen_ids: Mutable set of post IDs; modified in place.
        output_dir: Output directory where ``rejected_post_ids.txt`` may exist.
    """
    path = output_dir / "rejected_post_ids.txt"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        # Strip comments and whitespace; skip empty lines
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
    """Crawl one or more tag query variants until the per-group target count is reached.

    This is the core crawl loop. It implements the multi-query strategy that makes the
    crawler resilient to sparse tag coverage on Safebooru:

    Multi-query strategy:
        Each crawl group provides a list of ``query_variants`` ordered from most to
        least restrictive. The loop tries each variant in sequence, paginating through
        its results until ``target_count`` images have been accepted or
        ``max_pages_per_query`` pages have been scanned for that variant.  As soon as
        the target is reached, the loop exits early without fetching further variants
        or pages, minimising unnecessary API requests.

        Example: a group might have:
            variant 0: "turnaround multiple_views full_body solo 1girl ..."  (strict)
            variant 1: "turnaround multiple_views solo 1girl ..."            (relaxed)
        If variant 0 yields only 5 acceptable posts, variant 1 fills the remaining
        quota from a wider result set.

    Pagination (page_limit=50):
        The Safebooru DAPI returns at most 100 results per page, but 50 is used here.
        Why 50: It provides a coarse-grained page granularity that works reliably across
        different tag query sizes. Very large limits (100) can cause timeouts on rare
        tags, while very small limits (10) increase the number of API round trips
        significantly.  50 is a stable, well-tested compromise.

    Rate limiting:
        - ``request_sleep_seconds``: Optional delay inserted after each API page
          request. Useful when running multiple parallel crawler instances to avoid
          being rate-limited by Safebooru. Default is 0 (no delay), sufficient for
          single-process crawls.
        - ``sleep_seconds``: Delay inserted between individual image downloads (after
          a post is accepted). Default 0.3s prevents burst download patterns that
          could trigger CDN rate limiting.

    Colour gate:
        Even after prefilter passes, each downloaded image is checked with
        ``image_metrics``. Images where ``likely_color`` is False (greyscale or very
        pale) are deleted and skipped. This catches ``greyscale`` images that lack the
        explicit Safebooru tag that ``prefilter_post`` would have caught.

    Deduplication side-effects:
        Both ``seen_ids`` and ``seen_signatures`` are mutated in place when a post is
        accepted. This ensures cross-variant and cross-group deduplication: a character
        accepted via variant 0 will not be re-collected by variant 1.

    Args:
        session: Requests session with User-Agent set.
        crawl_label: Human-readable label for this crawl group, used in progress bars
                     and metadata.
        query_variants: Ordered list of Safebooru tag query strings to try.
        target_count: Stop when this many images have been accepted.
        images_dir: Directory where downloaded images are saved.
        image_kind: Preferred URL kind (``"sample"``, ``"file"``, ``"preview"``).
        overwrite: Whether to re-download already-existing files.
        sleep_seconds: Delay between accepted downloads (rate limiting).
        request_sleep_seconds: Delay after each API page request (rate limiting).
        max_pages_per_query: Hard limit on pages scanned per query variant.
        seen_ids: Shared set of already-accepted post IDs (mutated in place).
        seen_signatures: Shared set of already-accepted character signatures (mutated).
        on_accept: Optional callback invoked with the new metadata row immediately
                   after each accepted image, used for incremental writes.

    Returns:
        List of metadata dicts for newly accepted images (does not include images that
        were already in ``seen_ids``/``seen_signatures`` from prior runs).
    """
    rows: list[dict[str, Any]] = []
    if target_count <= 0:
        return rows

    with tqdm(total=target_count, desc=f"Downloading {crawl_label}", unit="img") as progress:
        for raw_tags in query_variants:
            tags = normalize_tags(raw_tags)
            page = 0
            # Paginate through this variant until target is reached or pages exhausted
            while len(rows) < target_count and page < max_pages_per_query:
                # page_limit=50: stable sweet spot between request count and latency
                posts = fetch_posts(session, tags, page=page, page_limit=50)
                if request_sleep_seconds:
                    # Rate-limiting delay after each API page request
                    time.sleep(request_sleep_seconds)
                if not posts:
                    break  # No more results for this variant; move to next

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
                    # Skip posts where the download failed entirely
                    if not status.startswith(("downloaded", "skipped_existing")):
                        continue

                    try:
                        metrics = image_metrics(output_path)
                    except Exception:
                        # Corrupt or unsupported image format; remove and skip
                        if output_path.exists():
                            output_path.unlink()
                        continue

                    # Final colour gate: reject greyscale/lineart that slipped
                    # through the tag filter (e.g. posts missing the "greyscale" tag)
                    if not metrics["likely_color"]:
                        if output_path.exists():
                            output_path.unlink()
                        continue

                    # Register the accepted post in both deduplication sets
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
                        # Per-download rate-limiting delay to avoid CDN throttling
                        time.sleep(sleep_seconds)

                page += 1
                if len(rows) >= target_count:
                    break

    return rows


def crawl_custom_tags(args: argparse.Namespace, session: requests.Session) -> tuple[Path, list[dict[str, Any]]]:
    """Run a single-query crawl using the custom ``--tags`` argument.

    Used when the user supplies their own tag query rather than selecting a preset.
    The output folder name defaults to a slugified version of the tag query, or can be
    overridden with ``--output-name``.

    Supports incremental writes via the ``on_accept`` callback so that downstream
    workers can begin processing images before the crawl completes.

    Args:
        args: Parsed CLI arguments.
        session: Requests session with User-Agent set.

    Returns:
        Tuple of (output_dir, all_rows) where ``all_rows`` includes both any
        pre-existing rows from ``--existing-metadata`` and newly accepted rows.
    """
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
    """Run a multi-group preset crawl, distributing the target count across groups.

    Each preset (e.g. ``aniplex_supervision_strict``) defines multiple crawl groups
    with different tag queries. The total ``--limit`` is split evenly across groups
    using ``split_counts``. Groups are processed sequentially so that the shared
    ``seen_ids`` / ``seen_signatures`` sets prevent cross-group duplicates.

    Backfill phase:
        If the total accepted count is still below ``--limit`` after all primary
        groups complete (e.g. because some niche groups exhausted their tag corpus
        before hitting their per-group quota), a backfill pass runs a broader set of
        fallback queries to fill the remaining slots. Backfill queries are intentionally
        generic to maximise coverage without polluting the primary group labels.

    Args:
        args: Parsed CLI arguments.
        session: Requests session with User-Agent set.

    Returns:
        Tuple of (output_dir, all_rows) where ``all_rows`` includes both any
        pre-existing rows from ``--existing-metadata`` and newly accepted rows.
    """
    query_groups = preset_query_groups(args.view_preset)
    output_name = args.output_name or DEFAULT_OUTPUT_NAMES[args.view_preset]
    output_dir = args.out_dir / output_name
    # Distribute the total limit across groups; first groups absorb any remainder
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
        # Cap per-group target so late groups can fill slack from under-performing earlier groups
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
        # Primary groups did not reach the target — run a backfill pass with broader queries
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
    """Validate arguments, run the appropriate crawl strategy, and write final outputs.

    This is the top-level orchestration function. It validates all CLI arguments
    before creating any files, then dispatches to either ``crawl_custom_tags`` (for a
    user-supplied ``--tags`` query) or ``crawl_preset`` (for a named preset).

    After crawling, it performs a final atomic write of ``metadata.jsonl`` and
    ``manifest.csv``.  If ``--incremental-write`` was enabled, this final write merges
    the pre-existing rows with the newly collected rows, ensuring a complete file even
    if the incremental writes used a growing-list approach.

    Args:
        args: Validated argument namespace from ``parse_args()``.

    Returns:
        Path to the output directory containing images, metadata.jsonl, and manifest.csv.

    Raises:
        ValueError: If any argument is out of the valid range or both/neither of
                    ``--tags`` and ``--view-preset`` are provided.
    """
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

    # Final authoritative write — overwrites incremental partial files if any
    metadata_path = output_dir / "metadata.jsonl"
    manifest_path = output_dir / "manifest.csv"
    write_outputs(rows, metadata_path, manifest_path)
    return output_dir


def main() -> None:
    """Entry point: parse arguments, run the crawl, and print the output path."""
    args = parse_args()
    output_dir = crawl(args)
    print(f"Saved Safebooru crawl to {output_dir}")


if __name__ == "__main__":
    main()
