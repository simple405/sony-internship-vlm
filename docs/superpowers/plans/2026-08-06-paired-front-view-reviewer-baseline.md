# Paired Front-View Reviewer Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Qwen-VL reviewer baseline that scores each generated PVC front-view image against its paired gold JSON, without leaking the original 2D source image into the review request, then run it against the 20-sample pilot.

**Architecture:** A new standalone script (`vlm/scripts/supervise/run_paired_front_view_review.py`) discovers complete 3-file sample directories under `vlm/data/front_view_generation_v1/`, renders a frozen prompt template with the sample's gold element list, calls Qwen-VL with only the generated image, parses/aligns the JSON response against the gold element order, and writes per-sample predictions plus a batch summary to `vlm/tmp/paired_front_view_review_v1/`.

**Tech Stack:** Python 3.11, `requests` (DashScope OpenAI-compatible chat/completions endpoint), `Pillow` (already a dependency), `pytest`.

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-08-06-paired-front-view-reviewer-baseline-design.md`.
- Default review request must reference exactly one image: the generated front-view PNG. The original 2D source image path/content must never appear in any request payload, preview file, or log line produced by this script.
- `evidence_bbox` values are always in the generated image's pixel coordinate system (fixed 1915x821 for this pilot) — never the gold JSON's original-image coordinate system.
- `rule_index` is 1-based and must match the gold element's position in its JSON array; the script must overwrite/repair whatever the model returns rather than trusting it.
- `result` must be one of exactly five values: `pass`, `partial`, `fail`, `not_evaluable`, `review`.
- Output goes to `vlm/tmp/paired_front_view_review_v1/` (scratch), never into `vlm/data/front_view_generation_v1/` (must not mutate Phase A's deliverable directories).
- CSV files use `utf-8-sig` encoding (project convention, Excel compatibility).
- Every `.py` file needs a module docstring and Google-style docstrings on non-trivial functions (project convention, enforced by `pydocstyle` pre-commit hook).
- The script must refuse to scale beyond the 20-sample pilot unless the caller passes explicit `--sample-id` values (guard against accidentally reviewing all 6901 samples).
- No test may call the real Qwen/DashScope endpoint — API calls are injected via a `call_fn` parameter so tests can substitute a stub.

---

## File Structure

- Create: `vlm/prompts/supervision/paired_front_view_review_v1_cn.txt` — frozen reviewer prompt template with `{{GOLD_COUNT}}` / `{{GOLD_ELEMENTS}}` placeholders.
- Create: `vlm/scripts/supervise/run_paired_front_view_review.py` — the reviewer script (sample discovery, prompt rendering, Qwen call, validation, output writing, CLI).
- Create: `tests/test_paired_front_view_review.py` — unit tests covering discovery, prompt rendering, leak checks, rule alignment, and the pilot-scale guard, with all network calls mocked.

---

### Task 1: Frozen reviewer prompt template

**Files:**
- Create: `vlm/prompts/supervision/paired_front_view_review_v1_cn.txt`
- Test: `tests/test_paired_front_view_review.py`

**Interfaces:**
- Produces: a template file containing the literal placeholder tokens `{{GOLD_COUNT}}` and `{{GOLD_ELEMENTS}}`, which Task 3's `build_review_prompt()` will substitute via `str.replace`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_paired_front_view_review.py` with this first test:

```python
from pathlib import Path

PROMPT_TEMPLATE_PATH = Path("vlm/prompts/supervision/paired_front_view_review_v1_cn.txt")


def test_prompt_template_exists_and_declares_contract():
    text = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8-sig")
    assert text.strip()
    assert "{{GOLD_COUNT}}" in text
    assert "{{GOLD_ELEMENTS}}" in text
    for keyword in ("rule_index", "evidence_bbox", "pass", "partial", "fail", "not_evaluable", "review", "extra_elements"):
        assert keyword in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: FAIL with "No such file or directory" (template does not exist yet).

- [ ] **Step 3: Write the prompt template**

Create `vlm/prompts/supervision/paired_front_view_review_v1_cn.txt` with exactly this content:

```text
你是动漫 IP 周边商品监修 VLM。你的任务是：只根据一张 3D PVC 手办正面设计图，逐条判断给定的角色元素描述规格（gold 规格）是否在这张图中被正确呈现。

严格输出：只能输出一个 JSON object，不要输出 Markdown、代码块或除 JSON 外的任何文字。

═══════════════════════════════════════
输入
═══════════════════════════════════════
你会看到一张图片：3D PVC 手办正面渲染图。
你不会看到原始 2D 角色图 —— 只能依据下方列出的 gold 规格描述和你看到的这张图进行判断，不要假设或猜测图片之外的内容。

gold 规格（共 {{GOLD_COUNT}} 条，按顺序编号，对应输出的 rule_index）：
{{GOLD_ELEMENTS}}

═══════════════════════════════════════
输出 schema
═══════════════════════════════════════
返回一个 JSON object，包含：
{
  "rules": [
    {
      "rule_index": 1,
      "image_grounded": true,
      "description_correct": true,
      "issue_types": [],
      "observed_description": "你在图中观察到的内容，用中文描述。",
      "evidence_bbox": [x1, y1, x2, y2],
      "confidence": 0.0到1.0之间的浮点数,
      "reason": "你为什么给出这个 result 的简要理由。",
      "result": "pass | partial | fail | not_evaluable | review"
    }
  ],
  "extra_elements": [
    {
      "element": "图中出现但不在上方 gold 规格中的显著元素名称",
      "observed_description": "...",
      "evidence_bbox": [x1, y1, x2, y2],
      "confidence": 0.0到1.0,
      "issue_types": ["extra"],
      "reason": "..."
    }
  ]
}

═══════════════════════════════════════
判断规则
═══════════════════════════════════════
1. rules 数组必须恰好包含 {{GOLD_COUNT}} 个对象，顺序必须与上方 gold 规格顺序完全一致，rule_index 从 1 开始严格对应。不要合并、拆分、新增或省略任何一条。
2. result 只能是以下五个值之一：
   - pass：该元素在图中清晰可见，且颜色、形状、结构与描述一致。
   - partial：描述包含多个子特征，其中部分正确、部分错误或缺失，不能算完全正确也不能算完全错误。
   - fail：该元素在图中明显缺失，或颜色/形状/结构与描述明显不符。
   - not_evaluable：该元素本应只在背面或侧面才可见，本图为正面视角，无法判断，不算缺失。
   - review：图像证据不足、描述本身含糊，或你的置信度较低，需要人工复核。
