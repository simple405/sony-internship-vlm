"""Generate deterministic candidates from human findings to atomic rules.

This is a pre-gold alignment helper. It does not rewrite gold data and does not
claim final semantic equivalence. It only proposes candidates that a later human
review or LLM-assisted text-only step can accept, reject, or refine.

A "candidate alignment" is a proposed mapping between one human visual finding
(a free-text observation written by a Stage 1 annotator) and one atomic rule
entry (a structured rule_id/value pair from atomic_rules.json). Because a single
finding can reasonably map to several rules, the script emits up to --top-k
candidates per finding, ranked by a composite score. The caller then filters or
accepts candidates based on the candidate_match_type and needs_review flag.

Scoring formula
---------------
    score = jaccard * 0.65 + sequence * 0.25 + value_bonus

- jaccard (weight 0.65): Jaccard similarity over the bag-of-tokens for the human
  finding text vs. the rule text (rule_id + atomic_value). Token-level overlap is
  the primary signal because the human text and the rule text tend to share
  domain-specific nouns (color names, body-part names, garment names). The high
  weight reflects that token identity is a stronger signal than character-sequence
  similarity for this domain.

- sequence (weight 0.25): SequenceMatcher ratio on the full lowercased strings.
  This captures partial matches where the same substring appears in both sides
  without being a whole token (e.g. "long straight hair" vs. "hair_straight").
  The lower weight (0.25) keeps it as a tiebreaker / soft-match booster rather
  than the primary driver.

- value_bonus (0.15 flat): Added when the finding's expected_value (or
  expected_from_2d) is a substring of the rule's atomic_value. This rewards
  exact value matches that might be missed by token overlap alone (e.g. a rule
  value of "deep blue" matching an expected_value of "deep blue").

The weights sum to 1.05 (with value_bonus). The slight over-budget is intentional:
value bonus acts as a small reward on top of the base 1.0 budget, pushing
value-confirmed candidates a tier higher than borderline token-overlap candidates.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("vlm/tmp/human_to_atomic_rule_alignment")

# Tokens stripped from all text before scoring because they carry no
# discriminative semantic content in this domain (article, preposition, copula).
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "has",
    "have",
    "is",
    "of",
    "the",
    "with",
}

# Surface-form aliases: map singular/plural variants and informal synonyms to a
# canonical token so that "shoe" and "footwear" both score against "footwear"
# rules. Extends token overlap without requiring a full lemmatizer.
TOKEN_ALIASES = {
    "bang": "bangs",
    "bows": "bow",
    "cloth": "clothing",
    "clothes": "clothing",
    "colour": "color",
    "eyes": "eye",
    "glasses": "glasses",
    "hat": "headwear",
    "hoodie": "hood",
    "ribbons": "ribbon",
    "shoe": "footwear",
    "shoes": "footwear",
    "sock": "legwear",
    "socks": "legwear",
}


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the alignment script.

    Returns:
        Parsed namespace with fields:
          visual_findings  -- path to human_visual_findings.csv
          sample_config    -- list of Qwen sample config JSON paths
          output_dir       -- directory for output CSVs and summary JSON
          top_k            -- maximum candidates to keep per finding (default 5)
          min_score        -- minimum composite score to include a candidate (default 0.18)
    """
    parser = argparse.ArgumentParser(description="Align human visual findings to atomic rule candidates.")
    parser.add_argument("--visual-findings", type=Path, required=True, help="human_visual_findings.csv")
    parser.add_argument(
        "--sample-config",
        type=Path,
        action="append",
        required=True,
        help="Qwen sample config JSON. Can be passed multiple times.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.18)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8-with-BOM CSV file and return a list of stripped row dicts.

    Args:
        path: Absolute path to the CSV file.

    Returns:
        List of row dicts where every key and value has been stripped of
        leading/trailing whitespace. None cell values are coerced to "".
    """
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    """Write rows to a UTF-8-with-BOM CSV file, ignoring extra keys in rows.

    Args:
        path: Destination path (parent directories are created automatically).
        rows: List of row dicts to write.
        fieldnames: Ordered list of column names for the header and output.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    """Write payload as pretty-printed UTF-8 JSON (no ASCII escaping).

    Args:
        path: Destination path (parent directories are created automatically).
        payload: Any JSON-serialisable value.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_sample_registry(sample_configs: list[Path]) -> dict[tuple[str, str], list[dict[str, str]]]:
    """Build a registry mapping (category, sample_id) -> list of atomic rules.

    Each Qwen sample config JSON may contain either a top-level list of samples
    or a dict with a "samples" key. For each sample entry, the atomic_rules.json
    file referenced by sample["atomic_rules"] is loaded and its rules are indexed.

    Args:
        sample_configs: Paths to one or more Qwen sample config JSON files.

    Returns:
        Dict keyed by (category, sample_id) tuples. Each value is the flat list
        of rule dicts [{"rule_id": str, "atomic_value": str}, ...] loaded from
        that sample's atomic_rules.json.
    """
    registry: dict[tuple[str, str], list[dict[str, str]]] = {}
    for config_path in sample_configs:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        # Config may be a bare list or wrapped in {"samples": [...]}
        samples = data if isinstance(data, list) else data.get("samples", [])
        for sample in samples:
            sample_id = str(sample.get("sample_id", "")).strip()
            category = str(sample.get("category", "")).strip()
            if not sample_id:
                continue
            registry[(category, sample_id)] = load_atomic_rules(Path(sample["atomic_rules"]))
    return registry


def load_atomic_rules(path: Path) -> list[dict[str, str]]:
    """Load and normalise atomic rules from a JSON file.

    Handles three atomic_rules.json shapes:
      - {"atomic_rules": [...]}  (most common wrapper shape)
      - A bare list of rule objects
      - A dict with another top-level key containing a list (falls through to
        the first branch and returns an empty list)

    Each rule object is expected to have a rule_id (also accepted under "id" or
    "name") and an optional "value" field.

    Args:
        path: Path to an atomic_rules.json file.

    Returns:
        Flat list of normalised rule dicts: [{"rule_id": str, "atomic_value": str}, ...]
    """
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    # Accept {"atomic_rules": [...]} wrapper or bare list
    raw_rules = data.get("atomic_rules", data) if isinstance(data, dict) else data
    rules: list[dict[str, str]] = []
    if not isinstance(raw_rules, list):
        return rules
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        # Accept rule_id under several historical key names
        rule_id = str(item.get("rule_id") or item.get("id") or item.get("name") or "").strip()
        if not rule_id:
            continue
        value = item.get("value", "")
        rules.append({"rule_id": rule_id, "atomic_value": str(value)})
    return rules


def tokens(text: str) -> set[str]:
    """Tokenise text into a set of normalised, stopword-filtered tokens.

    Steps:
      1. Split on any run of non-alphanumeric characters (handles both English
         spaces/punctuation and CJK separators).
      2. Lowercase every token.
      3. Drop tokens in STOPWORDS.
      4. Apply TOKEN_ALIASES so surface variants map to canonical forms.

    Args:
        text: Raw text string (may contain Chinese or mixed script).

    Returns:
        Set of canonical, lowercase, stopword-free tokens.
    """
    raw = re.split(r"[^A-Za-z0-9]+", text.lower())
    output: set[str] = set()
    for token in raw:
        if not token or token in STOPWORDS:
            continue
        # Canonicalise via aliases; keep token as-is if no alias found
        output.add(TOKEN_ALIASES.get(token, token))
    return output


def finding_text(row: dict[str, str]) -> str:
    """Build a single text string from all informative fields of a visual finding row.

    Concatenates several columns that collectively describe the human finding.
    All non-empty fields are joined with spaces so the token extractor and
    SequenceMatcher see the full semantics of the finding.

    Fields used (in order):
      human_rule_name, element_name, feature_key, attribute,
      expected_value, expected_from_2d, observed_value,
      observed_in_multiview, issue_type

    Args:
        row: A row dict from human_visual_findings.csv.

    Returns:
        Space-joined string of all non-empty field values.
    """
    parts = [
        row.get("human_rule_name", ""),
        row.get("element_name", ""),
        row.get("feature_key", ""),
        row.get("attribute", ""),
        row.get("expected_value", ""),
        row.get("expected_from_2d", ""),
        row.get("observed_value", ""),
        row.get("observed_in_multiview", ""),
        row.get("issue_type", ""),
    ]
    return " ".join(part for part in parts if part)


def score_candidate(finding: dict[str, str], rule: dict[str, str]) -> tuple[float, str]:
    """Compute the composite alignment score between one finding and one rule.

    Scoring formula (see module docstring for full rationale):
        score = jaccard * 0.65 + sequence * 0.25 + value_bonus

    - jaccard  (0.65): Token-set Jaccard similarity. Primary discriminator.
    - sequence (0.25): SequenceMatcher.ratio() on the full lowercased strings.
                       Captures substring matches missed by the token bag.
    - value_bonus (0.15 flat): Awarded when finding's expected_value (or
                       expected_from_2d) is a substring of the rule's atomic_value.

    Args:
        finding: Row dict from human_visual_findings.csv.
        rule: Dict with keys "rule_id" and "atomic_value".

    Returns:
        Tuple (score: float, reason: str) where reason is a semicolon-delimited
        diagnostic string logged to the output CSV for human review.
    """
    human_text = finding_text(finding)
    # Combine rule_id and atomic_value so both parts contribute to token overlap
    rule_text = f"{rule['rule_id']} {rule.get('atomic_value', '')}"

    human_tokens = tokens(human_text)
    rule_tokens = tokens(rule_text)
    if not human_tokens or not rule_tokens:
        return 0.0, "empty_tokens"

    # --- Jaccard component ---
    overlap = len(human_tokens & rule_tokens)
    union = len(human_tokens | rule_tokens)
    jaccard = overlap / union if union else 0.0

    # --- SequenceMatcher component ---
    # Works on full strings (not tokens) to reward partial-word matches
    sequence = difflib.SequenceMatcher(None, human_text.lower(), rule_text.lower()).ratio()

    # --- Value bonus: exact expected-value substring match in atomic_value ---
    value_bonus = 0.0
    expected = (finding.get("expected_value") or finding.get("expected_from_2d") or "").lower()
    atomic_value = rule.get("atomic_value", "").lower()
    if expected and atomic_value and expected in atomic_value:
        value_bonus = 0.15  # flat bonus, capped regardless of overlap size

    score = round((jaccard * 0.65) + (sequence * 0.25) + value_bonus, 4)
    reason = f"token_overlap={overlap};jaccard={jaccard:.3f};sequence={sequence:.3f};value_bonus={value_bonus:.2f}"
    return score, reason


def candidate_type(score: float, human_tokens: set[str], rule_tokens: set[str]) -> str:
    """Classify the strength of a candidate alignment into a named tier.

    Tiers (in descending confidence order):
      exact_match_candidate        -- score >= 0.86: very high overlap, likely the same rule
      semantic_equivalent_candidate -- score >= 0.55: high overlap, same concept expressed differently
      broader_or_narrower_candidate -- one token set is a subset of the other; specificity differs
      related_candidate            -- score >= 0.25: some overlap but not confidently equivalent
      low_confidence_candidate     -- score < 0.25 and no containment: weak association

    Args:
        score: Composite alignment score from score_candidate().
        human_tokens: Token set extracted from the human finding text.
        rule_tokens: Token set extracted from the rule text.

    Returns:
        String label for the candidate_match_type column.
    """
    if score >= 0.86:
        return "exact_match_candidate"
    if score >= 0.55:
        return "semantic_equivalent_candidate"
    # Containment check: one side is entirely inside the other's vocabulary
    if human_tokens <= rule_tokens or rule_tokens <= human_tokens:
        return "broader_or_narrower_candidate"
    if score >= 0.25:
        return "related_candidate"
    return "low_confidence_candidate"


def align_rows(
    findings: list[dict[str, str]],
    registry: dict[tuple[str, str], list[dict[str, str]]],
    top_k: int,
    min_score: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Score every finding against all atomic rules for its sample and return candidates.

    Algorithm for each finding:
      1. Look up atomic rules by (category, sample_id); fall back to ("", sample_id)
         to handle configs that omit category.
      2. Score each rule and keep only those >= min_score.
      3. Sort by score descending and keep the top_k candidates.
      4. If no candidate passes min_score, emit a single no_match_candidate row.
      5. Flag needs_review=True for any non-exact-match candidate.
      6. Add a "multiple_high_confidence_candidates" warning when >= 2 candidates
         score >= 0.55 for the same finding_id (ambiguous finding).

    Args:
        findings: List of row dicts from human_visual_findings.csv.
        registry: (category, sample_id) -> [rule dicts] mapping.
        top_k: Maximum candidates to retain per finding.
        min_score: Minimum composite score threshold.

    Returns:
        Tuple (candidates, review_queue):
          candidates    -- all emitted candidate rows (full set, multiple per finding)
          review_queue  -- subset flagged as needs_review=true or not exact_match
    """
    candidates: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []

    for row in findings:
        sample_id = row.get("sample_id", "")
        category = row.get("category", "")
        finding_id = row.get("finding_id", "")

        # Try exact (category, sample_id) key first, then ("", sample_id) fallback
        rules = registry.get((category, sample_id)) or registry.get(("", sample_id)) or []
        if not rules:
            # No atomic rules loaded for this sample — cannot produce any candidate
            no_match = candidate_row(row, "", "", 0.0, "no_atomic_rules_for_sample", "no_match_candidate", True)
            candidates.append(no_match)
            review_queue.append(no_match)
            continue

        scored: list[dict[str, Any]] = []
        human_tokens = tokens(finding_text(row))
        for rule in rules:
            score, reason = score_candidate(row, rule)
            rule_tokens = tokens(f"{rule['rule_id']} {rule.get('atomic_value', '')}")
            if score >= min_score:
                scored.append(
                    candidate_row(
                        row,
                        rule["rule_id"],
                        rule.get("atomic_value", ""),
                        score,
                        reason,
                        candidate_type(score, human_tokens, rule_tokens),
                        # Require review if score is below "semantic equivalent" threshold
                        score < 0.55,
                    )
                )

        # Sort descending by composite score, keep top_k
        scored.sort(key=lambda item: item["mapping_score"], reverse=True)
        kept = scored[:top_k]

        if not kept:
            no_match = candidate_row(row, "", "", 0.0, "no_candidate_above_min_score", "no_match_candidate", True)
            candidates.append(no_match)
            review_queue.append(no_match)
            continue

        candidates.extend(kept)
        # Populate review queue: any non-exact or flagged candidate
        for item in kept:
            if item["needs_review"] == "true" or item["candidate_match_type"] != "exact_match_candidate":
                review_queue.append(item)

        # Warn when multiple high-confidence candidates exist for the same finding —
        # this usually means the human finding text is too broad (e.g. just "hair")
        if finding_id and sum(1 for item in kept if item["mapping_score"] >= 0.55) > 1:
            for item in kept:
                item["warnings"] = append_warning(str(item.get("warnings", "")), "multiple_high_confidence_candidates")

    return candidates, review_queue


