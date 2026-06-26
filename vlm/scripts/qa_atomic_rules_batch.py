"""QA harness for a Safebooru atomic_rules batch.

This script is intentionally offline: it scans metadata.jsonl plus the generated
atomic_rules folders and writes machine-readable QA artifacts for human review.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DATASET = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20")
DEFAULT_METADATA = DEFAULT_DATASET / "metadata.jsonl"
DEFAULT_ATOMIC_DIR = DEFAULT_DATASET / "atomic_rules"
DEFAULT_REPORT_DIR = DEFAULT_DATASET / "reports"

ALLOWED_TOP_KEYS = {"code", "atomic_rules"}
ALLOWED_RULE_KEYS = {"id", "value"}
SKIN_TONE_ALLOWED_VALUES = {"fair", "tan", "dark"}
LENGTH_ALLOWED_VALUES = {"short", "medium", "long"}
HEIGHT_ALLOWED_VALUES = {"low", "medium", "high"}
LENGTH_VALUE_ALIASES = {
    "very_long": "long",
    "long_sleeve": "long",
    "long_sleeves": "long",
    "full_length": "long",
    "waist_length": "long",
    "hip_length": "long",
    "knee_length": "long",
    "knee_high": "long",
    "knee_highs": "long",
    "thigh_high": "long",
    "thigh_highs": "long",
    "thighhigh": "long",
    "thighhighs": "long",
    "over_knee": "long",
    "floor_length": "long",
    "trailing": "long",
    "three_quarter": "medium",
    "three_quarter_sleeve": "medium",
    "three_quarter_sleeves": "medium",
    "midi": "medium",
    "elbow": "medium",
    "elbow_length": "medium",
    "mid_calf": "medium",
    "calf_length": "medium",
    "shoulder_length": "medium",
    "medium_length": "medium",
    "mid_length": "medium",
    "short_sleeve": "short",
    "short_sleeves": "short",
    "sleeveless": "short",
    "cropped": "short",
    "crop": "short",
    "mini": "short",
    "miniskirt": "short",
    "micro": "short",
    "ankle": "short",
    "ankle_length": "short",
    "neck": "short",
    "neck_length": "short",
    "very_short": "short",
}
HEIGHT_VALUE_ALIASES = {
    "low": "low",
    "short": "low",
    "flat": "low",
    "ankle": "low",
    "ankle_high": "low",
    "ankle_boot": "low",
    "ankle_boots": "low",
    "low_heel": "low",
    "low_heels": "low",
    "medium": "medium",
    "mid": "medium",
    "moderate": "medium",
    "mid_height": "medium",
    "mid_calf": "medium",
    "calf": "medium",
    "calf_high": "medium",
    "high": "high",
    "tall": "high",
    "long": "high",
    "high_waist": "high",
    "knee": "high",
    "knee_high": "high",
    "thigh": "high",
    "thigh_high": "high",
    "thighhigh": "high",
    "platform": "high",
    "high_heel": "high",
    "high_heels": "high",
}
BANNED_VALUES = {
    "",
    "none",
    "no",
    "n_a",
    "na",
    "not_visible",
    "not_applicable",
    "unknown",
    "unclear",
    "hidden",
    "occluded",
    "covered",
    "fully_covered",
    "covered_by_helmet",
    "hidden_by_helmet",
    "covered_by_hood",
    "hidden_by_hood",
    "covered_by_mask",
    "hidden_by_mask",
    "eyes_closed",
    "closed_eyes",
    "eye_closed",
    "closed_eye",
    "false",
}
BANNED_VALUE_PREFIXES = (
    "very_",
    "slightly_",
    "extremely_",
    "super_",
    "somewhat_",
    "rather_",
    "quite_",
    "fairly_",
    "really_",
    "moderately_",
    "a_bit_",
    "kind_of_",
    "sort_of_",
)
REVIEW_COLUMNS = [
    "sample_id",
    "json_valid",
    "core_features_complete",
    "too_fragmented",
    "wrong_category",
    "value_normalized",
    "usable",
    "notes",
]
ANOMALY_COLUMNS = [
    "sample_id",
    "severity",
    "issue_type",
    "detail",
    "json_path",
    "image_path",
    "rule_count",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QA atomic_rules JSON files and produce review artifacts.")
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--atomic-dir", type=Path, default=DEFAULT_ATOMIC_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--min-rules", type=int, default=6, help="Flag non-empty JSONs with fewer rules.")
    parser.add_argument("--max-rules", type=int, default=60, help="Flag JSONs with unusually many rules.")
    parser.add_argument("--review-all", action="store_true", help="Write every metadata row to review_samples.csv.")
    parser.add_argument(
        "--timestamped",
        action="store_true",
        help="Append a timestamp to generated report filenames instead of overwriting stable names.",
    )
    return parser.parse_args()


def sample_code(row: dict[str, Any]) -> str:
    return str(row.get("post_id") or row.get("code") or "").strip()


def load_metadata(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    if not path.exists():
        raise FileNotFoundError(path)
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(
                {
                    "sample_id": f"metadata_line_{line_number}",
                    "severity": "fail",
                    "issue_type": "metadata_invalid_json",
                    "detail": str(exc),
                    "json_path": str(path),
                    "image_path": "",
                    "rule_count": "",
                }
            )
            continue
        if not isinstance(row, dict):
            errors.append(
                {
                    "sample_id": f"metadata_line_{line_number}",
                    "severity": "fail",
                    "issue_type": "metadata_not_object",
                    "detail": "metadata line is not a JSON object",
                    "json_path": str(path),
                    "image_path": "",
                    "rule_count": "",
                }
            )
            continue
        rows.append(row)
    return rows, errors


def atomic_path(atomic_dir: Path, code: str) -> Path:
    return atomic_dir / code / f"{code}_atomic_rules.json"


def image_path_for(row: dict[str, Any]) -> str:
    return str(row.get("image_path") or "")


def normalize_value_for_check(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower()


def is_length_rule(rule_id: str) -> bool:
    tokens = set(rule_id.split("_"))
    return "length" in tokens or rule_id.endswith("_length")


def is_height_rule(rule_id: str) -> bool:
    tokens = set(rule_id.split("_"))
    return "height" in tokens or rule_id.endswith("_height")


def canonical_value_for_check(rule_id: str, value: str) -> str:
    if is_length_rule(rule_id):
        return LENGTH_VALUE_ALIASES.get(value, value)
    if is_height_rule(rule_id):
        return HEIGHT_VALUE_ALIASES.get(value, value)
    return value


def add_issue(
    issues: list[dict[str, str]],
    *,
    code: str,
    severity: str,
    issue_type: str,
    detail: str,
    path: Path | None,
    image_path: str,
    rule_count: int | str = "",
) -> None:
    issues.append(
        {
            "sample_id": code,
            "severity": severity,
            "issue_type": issue_type,
            "detail": detail,
            "json_path": str(path) if path else "",
            "image_path": image_path,
            "rule_count": str(rule_count),
        }
    )


def load_json_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, "top-level JSON is not an object"
    return value, None


def check_rule(
    rule: Any,
    *,
    code: str,
    index: int,
    path: Path,
    image_path: str,
    issues: list[dict[str, str]],
) -> tuple[str, str] | None:
    if not isinstance(rule, dict):
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="rule_not_object",
            detail=f"atomic_rules[{index}] is not an object",
            path=path,
            image_path=image_path,
        )
        return None

    extra_keys = sorted(set(rule) - ALLOWED_RULE_KEYS)
    missing_keys = sorted(ALLOWED_RULE_KEYS - set(rule))
    if extra_keys or missing_keys:
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="rule_schema",
            detail=f"atomic_rules[{index}] extra_keys={extra_keys} missing_keys={missing_keys}",
            path=path,
            image_path=image_path,
        )

    rule_id = rule.get("id")
    value = rule.get("value")
    if not isinstance(rule_id, str) or not rule_id.strip():
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="invalid_rule_id",
            detail=f"atomic_rules[{index}].id must be a non-empty string",
            path=path,
            image_path=image_path,
        )
        return None

    rule_id = rule_id.strip()
    if not all(ch.islower() or ch.isdigit() or ch == "_" for ch in rule_id) or "__" in rule_id:
        add_issue(
            issues,
            code=code,
            severity="warn",
            issue_type="non_canonical_rule_id",
            detail=f"{rule_id} is not clean snake_case",
            path=path,
            image_path=image_path,
        )

    if not isinstance(value, str | bool):
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="invalid_value_type",
            detail=f"{rule_id} value must be string or true",
            path=path,
            image_path=image_path,
        )
        return None
    if isinstance(value, bool) and value is not True:
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="false_boolean_value",
            detail=f"{rule_id} uses false; absent features should be omitted",
            path=path,
            image_path=image_path,
        )
        return None

    raw_normalized_value = normalize_value_for_check(value)
    normalized_value = canonical_value_for_check(rule_id, raw_normalized_value)
    if normalized_value in BANNED_VALUES or normalized_value.startswith(BANNED_VALUE_PREFIXES):
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="banned_value",
            detail=f"{rule_id}={normalized_value}",
            path=path,
            image_path=image_path,
        )
    if " " in normalized_value:
        add_issue(
            issues,
            code=code,
            severity="warn",
            issue_type="non_canonical_value",
            detail=f"{rule_id} value contains spaces: {normalized_value}",
            path=path,
            image_path=image_path,
        )
    if rule_id == "skin_tone" and normalized_value not in SKIN_TONE_ALLOWED_VALUES:
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="invalid_skin_tone_value",
            detail=f"{rule_id}={normalized_value}; allowed={sorted(SKIN_TONE_ALLOWED_VALUES)}",
            path=path,
            image_path=image_path,
        )
    if is_length_rule(rule_id) and normalized_value not in LENGTH_ALLOWED_VALUES:
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="invalid_length_value",
            detail=f"{rule_id}={normalized_value}; allowed={sorted(LENGTH_ALLOWED_VALUES)}",
            path=path,
            image_path=image_path,
        )
    if is_height_rule(rule_id) and normalized_value not in HEIGHT_ALLOWED_VALUES:
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="invalid_height_value",
            detail=f"{rule_id}={normalized_value}; allowed={sorted(HEIGHT_ALLOWED_VALUES)}",
            path=path,
            image_path=image_path,
        )

    return rule_id, normalized_value


def check_doc(
    row: dict[str, Any],
    *,
    atomic_dir: Path,
    min_rules: int,
    max_rules: int,
) -> tuple[int, list[dict[str, str]], bool]:
    code = sample_code(row)
    image_path = image_path_for(row)
    path = atomic_path(atomic_dir, code)
    issues: list[dict[str, str]] = []
    if not code:
        add_issue(
            issues,
            code="",
            severity="fail",
            issue_type="missing_metadata_code",
            detail="metadata row has neither post_id nor code",
            path=None,
            image_path=image_path,
        )
        return 0, issues, False
    if not path.exists() or path.stat().st_size == 0:
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="missing_json",
            detail="atomic_rules JSON is missing or empty",
            path=path,
            image_path=image_path,
        )
        return 0, issues, False

    doc, error = load_json_file(path)
    if error or doc is None:
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="invalid_json",
            detail=error or "invalid JSON",
            path=path,
            image_path=image_path,
        )
        return 0, issues, False

    extra_top_keys = sorted(set(doc) - ALLOWED_TOP_KEYS)
    missing_top_keys = sorted(ALLOWED_TOP_KEYS - set(doc))
    if extra_top_keys or missing_top_keys:
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="top_level_schema",
            detail=f"extra_keys={extra_top_keys} missing_keys={missing_top_keys}",
            path=path,
            image_path=image_path,
        )
    if str(doc.get("code", "")).strip() != code:
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="code_mismatch",
            detail=f"json code={doc.get('code')!r}",
            path=path,
            image_path=image_path,
        )

    rules = doc.get("atomic_rules")
    if not isinstance(rules, list):
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="atomic_rules_not_list",
            detail="atomic_rules must be a list",
            path=path,
            image_path=image_path,
        )
        return 0, issues, False

    if not rules:
        add_issue(
            issues,
            code=code,
            severity="fail",
            issue_type="empty_rules",
            detail="atomic_rules is empty",
            path=path,
            image_path=image_path,
            rule_count=0,
        )
    elif len(rules) < min_rules:
        add_issue(
            issues,
            code=code,
            severity="warn",
            issue_type="few_rules",
            detail=f"rule_count={len(rules)} < min_rules={min_rules}",
            path=path,
            image_path=image_path,
            rule_count=len(rules),
        )
    elif len(rules) > max_rules:
        add_issue(
            issues,
            code=code,
            severity="warn",
            issue_type="many_rules",
            detail=f"rule_count={len(rules)} > max_rules={max_rules}",
            path=path,
            image_path=image_path,
            rule_count=len(rules),
        )

    seen: set[tuple[str, str]] = set()
    for index, rule in enumerate(rules):
        checked = check_rule(rule, code=code, index=index, path=path, image_path=image_path, issues=issues)
        if checked is None:
            continue
        if checked in seen:
            add_issue(
                issues,
                code=code,
                severity="fail",
                issue_type="duplicate_rule",
                detail=f"{checked[0]}={checked[1]}",
                path=path,
                image_path=image_path,
                rule_count=len(rules),
            )
        seen.add(checked)

    json_valid = not any(issue["severity"] == "fail" for issue in issues)
    return len(rules), issues, json_valid


def discover_extra_jsons(metadata_codes: set[str], atomic_dir: Path) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not atomic_dir.exists():
        return issues
    for path in sorted(atomic_dir.glob("*/*_atomic_rules.json")):
        code = path.name.removesuffix("_atomic_rules.json")
        if code not in metadata_codes:
            add_issue(
                issues,
                code=code,
                severity="warn",
                issue_type="orphan_json",
                detail="atomic_rules JSON has no matching metadata row",
                path=path,
                image_path="",
            )
    return issues


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def percentile(values: list[int], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return float(ordered[index])


def report_paths(report_dir: Path, timestamped: bool) -> dict[str, Path]:
    suffix = ""
    if timestamped:
        suffix = "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    return {
        "markdown": report_dir / f"atomic_rules_qa_report{suffix}.md",
        "anomalies": report_dir / f"atomic_rules_anomalies{suffix}.csv",
        "review": report_dir / f"review_samples{suffix}.csv",
        "retry": report_dir / f"retry_samples{suffix}.csv",
    }


def build_markdown(
    *,
    metadata: Path,
    atomic_dir: Path,
    rows: list[dict[str, Any]],
    rule_counts: dict[str, int],
    issues: list[dict[str, str]],
    valid_codes: set[str],
    paths: dict[str, Path],
) -> str:
    issue_counter = Counter(issue["issue_type"] for issue in issues)
    severity_counter = Counter(issue["severity"] for issue in issues)
    counts = list(rule_counts.values())
    fail_codes = {issue["sample_id"] for issue in issues if issue["severity"] == "fail" and issue["sample_id"]}
    review_codes = {issue["sample_id"] for issue in issues if issue["sample_id"]}

    lines = [
        "# Atomic Rules QA Report",
        "",
        f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"- Metadata: `{metadata}`",
        f"- Atomic dir: `{atomic_dir}`",
        f"- Metadata rows: {len(rows)}",
        f"- JSON-valid samples: {len(valid_codes)}",
        f"- Samples with fail issues: {len(fail_codes)}",
        f"- Samples needing review: {len(review_codes)}",
        f"- Total issues: {len(issues)}",
        f"- Fail issues: {severity_counter.get('fail', 0)}",
        f"- Warn issues: {severity_counter.get('warn', 0)}",
        "",
        "## Rule Count Distribution",
        "",
        f"- Counted JSON files: {len(counts)}",
        f"- Min: {min(counts) if counts else 0}",
        f"- P10: {percentile(counts, 0.10):.1f}",
        f"- Median: {statistics.median(counts) if counts else 0}",
        f"- P90: {percentile(counts, 0.90):.1f}",
        f"- Max: {max(counts) if counts else 0}",
        "",
        "## Issue Breakdown",
        "",
    ]
    if issue_counter:
        for issue_type, count in issue_counter.most_common():
            lines.append(f"- {issue_type}: {count}")
    else:
        lines.append("- No issues found.")

    lines.extend(
        [
            "",
            "## Review Artifacts",
            "",
            f"- Anomalies CSV: `{paths['anomalies']}`",
            f"- Review CSV: `{paths['review']}`",
            f"- Retry CSV: `{paths['retry']}`",
            "",
            "## First Issues",
            "",
        ]
    )
    for issue in issues[:30]:
        lines.append(
            f"- [{issue['severity']}] {issue['sample_id']} "
            f"{issue['issue_type']}: {issue['detail']}"
        )
    if len(issues) > 30:
        lines.append(f"- ... {len(issues) - 30} more issues in CSV.")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    if args.min_rules < 0:
        raise ValueError("--min-rules must not be negative")
    if args.max_rules < args.min_rules:
        raise ValueError("--max-rules must be >= --min-rules")

    rows, metadata_issues = load_metadata(args.metadata)
    metadata_codes = {sample_code(row) for row in rows if sample_code(row)}
    all_issues: list[dict[str, str]] = list(metadata_issues)
    rule_counts: dict[str, int] = {}
    json_valid_by_code: dict[str, bool] = {}
    row_by_code = {sample_code(row): row for row in rows if sample_code(row)}

    for row in rows:
        code = sample_code(row)
        rule_count, issues, json_valid = check_doc(
            row,
            atomic_dir=args.atomic_dir,
            min_rules=args.min_rules,
            max_rules=args.max_rules,
        )
        if code:
            rule_counts[code] = rule_count
            json_valid_by_code[code] = json_valid
        all_issues.extend(issues)

    all_issues.extend(discover_extra_jsons(metadata_codes, args.atomic_dir))

    issue_codes = {issue["sample_id"] for issue in all_issues if issue["sample_id"]}
    if args.review_all:
        review_codes = [sample_code(row) for row in rows if sample_code(row)]
    else:
        review_codes = sorted(code for code in issue_codes if code in row_by_code)
    review_rows = [
        {
            "sample_id": code,
            "json_valid": "TRUE" if json_valid_by_code.get(code, False) else "FALSE",
            "core_features_complete": "",
            "too_fragmented": "",
            "wrong_category": "",
            "value_normalized": "",
            "usable": "",
            "notes": "",
        }
        for code in review_codes
    ]
    retry_rows = [
        issue
        for issue in all_issues
        if issue["severity"] == "fail"
        and issue["issue_type"] in {"missing_json", "invalid_json", "empty_rules", "atomic_rules_not_list"}
    ]

    paths = report_paths(args.report_dir, args.timestamped)
    write_csv(paths["anomalies"], all_issues, ANOMALY_COLUMNS)
    write_csv(paths["review"], review_rows, REVIEW_COLUMNS)
    write_csv(paths["retry"], retry_rows, ANOMALY_COLUMNS)
    markdown = build_markdown(
        metadata=args.metadata,
        atomic_dir=args.atomic_dir,
        rows=rows,
        rule_counts=rule_counts,
        issues=all_issues,
        valid_codes={code for code, is_valid in json_valid_by_code.items() if is_valid},
        paths=paths,
    )
    paths["markdown"].write_text(markdown, encoding="utf-8")

    severity_counter = Counter(issue["severity"] for issue in all_issues)
    print(f"Metadata rows: {len(rows)}")
    print(f"JSON-valid samples: {sum(1 for value in json_valid_by_code.values() if value)}")
    print(f"Issues: fail={severity_counter.get('fail', 0)} warn={severity_counter.get('warn', 0)}")
    print(f"Report: {paths['markdown']}")
    print(f"Anomalies: {paths['anomalies']}")
    print(f"Review samples: {paths['review']}")
    print(f"Retry samples: {paths['retry']}")


if __name__ == "__main__":
    main()