3. evidence_bbox 是该元素在**这张生成图**上的像素坐标 [x1, y1, x2, y2]（图片尺寸约 1915x821）。如果 result 是 not_evaluable，evidence_bbox 可以为 null。
4. image_grounded 表示你的判断是否基于图中实际可见的内容（而不是猜测）；description_correct 表示描述与图像是否吻合。
5. issue_types 用简短英文关键词列出问题类型，例如 ["color"], ["shape"], ["missing"], ["material"], ["structure"], ["ambiguous"]；如果没有问题则为空列表 []。
6. extra_elements 记录图中明显可见、但不属于任何一条 gold 规格描述的显著元素（例如生成图中出现了原图没有的饰品）。不要把这类元素塞进某条 rule_index 里。如果没有额外元素，返回空列表 []。
7. 只依据图片可见内容判断，不要猜测图片之外的细节；如果证据不足，选择 review 而不是猜测 pass 或 fail。
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vlm/prompts/supervision/paired_front_view_review_v1_cn.txt tests/test_paired_front_view_review.py
git commit -m "feat: add frozen paired front-view reviewer prompt template"
```

---

### Task 2: Sample discovery

**Files:**
- Create: `vlm/scripts/supervise/run_paired_front_view_review.py`
- Test: `tests/test_paired_front_view_review.py`

**Interfaces:**
- Produces: `ReviewSample` dataclass (`sample_id: str`, `generated_image_path: Path`, `gold_path: Path`, `original_image_path: Path`) and `discover_samples(input_root: Path) -> list[ReviewSample]`, sorted by `sample_id`, skipping `_metadata` and any directory missing one of the three deliverable files.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_paired_front_view_review.py`:

