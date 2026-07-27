"""Run source-2D character element extraction with Qwen VL.

This is a lightweight research runner for Stage 1 of the supervision-agent
pipeline. It reads the small SN_6 pilot dataset, sends only the 2D source image
to the model, and writes one normalized extracted-elements JSON per sample.

CATEGORY_LABELS mapping
-----------------------
CATEGORY_LABELS maps VLM response keys to (canonical_category, Chinese label) tuples.
The mapping is used exclusively by elements_from_identity_features() as a last-resort
fallback when the model returns an "identity_features" dict instead of the expected
flat "elements" list. The keys are the field names the model may produce under
identity_features (e.g. "hair", "outfit", "props"). The tuple values are:
  - canonical_category: the standard category string used in VALID_CATEGORIES
    (e.g. "clothing" for outfit, "prop" for props)
  - Chinese label: the human-readable element name used as the fallback element
    name when the model does not provide a "type" field

normalize_elements fallback cascade
-------------------------------------
normalize_elements() tries to find a raw element list in the parsed JSON using
the following key order:

  1. parsed["elements"]         -- expected schema (flat list of element dicts)
  2. parsed["extracted_elements"] -- older schema variant (same shape as elements)
  3. parsed["atomic_rules"]    -- rule-shaped output sometimes produced by the model
                                   when it follows an atomic_rules.json prompt style
  4. elements_from_identity_features(parsed["identity_features"])
                                -- structured identity features dict (the model
                                   organizes output by feature category rather than
                                   flat list); converted to element dicts via
                                   CATEGORY_LABELS and stringify_feature()

If none of these paths produces a list, raw_elements defaults to [] and an empty
normalized output is written (allowing the run to complete without crashing).

--workers and DashScope QPS relationship
------------------------------------------
DashScope's Qwen VL API enforces a per-model queries-per-second (QPS) limit.
The --workers flag controls how many concurrent HTTP requests the script makes.
Setting --workers too high will cause HTTP 429 (rate limit) errors. Setting it
too low will serialize processing unnecessarily.

Recommended guidance:
  - Default --workers 6 is calibrated for the DashScope free-tier limit of ~6 QPS
    for qwen3.7-plus. For paid tiers with higher limits, increase --workers.
  - In dry-run mode (--dry-run), --workers is forced to 1 to avoid spamming
    disk I/O and because there are no API calls to parallelize.
  - Each worker sends one request at a time (synchronous HTTP via requests.post).
    The effective throughput is: min(--workers, DashScope_QPS_limit).
  - If you see HTTP 429 errors, reduce --workers. If all requests succeed and
    you want higher throughput, increase --workers within your tier's QPS limit.

Examples:
    python -m vlm.scripts.supervise.run_element_extraction --sample-id char_001 --dry-run
    python -m vlm.scripts.supervise.run_element_extraction --limit 3
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))


DEFAULT_DATA_ROOT = Path("vlm/data/SN_6期动漫数据标注")
DEFAULT_OUTPUT_ROOT = Path("vlm/data/element_extraction_results")
DEFAULT_PROMPT_TEMPLATE = Path("vlm/prompts/supervision/element_extraction_from_2d.txt")
DEFAULT_ENV_FILE = Path("vlm/config/api.env")
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.7-plus"

VALID_CATEGORIES = {
    "hair",
    "face",
    "skin_body",
    "clothing",
    "footwear",
    "accessory",
    "headwear",
    "prop",
    "other",
}
VALID_CONFIDENCE = {"high", "medium", "low"}

CATEGORY_LABELS = {
    "hair": ("hair", "发型与发色"),
    "eyes": ("face", "眼睛与表情"),
    "head_accessories": ("headwear", "头部配饰"),
    "outfit": ("clothing", "服装结构"),
    "patterns": ("accessory", "图案与色块"),
    "props": ("prop", "道具"),
    "special_body_parts": ("skin_body", "特殊身体特征"),
}


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the element extraction runner.

    Returns:
        Parsed namespace with fields:
          data_root       -- root directory of the SN_6 pilot dataset
          output_root     -- root directory for extraction result JSONs
          sample_id       -- if non-empty, run only this one sample
          limit           -- if > 0, run only the first N samples
          prompt_template -- path to the element_extraction_from_2d.txt template
          env_file        -- path to vlm/config/api.env for API credentials
          qwen_api_key    -- overrides QWEN_API_KEY from env_file if non-empty
          qwen_base_url   -- overrides QWEN_BASE_URL (default: DashScope endpoint)
          model           -- Qwen model name (default: qwen3.7-plus)
          temperature     -- sampling temperature (default 0.0 for determinism)
          max_tokens      -- max response tokens (default 4000)
          timeout         -- HTTP request timeout in seconds (default 300)
          dry_run         -- if True, write prompt/request preview without API calls
          workers         -- number of concurrent Qwen API calls (default 6)
    """
    parser = argparse.ArgumentParser(description="Run source-2D character element extraction.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--sample-id", default="", help="Run one sample, e.g. char_001.")
    parser.add_argument("--limit", type=int, default=0, help="Run the first N samples after filtering.")
    parser.add_argument("--prompt-template", type=Path, default=DEFAULT_PROMPT_TEMPLATE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--qwen-api-key", default="")
    parser.add_argument("--qwen-base-url", default=DEFAULT_QWEN_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=4000)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true", help="Write prompt/request preview without calling Qwen.")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent Qwen API calls (default 6).")
    return parser.parse_args()


