"""Run an isolated ten-rule Qwen smoke test for natural Chinese labels."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from vlm.scripts._paths import API_ENV_FILE, load_api_env
from vlm.scripts._validation import validate_qwen_base_url
from vlm.scripts.translate_atomic_rules_xlsx import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    RulePair,
    translate_batch,
    translation_quality_issues,
    write_json_atomic,
)
from vlm.scripts.utils.atomic_rule_xlsx import (
    TRANSLATION_CACHE_RELATIVE_PATH,
    canonical_rule_value,
    contextual_translation,
    load_translation_cache,
    translation_key,
)


DEFAULT_DATASET = Path("vlm/data/design_sheet_10610_smoke30")
DEFAULT_OUTPUT_DIR = Path("vlm/tmp/atomic_rule_translation_smoke")
SMOKE_RULES = (
    ("skirt_length", "knee_length"),
    ("skirt_length", "floor_length"),
    ("skirt_length", "thigh_length"),
    ("legwear_type", "knee_high_socks"),
    ("top_style", "long_sleeve_with_ruffles"),
    ("footwear_type", "none_visible"),
    ("arm_guard_color", "white_with_red_trim"),
    ("bag_color", "white_and_dark_green"),
    ("has_bow_on_waist", "true"),
    ("tail_color", "black_with_pink_tip"),
)


@dataclass(frozen=True)
class SmokeCase:
    """One real dataset rule selected for the translation smoke test."""

    sample_id: str
    source_file: Path
    pair: RulePair


def parse_args() -> argparse.Namespace:
    """Parse isolated smoke-test arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--env-file", type=Path, default=API_ENV_FILE)
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=4000)
    return parser.parse_args()


def select_smoke_cases(atomic_root: Path) -> list[SmokeCase]:
    """Select the first real occurrence of each representative rule pair."""
    wanted = set(SMOKE_RULES)
    selected: dict[tuple[str, str], SmokeCase] = {}
    for source_file in sorted(atomic_root.glob("*/atomic_rules.json")):
        payload = json.loads(source_file.read_text(encoding="utf-8-sig"))
        for rule in payload.get("atomic_rules", []):
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("id", "")).strip()
            value = canonical_rule_value(rule.get("value"))
            identity = (rule_id, value)
            if identity not in wanted or identity in selected:
                continue
            selected[identity] = SmokeCase(
                sample_id=source_file.parent.name,
                source_file=source_file,
                pair=RulePair(
                    key=translation_key(rule_id, rule.get("value")),
                    rule_id=rule_id,
                    value=value,
                    locations=(str(rule.get("location", "")),),
                ),
            )
    missing = [identity for identity in SMOKE_RULES if identity not in selected]
    if missing:
        raise ValueError(f"Smoke-test rules are missing from {atomic_root}: {missing}")
    return [selected[identity] for identity in SMOKE_RULES]


def semantic_issues(pair: RulePair, value_cn: str) -> list[str]:
    """Check that each smoke value retained its essential source meaning."""
    checks: dict[tuple[str, str], tuple[str, ...]] = {
        ("skirt_length", "knee_length"): (r"^及膝长度$",),
        ("skirt_length", "floor_length"): (r"及地|拖地",),
        ("skirt_length", "thigh_length"): (r"大腿",),
        ("legwear_type", "knee_high_socks"): (r"^及膝袜$",),
        ("top_style", "long_sleeve_with_ruffles"): (r"长袖", r"荷叶边"),
        ("footwear_type", "none_visible"): (r"未见|不可见|未显示",),
        ("arm_guard_color", "white_with_red_trim"): (r"白", r"红", r"滚边|镶边"),
        ("bag_color", "white_and_dark_green"): (r"白", r"深绿"),
        ("has_bow_on_waist", "true"): (r"^有$",),
        ("tail_color", "black_with_pink_tip"): (r"黑", r"粉", r"尾尖|末端|尖端"),
    }
    import re

    return [
        f"missing semantic pattern: {pattern}"
        for pattern in checks[(pair.rule_id, pair.value)]
        if re.search(pattern, value_cn) is None
    ]