```python
from vlm.scripts.supervise.run_paired_front_view_review import ReviewSample, discover_samples


def _write_complete_sample(root: Path, sample_id: str) -> Path:
    sample_dir = root / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    (sample_dir / f"{sample_id}_q_front_view.png").write_bytes(b"fake-png")
    (sample_dir / f"{sample_id}_original.png").write_bytes(b"fake-png")
    (sample_dir / f"{sample_id}.json").write_text("[]", encoding="utf-8")
    return sample_dir


def test_discover_samples_finds_only_complete_three_file_dirs(tmp_path: Path):
    _write_complete_sample(tmp_path, "sample-b")
    _write_complete_sample(tmp_path, "sample-a")
    incomplete_dir = tmp_path / "sample-incomplete"
    incomplete_dir.mkdir()
    (incomplete_dir / "sample-incomplete_q_front_view.png").write_bytes(b"fake-png")
    metadata_dir = tmp_path / "_metadata"
    metadata_dir.mkdir()
    (metadata_dir / "sample-a").mkdir()

    samples = discover_samples(tmp_path)

    assert [sample.sample_id for sample in samples] == ["sample-a", "sample-b"]
    assert isinstance(samples[0], ReviewSample)
    assert samples[0].generated_image_path == tmp_path / "sample-a" / "sample-a_q_front_view.png"
    assert samples[0].gold_path == tmp_path / "sample-a" / "sample-a.json"
    assert samples[0].original_image_path == tmp_path / "sample-a" / "sample-a_original.png"


def test_discover_samples_returns_empty_for_missing_root(tmp_path: Path):
    assert discover_samples(tmp_path / "does-not-exist") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: FAIL with "No module named 'vlm.scripts.supervise.run_paired_front_view_review'"

- [ ] **Step 3: Write minimal implementation**

Create `vlm/scripts/supervise/run_paired_front_view_review.py`:

```python
"""Run a Qwen-VL reviewer baseline on paired front-view generation samples.

Reads generated PVC front-view images and their paired gold JSON from
vlm/data/front_view_generation_v1/, calls Qwen-VL with only the generated
image (never the original 2D source image), and writes structured
per-element verdicts to vlm/tmp/paired_front_view_review_v1/.

Usage:
    python -m vlm.scripts.supervise.run_paired_front_view_review --dry-run --limit 20
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vlm.scripts.generate.runninghub_client import IMAGE_SUFFIXES


@dataclass(frozen=True)
class ReviewSample:
    """One pilot sample ready for review.

    Attributes:
        sample_id: Unique sample identifier (matches the Phase A output directory name).
        generated_image_path: Path to the RunningHub-generated PVC front-view PNG.
        gold_path: Path to the paired human-authored gold JSON.
        original_image_path: Path to the original 2D source image (audit-only, never sent to Qwen).
    """

    sample_id: str
    generated_image_path: Path
    gold_path: Path
    original_image_path: Path


def discover_samples(input_root: Path) -> list[ReviewSample]:
    """Find pilot sample directories with all three deliverable files.

    Args:
        input_root: Root directory to scan (e.g. vlm/data/front_view_generation_v1).

    Returns:
        ReviewSample list sorted by sample_id. Directories named "_metadata" and any
        directory missing the generated image, gold JSON, or original image are skipped.
    """
    samples: list[ReviewSample] = []
    if not input_root.is_dir():
        return samples
    for sample_dir in sorted(input_root.iterdir()):
        if not sample_dir.is_dir() or sample_dir.name == "_metadata":
            continue
        sample_id = sample_dir.name
        generated = sample_dir / f"{sample_id}_q_front_view.png"
        gold = sample_dir / f"{sample_id}.json"
        if not generated.is_file() or not gold.is_file():
            continue
        original = None
        for suffix in IMAGE_SUFFIXES:
            candidate = sample_dir / f"{sample_id}_original{suffix}"
            if candidate.is_file():
                original = candidate
                break
        if original is None:
            continue
        samples.append(ReviewSample(sample_id, generated, gold, original))
    return samples
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add vlm/scripts/supervise/run_paired_front_view_review.py tests/test_paired_front_view_review.py
git commit -m "feat: add paired front-view sample discovery"
```

---

### Task 3: Gold loading and prompt rendering

**Files:**
- Modify: `vlm/scripts/supervise/run_paired_front_view_review.py`
- Test: `tests/test_paired_front_view_review.py`

**Interfaces:**
- Consumes: nothing from prior tasks besides the module itself.
- Produces: `load_gold_elements(gold_path: Path) -> list[dict]` and `build_review_prompt(template: str, gold_elements: list[dict]) -> str`. Later tasks call `build_review_prompt` to get the exact text sent to Qwen.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_paired_front_view_review.py`:

```python
import json

from vlm.scripts.supervise.run_paired_front_view_review import build_review_prompt, load_gold_elements


def test_load_gold_elements_returns_raw_list(tmp_path: Path):
    gold_path = tmp_path / "sample-1.json"
    gold_path.write_text(
        json.dumps([{"element": "红色眼睛", "description": "鲜艳的红色", "bbox": [1, 2, 3, 4]}], ensure_ascii=False),
        encoding="utf-8",
    )

    elements = load_gold_elements(gold_path)

    assert elements == [{"element": "红色眼睛", "description": "鲜艳的红色", "bbox": [1, 2, 3, 4]}]


def test_build_review_prompt_numbers_elements_and_fills_count():
    template = "COUNT={{GOLD_COUNT}}\nELEMENTS:\n{{GOLD_ELEMENTS}}\nEND"
    gold_elements = [
        {"element": "金色长发", "description": "飘逸的金色长发"},
        {"element": "红色眼睛", "description": "鲜艳的红色"},
    ]

    prompt = build_review_prompt(template, gold_elements)

    assert "COUNT=2" in prompt
    assert "1. element: 金色长发" in prompt
    assert "2. element: 红色眼睛" in prompt
    assert prompt.index("1. element: 金色长发") < prompt.index("2. element: 红色眼睛")
    assert "{{GOLD_COUNT}}" not in prompt
    assert "{{GOLD_ELEMENTS}}" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: FAIL with "cannot import name 'build_review_prompt'"

- [ ] **Step 3: Write minimal implementation**

Add to `vlm/scripts/supervise/run_paired_front_view_review.py` (add `import json` and `from typing import Any` to the imports at the top):

```python
def load_gold_elements(gold_path: Path) -> list[dict[str, Any]]:
    """Load the raw gold element list from a paired sample JSON file.

    Args:
        gold_path: Path to <sample_id>.json, a JSON array of
            {"element": str, "description": str, "bbox": [x1, y1, x2, y2]} objects
            in the original 2D source image's coordinate system.

    Returns:
        The parsed list, unmodified. bbox values here are never comparable to
        evidence_bbox values produced by the reviewer (different coordinate system).
    """
    return json.loads(gold_path.read_text(encoding="utf-8"))


def build_review_prompt(template: str, gold_elements: list[dict[str, Any]]) -> str:
    """Render the frozen reviewer prompt template with a numbered gold element list.

    Args:
        template: Prompt template text containing the literal placeholders
            "{{GOLD_COUNT}}" and "{{GOLD_ELEMENTS}}".
        gold_elements: Gold element list as returned by load_gold_elements(). The
            1-based position of each element in this list becomes its rule_index.

    Returns:
        The template with both placeholders substituted.
    """
    lines = []
    for index, element in enumerate(gold_elements, start=1):
        lines.append(f"{index}. element: {element.get('element', '')}")
        lines.append(f"   description: {element.get('description', '')}")
    gold_block = "\n".join(lines)
    return template.replace("{{GOLD_COUNT}}", str(len(gold_elements))).replace("{{GOLD_ELEMENTS}}", gold_block)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add vlm/scripts/supervise/run_paired_front_view_review.py tests/test_paired_front_view_review.py
git commit -m "feat: add gold element loading and prompt rendering"
```

---

### Task 4: Request preview (leak-check) construction

**Files:**
- Modify: `vlm/scripts/supervise/run_paired_front_view_review.py`
- Test: `tests/test_paired_front_view_review.py`

**Interfaces:**
- Consumes: `ReviewSample` (Task 2).
- Produces: `request_preview(sample: ReviewSample, prompt_file: Path, prompt_text: str, gold_element_count: int, output_dir: Path) -> dict`. Task 7's `process_one()` writes this dict to `request_preview.json` for both dry-run and real-call paths.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_paired_front_view_review.py`:

```python
from vlm.scripts.supervise.run_paired_front_view_review import request_preview


def test_request_preview_references_only_generated_image_never_original(tmp_path: Path):
    sample_dir = _write_complete_sample(tmp_path, "sample-1")
    sample = ReviewSample(
        sample_id="sample-1",
        generated_image_path=sample_dir / "sample-1_q_front_view.png",
        gold_path=sample_dir / "sample-1.json",
        original_image_path=sample_dir / "sample-1_original.png",
    )
    prompt_text = "rendered prompt text mentioning gold description"

    preview = request_preview(sample, tmp_path / "prompt.txt", prompt_text, gold_element_count=3, output_dir=tmp_path / "out")

    serialized = json.dumps(preview, ensure_ascii=False)
    assert str(sample.original_image_path) not in serialized
    assert preview["request"]["image_path"] == str(sample.generated_image_path)
    assert preview["request"]["image_count"] == 1
    assert preview["gold_element_count"] == 3
    assert preview["request"]["prompt"] == prompt_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: FAIL with "cannot import name 'request_preview'"

- [ ] **Step 3: Write minimal implementation**

Add to `vlm/scripts/supervise/run_paired_front_view_review.py` (add `import hashlib` to imports):

```python
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_preview(
    sample: ReviewSample,
    prompt_file: Path,
    prompt_text: str,
    gold_element_count: int,
    output_dir: Path,
) -> dict[str, Any]:
    """Build a redacted-safe preview of the Qwen request for audit and dry-run inspection.

    Args:
        sample: The sample being reviewed. Only sample.generated_image_path may appear
            in the returned dict — sample.original_image_path must never be referenced.
        prompt_file: Path to the frozen prompt template file (recorded for provenance).
        prompt_text: The fully rendered prompt text that will be sent to Qwen.
        gold_element_count: Number of gold elements the prompt was rendered with.
        output_dir: Directory this sample's outputs will be written to.

    Returns:
        A JSON-serializable dict containing the exact request shape and hashes, with no
        reference to the original 2D source image.
    """
    return {
        "schema_version": "paired_front_view_review_request.v1",
        "sample_id": sample.sample_id,
        "generated_image_sha256": _sha256(sample.generated_image_path),
        "prompt_file": str(prompt_file),
        "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        "gold_element_count": gold_element_count,
        "request": {
            "prompt": prompt_text,
            "image_path": str(sample.generated_image_path),
            "image_count": 1,
        },
        "output_dir": str(output_dir),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add vlm/scripts/supervise/run_paired_front_view_review.py tests/test_paired_front_view_review.py
git commit -m "feat: add leak-safe request preview for paired front-view review"
```

---

### Task 5: Rule alignment, aggregate counts, overall decision

**Files:**
- Modify: `vlm/scripts/supervise/run_paired_front_view_review.py`
- Test: `tests/test_paired_front_view_review.py`

**Interfaces:**
- Consumes: nothing new from prior tasks.
- Produces: `ALLOWED_RESULTS: set[str]`, `validate_and_align_rules(raw_rules: Any, gold_elements: list[dict]) -> tuple[list[dict], list[str]]`, `compute_aggregate_counts(rules: list[dict]) -> dict[str, int]`, `compute_overall_decision(rules: list[dict], qc_issues: list[str]) -> str`. Task 7's `process_one()` calls all three in sequence on the parsed model response.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_paired_front_view_review.py`:

```python
from vlm.scripts.supervise.run_paired_front_view_review import (
    compute_aggregate_counts,
    compute_overall_decision,
    validate_and_align_rules,
)


def test_validate_and_align_rules_forces_rule_index_and_element_from_gold():
    gold_elements = [{"element": "金色长发"}, {"element": "红色眼睛"}]
    raw_rules = [
        {"rule_index": 99, "element": "wrong-name", "result": "pass", "confidence": 0.9},
        {"rule_index": 1, "result": "fail", "confidence": 0.8},
    ]

    aligned, issues = validate_and_align_rules(raw_rules, gold_elements)

    assert [rule["rule_index"] for rule in aligned] == [1, 2]
    assert [rule["element"] for rule in aligned] == ["金色长发", "红色眼睛"]
    assert aligned[0]["result"] == "pass"
    assert aligned[1]["result"] == "fail"
    assert issues == []


def test_validate_and_align_rules_repairs_missing_and_invalid_entries():
    gold_elements = [{"element": "金色长发"}, {"element": "红色眼睛"}]
    raw_rules = [{"rule_index": 1, "result": "not-a-real-result", "confidence": 0.9}]

    aligned, issues = validate_and_align_rules(raw_rules, gold_elements)

    assert len(aligned) == 2
    assert aligned[0]["result"] == "review"
    assert aligned[1]["result"] == "review"
    assert any("missing_rule_index_2" in issue for issue in issues)
    assert any("invalid_result_at_index_1" in issue for issue in issues)


def test_validate_and_align_rules_rejects_non_list_input():
    aligned, issues = validate_and_align_rules("not a list", [{"element": "金色长发"}])

    assert len(aligned) == 1
    assert aligned[0]["result"] == "review"
    assert "rules_not_a_list" in issues


def test_compute_aggregate_counts_tallies_by_result():
    rules = [{"result": "pass"}, {"result": "pass"}, {"result": "fail"}, {"result": "review"}]

    counts = compute_aggregate_counts(rules)

    assert counts == {"pass": 2, "partial": 0, "fail": 1, "not_evaluable": 0, "review": 1}


def test_compute_overall_decision_prioritizes_fail_then_review_then_pass():
    assert compute_overall_decision([{"result": "fail", "confidence": 0.9}], []) == "fail"
    assert compute_overall_decision([{"result": "pass", "confidence": 0.9}], ["some_qc_issue"]) == "review"
    assert compute_overall_decision([{"result": "review", "confidence": 0.9}], []) == "review"
    assert compute_overall_decision([{"result": "pass", "confidence": 0.4}], []) == "review"
    assert compute_overall_decision([{"result": "pass", "confidence": 0.9}], []) == "pass"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: FAIL with "cannot import name 'validate_and_align_rules'"

- [ ] **Step 3: Write minimal implementation**

Add to `vlm/scripts/supervise/run_paired_front_view_review.py`:

```python
ALLOWED_RESULTS = {"pass", "partial", "fail", "not_evaluable", "review"}


def validate_and_align_rules(
    raw_rules: Any,
    gold_elements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Force the model's rules array to match gold element count, order, and enum values.

    Args:
        raw_rules: Whatever the model returned under the "rules" key (may be malformed).
        gold_elements: The gold element list this sample's prompt was built from.

    Returns:
        A tuple of (aligned_rules, qc_issues). aligned_rules always has exactly
        len(gold_elements) entries, in gold order, with rule_index and element forced
        to match gold and result guaranteed to be in ALLOWED_RESULTS (unrecoverable
        entries are downgraded to "review"). qc_issues lists every repair made.
    """
    issues: list[str] = []
    if not isinstance(raw_rules, list):
        issues.append("rules_not_a_list")
        raw_rules = []
    if len(raw_rules) > len(gold_elements):
        issues.append("extra_rule_entries_beyond_gold_count")

    aligned: list[dict[str, Any]] = []
    for index, gold in enumerate(gold_elements, start=1):
        candidate = raw_rules[index - 1] if index - 1 < len(raw_rules) else None
        rule = dict(candidate) if isinstance(candidate, dict) else {}
        if candidate is None:
            issues.append(f"missing_rule_index_{index}")
        rule["rule_index"] = index
        rule["element"] = gold.get("element", "")
        result = str(rule.get("result", "")).strip()
        if result not in ALLOWED_RESULTS:
            issues.append(f"invalid_result_at_index_{index}:{result}")
            rule["result"] = "review"
        bbox = rule.get("evidence_bbox")
        if bbox is not None and (not isinstance(bbox, list) or len(bbox) != 4):
            issues.append(f"invalid_evidence_bbox_at_index_{index}")
            rule["evidence_bbox"] = None
        aligned.append(rule)
    return aligned, issues