def load_env_file(path: Path) -> None:
    """Load key=value pairs from an env file into os.environ (non-overwriting).

    Skips blank lines and lines starting with "#". Strips surrounding quotes
    from values so that QWEN_API_KEY="sk-xxx" and QWEN_API_KEY=sk-xxx both work.
    Uses os.environ.setdefault so existing environment variables are not overwritten
    (allowing CLI overrides to take precedence over the env file).

    Args:
        path: Path to the env file (e.g. vlm/config/api.env). No-op if missing.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def require_value(cli_value: str, env_name: str, default: str = "") -> str:
    """Resolve a configuration value from CLI flag, environment, or default.

    Priority order: CLI flag > environment variable > default.

    Args:
        cli_value: Value provided via CLI flag (may be empty string if not set).
        env_name: Environment variable name to check if cli_value is empty.
        default: Fallback value if neither CLI flag nor env var is set.

    Returns:
        The first non-empty value from the priority chain.

    Raises:
        SystemExit: If all three sources are empty (configuration is required).
    """
    value = cli_value.strip() or os.environ.get(env_name, "").strip() or default
    if not value:
        raise SystemExit(f"{env_name} is required. Set it in {DEFAULT_ENV_FILE} or pass the CLI flag.")
    return value


def media_type(path: Path) -> str:
    """Return the MIME type string for a supported image file extension.

    Args:
        path: Path to an image file.

    Returns:
        MIME type string (e.g. "image/jpeg", "image/png", "image/webp").

    Raises:
        SystemExit: If the file extension is not in the supported set.
    """
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    raise SystemExit(f"Unsupported image suffix for {path}. Use jpg, jpeg, png, webp, or gif.")


def encode_image_data_url(path: Path) -> str:
    """Read an image file and encode it as a base64 data URL for the Qwen VL API.

    The resulting string has the format:
        data:{media_type};base64,{base64_encoded_bytes}

    This is the format expected by the OpenAI-compatible chat completions API
    for image inputs (used by DashScope's Qwen VL endpoint).

    Args:
        path: Absolute path to the image file.

    Returns:
        Base64 data URL string.

    Raises:
        SystemExit: If the image file does not exist or has an unsupported extension.
    """
    if not path.exists():
        raise SystemExit(f"Image not found: {path}")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type(path)};base64,{data}"


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object from a raw model response string.

    Handles two common model output patterns:
      1. Bare JSON: the entire response is a JSON string.
      2. Markdown code block: the JSON is wrapped in ```json ... ``` or ``` ... ```.

    Falls back to searching for the outermost { ... } substring if standard
    parsing fails (handles models that prefix JSON with explanation text).

    Args:
        text: Raw text response from the Qwen VL model.

    Returns:
        Parsed dict from the response.

    Raises:
        json.JSONDecodeError: If no valid JSON object is found.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def write_json(path: Path, payload: Any) -> None:
    """Write payload as pretty-printed UTF-8 JSON (no ASCII escaping).

    Creates parent directories if they don't exist.

    Args:
        path: Destination file path.
        payload: Any JSON-serialisable value.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def discover_samples(data_root: Path, sample_id: str = "", limit: int = 0) -> list[dict[str, Any]]:
    """Discover and validate sample directories in the SN_6 pilot dataset.

    Each sample directory must contain a {sample_dir.name}.json file (the sample
    config) with a "source_image" field pointing to an image file in the same
    directory. sample_id in the config must match the directory name.

    Args:
        data_root: Root directory containing one subdirectory per sample.
        sample_id: If non-empty, only the matching sample directory is returned.
        limit: If > 0, only the first N samples (after optional sample_id filter)
               are returned.

    Returns:
        List of sample dicts with keys:
          sample_id   -- directory name (str)
          json_path   -- path to the sample config JSON
          source_image -- image filename (str, relative to sample_dir)
          image_path  -- absolute path to the source image (Path)

    Raises:
        SystemExit: If data_root doesn't exist, sample_id not found, sample config
                    JSON is missing, sample_id mismatches, or source_image is missing.
    """
    if not data_root.exists():
        raise SystemExit(f"Data root not found: {data_root}")

    sample_dirs = sorted(path for path in data_root.iterdir() if path.is_dir())
    if sample_id:
        sample_dirs = [path for path in sample_dirs if path.name == sample_id]
        if not sample_dirs:
            raise SystemExit(f"Sample not found under {data_root}: {sample_id}")
    if limit > 0:
        sample_dirs = sample_dirs[:limit]

    samples = []
    for sample_dir in sample_dirs:
        json_path = sample_dir / f"{sample_dir.name}.json"
        if not json_path.exists():
            raise SystemExit(f"Missing sample JSON: {json_path}")
        sample = json.loads(json_path.read_text(encoding="utf-8-sig"))
        image_name = str(sample.get("source_image", "")).strip()
        image_path = sample_dir / image_name
        if sample.get("sample_id") != sample_dir.name:
            raise SystemExit(f"sample_id mismatch in {json_path}: {sample.get('sample_id')} != {sample_dir.name}")
        if not image_name or not image_path.exists():
            raise SystemExit(f"Missing source_image for {sample_dir.name}: {image_path}")
        samples.append({
            "sample_id": sample_dir.name,
            "json_path": json_path,
            "source_image": image_name,
            "image_path": image_path,
        })
    return samples


def build_prompt(template_path: Path, *, sample_id: str, source_image: str) -> str:
    """Fill the prompt template with sample-specific values.

    Replaces {{SAMPLE_ID}} and {{SOURCE_IMAGE}} placeholders in the template
    file with the provided values. The template is read with UTF-8 encoding
    (no BOM) since it is a text file managed in the repo.

    Args:
        template_path: Path to the element_extraction_from_2d.txt template.
        sample_id: Sample identifier to substitute for {{SAMPLE_ID}}.
        source_image: Source image filename to substitute for {{SOURCE_IMAGE}}.

    Returns:
        Filled prompt string.
    """
    template = template_path.read_text(encoding="utf-8")
    return template.replace("{{SAMPLE_ID}}", sample_id).replace("{{SOURCE_IMAGE}}", source_image)


def build_messages(prompt: str, image_path: Path) -> list[dict[str, Any]]:
    """Build the OpenAI-compatible messages list for a Qwen VL chat request.

    The messages list contains:
      1. A system message instructing the model to output only valid JSON
         and follow the user-provided schema strictly.
      2. A user message with two content parts:
           - text: the filled prompt string
           - image_url: base64 data URL of the source image

    Args:
        prompt: Filled prompt string from build_prompt().
        image_path: Absolute path to the source image file.

    Returns:
        List of message dicts compatible with the OpenAI chat completions API.
    """
    return [
        {"role": "system", "content": "你只能输出合法 JSON，并严格遵守用户给定的 schema。"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": encode_image_data_url(image_path)}},
            ],
        },
    ]