def candidate_row(
    finding: dict[str, str],
    atomic_rule_id: str,
    atomic_rule_value: str,
    score: float,
    reason: str,
    match_type: str,
    needs_review: bool,
) -> dict[str, Any]:
    """Build a single candidate output row dict from a finding and matched rule.

    Consolidates all fields needed by the downstream reviewer into one flat dict.
    The human_rule_name falls back to feature_key when the primary column is empty,
    and similarly for human_element_name and human_value — this handles older CSV
    exports that used different column names.

    Args:
        finding: Source finding row dict.
        atomic_rule_id: Matched rule_id string (empty string for no-match rows).
        atomic_rule_value: Matched rule's atomic_value string.
        score: Composite alignment score (0.0 for no-match rows).
        reason: Diagnostic reason string from score_candidate().
        match_type: Candidate type label from candidate_type().
        needs_review: Whether this candidate should be added to the review queue.

    Returns:
        Flat row dict for writing to the output CSV.
    """
    return {
        "sample_id": finding.get("sample_id", ""),
        "category": finding.get("category", ""),
        "human_finding_id": finding.get("finding_id", ""),
        # Prefer human_rule_name; fall back to feature_key for older exports
        "human_rule_name": finding.get("human_rule_name") or finding.get("feature_key", ""),
        "human_element_name": finding.get("element_name") or finding.get("feature_key", ""),
        "human_attribute": finding.get("attribute", ""),
        # Prefer explicit expected_value; fall back to the 2D-view column
        "human_value": finding.get("expected_value") or finding.get("expected_from_2d", ""),
        "atomic_rule_id": atomic_rule_id,
        "atomic_rule_value": atomic_rule_value,
        "candidate_match_type": match_type,
        "mapping_score": score,
        "mapping_reason": reason,
        "needs_review": "true" if needs_review else "false",
        "warnings": "",
    }


