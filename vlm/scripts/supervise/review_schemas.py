"""Shared schemas for offline supervision review artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


SCHEMA_VERSION = "supervision_offline.v1"
# Note 1: Keep all schema-bearing artifacts on the same version string so a
# future migration can detect mixed old/new result files with one field check.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
# Note 2: This category tuple is the shared contract used by CLI choices,
# folder routing, category_rules.json, and report grouping. Add new categories
# here only after deciding their generated-output folder convention.
CATEGORIES = (
    "head_key_chain",
    "backpack",
    "cake_roll",
    "plush",
    "dataset_QSitFigures",
    "dataset_figurine",
)
HEAD_ONLY_CATEGORIES = {"head_key_chain", "backpack", "cake_roll"}
FULL_BODY_CATEGORIES = {"plush", "dataset_QSitFigures", "dataset_figurine"}
# Note 3: These two sets encode the current on-disk split under
# generated_3d_no_rules/.../head_only and full body. They are intentionally
# data-layout rules, not semantic rules about what the product should depict.

Decision = Literal[
    "approved",
    "needs_revision",
    "human_review_required",
    "rejected",
    "blocked",
    "not_reviewed",
    "unknown",
]
Severity = Literal["critical", "high", "medium", "low", "info"]


@dataclass
class ReviewPair:
    # Note 4: ReviewPair is the minimal durable unit of work. Downstream runners
    # should never rediscover paths from scratch when this object already exists,
    # because that would make one run harder to reproduce later.
    sample_id: str
    category: str
    source_image_path: str
    generated_image_path: str
    generated_candidates: list[str] = field(default_factory=list)
    atomic_rules_path: str | None = None
    manifest_row: dict[str, Any] = field(default_factory=dict)
    # Note 5: seed_case is optional metadata from experiments/supervision. It is
    # kept beside the pair so reports can compare dry-run or model outputs with
    # the human-curated expected labels without changing the pair identity.
    seed_case: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION


@dataclass
class Finding:
    # Note 6: Findings are intentionally specific rather than a single free-text
    # review. This shape lets CSV reports count recurring failure types and lets
    # humans audit whether each high-risk claim has evidence.
    finding_id: str
    type: str
    dimension: str
    severity: Severity
    confidence: float
    source_region: str
    generated_region: str
    problem_cn: str
    expected_cn: str
    suggestion_cn: str
    evidence_cn: str


@dataclass
class ReviewResult:
    # Note 7: ReviewResult stores the machine-readable decision surface. Even in
    # dry-run mode we write this full object so later real VLM integrations can
    # reuse the same report writer and human feedback workflow.
    sample_id: str
    category: str
    decision: Decision
    score: int
    risk_level: str
    confidence: float
    requires_human_review: bool
    review_status: str
    summary_cn: str
    findings: list[Finding] = field(default_factory=list)
    positive_points: list[str] = field(default_factory=list)
    source_evidence: dict[str, Any] = field(default_factory=dict)
    generated_evidence: dict[str, Any] = field(default_factory=dict)
    # Note 8: metadata is the escape hatch for provenance, not for new review
    # judgments. Put paths, seed labels, provider IDs, or raw payload references
    # here; add first-class fields only when reports depend on them.
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION


@dataclass
class RunSummary:
    # Note 9: RunSummary should stay small and spreadsheet-friendly. Detailed
    # per-sample information belongs in result.json or the CSV tables.
    run_id: str
    review_status: str
    total_pairs: int
    processed: int
    skipped_existing: int
    errors: int
    output_dir: str
    skipped_pairs: int = 0
    schema_version: str = SCHEMA_VERSION


def to_jsonable(value: Any) -> Any:
    # Note 10: json.dumps cannot serialize Path or dataclass instances directly.
    # Centralizing this conversion prevents each caller from inventing slightly
    # different JSON shapes for the same schema objects.
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


def result_from_dict(data: dict[str, Any]) -> ReviewResult:
    # Note 11: JSON round-trips turn nested dataclasses into dictionaries. This
    # helper rebuilds Finding objects so skipped/resume logic can treat loaded
    # results the same as freshly produced results.
    findings = [Finding(**item) for item in data.get("findings", [])]
    payload = dict(data)
    payload["findings"] = findings
    return ReviewResult(**payload)