def qwen_vl_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> str:
    """Send a chat request to the Qwen VL API and return the response text.

    Uses the OpenAI-compatible chat completions endpoint. Sets
    response_format={"type": "json_object"} to request structured JSON output
    (supported by qwen3.7-plus and later Qwen VL models).

    Args:
        api_key: DashScope API key (QWEN_API_KEY).
        base_url: Base URL for the API (default: DashScope compatible-mode endpoint).
        model: Qwen model name (e.g. "qwen3.7-plus").
        messages: Messages list from build_messages().
        temperature: Sampling temperature (0.0 for deterministic output).
        max_tokens: Maximum number of tokens in the response.
        timeout: HTTP request timeout in seconds.

    Returns:
        Raw response text string from choices[0].message.content.

    Raises:
        requests.HTTPError: If the API returns a non-2xx status code.
        RuntimeError: If the response is missing choices[0].message.content.
    """
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
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


def normalize_category(value: Any) -> str:
    """Normalise a raw category value to a canonical VALID_CATEGORIES member.

    Converts the input to lowercase, replaces hyphens and spaces with underscores,
    and checks against VALID_CATEGORIES. Returns "other" if the result is not
    a recognised category.

    Args:
        value: Raw category value from the model response (may be None).

    Returns:
        Lowercase canonical category string (always a member of VALID_CATEGORIES).
    """
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in VALID_CATEGORIES else "other"