def compute_aggregate_counts(rules: list[dict[str, Any]]) -> dict[str, int]:
    """Tally rule results by the five allowed result values.

    Args:
        rules: Aligned rules as returned by validate_and_align_rules().

    Returns:
        Dict with one key per ALLOWED_RESULTS value, each mapped to its count.
    """
    counts = {result: 0 for result in ALLOWED_RESULTS}
    for rule in rules:
        result = rule.get("result", "review")
        counts[result] = counts.get(result, 0) + 1
    return counts


def compute_overall_decision(rules: list[dict[str, Any]], qc_issues: list[str]) -> str:
    """Derive a single sample-level decision from per-rule results and QC issues.

    Args:
        rules: Aligned rules as returned by validate_and_align_rules().
        qc_issues: QC issue strings from validate_and_align_rules(); any issue forces
            at least "review" since the model's output required repair.

    Returns:
        "fail" if any rule failed; else "review" if any rule needs review, confidence
        is low, or there were QC issues; else "pass".
    """
    if any(rule.get("result") == "fail" for rule in rules):
        return "fail"
    if qc_issues:
        return "review"
    if any(rule.get("result") == "review" for rule in rules):
        return "review"
    if any(float(rule.get("confidence") or 0.0) < 0.6 for rule in rules):
        return "review"
    return "pass"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add vlm/scripts/supervise/run_paired_front_view_review.py tests/test_paired_front_view_review.py
git commit -m "feat: add rule alignment, aggregate counts, and overall decision"
```

---

### Task 6: Qwen VL call and message building

**Files:**
- Modify: `vlm/scripts/supervise/run_paired_front_view_review.py`
- Test: `tests/test_paired_front_view_review.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `media_type(path: Path) -> str`, `encode_image_data_url(path: Path) -> str`, `build_messages(prompt_text: str, image_path: Path) -> list[dict]`, `extract_json_object(text: str) -> dict`, `call_qwen_review(*, api_key: str, base_url: str, model: str, image_path: Path, prompt_text: str, timeout: int) -> str`. Task 7's `process_one()` takes `call_qwen_review` as the default value of its injectable `call_fn` parameter.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_paired_front_view_review.py`:

```python
from vlm.scripts.supervise.run_paired_front_view_review import build_messages, extract_json_object


def test_build_messages_has_exactly_one_text_and_one_image_block(tmp_path: Path):
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"fake-png-bytes")

    messages = build_messages("the prompt text", image_path)

    assert len(messages) == 1
    content = messages[0]["content"]
    assert content[0] == {"type": "text", "text": "the prompt text"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert len(content) == 2


def test_extract_json_object_handles_markdown_fence():
    text = '```json\n{"rules": [], "extra_elements": []}\n```'

    result = extract_json_object(text)

    assert result == {"rules": [], "extra_elements": []}


def test_extract_json_object_handles_bare_json():
    assert extract_json_object('{"rules": []}') == {"rules": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: FAIL with "cannot import name 'build_messages'"

- [ ] **Step 3: Write minimal implementation**

Add to `vlm/scripts/supervise/run_paired_front_view_review.py` (add `import base64` and `import requests` to imports):

```python
def media_type(path: Path) -> str:
    """Return the MIME type for a supported image file extension.

    Args:
        path: Image file path; only the suffix is inspected.

    Returns:
        MIME type string, e.g. "image/png".
    """
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def encode_image_data_url(path: Path) -> str:
    """Read an image file and return it as a base64 data-URI string.

    Args:
        path: Path to the image file to encode.

    Returns:
        A "data:<mime>;base64,<bytes>" string suitable for an image_url content block.
    """
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type(path)};base64,{data}"


