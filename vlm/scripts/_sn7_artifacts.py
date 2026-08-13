"""Canonical SN-7 category, suffix, and generated-image artifact helpers."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


CATEGORIES = (
    "head_key_chain",
    "cake_roll",
    "backpack",
    "plush",
    "dataset_QSitFigures",
    "dataset_figurine",
)
HEAD_ONLY_CATEGORIES = CATEGORIES[:3]
FULL_BODY_CATEGORIES = CATEGORIES[3:]
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
CATEGORY_OUTPUT_SUFFIXES = {
    "head_key_chain": "head_keychain",
    "cake_roll": "cake_roll",
    "backpack": "backpack",
    "plush": "plush",
    "dataset_QSitFigures": "SitFigures",
    "dataset_figurine": "figurine",
}


def output_suffix_for_category(category: str) -> str:
    """Return the canonical generated-output suffix for one SN-7 category."""
    try:
        return CATEGORY_OUTPUT_SUFFIXES[category]
    except KeyError as exc:
        raise ValueError(f"Unsupported SN-7 category: {category!r}") from exc


def validate_category_suffix(category: str, output_suffix: str | None) -> str:
    """Return the canonical suffix, rejecting explicit category/suffix mismatches."""
    canonical = output_suffix_for_category(category)
    if output_suffix is None or str(output_suffix).strip() == "":
        return canonical
    provided = str(output_suffix).strip()
    if provided != canonical:
        raise ValueError(
            f"--output-suffix {provided!r} does not match category {category!r}; "
            f"expected {canonical!r}"
        )
    return canonical


def valid_image(path: Path) -> bool:
    """Return whether a path is a non-empty readable raster image."""
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        with Image.open(path) as image:
            image.verify()
    except Exception:
        return False
    return True


def find_generated_output(sample_dir: Path, sample_id: str, output_suffix: str) -> Path | None:
    """Find the first valid canonical generated image in one sample directory."""
    for suffix in IMAGE_SUFFIXES:
        candidate = sample_dir / f"{sample_id}_{output_suffix}{suffix}"
        if valid_image(candidate):
            return candidate
    return None


def find_category_generated_output(root: Path, category: str, sample_id: str) -> Path | None:
    """Find the valid generated image for ``root/<category>/<sample_id>``."""
    return find_generated_output(
        root / category / sample_id,
        sample_id,
        output_suffix_for_category(category),
    )
