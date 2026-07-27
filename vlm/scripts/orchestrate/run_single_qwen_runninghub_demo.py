"""Run one sample through Qwen rule extraction and RunningHub generation.

Full pipeline overview
----------------------
1. Qwen VL (vision-language model) — given a source character-design image,
   the vision model (qwen-vl-plus or equivalent) analyses visible features and
   returns a free-form JSON description of the character.

2. JSON schema validation / normalisation — a second call to a Qwen text model
   applies a structured schema prompt so the raw visual features are mapped to
   a canonical, validated JSON object.

3. atomic_rules generation — a third Qwen text call converts the normalised
   schema into a flat list of fine-grained "atomic rules" (e.g. hair colour,
   accessory details) that can be injected verbatim into a generation prompt.

4. RunningHub image generation — the source image and a formatted prompt
   (optionally augmented by atomic rules) are submitted to a RunningHub
   workflow endpoint, which produces figurine-style reference renders.

Each intermediate artifact is saved to an output directory under the sample ID
so that the pipeline can be audited or replayed step-by-step.

Usage example (PowerShell)::

    .venv\\Scripts\\python.exe -m vlm.scripts.orchestrate.run_single_qwen_runninghub_demo `
        --sample-id char_001 `
        --source-dir vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/image `
        --output-dir vlm/tmp/qwen_runninghub_single_demo
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Package-path bootstrap
# When the script is executed directly (not as part of a package) the project
# root is not on sys.path.  We detect this by checking __package__ and, if
# needed, insert the project root (three levels above this file) so that
# ``from vlm.scripts...`` imports work correctly.
# ---------------------------------------------------------------------------
if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts.generate.generate_head_keychain_with_runninghub_g2 import (  # noqa: E402
    DEFAULT_ENDPOINT,
    IMAGE_SUFFIXES,
    download_results,
    image_metadata,
    submit_task,
    upload_image,
    wait_for_results,
)


DEFAULT_DATASET = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20")
DEFAULT_SOURCE_DIR = DEFAULT_DATASET / "image"
DEFAULT_OUTPUT_DIR = Path("vlm/tmp/qwen_runninghub_single_demo")
DEFAULT_REFERENCE_PROMPT_DIR = Path("vlm/archive/ip_review_project/prompts")
DEFAULT_ENV_FILE = Path("vlm/archive/ip_review_project/.env")
DEFAULT_RUNNINGHUB_PROMPT = Path("vlm/prompts/generation/runninghub/runninghub_g2_dataset_figurine_user_cn.txt")
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the single-sample demo pipeline.

    All arguments have sensible defaults so the script can be invoked with
    nothing more than ``--sample-id``.  API keys are intentionally left empty
    by default; they are resolved later through environment variables loaded
    from the env file (see ``load_env_file`` and ``require_key``).

    Returns
    -------
    argparse.Namespace
        Populated namespace with all pipeline configuration values.
    """
    parser = argparse.ArgumentParser(description="Run one source image through Qwen rules and RunningHub generation.")
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--qwen-api-key", default="", help="Qwen/DashScope API key. Prefer passing via PowerShell variable.")
    parser.add_argument("--qwen-base-url", default=DEFAULT_QWEN_BASE_URL)
    parser.add_argument("--qwen-vision-model", default="qwen-vl-plus")
    parser.add_argument("--qwen-text-model", default="qwen-plus")
    parser.add_argument("--prompt-dir", type=Path, default=DEFAULT_REFERENCE_PROMPT_DIR)
    parser.add_argument("--runninghub-prompt-file", type=Path, default=DEFAULT_RUNNINGHUB_PROMPT)
    parser.add_argument("--runninghub-endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--output-suffix", default="figurine")
    parser.add_argument("--aspect-ratio", default="21:9")
    parser.add_argument("--resolution", default="1k", choices=("1k", "2k", "4k"))
    parser.add_argument("--poll-interval", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--skip-runninghub", action="store_true")
    return parser.parse_args()


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs from a plain-text env file into ``os.environ``.

    The file is read with UTF-8-BOM encoding (``utf-8-sig``) so that files
    saved from Windows tools with a BOM are handled transparently.

    Parsing rules:
    - Blank lines and lines starting with ``#`` are silently skipped.
    - Lines without ``=`` are silently skipped.
    - Only the *first* ``=`` acts as the delimiter; values may contain ``=``.
    - Surrounding whitespace and one layer of surrounding quotes (``"`` or
      ``'``) are stripped from both key and value.
    - ``os.environ.setdefault`` is used, so existing environment variables
      (e.g. set by the calling shell or CI system) are **not** overwritten.
      This means the shell environment always wins over the file.

    Parameters
    ----------
    path:
        Path to the ``.env`` file.  If the file does not exist the function
        returns silently without raising an error.
    """
    if not path.exists():
        return  # Non-existent env file is not an error; skip gracefully.
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        # Skip blank lines, comment lines, and lines missing the '=' separator.
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        # Split on the first '=' only so values containing '=' are preserved.
        key, value = stripped.split("=", 1)
        key = key.strip()
        # Strip surrounding whitespace and optional quote characters from value.
        value = value.strip().strip("\"'")
        if key:
            # setdefault: existing env vars (from the shell) take priority.
            os.environ.setdefault(key, value)


def apply_env_defaults(args: argparse.Namespace) -> None:
    """Override argparse defaults with environment variables when appropriate.

    This function is called **after** ``load_env_file`` so that values from
    the env file (which have been loaded into ``os.environ``) can override
    the argparse defaults.

    Override priority (highest to lowest):
    1. Explicit command-line argument (non-default value)
    2. Environment variable from shell or env file
    3. Argparse default

    The function only attempts an override when the argparse value still
    matches its default (meaning the user did not pass an explicit CLI arg).
    For example, if ``args.qwen_base_url`` is the literal default constant
    ``DEFAULT_QWEN_BASE_URL``, the function checks for ``QWEN_BASE_URL`` in
    the environment; otherwise it leaves ``args.qwen_base_url`` untouched.

    Parameters
    ----------
    args:
        The argparse Namespace to mutate in-place.
    """
    # Only override if the user did not pass an explicit --qwen-base-url.
    if args.qwen_base_url == DEFAULT_QWEN_BASE_URL:
        args.qwen_base_url = os.environ.get("QWEN_BASE_URL", args.qwen_base_url).strip() or args.qwen_base_url
    # Only override if the user did not pass an explicit --qwen-vision-model.
    if args.qwen_vision_model == "qwen-vl-plus":
        args.qwen_vision_model = os.environ.get("QWEN_VISION_MODEL", args.qwen_vision_model).strip() or args.qwen_vision_model
    # Only override if the user did not pass an explicit --qwen-text-model.
    # Fallback chain: QWEN_TEXT_MODEL → QWEN_MODEL → argparse default.
    if args.qwen_text_model == "qwen-plus":
        args.qwen_text_model = (
            os.environ.get("QWEN_TEXT_MODEL") or os.environ.get("QWEN_MODEL") or args.qwen_text_model
        ).strip() or args.qwen_text_model


def require_key(value: str, env_name: str) -> str:
    """Resolve an API key from a supplied value or the environment, raising SystemExit if neither is present.

    This helper is used for keys that are mandatory but should not be hardcoded
    in argparse defaults (for security reasons).  The resolution order is:
    1. The ``value`` parameter (e.g. from a CLI flag like ``--qwen-api-key``).
    2. The environment variable named ``env_name`` (e.g. ``QWEN_API_KEY``).

    Parameters
    ----------
    value:
        The possibly-empty value provided by the user (e.g. from argparse).
    env_name:
        Name of the environment variable to check (e.g. "QWEN_API_KEY").

    Returns
    -------
    str
        The resolved API key, guaranteed to be non-empty.

    Raises
    ------
    SystemExit:
        If neither ``value`` nor the environment variable is non-empty.
    """
    key = value.strip() or os.environ.get(env_name, "").strip()
    if not key:
        raise SystemExit(f"{env_name} is required. Pass --{env_name.lower().replace('_', '-')} or set the environment variable.")
    return key


def find_sample_image(source_dir: Path, sample_id: str) -> Path:
    """Locate the source image file for a given sample ID.

    Two lookup strategies are attempted in order:

    1. Exact match — checks for ``<source_dir>/<sample_id><suffix>`` for each
       suffix in ``IMAGE_SUFFIXES``.  Returns the first file found.
    2. Prefix match — lists all image files whose name starts with
       ``<sample_id>_`` (i.e. the sample ID followed by an underscore).  The
       results are sorted alphabetically and the first match is returned.
       This handles naming conventions like ``char_001_front.png``.

    Parameters
    ----------
    source_dir:
        Directory that contains the source character-design images.
    sample_id:
        The identifier string for the desired sample (e.g. ``"char_001"``).

    Returns
    -------
    Path
        Resolved path to the image file.

    Raises
    ------
    FileNotFoundError:
        If neither strategy locates a matching file.
    """
    # Strategy 1: try exact filenames like char_001.png, char_001.jpg, etc.
    for suffix in IMAGE_SUFFIXES:
        exact = source_dir / f"{sample_id}{suffix}"
        if exact.exists():
            return exact
    # Strategy 2: prefix match for names like char_001_front.png.
    matches = sorted(
        path
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.name.startswith(f"{sample_id}_")
    )
    if not matches:
        raise FileNotFoundError(f"No source image found for sample {sample_id} under {source_dir}")
    return matches[0]


def media_type(path: Path) -> str:
    """Return the MIME type string for an image file based on its suffix.

    Used to build the ``data:`` URI prefix when base64-encoding an image for
    the Qwen VL API.  Unrecognised suffixes default to ``image/jpeg`` as a
    safe fallback, since JPEG is the most commonly accepted format.

    Parameters
    ----------
    path:
        Path whose suffix determines the MIME type.

    Returns
    -------
    str
        A MIME type string such as ``"image/png"`` or ``"image/jpeg"``.
    """
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    # Default fallback: most APIs accept JPEG even if the file is not JPEG.
    return "image/jpeg"


def encode_image_data_url(path: Path) -> str:
    """Read an image file and return it as a base64-encoded data URI.

    The Qwen VL API accepts images as data URIs in the
    ``image_url.url`` field.  This avoids the need for a separate image
    hosting step and keeps the pipeline self-contained.

    Parameters
    ----------
    path:
        Path to the image file to encode.

    Returns
    -------
    str
        A data URI of the form ``data:<mime_type>;base64,<base64_data>``.
    """
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type(path)};base64,{data}"


def qwen_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    timeout: int = 180,
) -> str:
    """Send a chat-completions request to a Qwen-compatible API endpoint.

    The function uses the OpenAI-compatible ``/chat/completions`` endpoint
    exposed by DashScope (or any proxy that mirrors the same interface).
    The request body is serialised with ``ensure_ascii=False`` to preserve
    Chinese and other non-ASCII characters in prompts.

    Error handling:
    - ``response.raise_for_status()`` converts 4xx/5xx HTTP errors into
      ``requests.HTTPError`` exceptions.
    - A missing or unexpected response structure is converted into a
      ``RuntimeError`` with the full raw payload attached for debugging.

    Parameters
    ----------
    api_key:
        Bearer token for the Qwen / DashScope API.
    base_url:
        Base URL of the API endpoint (trailing slash is stripped).
    model:
        Model identifier, e.g. ``"qwen-vl-plus"`` or ``"qwen-plus"``.
    messages:
        OpenAI-format message list.  Vision messages may include
        ``image_url`` content items with base64 data URIs.
    timeout:
        HTTP request timeout in seconds (default 180).

    Returns
    -------
    str
        The ``content`` string from ``choices[0].message``.

    Raises
    ------
    requests.HTTPError:
        For non-2xx HTTP responses.
    RuntimeError:
        If ``choices[0].message.content`` is absent in the response payload.
    """
    # Append the standard chat-completions path to the provided base URL.
    url = base_url.rstrip("/") + "/chat/completions"
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        # Serialize with ensure_ascii=False to keep Chinese prompts intact.
        data=json.dumps({"model": model, "messages": messages}, ensure_ascii=False),
        timeout=timeout,
    )
    response.raise_for_status()  # Raise for 4xx/5xx errors.
    payload = response.json()
    try:
        # Standard OpenAI-compatible response path.
        return str(payload["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Qwen response did not include choices[0].message.content: {payload}") from exc


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a string that may contain surrounding text.

    LLMs frequently wrap JSON output in markdown code fences or add
    explanatory prose before/after the JSON.  This function applies a
    three-stage fallback chain to handle the most common cases:

    Stage 1 — Markdown fence stripping:
        If the text starts with ````` `` ` `````, the opening fence line
        (e.g. ` ```json ` or plain ` ``` `) and closing fence are removed,
        leaving only the raw JSON text.

    Stage 2 — Direct parse:
        ``json.loads`` is attempted on the stripped text.  If the model
        returned clean JSON this is the only step that runs.

    Stage 3 — Bracket search (brute-force heuristic):
        If the direct parse fails, the function looks for the first ``{``
        and the last ``}`` in the text and attempts to parse only the
        substring between them (inclusive).  This handles cases where the
        model prepended or appended plain-text explanations.

        If no valid ``{...}`` span is found, the original ``json.JSONDecodeError``
        from Stage 2 is re-raised, preserving the original error message.

    Parameters
    ----------
    text:
        Raw string output from a Qwen model call.

    Returns
    -------
    dict[str, Any]
        Parsed JSON object.

    Raises
    ------
    json.JSONDecodeError:
        If all three stages fail to produce valid JSON.
    """
    stripped = text.strip()
    # Stage 1: strip markdown code fence if present.
    if stripped.startswith("```"):
        # Remove the opening fence line (handles both ```json and plain ```).
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        # Remove the closing fence.
        stripped = stripped.removesuffix("```").strip()
    # Stage 2: attempt a direct JSON parse on the (possibly fence-stripped) text.
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # Stage 3: brute-force bracket extraction.
        # Find the outermost { ... } span and try parsing only that slice.
        start = stripped.find("{")   # Index of the first opening brace.
        end = stripped.rfind("}")    # Index of the last closing brace.
        if start == -1 or end <= start:
            # No plausible JSON object found; re-raise the original parse error.
            raise
        return json.loads(stripped[start : end + 1])


def write_json(path: Path, payload: Any) -> None:
    """Serialise ``payload`` as indented JSON and write it to ``path``.

    Parent directories are created automatically (``mkdir -p`` semantics) so
    the caller does not need to ensure the output directory exists.

    The file is written with UTF-8 encoding and ``ensure_ascii=False`` so that
    Chinese characters in rules and prompts are stored as readable text rather
    than ``\\uXXXX`` escape sequences.

    Parameters
    ----------
    path:
        Destination file path.  Will be created or overwritten.
    payload:
        Any JSON-serialisable Python object (dict, list, str, etc.).
    """
    path.parent.mkdir(parents=True, exist_ok=True)  # Create missing parent dirs.
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_qwen_rule_pipeline(args: argparse.Namespace, api_key: str, image_path: Path, sample_dir: Path) -> Path:
    """Execute the three-stage Qwen rule-extraction pipeline for one sample.

    Stage 1 — Visual feature extraction (vision model):
        The source image is sent to the Qwen VL model together with
        ``vision_prompt.txt``.  The model returns a free-form JSON description
        of visible character features (hair, eyes, outfit, accessories, etc.).
        Raw response is saved to ``qwen_visual_features_raw.txt``; the parsed
        object is saved to ``qwen_visual_features.json``.

    Stage 2 — Schema normalisation (text model):
        The visual JSON is sent to the Qwen text model together with
        ``schema_prompt.txt``.  The model remaps the free-form features to a
        canonical schema.  Raw response → ``qwen_schema_raw.txt``;
        parsed → ``qwen_schema.json``.

    Stage 3 — Atomic rule generation (text model):
        The normalised schema is injected into ``extract_atomic_rules_prompt.txt``
        (via the ``{{INSERT_JSON_HERE}}`` placeholder) and sent to the text model.
        The response must contain an ``"atomic_rules"`` key; if absent a
        ``RuntimeError`` is raised.  Raw response → ``qwen_atomic_rules_raw.txt``;
        final output → ``<sample_id>_atomic_rules.json``.

    Parameters
    ----------
    args:
        Parsed argparse Namespace (provides model names, API URLs, prompt dir,
        sample ID, etc.).
    api_key:
        Resolved Qwen / DashScope API key.
    image_path:
        Path to the source character-design image.
    sample_dir:
        Output directory for this sample.  All intermediate artifacts are
        written here.

    Returns
    -------
    Path
        Path to the generated ``<sample_id>_atomic_rules.json`` file.

    Raises
    ------
    RuntimeError:
        If the atomic-rules response from Qwen does not contain the
        ``"atomic_rules"`` key.
    """
    # Load the three prompt templates from disk.
    vision_prompt = (args.prompt_dir / "vision_prompt.txt").read_text(encoding="utf-8")
    schema_prompt = (args.prompt_dir / "schema_prompt.txt").read_text(encoding="utf-8")
    atomic_prompt_template = (args.prompt_dir / "extract_atomic_rules_prompt.txt").read_text(encoding="utf-8")

    # --- Stage 1: Visual feature extraction ---
    # Send the image as a base64 data URI alongside the vision system prompt.
    visual_text = qwen_chat(
        api_key=api_key,
        base_url=args.qwen_base_url,
        model=args.qwen_vision_model,
        messages=[
            {"role": "system", "content": vision_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze this character design sheet and return only valid JSON."},
                    {"type": "image_url", "image_url": {"url": encode_image_data_url(image_path)}},
                ],
            },
        ],
    )
    # Persist raw text before parsing in case extraction fails.
    (sample_dir / "qwen_visual_features_raw.txt").write_text(visual_text, encoding="utf-8")
    visual_json = extract_json_object(visual_text)
    write_json(sample_dir / "qwen_visual_features.json", visual_json)

    # --- Stage 2: Schema normalisation ---
    # Append the serialised visual JSON to the schema prompt as context.
    schema_text = qwen_chat(
        api_key=api_key,
        base_url=args.qwen_base_url,
        model=args.qwen_text_model,
        messages=[{"role": "user", "content": schema_prompt + "\n" + json.dumps(visual_json, ensure_ascii=False, indent=2)}],
    )
    (sample_dir / "qwen_schema_raw.txt").write_text(schema_text, encoding="utf-8")
    schema_json = extract_json_object(schema_text)
    write_json(sample_dir / "qwen_schema.json", schema_json)

    # --- Stage 3: Atomic rule generation ---
    # The schema may wrap its output under a "normalized_rules" key; fall back
    # to the entire schema object if that key is absent.
    normalized_rules = schema_json.get("normalized_rules") or schema_json
    # Inject the normalised rules into the prompt template.
    atomic_prompt = atomic_prompt_template.replace(
        "{{INSERT_JSON_HERE}}",
        json.dumps(normalized_rules, ensure_ascii=False, indent=2),
    )
    atomic_text = qwen_chat(
        api_key=api_key,
        base_url=args.qwen_base_url,
        model=args.qwen_text_model,
        messages=[{"role": "user", "content": atomic_prompt}],
    )
    (sample_dir / "qwen_atomic_rules_raw.txt").write_text(atomic_text, encoding="utf-8")
    atomic_json = extract_json_object(atomic_text)
    # Validate that the model returned the required key.
    if "atomic_rules" not in atomic_json:
        raise RuntimeError(f"Qwen atomic response did not include atomic_rules: {atomic_json}")

    # Write the final atomic rules file with the sample code for traceability.
    atomic_path = sample_dir / f"{args.sample_id}_atomic_rules.json"
    write_json(atomic_path, {"code": args.sample_id, "atomic_rules": atomic_json["atomic_rules"]})
    return atomic_path


def run_runninghub(args: argparse.Namespace, image_path: Path, atomic_path: Path, sample_dir: Path) -> dict[str, Any]:
    """Submit the source image to RunningHub and wait for the generated figurine renders.

    Steps performed:
    1. Load the RunningHub prompt text from the configured prompt file.
    2. Copy the source image and atomic-rules JSON into ``sample_dir`` for
       traceability (the copies use the sample ID as a prefix).
    3. Upload the source image to RunningHub storage and obtain a CDN URL.
    4. Submit a generation task with the CDN URL, prompt, aspect ratio and
       resolution settings.
    5. Poll ``wait_for_results`` until the task finishes or the timeout
       (``args.timeout`` seconds) is reached.
    6. Download all result images to ``sample_dir``.
    7. Write per-step JSON audit logs (upload payload, submit response, final
       response, and a consolidated status object).

    The RunningHub API key is read exclusively from the environment variable
    ``RUNNINGHUB_API_KEY`` (not from a CLI flag) to avoid accidental exposure
    in shell history.

    Parameters
    ----------
    args:
        Parsed argparse Namespace with RunningHub settings (endpoint, prompt
        file, aspect ratio, resolution, poll interval, timeout, sample ID,
        output suffix).
    image_path:
        Path to the source character-design image.
    atomic_path:
        Path to the ``<sample_id>_atomic_rules.json`` file produced by the
        Qwen pipeline (copied into ``sample_dir`` if not already there).
    sample_dir:
        Output directory for this sample.

    Returns
    -------
    dict[str, Any]
        Status dictionary with keys: ``status``, ``sample_id``, ``task_id``,
        ``elapsed_seconds``, ``downloaded_images``, and ``image_metadata``.
        ``status`` is ``"succeeded"`` if at least one image was downloaded,
        or ``"no_image_url_found"`` otherwise.

    Raises
    ------
    SystemExit:
        If the RunningHub prompt file is empty or ``RUNNINGHUB_API_KEY`` is
        not set.
    """
    # Require RUNNINGHUB_API_KEY from the environment (not from a CLI flag).
    runninghub_key = require_key("", "RUNNINGHUB_API_KEY")
    prompt = args.runninghub_prompt_file.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise SystemExit(f"RunningHub prompt is empty: {args.runninghub_prompt_file}")

    # --- Archive inputs alongside outputs for traceability ---
    # Copy the original image into sample_dir with a standardised name.
    original_suffix = image_path.suffix.lower() if image_path.suffix.lower() in IMAGE_SUFFIXES else ".jpg"
    shutil.copy2(image_path, sample_dir / f"{args.sample_id}_original{original_suffix}")
    # Copy the atomic-rules JSON if it is not already in sample_dir.
    atomic_output_path = sample_dir / f"{args.sample_id}_atomic_rules.json"
    if atomic_path.resolve() != atomic_output_path.resolve():
        shutil.copy2(atomic_path, atomic_output_path)
    # Save the prompt text used for this run so outputs are fully reproducible.
    (sample_dir / f"{args.sample_id}_runninghub_prompt.txt").write_text(prompt, encoding="utf-8")

    # --- RunningHub API calls ---
    started = time.time()  # Wall-clock start for elapsed-time reporting.
    # Step 1: Upload the source image to RunningHub; get back a CDN download URL.
    upload_payload = upload_image(runninghub_key, image_path)
    image_urls = [str(upload_payload["download_url"])]
    # Step 2: Submit the generation task with the uploaded image and prompt.
    submit_response = submit_task(
        runninghub_key,
        args.runninghub_endpoint,
        image_urls,
        prompt,
        args.aspect_ratio,
        args.resolution,
    )
    task_id = str(submit_response["taskId"])
    # Step 3: Poll until the task reaches a terminal state or the timeout fires.
    final_response = wait_for_results(runninghub_key, task_id, args.poll_interval, args.timeout)
    # Step 4: Download all result images into sample_dir.
    downloaded = download_results(final_response.get("results") or [], sample_dir, args.sample_id, args.output_suffix)

    # Omit the CDN download_url from the persisted upload log (it is large and
    # already used; keeping it would just bloat the audit file).
    safe_upload = {key: value for key, value in upload_payload.items() if key != "download_url"}
    status = {
        "status": "succeeded" if downloaded else "no_image_url_found",
        "sample_id": args.sample_id,
        "task_id": task_id,
        "elapsed_seconds": round(time.time() - started, 2),
        "downloaded_images": [str(path) for path in downloaded],
        "image_metadata": [image_metadata(path) for path in downloaded],
    }
    # Persist per-step audit logs for debugging and reproducibility.
    write_json(sample_dir / f"{args.sample_id}_runninghub_upload.json", safe_upload)
    write_json(sample_dir / f"{args.sample_id}_runninghub_submit_response.json", submit_response)
    write_json(sample_dir / f"{args.sample_id}_runninghub_final_response.json", final_response)
    write_json(sample_dir / f"{args.sample_id}_status.json", status)
    return status


def main() -> None:
    """Entry point: orchestrate the full Qwen → RunningHub pipeline for one sample.

    Execution order:
    1. Parse CLI arguments with ``parse_args()``.
    2. Load the env file (``--env-file``) into ``os.environ`` so downstream
       calls to ``require_key`` can find API keys.
    3. Apply env-variable overrides to any argparse defaults that were not
       explicitly set on the command line (``apply_env_defaults``).
    4. Resolve the Qwen API key (CLI flag or ``QWEN_API_KEY`` env var).
    5. Locate the source image file for the requested sample ID.
    6. Create the per-sample output directory.
    7. Write a ``request_preview.json`` snapshot of all effective settings
       before any API calls, so a failed run can be diagnosed and replayed.
    8. Run the three-stage Qwen rule pipeline (``run_qwen_rule_pipeline``).
    9. Unless ``--skip-runninghub`` is set, submit to RunningHub and download
       results (``run_runninghub``).
    10. Print a final JSON status line to stdout for programmatic consumers.
    """
    args = parse_args()
    # Load API keys and overrides from the project env file into os.environ.
    load_env_file(args.env_file)
    # Apply env-variable overrides for model names and base URL.
    apply_env_defaults(args)
    # Resolve Qwen API key; exits with a clear error if neither source has it.
    qwen_key = require_key(args.qwen_api_key, "QWEN_API_KEY")
    image_path = find_sample_image(args.source_dir, args.sample_id)
    # Create the per-sample output subdirectory (e.g. output_dir/char_001/).
    sample_dir = args.output_dir / args.sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)

    # Write a pre-run snapshot of all effective settings for audit/replay.
    write_json(
        sample_dir / "request_preview.json",
        {
            "sample_id": args.sample_id,
            "source_image": str(image_path),
            "output_dir": str(sample_dir),
            "qwen_base_url": args.qwen_base_url,
            "qwen_vision_model": args.qwen_vision_model,
            "qwen_text_model": args.qwen_text_model,
            "runninghub_endpoint": args.runninghub_endpoint,
            "runninghub_prompt_file": str(args.runninghub_prompt_file),
            "skip_runninghub": args.skip_runninghub,
        },
    )

    # Run the Qwen extraction pipeline; always executed.
    atomic_path = run_qwen_rule_pipeline(args, qwen_key, image_path, sample_dir)
    # Default status if RunningHub is skipped.
    status: dict[str, Any] = {"status": "qwen_only", "sample_id": args.sample_id, "atomic_rules": str(atomic_path)}
    # Optionally submit to RunningHub for figurine image generation.
    if not args.skip_runninghub:
        status = run_runninghub(args, image_path, atomic_path, sample_dir)

    # Emit a final machine-readable summary to stdout.
    print(json.dumps({"status": "finished", "sample_dir": str(sample_dir), "result": status}, ensure_ascii=False))


if __name__ == "__main__":
    main()