def write_preview_xlsx(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write a standalone ten-row old/new translation comparison workbook."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "翻译对照"
    headers = (
        "样本编号",
        "原始规则ID",
        "原始取值",
        "旧规则名称",
        "旧中文取值",
        "新规则名称",
        "新中文取值",
        "检查结果",
        "源文件",
    )
    sheet.append(headers)
    for row in rows:
        sheet.append(
            (
                row["sample_id"],
                row["rule_id"],
                row["value"],
                row["old_rule_name_cn"],
                row["old_value_cn"],
                row["new_rule_name_cn"],
                row["new_value_cn"],
                "通过" if row["passed"] else "；".join(row["issues"]),
                row["source_file"],
            )
        )
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    widths = (16, 24, 30, 20, 28, 20, 32, 36, 72)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = width
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.tmp.xlsx")
    try:
        workbook.save(temporary)
        temporary.replace(path)
    finally:
        workbook.close()
        temporary.unlink(missing_ok=True)


def main() -> None:
    """Call Qwen once for ten rules and save isolated comparison artifacts."""
    args = parse_args()
    if args.timeout < 1 or args.max_retries < 0 or args.max_tokens < 1:
        raise ValueError("timeout and max tokens must be positive; retries must be non-negative")
    dataset_dir = args.dataset_dir.resolve()
    cases = select_smoke_cases(dataset_dir / "atomic_rules")
    cache_path = dataset_dir / TRANSLATION_CACHE_RELATIVE_PATH
    old_translations = load_translation_cache(cache_path)
    load_api_env(args.env_file)
    api_key = os.environ.get("QWEN_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("QWEN_API_KEY is required for the translation smoke test")
    base_url = validate_qwen_base_url(os.environ.get("QWEN_BASE_URL", DEFAULT_BASE_URL))
    model = args.model.strip() or os.environ.get("QWEN_TEXT_MODEL", "").strip() or DEFAULT_MODEL

    run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    run_dir = args.output_dir.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    request_document = {
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "base_url": base_url,
        "system_prompt": SYSTEM_PROMPT,
        "items": [
            {
                "index": index,
                "sample_id": case.sample_id,
                "rule_id": case.pair.rule_id,
                "value": case.pair.value,
                "location": list(case.pair.locations),
                "source_file": str(case.source_file),
            }
            for index, case in enumerate(cases)
        ],
    }
    write_json_atomic(run_dir / "request.json", request_document)

    raw_responses: list[str] = []
    translated = translate_batch(
        [case.pair for case in cases],
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=args.timeout,
        max_retries=args.max_retries,
        max_tokens=args.max_tokens,
        response_observer=raw_responses.append,
    )
    write_json_atomic(run_dir / "raw_responses.json", {"responses": raw_responses})

    rows: list[dict[str, Any]] = []
    for case, new_translation in zip(cases, translated, strict=True):
        old_translation = contextual_translation(
            old_translations,
            case.pair.rule_id,
            case.pair.value,
        ) or {}
        issues = translation_quality_issues(
            case.pair,
            new_translation["rule_name_cn"],
            new_translation["value_cn"],
        )
        issues.extend(semantic_issues(case.pair, new_translation["value_cn"]))
        rows.append(
            {
                "sample_id": case.sample_id,
                "rule_id": case.pair.rule_id,
                "value": case.pair.value,
                "location": list(case.pair.locations),
                "source_file": str(case.source_file),
                "old_rule_name_cn": str(old_translation.get("rule_name_cn", "")),
                "old_value_cn": str(old_translation.get("value_cn", "")),
                "new_rule_name_cn": new_translation["rule_name_cn"],
                "new_value_cn": new_translation["value_cn"],
                "issues": issues,
                "passed": not issues,
            }
        )
    result = {
        "status": "passed" if all(row["passed"] for row in rows) else "failed",
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "rules": rows,
    }
    write_json_atomic(run_dir / "result.json", result)
    write_preview_xlsx(run_dir / "atomic_rule_translation_smoke.xlsx", rows)
    (args.output_dir.resolve() / "LATEST.txt").write_text(str(run_dir) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), **result}, ensure_ascii=False), flush=True)
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