def normalize_confidence(value: Any) -> str:
    """Normalise a raw confidence value to "high", "medium", or "low".

    Accepts the string members of VALID_CONFIDENCE directly. Also recognises
    common near-equivalent strings:
      - "very high", "0.9", "0.95", "1.0" -> "high"
    Defaults to "medium" for any other unrecognised value.

    Args:
        value: Raw confidence value from the model response (may be None).

    Returns:
        Canonical confidence string ("high", "medium", or "low").
    """
    text = str(value or "").strip().lower().replace("_", " ")
    if text in VALID_CONFIDENCE:
        return text
    if text in {"very high", "0.9", "0.95", "1.0"}:
        return "high"
    return "medium"


def normalize_elements(parsed: dict[str, Any], *, sample: dict[str, Any], model: str, elapsed_seconds: float) -> dict[str, Any]:
    """Normalise the parsed VLM response into the element_extraction.v1 schema.

    Fallback cascade (see module docstring for full explanation):
      1. parsed["elements"]               -- expected schema
      2. parsed["extracted_elements"]     -- older schema variant
      3. parsed["atomic_rules"]           -- rule-shaped output
      4. elements_from_identity_features(parsed["identity_features"])
      5. []                               -- empty list if none found

    For each raw element:
      - Generates a deterministic element_id: {sample_id}_e{index:03d}
      - Extracts name (fallback: first 20 chars of value) and value (fallback: name)
      - Normalises category via normalize_category()
      - Extracts and normalises attribute sub-dict (color, material, shape, location)
      - Normalises confidence via normalize_confidence()
      - Skips elements where both name and value are empty

    Args:
        parsed: Dict parsed from the model's JSON response.
        sample: Sample dict from discover_samples() (needs sample_id and image_path).
        model: Model name string (written to metadata).
        elapsed_seconds: Wall-clock time for the API call (written to metadata).

    Returns:
        Normalised output dict with schema_version="element_extraction.v1".
    """
    raw_elements = parsed.get("elements")
    if not isinstance(raw_elements, list):
        raw_elements = parsed.get("extracted_elements")
    if not isinstance(raw_elements, list):
        raw_elements = parsed.get("atomic_rules")
    if not isinstance(raw_elements, list):
        raw_elements = elements_from_identity_features(parsed.get("identity_features", {}))
    if not isinstance(raw_elements, list):
        raw_elements = []

    normalized = []
    for index, raw in enumerate(raw_elements, start=1):
        if not isinstance(raw, dict):
            continue
        attributes = raw.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {}
        name = str(raw.get("name", "")).strip()
        value = str(raw.get("value", raw.get("description", ""))).strip()
        if not name and not value:
            continue
        normalized.append({
            "element_id": f"{sample['sample_id']}_e{index:03d}",
            "name": name or value[:20],
            "value": value or name,
            "category": normalize_category(raw.get("category")),
            "attributes": {
                "color": str(attributes.get("color", "")).strip(),
                "material": str(attributes.get("material", "")).strip(),
                "shape": str(attributes.get("shape", "")).strip(),
                "location": str(attributes.get("location", "")).strip(),
            },
            "confidence": normalize_confidence(raw.get("confidence")),
        })

    return {
        "schema_version": "element_extraction.v1",
        "task": "source_2d_character_element_extraction",
        "sample_id": sample["sample_id"],
        "source_image": str(sample["image_path"]),
        "elements": normalized,
        "summary": {
            "element_count": len(normalized),
        },
        "metadata": {
            "model": model,
            "created_at": datetime.now().astimezone().isoformat(),
            "elapsed_seconds": round(elapsed_seconds, 2),
            "extraction_method": "observe_then_extract_main_elements",
        },
    }