def append_warning(current: str, warning: str) -> str:
    """Append a warning token to a semicolon-delimited warning string (idempotent).

    Args:
        current: Existing warnings string (may be empty).
        warning: New warning token to append.

    Returns:
        Updated warnings string. If warning is already present, returns current
        unchanged to avoid duplication.
    """
    if not current:
        return warning
    # Avoid adding duplicate warnings
    if warning in current.split(";"):
        return current
    return current + ";" + warning


def summarize_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Count candidates by candidate_match_type for the summary JSON.

    Args:
        candidates: Full list of candidate row dicts.

    Returns:
        Dict mapping each match type to its count, sorted alphabetically.
    """
    by_type: dict[str, int] = defaultdict(int)
    for row in candidates:
        by_type[str(row.get("candidate_match_type", ""))] += 1
    return dict(sorted(by_type.items()))


def main() -> None:
    """Entry point: load findings + registry, run alignment, write output files.

    Output files written to --output-dir:
      human_to_atomic_rule_mapping_candidates.csv -- all candidate rows
      mapping_review_queue.csv                    -- subset needing human review
      summary.json                                -- run statistics
    """
    args = parse_args()
    findings = read_csv(args.visual_findings)
    registry = load_sample_registry(args.sample_config)
    candidates, review_queue = align_rows(findings, registry, args.top_k, args.min_score)

    output_dir = args.output_dir
    columns = [
        "sample_id",
        "category",
        "human_finding_id",
        "human_rule_name",
        "human_element_name",
        "human_attribute",
        "human_value",
        "atomic_rule_id",
        "atomic_rule_value",
        "candidate_match_type",
        "mapping_score",
        "mapping_reason",
        "needs_review",
        "warnings",
    ]
    write_csv(output_dir / "human_to_atomic_rule_mapping_candidates.csv", candidates, columns)
    write_csv(output_dir / "mapping_review_queue.csv", review_queue, columns)

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "visual_findings": str(args.visual_findings),
        "sample_configs": [str(path) for path in args.sample_config],
        "findings": len(findings),
        "known_samples": len(registry),
        "candidate_rows": len(candidates),
        "review_queue_rows": len(review_queue),
        "candidate_type_counts": summarize_candidates(candidates),
    }
    write_json(output_dir / "summary.json", summary)
    print(json.dumps({"status": "finished", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
