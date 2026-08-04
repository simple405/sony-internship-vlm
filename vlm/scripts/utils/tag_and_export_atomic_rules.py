"""Tag atomic_rules by body location and export each JSON to xlsx.

Scans all atomic_rules.json files under multi_view试标数据集, calls the
Qwen text model once to classify every unique rule_id as 'head' or 'body',
then writes one {code}.xlsx per sample with an English-only annotation
template matching the reference format.

Outputs:
    vlm/tmp/rule_location_tags.json   — saved classification map (inspect/edit)
    <same dir as json>/{code}.xlsx    — 24 xlsx annotation templates

Usage:
    python -m vlm.scripts.utils.tag_and_export_atomic_rules
    python -m vlm.scripts.utils.tag_and_export_atomic_rules --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts._paths import DATA_ROOT, TMP_DIR, load_api_env
from vlm.scripts.data.assign_merchandise_categories import HEAD_ONLY_CATEGORIES
from vlm.scripts.utils.atomic_rule_xlsx import add_annotation_dropdowns, normalize_position_value

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MULTI_VIEW_ROOT = DATA_ROOT / "safebooru_2d" / "generated"

# Qwen text API defaults (overridden by api.env)
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.7-max"

# xlsx column order — matches the reference workbook layout
XLSX_COLUMNS = [
    "sample_id",
    "rule_id",
    "location",
    "value",
    "front_visible",
    "front_status",
    "side_visible",
    "side_status",
    "back_visible",
    "back_status",
    "note",
]

# ---------------------------------------------------------------------------
# Step 1 — discover files and collect rule IDs
# ---------------------------------------------------------------------------


def find_atomic_rules_files(root: Path) -> list[Path]:
    """Return all atomic_rules.json paths under root, sorted for determinism.

    Args:
        root: Directory to search recursively.

    Returns:
        Sorted list of matching Path objects.
    """
    files = list(root.rglob("atomic_rules.json"))
    files.extend(root.rglob("*_atomic_rules.json"))
    return sorted({path for path in files if path.is_file()})


def sample_category_from_json_path(json_path: Path) -> str:
    """Infer the sample category from the generated directory layout."""
    try:
        return json_path.parent.parent.name
    except IndexError:
        return ""


def collect_unique_ids(files: list[Path]) -> list[str]:
    """Gather every distinct rule_id across all atomic_rules.json files.

    Args:
        files: Paths to atomic_rules.json files.

    Returns:
        Sorted list of unique rule_id strings.
    """
    seen: set[str] = set()
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for rule in data.get("atomic_rules", []):
            seen.add(rule["id"])
    return sorted(seen)


# ---------------------------------------------------------------------------
# Step 2 — Qwen classification: head vs body
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a character design analyst specialising in anime merchandise. "
    "Classify each attribute rule_id as either:\n"
    "  'head'  — anything on or above the neck: hair, hairstyle, head accessories, "
    "horns, ears, face features, eyes, expression, glasses, headwear, etc.\n"
    "  'body'  — everything else: clothing, shoes, legwear, jewellery, choker, "
    "necklace, bracelets, handheld items, weapons, bags, body build, wings, etc.\n\n"
    "Return ONLY a valid JSON object mapping each rule_id string to 'head' or 'body'. "
    "No explanation, no markdown fences."
)

# ── Local keyword rules ──────────────────────────────────────────────────────
# Prefixes / substrings / exact matches that unambiguously indicate 'head'.
# Everything else defaults to 'body'.  Checked in order; first match wins.
_HEAD_PREFIXES = (
    "hair_", "has_hair", "eye_", "has_eye",
    "glasses_", "has_glasses",
    "headwear_", "has_headwear",
    "headband_", "has_headband",
    "head_accessory", "has_head_accessory",
    "head_chick", "has_head_chick", "head_ribbon",
    "horn_", "has_horn",
    "bangs_", "has_bangs",
    "mouth_", "has_blush",
    "ponytail_",
)
_HEAD_EXACT: frozenset[str] = frozenset({
    "expression", "has_ahoge", "has_wink",
    "has_pointed_ears", "has_hair_between_eyes",
    "hair_over_eye", "has_hair_over_eye",
    "skin_tone", "skin_color",          # face is the dominant visible surface
    "has_ponytail",
})
_HEAD_SUBSTRINGS = ("_ribbon_position", "hair_ribbon", "hair_ornament",
                    "hair_flower", "hair_tie", "hair_streak",
                    "hair_bangs", "hair_accessory")


def _local_classify(rule_id: str) -> str | None:
    """Return 'head', 'body', or None if uncertain.

    Args:
        rule_id: The attribute identifier string to classify.

    Returns:
        'head', 'body', or None when no local rule matches.
    """
    if rule_id in _HEAD_EXACT:
        return "head"
    for prefix in _HEAD_PREFIXES:
        if rule_id.startswith(prefix):
            return "head"
    for sub in _HEAD_SUBSTRINGS:
        if sub in rule_id:
            return "head"
    return None  # ambiguous — needs Qwen


def _qwen_batch(
    ids: list[str],
    api_key: str,
    base_url: str,
    model: str,
    batch_size: int = 60,
    timeout: int = 180,
) -> dict[str, str]:
    """Send ids to Qwen in chunks and merge results.

    Args:
        ids: Rule IDs to classify.
        api_key: DashScope API key.
        base_url: Compatible-mode endpoint base URL.
        model: Model name.
        batch_size: Maximum IDs per API call (default 60 avoids timeouts).
        timeout: Per-request read timeout in seconds.

    Returns:
        Dict mapping each id to 'head' or 'body'.

    Raises:
        requests.HTTPError: On non-2xx API response.
        ValueError: If model response is not valid JSON.
    """
    result: dict[str, str] = {}
    url = base_url.rstrip("/") + "/chat/completions"
    chunks = [ids[i: i + batch_size] for i in range(0, len(ids), batch_size)]

    for idx, chunk in enumerate(chunks, 1):
        print(f"    Qwen batch {idx}/{len(chunks)} ({len(chunk)} IDs) …")
        user_content = "Classify these rule IDs as 'head' or 'body'.\n\n" + "\n".join(chunk)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        }
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()

        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown fences if the model wraps the JSON
        if raw.startswith("```"):
            raw = "\n".join(
                line for line in raw.splitlines()
                if not line.startswith("```")
            ).strip()

        try:
            mapping: dict[str, str] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Qwen returned non-JSON for batch {idx}:\n{raw}") from exc

        for rid in chunk:
            tag = mapping.get(rid, "body").lower().strip()
            result[rid] = tag if tag in ("head", "body") else "body"

    return result


def call_qwen_classify(
    rule_ids: list[str],
    api_key: str,
    base_url: str,
    model: str,
    dry_run: bool = False,
) -> dict[str, str]:
    """Classify each rule_id as 'head' or 'body'.

    Uses a local keyword classifier first, then sends only ambiguous IDs
    to Qwen in small batches (max 60 per call) to avoid API timeouts.

    Args:
        rule_ids: Sorted list of unique rule_id strings to classify.
        api_key: DashScope API key.
        base_url: Compatible-mode endpoint base URL.
        model: Model name, e.g. 'qwen3.7-max'.
        dry_run: If True, skip Qwen calls; assign all non-local IDs to 'body'.

    Returns:
        Dict mapping rule_id -> 'head' or 'body'.
    """
    result: dict[str, str] = {}
    ambiguous: list[str] = []

    for rid in rule_ids:
        local = _local_classify(rid)
        if local is not None:
            result[rid] = local
        else:
            ambiguous.append(rid)

    print(f"  Local classifier: {len(result)} IDs resolved "
          f"({sum(1 for v in result.values() if v == 'head')} head, "
          f"{sum(1 for v in result.values() if v == 'body')} body)")
    print(f"  Sending {len(ambiguous)} ambiguous IDs to Qwen …")

    if ambiguous:
        if dry_run:
            print(f"  [dry-run] assigning {len(ambiguous)} ambiguous IDs to 'body'")
            for rid in ambiguous:
                result[rid] = "body"
        else:
            qwen_result = _qwen_batch(ambiguous, api_key, base_url, model)
            result.update(qwen_result)

    return result


# ---------------------------------------------------------------------------
# Step 3 — write xlsx
# ---------------------------------------------------------------------------


def write_xlsx(json_path: Path, location_map: dict[str, str]) -> Path:
    """Generate an xlsx annotation template from one atomic_rules.json.

    Columns follow the reference format (English only). Evaluation columns
    (front_visible … result) are left blank for later annotation.

    Args:
        json_path: Path to the source atomic_rules.json.
        location_map: Mapping of rule_id -> 'head' | 'body'.

    Returns:
        Path to the written xlsx file.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError as exc:
        raise ImportError("openpyxl is required: pip install openpyxl") from exc

    data = json.loads(json_path.read_text(encoding="utf-8"))
    code: str = data["code"]
    rules: list[dict] = data.get("atomic_rules", [])
    category = sample_category_from_json_path(json_path)
    if category in HEAD_ONLY_CATEGORIES:
        rules = [rule for rule in rules if location_map.get(str(rule.get("id")), "body") == "head"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # Header row — bold, light-grey background
    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="D9D9D9")
    header_align = Alignment(horizontal="center", vertical="center")

    for col_idx, col_name in enumerate(XLSX_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align

    # Data rows
    for row_idx, rule in enumerate(rules, start=2):
        rule_id: str = rule["id"]
        value = rule["value"]
        location = location_map.get(rule_id, "body")
        display_value = normalize_position_value(rule_id, str(value) if isinstance(value, bool) else value)

        row_data = [
            code,       # sample_id
            rule_id,    # rule_id
            location,   # location (head | body)
            display_value,  # value already uses annotator viewpoint
        ]
        # Evaluation columns: front_visible, front_status, side_visible,
        # side_status, back_visible, back_status, note — all left blank
        row_data += [""] * (len(XLSX_COLUMNS) - len(row_data))

        for col_idx, cell_value in enumerate(row_data, start=1):
            ws.cell(row=row_idx, column=col_idx, value=cell_value)

    add_annotation_dropdowns(ws)

    # Auto-size columns for readability
    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    out_path = json_path.parent / f"{code}.xlsx"
    wb.save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Orchestrate tagging and xlsx export for all samples."""
    parser = argparse.ArgumentParser(
        description="Tag atomic_rules by head/body location and export to xlsx."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Qwen API call; assign every rule_id to 'body'.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the Qwen text model (default: QWEN_TEXT_MODEL from api.env or qwen3.7-max).",
    )
    args = parser.parse_args()

    # Load credentials and config from api.env
    load_api_env()
    api_key = os.environ.get("QWEN_API_KEY", "")
    base_url = os.environ.get("QWEN_BASE_URL", DEFAULT_BASE_URL)
    model = args.model or os.environ.get("QWEN_TEXT_MODEL", DEFAULT_MODEL)

    if not api_key and not args.dry_run:
        sys.exit("ERROR: QWEN_API_KEY not found in api.env — aborting.")

    # ── 1. Discover all atomic_rules.json files ──────────────────────────
    json_files = find_atomic_rules_files(MULTI_VIEW_ROOT)
    if not json_files:
        sys.exit(f"ERROR: no atomic_rules.json found under {MULTI_VIEW_ROOT}")
    print(f"Found {len(json_files)} atomic_rules.json files.")

    # ── 2. Collect unique rule IDs ────────────────────────────────────────
    unique_ids = collect_unique_ids(json_files)
    print(f"Collected {len(unique_ids)} unique rule IDs.")

    # ── 3. Classify via Qwen ──────────────────────────────────────────────
    print(f"Calling Qwen ({model}) to classify rule IDs as head / body …")
    location_map = call_qwen_classify(
        unique_ids,
        api_key=api_key,
        base_url=base_url,
        model=model,
        dry_run=args.dry_run,
    )

    # Save classification map for inspection / manual correction
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tags_path = TMP_DIR / "rule_location_tags.json"
    tags_path.write_text(
        json.dumps(location_map, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved location map → {tags_path}")

    # Print a quick summary
    head_count = sum(1 for v in location_map.values() if v == "head")
    body_count = len(location_map) - head_count
    print(f"  head: {head_count} rules,  body: {body_count} rules")

    # ── 4. Generate xlsx files ────────────────────────────────────────────
    print(f"\nWriting xlsx files …")
    for json_path in json_files:
        out = write_xlsx(json_path, location_map)
        rel = out.relative_to(MULTI_VIEW_ROOT)
        print(f"  ✓ {rel}")

    print(f"\nDone — {len(json_files)} xlsx files written.")


if __name__ == "__main__":
    main()