def stringify_feature(value: Any) -> str:
    """Recursively convert a nested feature value to a human-readable string.

    Handles four value types:
      - str: return stripped string
      - dict: format as "key: value; key: value" (skip None/""/[]/{}
              values)
      - list: join non-empty items with "；" (Chinese fullwidth semicolon)
      - None: return ""
      - other: return str(value).strip()

    Used by elements_from_identity_features() to flatten nested feature dicts
    (e.g. {"color": "blue", "length": "long"}) into a single descriptive string.

    Args:
        value: Any value from the identity_features dict.

    Returns:
        Human-readable string representation.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            parts.append(f"{key}: {stringify_feature(item)}")
        return "；".join(part for part in parts if part)
    if isinstance(value, list):
        return "；".join(stringify_feature(item) for item in value if item not in (None, "", [], {}))
    if value is None:
        return ""
    return str(value).strip()


def elements_from_identity_features(identity_features: Any) -> list[dict[str, Any]]:
    """Convert an identity_features dict into a flat list of element dicts.

    This is the last fallback in normalize_elements(). Some older Qwen VL model
    responses organise output as {"identity_features": {"hair": [...], "outfit": [...], ...}}
    rather than the expected flat "elements" list.

    CATEGORY_LABELS maps each identity_features key to:
      - canonical_category: used as element["category"]
      - Chinese label: used as element["name"] when the model doesn't provide a "type"

    For list-valued features (e.g. hair=[{...}, {...}]):
      - Each list item is converted independently.
      - The "type" field of each item (if present) is used as element["name"].

    For scalar-valued features (e.g. a string or nested dict):
      - A single element dict is created with label as name.

    Args:
        identity_features: The value of parsed["identity_features"]. Must be a
                           dict; returns [] for any other type.

    Returns:
        List of partially-normalised element dicts (attributes are empty strings;
        confidence is "medium"). Full normalisation happens in normalize_elements().
    """
    if not isinstance(identity_features, dict):
        return []
    elements = []
    for key, (category, label) in CATEGORY_LABELS.items():
        value = identity_features.get(key)
        if isinstance(value, list):
            for item in value:
                text = stringify_feature(item)
                if not text:
                    continue
                item_type = item.get("type", "") if isinstance(item, dict) else ""
                elements.append({
                    "name": str(item_type or label).strip(),
                    "value": text,
                    "category": category,
                    "attributes": {
                        "color": "",
                        "material": "",
                        "shape": "",
                        "location": "",
                    },
                    "confidence": "medium",
                })
        else:
            text = stringify_feature(value)
            if not text:
                continue
            elements.append({
                "name": label,
                "value": text,
                "category": category,
                "attributes": {
                    "color": "",
                    "material": "",
                    "shape": "",
                    "location": "",
                },
                "confidence": "medium",
            })
    return elements


def write_request_preview(
    path: Path,
    *,
    model: str,
    base_url: str,
    image_path: Path,
    prompt: str,
    dry_run: bool,
) -> None:
    """Write a sanitised request preview JSON (no API key, no image bytes).

    This file is written for every sample (including live runs) so that the
    exact request parameters can be inspected and reproduced without access to
    the raw API key or image data.

    Args:
        path: Destination path for the request_redacted.json file.
        model: Qwen model name.
        base_url: API base URL.
        image_path: Absolute path to the source image (logged as path, not bytes).
        prompt: Filled prompt string (only character count is logged).
        dry_run: Whether this is a dry-run (logged in the output).
    """
    write_json(path, {
        "model": model,
        "base_url": base_url,
        "image_path": str(image_path),
        "prompt_chars": len(prompt),
        "response_format": {"type": "json_object"},
        "dry_run": dry_run,
        "note": "API key and image bytes are intentionally omitted.",
    })


def run_sample(
    *,
    sample: dict[str, Any],
    prompt_template: Path,
    output_root: Path,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    dry_run: bool,
) -> dict[str, Any]:
    """Run the full extraction pipeline for a single sample.

    For each sample the following files are written to output_root/{sample_id}/:
      element_extraction_prompt.txt -- the filled prompt (always written)
      request_redacted.json         -- sanitised request parameters (always written)
      raw_response.txt              -- raw model text response (skipped in dry_run)
      extracted_elements.json       -- normalised element_extraction.v1 output (skipped in dry_run)

    In dry-run mode, returns a "dry_run" status dict immediately after writing
    the prompt and request preview.

    Args:
        sample: Sample dict from discover_samples().
        prompt_template: Path to the prompt template file.
        output_root: Root directory for output files.
        api_key: DashScope API key.
        base_url: API base URL.
        model: Qwen model name.
        temperature: Sampling temperature.
        max_tokens: Maximum response tokens.
        timeout: HTTP timeout in seconds.
        dry_run: If True, skip the actual API call.

    Returns:
        Result dict with keys:
          status        -- "ok", "dry_run", or "error"
          sample_id     -- sample ID string
          result_path   -- path to extracted_elements.json (if status=="ok")
          element_count -- number of normalised elements (if status=="ok")
    """
    sample_dir = output_root / sample["sample_id"]
    sample_dir.mkdir(parents=True, exist_ok=True)
    prompt = build_prompt(prompt_template, sample_id=sample["sample_id"], source_image=sample["source_image"])

    prompt_path = sample_dir / "element_extraction_prompt.txt"
    request_path = sample_dir / "request_redacted.json"
    raw_path = sample_dir / "raw_response.txt"
    result_path = sample_dir / "extracted_elements.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    write_request_preview(
        request_path,
        model=model,
        base_url=base_url,
        image_path=sample["image_path"],
        prompt=prompt,
        dry_run=dry_run,
    )

    if dry_run:
        return {
            "status": "dry_run",
            "sample_id": sample["sample_id"],
            "prompt_path": str(prompt_path),
            "request_path": str(request_path),
        }

    messages = build_messages(prompt, sample["image_path"])
    started = time.time()
    raw_text = qwen_vl_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    elapsed_seconds = time.time() - started
    raw_path.write_text(raw_text, encoding="utf-8")
    parsed = extract_json_object(raw_text)
    normalized = normalize_elements(parsed, sample=sample, model=model, elapsed_seconds=elapsed_seconds)
    write_json(result_path, normalized)
    return {
        "status": "ok",
        "sample_id": sample["sample_id"],
        "result_path": str(result_path),
        "element_count": normalized["summary"]["element_count"],
    }


def main() -> None:
    """Entry point: load env, discover samples, run extraction with thread pool, print summary.

    Uses a ThreadPoolExecutor with --workers threads (1 in dry-run mode).
    Failed samples write error.json to their output directory and are counted
    in the failure_count summary. Exits with code 1 if any sample failed.

    Output layout for each sample at output_root/{sample_id}/:
      element_extraction_prompt.txt  -- filled prompt
      request_redacted.json          -- sanitised request parameters
      raw_response.txt               -- raw model response (real run only)
      extracted_elements.json        -- normalised extraction output (real run only)
      error.json                     -- error details if the sample failed
    """
    args = parse_args()
    load_env_file(args.env_file)
    if not args.prompt_template.exists():
        raise SystemExit(f"Prompt template not found: {args.prompt_template}")

    samples = discover_samples(args.data_root, sample_id=args.sample_id, limit=args.limit)
    api_key = "" if args.dry_run else require_value(args.qwen_api_key, "QWEN_API_KEY")
    base_url = require_value(args.qwen_base_url, "QWEN_BASE_URL", DEFAULT_QWEN_BASE_URL)
    model = require_value(args.model, "QWEN_VISION_MODEL", DEFAULT_MODEL)

    results = []
    failures = 0

    def _run(sample: dict[str, Any]) -> dict[str, Any]:
        try:
            return run_sample(
                sample=sample,
                prompt_template=args.prompt_template,
                output_root=args.output_root,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
                dry_run=args.dry_run,
            )
        except Exception as exc:  # noqa: BLE001
            result = {"status": "error", "sample_id": sample.get("sample_id", ""), "error": str(exc)}
            write_json(args.output_root / sample.get("sample_id", "unknown") / "error.json", result)
            return result

    workers = 1 if args.dry_run else args.workers
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_sample = {pool.submit(_run, s): s for s in samples}
        for future in as_completed(future_to_sample):
            result = future.result()
            if result.get("status") == "error":
                failures += 1
                print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
            else:
                print(json.dumps(result, ensure_ascii=False))
            results.append(result)

    summary = {
        "status": "ok" if failures == 0 else "error",
        "sample_count": len(samples),
        "failure_count": failures,
        "output_root": str(args.output_root),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
