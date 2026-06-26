"""Generate Qwen atomic rules for raw_trials and compare them with trial annotations."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from atomic_rules_qwen_shared import (
    DEFAULT_SOURCE_TAG_HINTS,
    call_qwen_atomic_rules,
    normalize_label,
    normalize_rule_doc,
    normalize_value,
)


SEMANTIC_FACET_ORDER = [
    "hair.length",
    "hair.color",
    "hair.shape",
    "eyes.shape",
    "eyes.color",
    "mouth.shape",
    "skin.color",
    "head_accessory.type",
    "head_accessory.color",
    "face_signature.type",
    "face_signature.color",
    "face_signature.position",
    "outfit.shape",
    "outfit.color",
    "body_accessory.type",
    "body_accessory.color",
    "body_signature.type",
    "body_signature.color",
    "body_signature.position",
    "key_elements",
]
LENGTH_LIKE_VALUES = {
    "short",
    "medium",
    "long",
    "very_long",
    "waist_length",
    "shoulder_length",
    "neck",
    "very_short",
}
UNCOMPARABLE_VALUES = {
    "not_visible",
    "replaced_by_mechanical_features",
    "unknown_due_to_blur",
    "unviewable",
}
FACET_VALUE_ALIASES = {
    "hair.length": {
        "short_to_medium": "medium",
        "short_hair": "short",
        "medium_hair": "medium",
        "long_hair": "long",
        "very_long": "long",
        "waist_length": "long",
        "shoulder_length": "medium",
        "neck_length": "short",
        "neck": "short",
        "very_short": "short",
    },
    "hair.shape": {
        "asymmetric": "asymmetry",
        "blunt": "blunt_cut",
        "bob": "bob_cut",
        "braided_twintails": "twintails",
        "full_bangs": "straight_bangs",
        "jagged": "uneven_strands",
        "natural": "spikes",
        "spiky": "spikes",
        "spiky_hair": "spikes",
        "straight_bang": "straight_bangs",
        "twin_tail": "twintails",
        "twin": "twintails",
        "loose_waves": "wavy",
        "side_swept_bangs": "side_swept",
        "front_bang": "front_bangs",
        "front_bang_detail": "front_bangs",
    },
    "hair.color": {
        "blond": "blonde",
        "dark_blue": "blue",
        "light_blue": "blue",
        "navy": "blue",
        "navy_blue": "blue",
        "dark_purple": "purple",
        "light_purple": "purple",
        "dark_brown": "brown",
        "light_brown": "brown",
        "reddish_brown": "brown",
        "white_blonde": "blonde",
    },
    "eyes.shape": {
        "almond_shaped": "almond",
        "rounded": "round",
    },
    "eyes.color": {
        "dark": "black",
        "dark_brown": "brown",
        "light_brown": "brown",
        "dark_blue": "blue",
        "light_blue": "blue",
        "dark_purple": "purple",
        "light_purple": "purple",
    },
    "skin.color": {
        "light": "fair",
        "fair": "fair",
        "light_peach": "fair",
        "pale": "fair",
        "peach": "fair",
        "ivory": "fair",
        "beige": "fair",
        "warm_beige": "fair",
        "light_tan": "tan",
        "wheat": "tan",
        "wheatish": "tan",
        "tanned": "tan",
        "brown": "dark",
        "dark_skin": "dark",
        "dark_brown": "dark",
        "deep_brown": "dark",
        "metallic_gray": "dark",
        "metallic_grey": "dark",
        "grey": "dark",
        "gray": "dark",
    },
    "head_accessory.type": {
        "bunny_ears_head_accessory": "bunny_ears",
        "cat_ear_headband": "headband",
        "headband_frills": "headband",
        "headband_inner": "headband",
        "head_ribbon": "ribbon",
        "hair_ribbon": "ribbon",
        "hair_ribbons": "ribbon",
        "ribbons": "ribbon",
        "head_bow": "bow",
        "hair_bow": "bow",
        "hair_bows": "bow",
        "hair_clip": "hairpin",
        "hair_ornament": "hairpin",
        "rose_hair_accessory": "rose",
        "star_hair_clip": "star_hairpin",
        "skull_hair_accessory": "skull_hairpin",
        "skull_hair_pin": "skull_hairpin",
        "skull_accessory": "skull_hairpin",
        "wide_brimmed_hat": "hat",
        "witch_hat": "pointed_hat",
    },
    "outfit.shape": {
        "apron_dress": "dress",
        "ball_gown": "dress",
        "cardigan": "school_uniform",
        "hooded_robe": "hooded_cape_outfit",
        "long_sleeve_shirt": "shirt",
        "overalls": "overall",
        "pleated_skirt": "skirt",
        "robe": "hooded_cape_outfit",
        "sailor_suit": "sailor_uniform",
        "sailor_collar": "school_uniform",
        "trench_coat": "coat",
    },
    "outfit.color": {
        "dark_blue": "blue",
        "light_blue": "blue",
        "navy": "blue",
        "navy_blue": "blue",
        "dark_brown": "brown",
        "light_brown": "brown",
        "dark_green": "green",
        "light_green": "green",
        "dark_grey": "gray",
        "grey": "gray",
        "maroon": "red",
    },
    "body_signature.type": {
        "back_wings": "wing",
        "horn": "horn",
        "horns": "horn",
        "horn_like_shape": "horn",
        "multiple_tails": "tail",
        "ribbon_tail": "tail",
        "wings": "wing",
    },
    "key_elements": {
        "chest_tag": "tag",
        "neck_tag": "tag",
        "nectar_shaped_tag_necklace": "tag",
        "yellow_tag": "tag",
    },
}
FACET_NEAR_VALUE_GROUPS = {
    "hair.shape": [
        {"loose_hair", "front_bangs", "side_layers", "wavy"},
        {"side_swept", "side_swept_bangs"},
        {"blunt_cut", "bob_cut", "straight_bangs"},
        {"jagged", "spikes", "spiky", "spiky_hair", "uneven_strands"},
        {"asymmetry", "asymmetric"},
    ],
    "hair.color": [
        {"black", "dark"},
        {"blonde", "yellow", "gold"},
        {"blue", "dark_blue", "light_blue", "navy", "navy_blue"},
        {"brown", "dark_brown", "light_brown", "reddish_brown"},
        {"pink", "light_pink"},
        {"purple", "dark_purple", "light_purple"},
        {"gold", "yellow"},
        {"gray", "silver"},
        {"white", "silver"},
    ],
    "eyes.color": [
        {"black", "dark"},
        {"blue", "dark_blue", "light_blue"},
        {"brown", "dark_brown", "light_brown"},
        {"purple", "dark_purple", "light_purple"},
        {"gold", "yellow"},
        {"gray", "silver"},
    ],
    "outfit.color": [
        {"black", "dark_grey", "gray", "grey"},
        {"blue", "dark_blue", "light_blue", "navy", "navy_blue"},
        {"brown", "dark_brown", "light_brown"},
        {"gold", "yellow"},
        {"gray", "silver"},
        {"cream", "beige"},
        {"maroon", "red"},
        {"pink", "light_pink"},
        {"purple", "dark_purple"},
    ],
    "head_accessory.color": [
        {"gold", "yellow"},
        {"gray", "silver"},
    ],
    "head_accessory.type": [
        {"bow", "ribbon"},
        {"hair_clip", "hairpin"},
        {"star_hair_clip", "star_hairpin"},
    ],
    "body_accessory.color": [
        {"gold", "yellow"},
        {"gray", "silver"},
    ],
    "face_signature.color": [
        {"gold", "yellow"},
        {"gray", "silver"},
    ],
    "body_signature.color": [
        {"gold", "yellow"},
        {"gray", "silver"},
    ],
    "outfit.shape": [
        {"ball_gown", "dress"},
        {"casual", "dress", "shirt"},
        {"combat_oriented_attire", "combat_mage_inspired_attire", "regal_warrior_outfit"},
        {"hooded_cape_outfit", "hooded_robe", "robe"},
        {"overall", "overalls"},
        {"sailor_uniform", "sailor_suit", "school_uniform"},
        {"two_piece", "pink_set"},
    ],
    "key_elements": [
        {"chest_tag", "neck_tag", "nectar_shaped_tag_necklace", "tag", "yellow_tag"},
        {"shirt", "inner_shirt", "inner_top"},
    ],
}
HEAD_ACCESSORY_KEYWORDS = {
    "ribbon",
    "bow",
    "headband",
    "hair_tie",
    "hairpin",
    "hair_pin",
    "hair_clip",
    "hair_accessory",
    "head_accessory",
    "bonnet",
    "rose",
    "tiara",
    "hat",
    "monocle",
    "earring",
    "flower_crown",
    "feather",
    "clip",
    "crown",
    "hair",
}
BODY_ACCESSORY_KEYWORDS = {
    "fan",
    "book",
    "notebook",
    "weapon",
    "papers",
    "sword",
    "bag",
    "handbag",
    "backpack",
    "schoolbag",
    "umbrella",
    "glove",
    "gloves",
    "belt",
    "choker",
    "necklace",
    "sheath",
    "tassel",
    "armor",
}
FACE_SIGNATURE_KEYWORDS = {
    "scar",
    "mole",
    "birthmark",
    "freckle",
    "facial_mark",
    "face_mark",
    "marking",
    "mechanical_head",
    "head_object",
    "revolver_gun",
}
BODY_SIGNATURE_KEYWORDS = {
    "horn",
    "horns",
    "tail",
    "wing",
    "wings",
    "tattoo",
    "mechanical_arm",
    "mechanical_leg",
    "mechanical_wing",
    "prosthetic",
    "cyborg",
}
KEY_ELEMENT_HINTS = {
    "symbol",
    "design",
    "decal",
    "pattern",
    "charm",
    "tag",
    "crest",
    "emblem",
}
BODY_LOCAL_ITEM_PREFIXES = {
    "alternate_outfit",
    "bottom",
    "chest",
    "collar",
    "cuff",
    "dress",
    "footwear",
    "headwear",
    "hem",
    "inner",
    "inner_shirt",
    "inner_top",
    "jacket",
    "legwear",
    "lower_body",
    "main_outfit",
    "neckline",
    "neckwear",
    "outerwear",
    "pants",
    "shoe",
    "skirt",
    "sleeve",
    "sock",
    "top",
    "uniform",
    "upper_body",
    "vest",
}
LOW_PRIORITY_BODY_DETAIL_ITEMS = {
    "collar_trim",
    "dress",
    "footwear",
    "headwear_trim",
    "hem_trim",
    "inner_shirt",
    "inner_top",
    "jacket",
    "jacket_trim",
    "legwear",
    "neckwear",
    "outerwear_trim",
    "pants",
    "shoe",
    "skirt_hem",
    "skirt_hem_trim",
    "sock",
    "sock_trim",
    "top",
}
LOW_PRIORITY_BODY_DETAIL_ITEM_PREFIXES = {
    "collar_trim",
    "cuff",
    "footwear",
    "headwear_trim",
    "hem_trim",
    "jacket_trim",
    "legwear",
    "neckline",
    "shoe",
    "skirt_hem",
    "sock",
    "top",
    "uniform_button",
    "uniform_collar",
}
LOW_PRIORITY_BODY_DETAIL_RULE_PREFIXES = {
    "alternate_outfit_footwear",
    "bottom_type",
    "collar_trim",
    "cuff",
    "footwear",
    "glove_type",
    "hair_clip_side",
    "hair_ends",
    "headband_pattern",
    "headwear_trim",
    "hem_trim",
    "inner_top_sleeve",
    "jacket_trim",
    "legwear",
    "neckwear",
    "outerwear_trim",
    "shoe",
    "skirt_hem",
    "skirt_length",
    "skirt_pattern",
    "sock",
    "socks",
    "top_sleeve",
    "uniform_button",
    "waist_belt",
}
OUTFIT_COLOR_ITEMS = {
    "clothing",
    "clothing_main",
    "dress",
    "inner_shirt",
    "inner_top",
    "jacket",
    "outerwear",
    "skirt",
    "top",
    "uniform_main",
}
OUTFIT_TYPE_RULE_IDS = {
    "alternate_outfit_bottom_type",
    "bottom_type",
    "inner_shirt_type",
    "inner_top_type",
    "jacket_type",
    "lower_body_clothing",
    "main_outfit_type",
    "outerwear_type",
    "skirt_type",
    "top_style",
    "uniform_collar_type",
    "upper_body_clothing",
}
KEY_ELEMENT_RULE_IDS = {
    "bag_pattern",
    "bib_pocket",
    "cuff_emblem_shape",
    "chest_armor_symbol",
    "chest_strap_pattern",
    "neck_tag_color",
    "pants_style",
    "weapon_type",
}
BOOLEAN_RULE_VALUE_OVERRIDES = {
    "hair_bang_asymmetry": "asymmetry",
    "hair_bang_uneven_strands": "uneven_strands",
    "hair_bang_face_side": "face_side",
    "hair_bang_jagged": "jagged",
    "hair_bang_type_asymmetric": "asymmetric",
    "eye_shape_round": "round",
    "outfit_type_with_shirt": "shirt",
    "has_side_layering": "side_layering",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate qwen_atomic_rules for raw_trials and compare them with existing atomic_rules."
    )
    parser.add_argument("--root", type=Path, default=Path("vlm/data/raw_trials"))
    parser.add_argument("--report-dir", type=Path, default=Path("vlm/data/raw_trials/qwen_comparison_reports"))
    parser.add_argument("--model", default="qwen3.5-plus")
    parser.add_argument("--limit", type=int, default=0, help="0 means all samples.")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.4)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--write-debug-files",
        action="store_true",
        help="Also write per-sample raw_response and comparison debug files.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args()


def discover_samples(root: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for atomic_path in sorted(root.rglob("*_atomic_rules.json")):
        if atomic_path.name.endswith("_qwen_atomic_rules.json"):
            continue
        code = atomic_path.name.removesuffix("_atomic_rules.json")
        sample_dir = atomic_path.parent
        image_path = locate_original_image(sample_dir, code)
        if not image_path:
            continue
        samples.append(
            {
                "code": code,
                "sample_dir": sample_dir,
                "atomic_path": atomic_path,
                "image_path": image_path,
                "relative_dir": sample_dir.relative_to(root).as_posix(),
                "dataset_name": sample_dir.parent.name,
            }
        )
    return samples


def locate_original_image(sample_dir: Path, code: str) -> Path | None:
    exact = sorted(sample_dir.glob(f"{code}_original.*"))
    if exact:
        return exact[0]
    fallback = sorted(sample_dir.glob("*_original.*"))
    if fallback:
        return fallback[0]
    return None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def prepare_qwen_input(image_path: Path, code: str) -> Path:
    temp_dir = Path(tempfile.gettempdir()) / "qwen_raw_trials_inputs"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{code}.png"

    with Image.open(image_path) as image:
        if getattr(image, "is_animated", False):
            image.seek(0)
        converted = image.convert("RGBA")
        converted.save(temp_path, format="PNG")
    return temp_path


def rule_value_text(value: Any) -> str:
    return "true" if value is True else str(value)


def rule_pairs(doc: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for rule in doc.get("atomic_rules", []):
        pairs.add((rule["id"], rule_value_text(rule["value"])))
    return pairs


def rules_by_id(doc: dict[str, Any]) -> dict[str, set[str]]:
    bucket: dict[str, set[str]] = {}
    for rule in doc.get("atomic_rules", []):
        bucket.setdefault(rule["id"], set()).add(rule_value_text(rule["value"]))
    return bucket


def compare_legacy_docs(original_doc: dict[str, Any], qwen_doc: dict[str, Any]) -> dict[str, Any]:
    original_pairs = rule_pairs(original_doc)
    qwen_pairs = rule_pairs(qwen_doc)
    exact_matches = sorted(original_pairs & qwen_pairs)
    missing_pairs = sorted(original_pairs - qwen_pairs)
    extra_pairs = sorted(qwen_pairs - original_pairs)

    original_by_id = rules_by_id(original_doc)
    qwen_by_id = rules_by_id(qwen_doc)
    changed_ids = sorted(
        rule_id
        for rule_id in (set(original_by_id) & set(qwen_by_id))
        if original_by_id[rule_id] != qwen_by_id[rule_id]
    )
    changed_details = [
        {
            "id": rule_id,
            "original_values": sorted(original_by_id[rule_id]),
            "qwen_values": sorted(qwen_by_id[rule_id]),
        }
        for rule_id in changed_ids
    ]

    union_pairs = original_pairs | qwen_pairs
    jaccard = len(exact_matches) / len(union_pairs) if union_pairs else 1.0
    coverage = len(exact_matches) / len(original_pairs) if original_pairs else 1.0
    return {
        "summary": {
            "original_rule_count": len(original_pairs),
            "qwen_rule_count": len(qwen_pairs),
            "exact_match_count": len(exact_matches),
            "missing_from_qwen_count": len(missing_pairs),
            "extra_from_qwen_count": len(extra_pairs),
            "changed_value_id_count": len(changed_ids),
            "pair_jaccard_score": round(jaccard, 4),
            "original_coverage_score": round(coverage, 4),
        },
        "exact_matches": [{"id": rule_id, "value": value} for rule_id, value in exact_matches],
        "missing_from_qwen": [{"id": rule_id, "value": value} for rule_id, value in missing_pairs],
        "extra_from_qwen": [{"id": rule_id, "value": value} for rule_id, value in extra_pairs],
        "changed_value_ids": changed_details,
    }


def canonicalize_facet_value(facet: str, value: Any) -> str | None:
    normalized = normalize_value(value)
    if normalized is None:
        return None
    text = rule_value_text(normalized)
    if text in UNCOMPARABLE_VALUES:
        return None
    return FACET_VALUE_ALIASES.get(facet, {}).get(text, text)


def add_canonical_entry(
    entries: list[dict[str, str]],
    facet: str,
    value: str | None,
    source_id: str,
    source_value: str,
) -> None:
    if not value:
        return
    entries.append(
        {
            "facet": facet,
            "value": value,
            "source_id": source_id,
            "source_value": source_value,
        }
    )


def add_unaligned_rule(
    unaligned: list[dict[str, str]],
    rule_id: str,
    source_value: str,
    source_side: str,
    reason: str,
) -> None:
    unaligned.append(
        {
            "id": rule_id,
            "value": source_value,
            "source_side": source_side,
            "reason": reason,
        }
    )


def clean_item_name(item: str) -> str:
    normalized = normalize_label(item) or item
    if normalized.startswith("has_"):
        normalized = normalized.removeprefix("has_")
    return normalized.strip("_")


def item_starts_with_any(item: str, prefixes: set[str]) -> bool:
    return any(item == prefix or item.startswith(f"{prefix}_") for prefix in prefixes)


def is_low_priority_body_detail_item(item: str) -> bool:
    cleaned = clean_item_name(item)
    return cleaned in LOW_PRIORITY_BODY_DETAIL_ITEMS or item_starts_with_any(cleaned, LOW_PRIORITY_BODY_DETAIL_ITEM_PREFIXES)


def is_low_priority_body_detail_rule(rule_id: str) -> bool:
    cleaned = clean_item_name(rule_id)
    return item_starts_with_any(cleaned, LOW_PRIORITY_BODY_DETAIL_RULE_PREFIXES)


def classify_item(item: str) -> str:
    cleaned = clean_item_name(item)
    if cleaned in FACE_SIGNATURE_KEYWORDS or any(keyword in cleaned for keyword in FACE_SIGNATURE_KEYWORDS):
        return "face_signature"
    if cleaned in BODY_SIGNATURE_KEYWORDS or any(keyword in cleaned for keyword in BODY_SIGNATURE_KEYWORDS):
        return "body_signature"
    if any(keyword in cleaned for keyword in KEY_ELEMENT_HINTS):
        return "key_elements"
    if cleaned == "mechanical_head":
        return "face_signature"
    if item_starts_with_any(cleaned, BODY_LOCAL_ITEM_PREFIXES):
        return "body_accessory"
    if any(keyword in cleaned for keyword in HEAD_ACCESSORY_KEYWORDS):
        return "head_accessory"
    if any(keyword in cleaned for keyword in BODY_ACCESSORY_KEYWORDS):
        return "body_accessory"
    return "body_accessory"


def bool_descriptor(rule_id: str) -> str | None:
    if rule_id in BOOLEAN_RULE_VALUE_OVERRIDES:
        return BOOLEAN_RULE_VALUE_OVERRIDES[rule_id]
    if rule_id.startswith("has_"):
        return clean_item_name(rule_id.removeprefix("has_"))
    return None


def classify_boolean_has_rule(entries: list[dict[str, str]], rule_id: str, source_value: str) -> bool:
    if rule_id.startswith("has_"):
        item = clean_item_name(rule_id.removeprefix("has_"))
        if is_low_priority_body_detail_item(item):
            return True
        category = classify_item(item)
        if category == "head_accessory":
            add_canonical_entry(
                entries,
                "head_accessory.type",
                canonicalize_facet_value("head_accessory.type", item),
                rule_id,
                source_value,
            )
            return True
        if category == "body_accessory":
            add_canonical_entry(entries, "body_accessory.type", item, rule_id, source_value)
            return True
        if category == "face_signature":
            add_canonical_entry(
                entries,
                "face_signature.type",
                canonicalize_facet_value("face_signature.type", item),
                rule_id,
                source_value,
            )
            return True
        if category == "body_signature":
            add_canonical_entry(
                entries,
                "body_signature.type",
                canonicalize_facet_value("body_signature.type", item),
                rule_id,
                source_value,
            )
            return True
        if category == "key_elements":
            add_canonical_entry(
                entries,
                "key_elements",
                canonicalize_facet_value("key_elements", item),
                rule_id,
                source_value,
            )
            return True
    return False


def canonicalize_generic_item_rule(
    entries: list[dict[str, str]],
    rule_id: str,
    source_value: str,
) -> bool:
    if rule_id.endswith("_color") and rule_id not in {"hair_color", "eye_color", "skin_color", "outfit_color"}:
        item = clean_item_name(rule_id.removesuffix("_color"))
        if item in OUTFIT_COLOR_ITEMS:
            add_canonical_entry(entries, "outfit.color", canonicalize_facet_value("outfit.color", source_value), rule_id, source_value)
            return True
        if is_low_priority_body_detail_item(item):
            return True
        category = classify_item(item)
        if category == "head_accessory":
            add_canonical_entry(
                entries,
                "head_accessory.type",
                canonicalize_facet_value("head_accessory.type", item),
                rule_id,
                source_value,
            )
            add_canonical_entry(entries, "head_accessory.color", source_value, rule_id, source_value)
            return True
        if category == "body_accessory":
            add_canonical_entry(entries, "body_accessory.type", item, rule_id, source_value)
            add_canonical_entry(entries, "body_accessory.color", source_value, rule_id, source_value)
            return True
        if category == "face_signature":
            add_canonical_entry(
                entries,
                "face_signature.type",
                canonicalize_facet_value("face_signature.type", item),
                rule_id,
                source_value,
            )
            add_canonical_entry(entries, "face_signature.color", source_value, rule_id, source_value)
            return True
        if category == "body_signature":
            add_canonical_entry(
                entries,
                "body_signature.type",
                canonicalize_facet_value("body_signature.type", item),
                rule_id,
                source_value,
            )
            add_canonical_entry(entries, "body_signature.color", source_value, rule_id, source_value)
            return True

    if rule_id.endswith("_position") or rule_id.endswith("_location"):
        suffix = "_position" if rule_id.endswith("_position") else "_location"
        item = clean_item_name(rule_id.removesuffix(suffix))
        if is_low_priority_body_detail_item(item):
            return True
        category = classify_item(item)
        if category == "face_signature":
            add_canonical_entry(entries, "face_signature.position", source_value, rule_id, source_value)
            return True
        if category == "body_signature":
            add_canonical_entry(entries, "body_signature.position", source_value, rule_id, source_value)
            return True
        if category == "key_elements":
            add_canonical_entry(entries, "key_elements", f"{item}_{source_value}", rule_id, source_value)
            return True

    if rule_id.endswith("_shape") or rule_id.endswith("_shape_detail"):
        suffix = "_shape_detail" if rule_id.endswith("_shape_detail") else "_shape"
        item = clean_item_name(rule_id.removesuffix(suffix))
        if is_low_priority_body_detail_item(item):
            return True
        category = classify_item(item)
        combined = clean_item_name(f"{source_value}_{item}")
        if category == "head_accessory":
            add_canonical_entry(
                entries,
                "head_accessory.type",
                canonicalize_facet_value("head_accessory.type", combined),
                rule_id,
                source_value,
            )
            return True
        if category == "body_accessory":
            add_canonical_entry(entries, "body_accessory.type", combined, rule_id, source_value)
            return True
        if category == "face_signature":
            add_canonical_entry(entries, "face_signature.type", combined, rule_id, source_value)
            return True
        if category == "body_signature":
            add_canonical_entry(entries, "body_signature.type", combined, rule_id, source_value)
            return True
    return False


def canonicalize_direct_rule(
    entries: list[dict[str, str]],
    rule_id: str,
    source_value: str,
) -> bool:
    if rule_id in {"hair_length", "hair_length_detail"}:
        add_canonical_entry(entries, "hair.length", canonicalize_facet_value("hair.length", source_value), rule_id, source_value)
        return True
    if rule_id == "hair_color":
        add_canonical_entry(entries, "hair.color", canonicalize_facet_value("hair.color", source_value), rule_id, source_value)
        return True
    if rule_id in {"hair_style", "hair_shape"}:
        facet = "hair.length" if source_value in LENGTH_LIKE_VALUES else "hair.shape"
        add_canonical_entry(entries, facet, canonicalize_facet_value(facet, source_value), rule_id, source_value)
        return True
    if rule_id.startswith("hair_bang"):
        descriptor = bool_descriptor(rule_id) if source_value == "true" else source_value
        add_canonical_entry(entries, "hair.shape", canonicalize_facet_value("hair.shape", descriptor), rule_id, source_value)
        return True
    if rule_id in {"bangs_style", "bang_style", "hair_texture"}:
        add_canonical_entry(entries, "hair.shape", canonicalize_facet_value("hair.shape", source_value), rule_id, source_value)
        return True
    if rule_id in {"front_bangs", "full_bangs", "short_bangs", "side_bangs"} and source_value == "true":
        add_canonical_entry(entries, "hair.shape", canonicalize_facet_value("hair.shape", rule_id), rule_id, source_value)
        return True
    if rule_id == "mouth_shape":
        add_canonical_entry(entries, "mouth.shape", canonicalize_facet_value("mouth.shape", source_value), rule_id, source_value)
        return True
    if rule_id in {"skin_tone", "skin_color"}:
        add_canonical_entry(entries, "skin.color", canonicalize_facet_value("skin.color", source_value), rule_id, source_value)
        return True
    if rule_id in {"outfit_shape", "outfit_type", "outfit_type_detail", "clothing_type", "clothing_shape"}:
        add_canonical_entry(entries, "outfit.shape", canonicalize_facet_value("outfit.shape", source_value), rule_id, source_value)
        return True
    if rule_id in OUTFIT_TYPE_RULE_IDS:
        add_canonical_entry(entries, "outfit.shape", canonicalize_facet_value("outfit.shape", source_value), rule_id, source_value)
        return True
    if rule_id == "outfit_type_with_shirt" and source_value == "true":
        add_canonical_entry(entries, "outfit.shape", "shirt", rule_id, source_value)
        return True
    if rule_id.startswith("outfit_main_color_") or rule_id == "outfit_color":
        add_canonical_entry(entries, "outfit.color", canonicalize_facet_value("outfit.color", source_value), rule_id, source_value)
        return True
    if rule_id == "key_element":
        add_canonical_entry(entries, "key_elements", canonicalize_facet_value("key_elements", source_value), rule_id, source_value)
        return True
    if rule_id == "head_accessory_type":
        add_canonical_entry(entries, "head_accessory.type", canonicalize_facet_value("head_accessory.type", source_value), rule_id, source_value)
        return True
    if rule_id == "head_accessory_color":
        add_canonical_entry(entries, "head_accessory.color", canonicalize_facet_value("head_accessory.color", source_value), rule_id, source_value)
        return True
    if rule_id == "face_signature_feature_type":
        add_canonical_entry(entries, "face_signature.type", canonicalize_facet_value("face_signature.type", source_value), rule_id, source_value)
        return True
    if rule_id == "face_signature_feature_color":
        add_canonical_entry(entries, "face_signature.color", canonicalize_facet_value("face_signature.color", source_value), rule_id, source_value)
        return True
    if rule_id == "face_signature_feature_position":
        add_canonical_entry(entries, "face_signature.position", canonicalize_facet_value("face_signature.position", source_value), rule_id, source_value)
        return True
    if rule_id in {"outfit_pattern_type", "outfit_pattern_position"}:
        add_canonical_entry(entries, "key_elements", canonicalize_facet_value("key_elements", source_value), rule_id, source_value)
        return True
    if rule_id in KEY_ELEMENT_RULE_IDS:
        add_canonical_entry(entries, "key_elements", canonicalize_facet_value("key_elements", source_value), rule_id, source_value)
        return True
    if rule_id == "head_object":
        add_canonical_entry(entries, "face_signature.type", canonicalize_facet_value("face_signature.type", source_value), rule_id, source_value)
        return True
    if rule_id == "body_accessory_type":
        add_canonical_entry(entries, "body_accessory.type", canonicalize_facet_value("body_accessory.type", source_value), rule_id, source_value)
        return True
    if rule_id == "body_accessory_color":
        add_canonical_entry(entries, "body_accessory.color", canonicalize_facet_value("body_accessory.color", source_value), rule_id, source_value)
        return True
    if rule_id == "body_signature_feature_type":
        add_canonical_entry(entries, "body_signature.type", canonicalize_facet_value("body_signature.type", source_value), rule_id, source_value)
        return True
    if rule_id == "body_signature_feature_color":
        add_canonical_entry(entries, "body_signature.color", canonicalize_facet_value("body_signature.color", source_value), rule_id, source_value)
        return True
    if rule_id == "body_signature_feature_position":
        add_canonical_entry(entries, "body_signature.position", canonicalize_facet_value("body_signature.position", source_value), rule_id, source_value)
        return True
    return False


def resolve_eye_rules(
    entries: list[dict[str, str]],
    unaligned: list[dict[str, str]],
    deferred: dict[str, list[dict[str, str]]],
    source_side: str,
) -> None:
    for kind in ("shape", "color"):
        generic = deferred.get(f"generic_{kind}", [])
        left = deferred.get(f"left_{kind}", [])
        right = deferred.get(f"right_{kind}", [])
        facet = f"eyes.{kind}"

        if generic:
            for item in generic:
                add_canonical_entry(entries, facet, item["value"], item["id"], item["source_value"])
            continue

        left_values = {item["value"] for item in left}
        right_values = {item["value"] for item in right}
        if left and right:
            if left_values == right_values:
                for value in sorted(left_values):
                    add_canonical_entry(entries, facet, value, f"both_{kind}", value)
            else:
                for item in [*left, *right]:
                    add_unaligned_rule(
                        unaligned,
                        item["id"],
                        item["source_value"],
                        source_side,
                        f"side_specific_eye_{kind}",
                    )
            continue

        single_side = left or right
        if single_side:
            for item in single_side:
                add_canonical_entry(entries, facet, item["value"], item["id"], item["source_value"])


def canonicalize_doc(doc: dict[str, Any], source_side: str) -> dict[str, Any]:
    entries: list[dict[str, str]] = []
    unaligned: list[dict[str, str]] = []
    deferred_eyes = {
        "generic_shape": [],
        "generic_color": [],
        "left_shape": [],
        "right_shape": [],
        "left_color": [],
        "right_color": [],
    }

    for rule in doc.get("atomic_rules", []):
        rule_id = rule["id"]
        source_value = rule_value_text(rule["value"])
        value = normalize_value(rule["value"])
        if value is None and source_value != "true":
            add_unaligned_rule(unaligned, rule_id, source_value, source_side, "value_not_normalizable")
            continue

        if rule_id.startswith("eye_shape"):
            descriptor = bool_descriptor(rule_id) if source_value == "true" else source_value
            canonical_value = canonicalize_facet_value("eyes.shape", source_value)
            if descriptor is not None:
                canonical_value = canonicalize_facet_value("eyes.shape", descriptor)
            if canonical_value:
                deferred_eyes["generic_shape"].append(
                    {"id": rule_id, "value": canonical_value, "source_value": source_value}
                )
            continue
        if rule_id == "eye_color":
            canonical_value = canonicalize_facet_value("eyes.color", source_value)
            if canonical_value:
                deferred_eyes["generic_color"].append(
                    {"id": rule_id, "value": canonical_value, "source_value": source_value}
                )
            continue
        if rule_id.startswith("left_eye_shape"):
            canonical_value = canonicalize_facet_value("eyes.shape", source_value)
            if canonical_value:
                deferred_eyes["left_shape"].append(
                    {"id": rule_id, "value": canonical_value, "source_value": source_value}
                )
            continue
        if rule_id.startswith("right_eye_shape"):
            canonical_value = canonicalize_facet_value("eyes.shape", source_value)
            if canonical_value:
                deferred_eyes["right_shape"].append(
                    {"id": rule_id, "value": canonical_value, "source_value": source_value}
                )
            continue
        if rule_id.startswith("left_eye_color"):
            canonical_value = canonicalize_facet_value("eyes.color", source_value)
            if canonical_value:
                deferred_eyes["left_color"].append(
                    {"id": rule_id, "value": canonical_value, "source_value": source_value}
                )
            continue
        if rule_id.startswith("right_eye_color"):
            canonical_value = canonicalize_facet_value("eyes.color", source_value)
            if canonical_value:
                deferred_eyes["right_color"].append(
                    {"id": rule_id, "value": canonical_value, "source_value": source_value}
                )
            continue

        if canonicalize_direct_rule(entries, rule_id, source_value):
            continue

        if source_value == "true" and classify_boolean_has_rule(entries, rule_id, source_value):
            continue

        if source_value == "true":
            descriptor = bool_descriptor(rule_id)
            if descriptor:
                add_canonical_entry(
                    entries,
                    "hair.shape",
                    canonicalize_facet_value("hair.shape", descriptor),
                    rule_id,
                    source_value,
                )
                continue

        if canonicalize_generic_item_rule(entries, rule_id, source_value):
            continue

        if is_low_priority_body_detail_rule(rule_id):
            continue

        add_unaligned_rule(unaligned, rule_id, source_value, source_side, "no_canonical_facet_mapping")

    resolve_eye_rules(entries, unaligned, deferred_eyes, source_side)

    unique_entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        key = json.dumps([entry["facet"], entry["value"]], ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        unique_entries.append(entry)

    facets: dict[str, list[str]] = {}
    for entry in unique_entries:
        facets.setdefault(entry["facet"], []).append(entry["value"])
    for facet in facets:
        facets[facet] = sorted(set(facets[facet]))

    return {
        "entries": unique_entries,
        "facets": facets,
        "unaligned_rules": unaligned,
    }


def are_values_semantically_close(facet: str, original_value: str, qwen_value: str) -> bool:
    if original_value == qwen_value:
        return True
    for group in FACET_NEAR_VALUE_GROUPS.get(facet, []):
        if original_value in group and qwen_value in group:
            return True
    return False


def semantic_difference_level(value_match_rate: float) -> str:
    if value_match_rate >= 0.75:
        return "low"
    if value_match_rate >= 0.45:
        return "medium"
    return "high"


def compare_semantic_docs(original_doc: dict[str, Any], qwen_doc: dict[str, Any]) -> dict[str, Any]:
    original_canonical = canonicalize_doc(original_doc, "original")
    qwen_canonical = canonicalize_doc(qwen_doc, "qwen")

    original_facets = original_canonical["facets"]
    qwen_facets = qwen_canonical["facets"]
    aligned_facet_names = set(original_facets) & set(qwen_facets)
    original_only_facet_names = set(original_facets) - set(qwen_facets)
    qwen_only_facet_names = set(qwen_facets) - set(original_facets)

    exact_value_matches: list[dict[str, Any]] = []
    close_value_matches: list[dict[str, Any]] = []
    different_value_matches: list[dict[str, Any]] = []
    aligned_facets: list[dict[str, Any]] = []

    ordered_facet_names = sorted(
        aligned_facet_names,
        key=lambda item: (SEMANTIC_FACET_ORDER.index(item) if item in SEMANTIC_FACET_ORDER else len(SEMANTIC_FACET_ORDER), item),
    )
    for facet in ordered_facet_names:
        original_values = sorted(original_facets.get(facet, []))
        qwen_values = sorted(qwen_facets.get(facet, []))
        overlap_values = sorted(set(original_values) & set(qwen_values))
        near_value_pairs = sorted(
            {
                (original_value, qwen_value)
                for original_value in original_values
                for qwen_value in qwen_values
                if are_values_semantically_close(facet, original_value, qwen_value)
                and original_value != qwen_value
            }
        )

        detail = {
            "facet": facet,
            "original_values": original_values,
            "qwen_values": qwen_values,
            "overlap_values": overlap_values,
            "near_value_pairs": [
                {"original": original_value, "qwen": qwen_value}
                for original_value, qwen_value in near_value_pairs
            ],
        }
        if original_values == qwen_values:
            detail["status"] = "exact_match"
            exact_value_matches.append(detail)
        elif overlap_values or near_value_pairs:
            detail["status"] = "semantic_close"
            close_value_matches.append(detail)
        else:
            detail["status"] = "different"
            different_value_matches.append(detail)
        aligned_facets.append(detail)

    aligned_facet_count = len(aligned_facets)
    exact_match_count = len(exact_value_matches)
    close_match_count = len(close_value_matches)
    different_match_count = len(different_value_matches)
    semantic_value_match_count = exact_match_count + close_match_count
    value_match_rate = semantic_value_match_count / aligned_facet_count if aligned_facet_count else 0.0

    original_only_facets = [
        {"facet": facet, "values": original_facets[facet]}
        for facet in sorted(
            original_only_facet_names,
            key=lambda item: (SEMANTIC_FACET_ORDER.index(item) if item in SEMANTIC_FACET_ORDER else len(SEMANTIC_FACET_ORDER), item),
        )
    ]
    qwen_only_facets = [
        {"facet": facet, "values": qwen_facets[facet]}
        for facet in sorted(
            qwen_only_facet_names,
            key=lambda item: (SEMANTIC_FACET_ORDER.index(item) if item in SEMANTIC_FACET_ORDER else len(SEMANTIC_FACET_ORDER), item),
        )
    ]

    unaligned_rules = [*original_canonical["unaligned_rules"], *qwen_canonical["unaligned_rules"]]
    return {
        "summary": {
            "aligned_facet_count": aligned_facet_count,
            "exact_value_match_count": exact_match_count,
            "close_value_match_count": close_match_count,
            "different_value_match_count": different_match_count,
            "semantic_value_match_count": semantic_value_match_count,
            "semantic_value_match_rate": round(value_match_rate, 4),
            "original_only_facet_count": len(original_only_facets),
            "qwen_only_facet_count": len(qwen_only_facets),
            "unaligned_rule_count": len(unaligned_rules),
        },
        "aligned_facets": aligned_facets,
        "exact_value_matches": exact_value_matches,
        "close_value_matches": close_value_matches,
        "different_value_matches": different_value_matches,
        "original_only_facets": original_only_facets,
        "qwen_only_facets": qwen_only_facets,
        "unaligned_rules": unaligned_rules,
    }


def compare_docs(original_doc: dict[str, Any], qwen_doc: dict[str, Any]) -> dict[str, Any]:
    legacy = compare_legacy_docs(original_doc, qwen_doc)
    semantic = compare_semantic_docs(original_doc, qwen_doc)
    difference_level = semantic_difference_level(semantic["summary"]["semantic_value_match_rate"])
    return {
        "summary": {
            "original_rule_count": legacy["summary"]["original_rule_count"],
            "qwen_rule_count": legacy["summary"]["qwen_rule_count"],
            "aligned_semantic_facet_count": semantic["summary"]["aligned_facet_count"],
            "semantic_value_match_count": semantic["summary"]["semantic_value_match_count"],
            "semantic_value_match_rate": semantic["summary"]["semantic_value_match_rate"],
            "exact_value_match_count": semantic["summary"]["exact_value_match_count"],
            "close_value_match_count": semantic["summary"]["close_value_match_count"],
            "different_value_match_count": semantic["summary"]["different_value_match_count"],
            "original_only_facet_count": semantic["summary"]["original_only_facet_count"],
            "qwen_only_facet_count": semantic["summary"]["qwen_only_facet_count"],
            "unaligned_rule_count": semantic["summary"]["unaligned_rule_count"],
            "difference_level": difference_level,
        },
        "legacy_exact": legacy,
        "semantic_canonical": semantic,
    }


def write_report_files(report_dir: Path, rows: list[dict[str, Any]], errors: list[dict[str, Any]]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_report = report_dir / "qwen_atomic_rules_comparison_report.md"

    low = sum(1 for row in rows if row["comparison"]["summary"]["difference_level"] == "low")
    medium = sum(1 for row in rows if row["comparison"]["summary"]["difference_level"] == "medium")
    high = sum(1 for row in rows if row["comparison"]["summary"]["difference_level"] == "high")
    avg_semantic_value_match_rate = round(
        sum(row["comparison"]["semantic_canonical"]["summary"]["semantic_value_match_rate"] for row in rows) / len(rows),
        4,
    ) if rows else 0.0
    avg_aligned_facet_count = round(
        sum(row["comparison"]["semantic_canonical"]["summary"]["aligned_facet_count"] for row in rows) / len(rows),
        4,
    ) if rows else 0.0
    mismatch_counter = Counter(
        item["facet"]
        for row in rows
        for item in row["comparison"]["semantic_canonical"]["different_value_matches"]
    )
    hardest = sorted(rows, key=lambda row: row["comparison"]["semantic_canonical"]["summary"]["semantic_value_match_rate"])[:10]

    lines = [
        "# Qwen Atomic Rules Comparison Report",
        "",
        f"- Processed samples: {len(rows)}",
        f"- Errors: {len(errors)}",
        f"- Average semantic value match rate: {avg_semantic_value_match_rate}",
        f"- Average aligned semantic facet count: {avg_aligned_facet_count}",
        f"- Low difference: {low}",
        f"- Medium difference: {medium}",
        f"- High difference: {high}",
        "- Comparison method: only compare semantically aligned facets, then judge whether the values are semantically close.",
        "- Rule type mismatch does not directly lower the main score; only aligned-facet value similarity drives the main metric.",
        "",
        "## Most Common Mismatch Families",
        "",
    ]
    if mismatch_counter:
        for facet, count in mismatch_counter.most_common(10):
            lines.append(f"- `{facet}`: {count}")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Lowest-Match Samples",
            "",
            "| code | dataset | value_match_rate | aligned_facets | exact | close | different | unaligned | level |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in hardest:
        summary = row["comparison"]["summary"]
        semantic_summary = row["comparison"]["semantic_canonical"]["summary"]
        lines.append(
            f"| {row['code']} | {row['dataset_name']} | {semantic_summary['semantic_value_match_rate']} | "
            f"{semantic_summary['aligned_facet_count']} | {semantic_summary['exact_value_match_count']} | "
            f"{semantic_summary['close_value_match_count']} | {semantic_summary['different_value_match_count']} | "
            f"{summary['unaligned_rule_count']} | {summary['difference_level']} |"
        )

    lines.extend(["", "## Sample Details", ""])

    for row in sorted(rows, key=lambda item: item["comparison"]["semantic_canonical"]["summary"]["semantic_value_match_rate"]):
        summary = row["comparison"]["summary"]
        semantic = row["comparison"]["semantic_canonical"]
        lines.extend(
            [
                f"### {row['code']} ({row['dataset_name']})",
                "",
                f"- Sample dir: `{row['relative_dir']}`",
                f"- Original rules: {summary['original_rule_count']}",
                f"- Qwen rules: {summary['qwen_rule_count']}",
                f"- Aligned semantic facets: {summary['aligned_semantic_facet_count']}",
                f"- Semantic value match count: {summary['semantic_value_match_count']}",
                f"- Semantic value match rate: {summary['semantic_value_match_rate']}",
                f"- Exact value matches: {summary['exact_value_match_count']}",
                f"- Close value matches: {summary['close_value_match_count']}",
                f"- Different value matches: {summary['different_value_match_count']}",
                f"- Original-only semantic facets: {summary['original_only_facet_count']}",
                f"- Qwen-only semantic facets: {summary['qwen_only_facet_count']}",
                f"- Unaligned rules: {summary['unaligned_rule_count']}",
                f"- Difference level: {summary['difference_level']}",
                "",
            ]
        )

        if semantic["exact_value_matches"]:
            lines.append("Aligned facets with exact value match:")
            for item in semantic["exact_value_matches"]:
                lines.append(f"- `{item['facet']}` = `{', '.join(item['original_values'])}`")
            lines.append("")

        if semantic["close_value_matches"]:
            lines.append("Aligned facets with semantically close values:")
            for item in semantic["close_value_matches"]:
                overlap = ", ".join(item["overlap_values"]) if item["overlap_values"] else "none"
                near_pairs = ", ".join(
                    f"{pair['original']}~{pair['qwen']}" for pair in item["near_value_pairs"]
                ) if item["near_value_pairs"] else "none"
                lines.append(
                    f"- `{item['facet']}`: original = `{', '.join(item['original_values']) or 'none'}`, "
                    f"qwen = `{', '.join(item['qwen_values']) or 'none'}`, overlap = `{overlap}`, near = `{near_pairs}`"
                )
            lines.append("")

        if semantic["different_value_matches"]:
            lines.append("Aligned facets with semantically different values:")
            for item in semantic["different_value_matches"]:
                lines.append(
                    f"- `{item['facet']}`: original = `{', '.join(item['original_values']) or 'none'}`, "
                    f"qwen = `{', '.join(item['qwen_values']) or 'none'}`"
                )
            lines.append("")

        if semantic["original_only_facets"]:
            lines.append("Original-only semantic facets not compared:")
            for item in semantic["original_only_facets"]:
                lines.append(f"- `{item['facet']}` = `{', '.join(item['values'])}`")
            lines.append("")

        if semantic["qwen_only_facets"]:
            lines.append("Qwen-only semantic facets not compared:")
            for item in semantic["qwen_only_facets"]:
                lines.append(f"- `{item['facet']}` = `{', '.join(item['values'])}`")
            lines.append("")

        if semantic["unaligned_rules"]:
            lines.append("Rules that could not be aligned reliably:")
            for item in semantic["unaligned_rules"]:
                lines.append(
                    f"- `{item['source_side']}` `{item['id']}` = `{item['value']}` "
                    f"(reason: `{item['reason']}`)"
                )
            lines.append("")

        if (
            not semantic["different_value_matches"]
            and not semantic["unaligned_rules"]
        ):
            lines.append("- All aligned semantic facets have exact or semantically close values.")
            lines.append("")

    if errors:
        lines.extend(["## Errors", ""])
        for error in errors:
            lines.append(
                f"- `{error['code']}` in `{error['relative_dir']}`: "
                f"{error['error_type']} - {error['error_message']}"
            )
    markdown_report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    samples = discover_samples(args.root)
    if args.offset < 0:
        raise ValueError("--offset must not be negative")
    if args.limit < 0:
        raise ValueError("--limit must not be negative")

    sliced = samples[args.offset :]
    if args.limit:
        sliced = sliced[: args.limit]

    if args.dry_run:
        print(f"Discovered samples: {len(samples)}")
        print(f"Selected samples: {len(sliced)}")
        for sample in sliced[:10]:
            print(sample["relative_dir"])
        return

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for sample in sliced:
        code = sample["code"]
        sample_dir = sample["sample_dir"]
        qwen_output_path = sample_dir / f"{code}_qwen_atomic_rules.json"
        comparison_output_path = sample_dir / f"{code}_qwen_comparison.json"
        raw_output_path = sample_dir / f"{code}_qwen_raw_response.json"
        try:
            if qwen_output_path.exists() and not args.overwrite:
                qwen_doc = normalize_rule_doc(load_json(qwen_output_path), code)
            else:
                qwen_input_path = prepare_qwen_input(sample["image_path"], code)
                parsed, raw_response = call_qwen_atomic_rules(
                    qwen_input_path.resolve().as_uri(),
                    code,
                    args.model,
                    source_tag_hints=DEFAULT_SOURCE_TAG_HINTS,
                    force_continue=True,
                )
                qwen_doc = normalize_rule_doc(parsed, code)
                qwen_output_path.write_text(json.dumps(qwen_doc, ensure_ascii=False, indent=2), encoding="utf-8")
                if args.write_debug_files:
                    raw_output_path.write_text(json.dumps(raw_response, ensure_ascii=False, indent=2), encoding="utf-8")

            original_doc = normalize_rule_doc(load_json(sample["atomic_path"]), code)
            comparison = compare_docs(original_doc, qwen_doc)
            if args.write_debug_files:
                comparison_output_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")

            rows.append(
                {
                    "code": code,
                    "relative_dir": sample["relative_dir"],
                    "dataset_name": sample["dataset_name"],
                    "image_path": sample["image_path"].as_posix(),
                    "original_atomic_rules_path": sample["atomic_path"].as_posix(),
                    "original_atomic_rules": original_doc,
                    "qwen_atomic_rules": qwen_doc,
                    "comparison": comparison,
                }
            )
            if args.sleep:
                time.sleep(args.sleep)
        except Exception as exc:
            errors.append(
                {
                    "code": code,
                    "relative_dir": sample["relative_dir"],
                    "image_path": sample["image_path"].as_posix(),
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                }
            )
            if args.stop_on_error:
                raise

    write_report_files(args.report_dir, rows, errors)
    print(f"Processed samples: {len(rows)}")
    print(f"Errors: {len(errors)}")
    print(f"Report dir: {args.report_dir}")


if __name__ == "__main__":
    main()