def build_messages(prompt_text: str, image_path: Path) -> list[dict[str, Any]]:
    """Build the single-image OpenAI-style chat message sent to Qwen VL.

    Args:
        prompt_text: The fully rendered reviewer prompt (see build_review_prompt()).
        image_path: Path to the generated front-view image. This must be the generated
            image, never the original 2D source image, per the review's data boundary.

    Returns:
        A one-element messages list: a single user turn with one text block and one
        image_url block.
    """
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": encode_image_data_url(image_path)}},
            ],
        }
    ]


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object out of a raw model response string.

    Args:
        text: Raw text from the model; may be bare JSON or wrapped in a markdown fence.

    Returns:
        The parsed dict.

    Raises:
        json.JSONDecodeError: If no valid JSON object can be found.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        if stripped.startswith("```json"):
            stripped = stripped[7:]
        else:
            stripped = stripped[3:]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
        stripped = stripped.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def call_qwen_review(
    *,
    api_key: str,
    base_url: str,
    model: str,
    image_path: Path,
    prompt_text: str,
    timeout: int,
) -> str:
    """Send the review request to Qwen VL and return the raw response text.

    Args:
        api_key: DashScope API key (from QWEN_API_KEY).
        base_url: DashScope OpenAI-compatible base URL.
        model: Vision model name, e.g. "qwen-vl-max".
        image_path: Path to the generated front-view image to send.
        prompt_text: The fully rendered reviewer prompt.
        timeout: HTTP timeout in seconds.

    Returns:
        The model's raw reply text (choices[0].message.content).

    Raises:
        requests.HTTPError: For any non-2xx HTTP status.
        RuntimeError: If the response is missing the expected content path.
    """
    payload = {
        "model": model,
        "messages": build_messages(prompt_text, image_path),
        "temperature": 0.0,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload, ensure_ascii=False),
        timeout=timeout,
    )
    response.raise_for_status()
    result = response.json()
    try:
        return str(result["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Qwen response missing choices[0].message.content: {result}") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add vlm/scripts/supervise/run_paired_front_view_review.py tests/test_paired_front_view_review.py
git commit -m "feat: add Qwen VL single-image review call"
```

---

### Task 7: process_one — wiring dry-run and real-call paths

**Files:**
- Modify: `vlm/scripts/supervise/run_paired_front_view_review.py`
- Test: `tests/test_paired_front_view_review.py`

**Interfaces:**
- Consumes: `ReviewSample` (Task 2), `build_review_prompt` (Task 3), `request_preview` (Task 4), `validate_and_align_rules`/`compute_aggregate_counts`/`compute_overall_decision` (Task 5), `extract_json_object`/`call_qwen_review` (Task 6).
- Produces: `write_review_csv(path: Path, rules: list[dict]) -> None` and `process_one(sample, gold_elements, prompt_file, prompt_template, output_root, *, dry_run, api_key="", base_url="", model="", timeout=180, call_fn=call_qwen_review) -> dict`. Task 8's `main()` calls `process_one` once per selected sample and collects its returned status dicts.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_paired_front_view_review.py`:

```python
from vlm.scripts.supervise.run_paired_front_view_review import process_one


def test_process_one_dry_run_writes_preview_and_never_calls_network(tmp_path: Path):
    sample_dir = _write_complete_sample(tmp_path / "input", "sample-1")
    (sample_dir / "sample-1.json").write_text(
        json.dumps([{"element": "红色眼睛", "description": "鲜艳的红色"}], ensure_ascii=False), encoding="utf-8"
    )
    sample = ReviewSample(
        sample_id="sample-1",
        generated_image_path=sample_dir / "sample-1_q_front_view.png",
        gold_path=sample_dir / "sample-1.json",
        original_image_path=sample_dir / "sample-1_original.png",
    )
    gold_elements = load_gold_elements(sample.gold_path)

    def _fail_if_called(**_kwargs):
        raise AssertionError("call_fn must not be invoked during a dry run")

    status = process_one(
        sample,
        gold_elements,
        tmp_path / "prompt.txt",
        "COUNT={{GOLD_COUNT}}\n{{GOLD_ELEMENTS}}",
        tmp_path / "output",
        dry_run=True,
        call_fn=_fail_if_called,
    )

    assert status["status"] == "dry_run"
    output_dir = tmp_path / "output" / "sample-1"
    preview = json.loads((output_dir / "request_preview.json").read_text(encoding="utf-8"))
    assert preview["request"]["image_path"] == str(sample.generated_image_path)
    assert str(sample.original_image_path) not in json.dumps(preview, ensure_ascii=False)
    assert (output_dir / "review_prompt.txt").read_text(encoding="utf-8").startswith("COUNT=1")
    assert not (output_dir / "prediction.json").exists()


def test_process_one_real_call_writes_aligned_prediction(tmp_path: Path):
    sample_dir = _write_complete_sample(tmp_path / "input", "sample-1")
    (sample_dir / "sample-1.json").write_text(
        json.dumps([{"element": "红色眼睛", "description": "鲜艳的红色"}], ensure_ascii=False), encoding="utf-8"
    )
    sample = ReviewSample(
        sample_id="sample-1",
        generated_image_path=sample_dir / "sample-1_q_front_view.png",
        gold_path=sample_dir / "sample-1.json",
        original_image_path=sample_dir / "sample-1_original.png",
    )
    gold_elements = load_gold_elements(sample.gold_path)
    canned_response = json.dumps(
        {
            "rules": [
                {
                    "rule_index": 1,
                    "result": "pass",
                    "confidence": 0.95,
                    "image_grounded": True,
                    "description_correct": True,
                    "issue_types": [],
                    "observed_description": "可见红色眼睛",
                    "evidence_bbox": [10, 20, 30, 40],
                    "reason": "颜色一致",
                }
            ],
            "extra_elements": [],
        },
        ensure_ascii=False,
    )

    status = process_one(
        sample,
        gold_elements,
        tmp_path / "prompt.txt",
        "COUNT={{GOLD_COUNT}}\n{{GOLD_ELEMENTS}}",
        tmp_path / "output",
        dry_run=False,
        api_key="unused",
        base_url="unused",
        model="qwen-vl-max",
        call_fn=lambda **_kwargs: canned_response,
    )

    assert status["status"] == "succeeded"
    assert status["overall_decision"] == "pass"
    assert status["aggregate_counts"]["pass"] == 1
    output_dir = tmp_path / "output" / "sample-1"
    prediction = json.loads((output_dir / "prediction.json").read_text(encoding="utf-8"))
    assert prediction["inputs"]["source_image_used"] is False
    assert prediction["rules"][0]["rule_index"] == 1
    assert prediction["rules"][0]["element"] == "红色眼睛"
    assert (output_dir / "qc.csv").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: FAIL with "cannot import name 'process_one'"

- [ ] **Step 3: Write minimal implementation**

Add to `vlm/scripts/supervise/run_paired_front_view_review.py` (add `import csv` and `import time` to imports):

```python
def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_review_csv(path: Path, rules: list[dict[str, Any]]) -> None:
    """Write aligned rules to a flat CSV for spreadsheet review.

    Args:
        path: Output CSV path.
        rules: Aligned rules as returned by validate_and_align_rules().
    """
    if not rules:
        return
    columns = ["rule_index", "element", "result", "image_grounded", "description_correct", "issue_types", "confidence", "reason"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for rule in rules:
            row = {column: rule.get(column, "") for column in columns}
            row["issue_types"] = json.dumps(rule.get("issue_types", []), ensure_ascii=False)
            writer.writerow(row)


def process_one(
    sample: ReviewSample,
    gold_elements: list[dict[str, Any]],
    prompt_file: Path,
    prompt_template: str,
    output_root: Path,
    *,
    dry_run: bool,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    timeout: int = 180,
    call_fn: Any = call_qwen_review,
) -> dict[str, Any]:
    """Review one sample: render the prompt, optionally call Qwen, write outputs.

    Args:
        sample: The sample to review (generated image + gold JSON path; original
            image path is carried for provenance only and is never sent to Qwen).
        gold_elements: Gold element list for this sample, from load_gold_elements().
        prompt_file: Path to the frozen prompt template file (for provenance).
        prompt_template: The frozen template text (with placeholders, pre-render).
        output_root: Root directory for review outputs (e.g. vlm/tmp/paired_front_view_review_v1).
        dry_run: If True, write the request preview and prompt snapshot only — no
            network call, no prediction.json.
        api_key: DashScope API key, required when dry_run is False.
        base_url: DashScope base URL, required when dry_run is False.
        model: Qwen vision model name, required when dry_run is False.
        timeout: HTTP timeout in seconds for the Qwen call.
        call_fn: Injectable network function matching call_qwen_review's signature;
            tests substitute a stub here so no test hits the real API.

    Returns:
        A status dict. When dry_run is True: {"status": "dry_run", "sample_id": ...}.
        When dry_run is False: includes "status": "succeeded", "overall_decision",
        "aggregate_counts", and "qc_issue_count".
    """
    sample_dir = output_root / sample.sample_id
    prompt_text = build_review_prompt(prompt_template, gold_elements)
    preview = request_preview(sample, prompt_file, prompt_text, len(gold_elements), sample_dir)
    sample_dir.mkdir(parents=True, exist_ok=True)
    _write_json(sample_dir / "request_preview.json", preview)
    (sample_dir / "review_prompt.txt").write_text(prompt_text, encoding="utf-8")

    if dry_run:
        status = {"schema_version": "paired_front_view_review_status.v1", "sample_id": sample.sample_id, "status": "dry_run"}
        _write_json(sample_dir / "status.json", status)
        return status

    started = time.time()
    raw_text = call_fn(
        api_key=api_key,
        base_url=base_url,
        model=model,
        image_path=sample.generated_image_path,
        prompt_text=prompt_text,
        timeout=timeout,
    )
    parsed = extract_json_object(raw_text)
    aligned_rules, qc_issues = validate_and_align_rules(parsed.get("rules"), gold_elements)
    aggregate_counts = compute_aggregate_counts(aligned_rules)
    overall_decision = compute_overall_decision(aligned_rules, qc_issues)
    raw_extra = parsed.get("extra_elements")
    extra_elements = raw_extra if isinstance(raw_extra, list) else []

    prediction = {
        "schema_version": "paired_front_view_review.v1",
        "sample_id": sample.sample_id,
        "inputs": {
            "generated_image": str(sample.generated_image_path),
            "gold_json": str(sample.gold_path),
            "source_image_used": False,
        },
        "rules": aligned_rules,
        "extra_elements": extra_elements,
        "aggregate_counts": aggregate_counts,
        "overall_decision": overall_decision,
        "qc_issues": qc_issues,
        "metadata": {
            "model": model,
            "review_prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
            "elapsed_seconds": round(time.time() - started, 2),
        },
    }
    _write_json(sample_dir / "prediction.json", prediction)
    write_review_csv(sample_dir / "qc.csv", aligned_rules)

    status = {
        "schema_version": "paired_front_view_review_status.v1",
        "sample_id": sample.sample_id,
        "status": "succeeded",
        "overall_decision": overall_decision,
        "aggregate_counts": aggregate_counts,
        "qc_issue_count": len(qc_issues),
    }
    _write_json(sample_dir / "status.json", status)
    return status
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add vlm/scripts/supervise/run_paired_front_view_review.py tests/test_paired_front_view_review.py
git commit -m "feat: wire dry-run and real-call review paths in process_one"
```

---

### Task 8: CLI, pilot-scale guard, batch summary

**Files:**
- Modify: `vlm/scripts/supervise/run_paired_front_view_review.py`
- Test: `tests/test_paired_front_view_review.py`

**Interfaces:**
- Consumes: everything from Tasks 2-7.
- Produces: `MAX_PILOT_SAMPLES = 20`, `enforce_pilot_scale_guard(requested_ids: list[str], limit: int, max_pilot_samples: int = MAX_PILOT_SAMPLES) -> None`, `select_review_samples(samples: list[ReviewSample], requested_ids: list[str], limit: int) -> list[ReviewSample]`, `build_batch_summary(statuses: list[dict]) -> dict`, `parse_args() -> argparse.Namespace`, `main() -> None`. This is the final task — `main()` is the script's entry point.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_paired_front_view_review.py`:

```python
import pytest

from vlm.scripts.supervise.run_paired_front_view_review import (
    build_batch_summary,
    enforce_pilot_scale_guard,
    select_review_samples,
)


def test_enforce_pilot_scale_guard_blocks_large_limit_without_explicit_ids():
    with pytest.raises(SystemExit):
        enforce_pilot_scale_guard(requested_ids=[], limit=6901)


def test_enforce_pilot_scale_guard_allows_default_pilot_limit():
    enforce_pilot_scale_guard(requested_ids=[], limit=20)


def test_enforce_pilot_scale_guard_allows_large_limit_with_explicit_ids():
    enforce_pilot_scale_guard(requested_ids=["sample-1", "sample-2"], limit=6901)


def test_select_review_samples_filters_by_explicit_ids_or_limit():
    samples = [
        ReviewSample(sample_id, Path(f"{sample_id}.png"), Path(f"{sample_id}.json"), Path(f"{sample_id}_o.png"))
        for sample_id in ("a", "b", "c")
    ]

    assert [sample.sample_id for sample in select_review_samples(samples, [], 2)] == ["a", "b"]
    assert [sample.sample_id for sample in select_review_samples(samples, ["c", "a"], 0)] == ["c", "a"]

    with pytest.raises(ValueError, match="Unknown sample_id"):
        select_review_samples(samples, ["missing"], 0)


def test_build_batch_summary_aggregates_verdicts_and_queues():
    statuses = [
        {"sample_id": "a", "status": "succeeded", "overall_decision": "pass", "aggregate_counts": {"pass": 1, "partial": 0, "fail": 0, "not_evaluable": 0, "review": 0}},
        {"sample_id": "b", "status": "succeeded", "overall_decision": "fail", "aggregate_counts": {"pass": 0, "partial": 0, "fail": 1, "not_evaluable": 0, "review": 0}},
        {"sample_id": "c", "status": "failed", "error": "boom"},
    ]

    summary = build_batch_summary(statuses)

    assert summary["sample_count"] == 3
    assert summary["overall_decision_distribution"]["pass"] == 1
    assert summary["overall_decision_distribution"]["fail"] == 1
    assert summary["fail_or_review_sample_ids"] == ["b"]
    assert summary["parse_failures"] == ["c"]
    assert summary["verdict_distribution"]["pass"] == 1
    assert summary["verdict_distribution"]["fail"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: FAIL with "cannot import name 'enforce_pilot_scale_guard'"

- [ ] **Step 3: Write minimal implementation**

Add to `vlm/scripts/supervise/run_paired_front_view_review.py` (add `import argparse`, `import os`, and `from vlm.scripts._paths import SUPERVISION_PROMPTS_DIR, VLM_ROOT, load_api_env` and `from vlm.scripts.generate.generate_paired_front_view import DEFAULT_OUTPUT_ROOT as PILOT_GENERATION_ROOT` to imports):

```python
MAX_PILOT_SAMPLES = 20
DEFAULT_INPUT_ROOT = PILOT_GENERATION_ROOT
DEFAULT_OUTPUT_ROOT = VLM_ROOT / "tmp" / "paired_front_view_review_v1"
DEFAULT_PROMPT_FILE = SUPERVISION_PROMPTS_DIR / "paired_front_view_review_v1_cn.txt"
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen-vl-max"


def enforce_pilot_scale_guard(requested_ids: list[str], limit: int, max_pilot_samples: int = MAX_PILOT_SAMPLES) -> None:
    """Refuse to scale beyond the pilot unless sample_ids were passed explicitly.

    Args:
        requested_ids: Explicit --sample-id values from the CLI (empty if none given).
        limit: The --limit value from the CLI.
        max_pilot_samples: The pilot's known size; limits above this require explicit ids.

    Raises:
        SystemExit: If limit exceeds max_pilot_samples and no explicit ids were given.
    """
    if not requested_ids and limit > max_pilot_samples:
        raise SystemExit(
            f"--limit must be <= {max_pilot_samples} for this pilot baseline. "
            "Pass --sample-id explicitly to review specific samples beyond the pilot."
        )


def select_review_samples(samples: list[ReviewSample], requested_ids: list[str], limit: int) -> list[ReviewSample]:
    """Select explicit sample_ids, or the first `limit` discovered samples.

    Args:
        samples: All discovered samples, in discovery order (sorted by sample_id).
        requested_ids: Explicit sample_id values to select, in the given order.
        limit: Maximum number of samples to select when requested_ids is empty.
            0 or negative means no limit.

    Returns:
        The selected ReviewSample list.

    Raises:
        ValueError: If any requested_id is not among the discovered samples.
    """
    by_id = {sample.sample_id: sample for sample in samples}
    if requested_ids:
        missing = [sample_id for sample_id in requested_ids if sample_id not in by_id]
        if missing:
            raise ValueError(f"Unknown sample_id(s): {', '.join(missing)}")
        return [by_id[sample_id] for sample_id in dict.fromkeys(requested_ids)]
    return samples[:limit] if limit > 0 else samples


def build_batch_summary(statuses: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a batch of process_one() status dicts into verdict distributions and queues.

    Args:
        statuses: One status dict per attempted sample, as returned by process_one()
            for succeeded/dry_run samples, or a {"status": "failed", "sample_id": ...}
            dict for samples that raised an exception during processing.

    Returns:
        Dict with sample_count, overall_decision_distribution (sample-level), the
        per-rule verdict_distribution (summed aggregate_counts across samples),
        fail_or_review_sample_ids, and parse_failures (samples that raised).
    """
    overall_distribution = {"pass": 0, "fail": 0, "review": 0}
    verdict_distribution = {result: 0 for result in ALLOWED_RESULTS}
    fail_or_review_ids: list[str] = []
    parse_failures: list[str] = []

    for status in statuses:
        if status.get("status") == "failed":
            parse_failures.append(status["sample_id"])
            continue
        if status.get("status") != "succeeded":
            continue
        overall = status.get("overall_decision", "review")
        overall_distribution[overall] = overall_distribution.get(overall, 0) + 1
        if overall in ("fail", "review"):
            fail_or_review_ids.append(status["sample_id"])
        for result, count in status.get("aggregate_counts", {}).items():
            verdict_distribution[result] = verdict_distribution.get(result, 0) + count

    return {
        "schema_version": "paired_front_view_review_batch.v1",
        "sample_count": len(statuses),
        "overall_decision_distribution": overall_distribution,
        "verdict_distribution": verdict_distribution,
        "fail_or_review_sample_ids": fail_or_review_ids,
        "parse_failures": parse_failures,
    }


def parse_args() -> argparse.Namespace:
    """Define and parse CLI arguments for the paired front-view reviewer."""
    parser = argparse.ArgumentParser(description="Review paired front-view generations against gold JSON with Qwen VL.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT_FILE)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=MAX_PILOT_SAMPLES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--qwen-api-key", default="")
    parser.add_argument("--timeout", type=int, default=180)
    return parser.parse_args()


def main() -> None:
    """Discover pilot samples, review each, and write per-sample outputs plus a batch summary."""
    args = parse_args()
    enforce_pilot_scale_guard(args.sample_id, args.limit)

    all_samples = discover_samples(args.input_root)
    samples = select_review_samples(all_samples, args.sample_id, args.limit)
    if not samples:
        raise SystemExit("No samples selected")

    prompt_template = args.prompt_file.read_text(encoding="utf-8-sig").strip()
    if not prompt_template:
        raise SystemExit(f"Prompt template is empty: {args.prompt_file}")

    api_key = ""
    base_url = args.base_url
    model = args.model
    if not args.dry_run:
        load_api_env()
        api_key = args.qwen_api_key.strip() or os.environ.get("QWEN_API_KEY", "").strip()
        if not api_key:
            raise SystemExit("QWEN_API_KEY is required. Set it in vlm/config/api.env or pass --qwen-api-key.")
        base_url = base_url.strip() or os.environ.get("QWEN_BASE_URL", "").strip() or DEFAULT_QWEN_BASE_URL
        model = model.strip() or os.environ.get("QWEN_VISION_MODEL", "").strip() or DEFAULT_QWEN_MODEL

    args.output_root.mkdir(parents=True, exist_ok=True)
    statuses: list[dict[str, Any]] = []
    for sample in samples:
        gold_elements = load_gold_elements(sample.gold_path)
        try:
            status = process_one(
                sample,
                gold_elements,
                args.prompt_file,
                prompt_template,
                args.output_root,
                dry_run=args.dry_run,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout=args.timeout,
            )
        except Exception as exc:
            status = {"schema_version": "paired_front_view_review_status.v1", "sample_id": sample.sample_id, "status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
        statuses.append(status)
        print(json.dumps(status, ensure_ascii=False), flush=True)

    summary = build_batch_summary(statuses)
    _write_json(args.output_root / "batch_summary.json", summary)
    print(json.dumps({"status": "finished", "selected": len(samples), "dry_run": args.dry_run, "output_root": str(args.output_root)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: PASS (all tests, ~20)

- [ ] **Step 5: Run the full test file once more to confirm no regressions**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paired_front_view_review.py -v`
Expected: All tests PASS, 0 failures

- [ ] **Step 6: Commit**

```bash
git add vlm/scripts/supervise/run_paired_front_view_review.py tests/test_paired_front_view_review.py
git commit -m "feat: add CLI, pilot-scale guard, and batch summary for paired front-view review"
```

---

### Task 9 (operational): Dry-run validation against all 20 real pilot samples

**Files:** none (this task runs the finished script against real data on disk; no code changes).

**Interfaces:**
- Consumes: the finished `run_paired_front_view_review.py` from Task 8.

- [ ] **Step 1: Run dry-run on all 20 real pilot samples**

Run: `.\.venv\Scripts\python.exe -m vlm.scripts.supervise.run_paired_front_view_review --dry-run --limit 20`
Expected: JSON status line per sample with `"status": "dry_run"`, then a final `{"status": "finished", "selected": 20, "dry_run": true, ...}` line. No errors.

- [ ] **Step 2: Inspect 2-3 request previews for leaks**

Run: `.\.venv\Scripts\python.exe -c "import json,glob; [print(p, '1-1020644465' in open(p, encoding='utf-8').read()) for p in glob.glob(r'vlm/tmp/paired_front_view_review_v1/*/request_preview.json')[:3]]"`

Manually open 2-3 of the printed `request_preview.json` files and confirm:
- `request.image_path` ends in `_q_front_view.png`, never `_original.<ext>`.
- No `_original` substring appears anywhere in the file.
- `gold_element_count` matches the sample's actual gold JSON element count.

- [ ] **Step 3: Report result**

Report to the user: how many of the 20 samples produced a clean dry-run preview, and confirmation that no original-image path leaked into any preview file.

---

### Task 10 (operational): Small-batch real Qwen review (3-5 samples) for user feedback

**Files:** none (runs the finished script for real against a small sample subset).

**Interfaces:**
- Consumes: the finished `run_paired_front_view_review.py` from Task 8. Requires `QWEN_API_KEY` in `vlm/config/api.env`.

- [ ] **Step 1: Pick 3-5 sample IDs from batch_summary.json**

Run: `.\.venv\Scripts\python.exe -c "import json; d=json.load(open(r'vlm/data/front_view_generation_v1/batch_summary.json', encoding='utf-8')); print(d['selected'][:5])"`

Use the first 5 printed sample IDs for the small batch.

- [ ] **Step 2: Run the real reviewer on those samples**

Run (substitute the actual 5 sample IDs from Step 1):

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.run_paired_front_view_review `
  --sample-id <id1> --sample-id <id2> --sample-id <id3> --sample-id <id4> --sample-id <id5>
```

Expected: 5 JSON status lines with `"status": "succeeded"`, each with an `overall_decision` and `aggregate_counts`, then a `{"status": "finished", ...}` line. No exceptions.

- [ ] **Step 3: Inspect the predictions**

Read `vlm/tmp/paired_front_view_review_v1/<sample_id>/prediction.json` for each of the 5 samples and check:
- `rules` array length matches the sample's gold element count.
- `rule_index` values are `1..N` in order.
- `inputs.source_image_used` is `false`.
- `evidence_bbox` values (where present) look like plausible pixel coordinates within 1915x821.

- [ ] **Step 4: Report to the user for feedback**

Summarize the 5 samples' verdicts (pass/partial/fail/not_evaluable/review counts, any QC issues) and present 1-2 full `prediction.json` contents so the user can judge output quality before scaling to the full 20-sample pilot. Wait for user feedback before proceeding to Task 11.

---

### Task 11 (operational, gated on user approval from Task 10): Full 20-sample pilot run

**Files:** none.

**Interfaces:**
- Consumes: the finished `run_paired_front_view_review.py` from Task 8, and user approval from Task 10.

- [ ] **Step 1: Run the real reviewer on all 20 pilot samples**

Run: `.\.venv\Scripts\python.exe -m vlm.scripts.supervise.run_paired_front_view_review --limit 20`
Expected: 20 JSON status lines, each `"status": "succeeded"` (or `"failed"` with a recorded error), then a `{"status": "finished", "selected": 20, ...}` line.

- [ ] **Step 2: Inspect the batch summary**

Read `vlm/tmp/paired_front_view_review_v1/batch_summary.json` and report to the user:
- `overall_decision_distribution` (pass/fail/review counts across the 20 samples).
- `verdict_distribution` (per-rule pass/partial/fail/not_evaluable/review counts).
- `fail_or_review_sample_ids` — the human review queue.
- `parse_failures` — any samples where the model response could not be aligned.

- [ ] **Step 3: Update the project handoff doc**

Append a new checkpoint entry to `handoff/LATEST.md` (following the existing `CKPT-N` format already in that file) summarizing: Phase B reviewer baseline shipped, 20/20 pilot reviewed, verdict distribution, and the next action (Phase C human gold annotation on the fail/review queue).

---

## Self-Review Notes

- **Spec coverage:** All five design-doc sections (script location, prompt freeze location, structured-output enforcement, dry-run leak checks, batch summary) map to Tasks 1 (prompt), 2-7 (script), 4+9 (leak checks), 8+11 (batch summary). The rollout order (dry-run → small batch → full pilot) from design §9 maps to Tasks 9, 10, 11.
- **Placeholder scan:** No TBD/TODO markers; every step has literal file content or literal commands.
- **Type consistency:** `ReviewSample` fields (`sample_id`, `generated_image_path`, `gold_path`, `original_image_path`) are used identically across Tasks 2, 4, 7. `process_one`'s signature (positional `sample, gold_elements, prompt_file, prompt_template, output_root`, keyword-only `dry_run, api_key, base_url, model, timeout, call_fn`) is defined once in Task 7 and called identically in Task 8's `main()`. `ALLOWED_RESULTS` is defined once in Task 5 and reused by `compute_aggregate_counts` (Task 5) and `build_batch_summary` (Task 8).
- **Scope check:** This plan covers one subsystem (the Phase B reviewer baseline) and stops at the 20-sample pilot, matching the design's explicit non-goal of full-corpus review.
