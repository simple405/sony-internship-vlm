"""Claude Code-safe Qwen image understanding CLI.

WHY THIS SCRIPT EXISTS
----------------------
Claude Code's native Read tool can return images as Anthropic ``tool_result``
image blocks (base64 content items with type="image").  DashScope's
Anthropic-compatible endpoint rejects that exact message shape with the error:
    "Unexpected item type in content"
Rather than trying to suppress Claude Code's built-in image rendering, this
script acts as a thin wrapper: it encodes image files as OpenAI-style
``image_url`` data-URIs, sends them to the DashScope chat/completions endpoint
directly via ``requests``, and prints the model's plain-text (or JSON) reply to
stdout.  Claude Code then receives only text and never produces a tool_result
image block at all.

OUTPUT MODES
------------
* Default (text): the model's raw reply is printed to stdout as-is.
* ``--json`` mode: the prompt is automatically appended with a Chinese
  instruction to return a JSON object; the API call also sets
  ``response_format={"type": "json_object"}`` so the model is constrained to
  emit valid JSON.  The JSON string is still printed to stdout as plain text —
  the caller can parse it with ``json.loads``.

API AUTH
--------
Credentials are resolved in priority order:
  1. ``--api-key`` CLI flag
  2. ``QWEN_API_KEY`` environment variable
  3. Key read from ``vlm/config/api.env`` (loaded automatically at startup)
The ``api.env`` file uses ``KEY=value`` syntax; quoted values and BOM are both
handled.  Do NOT commit ``api.env`` to version control.

ERROR HANDLING
--------------
* Missing image file  → ``SystemExit`` before any network call.
* Unsupported format  → ``SystemExit`` with a friendly message.
* Missing API key     → ``SystemExit`` listing the env var name and config path.
* Non-2xx HTTP status → ``requests.HTTPError`` raised by ``raise_for_status()``.
* Malformed response  → ``RuntimeError`` with the raw response payload.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any

import requests
from requests import RequestsDependencyWarning

# Suppress urllib3/charset-normalizer version mismatch warnings that appear on
# some environments — they are cosmetic and do not affect correctness.
warnings.filterwarnings("ignore", category=RequestsDependencyWarning)

# When this file is run directly (python qwen_vl_image_tool.py) rather than via
# ``python -m vlm.scripts.supervise.qwen_vl_image_tool``, __package__ is None
# or "".  In that case, add the repo root to sys.path so that other vlm imports
# resolve correctly if they are ever needed.
if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Path to the project-level environment file that stores API keys.
DEFAULT_ENV_FILE = Path("vlm/config/api.env")

# DashScope's OpenAI-compatible base URL for Qwen models.
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Vision model used when neither --model nor QWEN_VISION_MODEL is set.
DEFAULT_MODEL = "qwen-vl-max"

# Default prompt instructs the model to describe merchandise visually in
# structured Chinese, focusing on features relevant to anime IP supervision.
DEFAULT_PROMPT = """你是动漫 IP 商品监修流程中的图片理解助手。
请只基于图片可见内容进行观察，不要猜测不可见细节。
输出中文，结构清晰，重点包含：主体/商品类型、视角、角色关键外观、服装配饰、明显缺失或异常。"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Define and parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        Parsed argument object.  Key fields:

        * ``images``        – one or more local image Path objects.
        * ``prompt``        – instruction string sent to the vision model.
        * ``env_file``      – path to the api.env credentials file.
        * ``api_key``       – optional inline API key (overrides env file).
        * ``base_url``      – optional DashScope base URL override.
        * ``model``         – vision model name (e.g. "qwen-vl-max").
        * ``max_tokens``    – upper bound on the model's output length.
        * ``temperature``   – sampling temperature; 0.0 = deterministic.
        * ``timeout``       – HTTP request timeout in seconds.
        * ``json``          – if True, request JSON output from the model.
        * ``output``        – optional file path to also save the response.
        * ``debug_request`` – optional file path to write a redacted request
          preview (no API key, no image bytes).
    """
    parser = argparse.ArgumentParser(
        description="Analyze one or more local images with Qwen VL and print text/JSON for Claude Code."
    )
    parser.add_argument("images", nargs="+", type=Path, help="Local image path(s).")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Question/instruction for the image model.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--api-key", default="", help="Qwen API key. Prefer vlm/config/api.env.")
    parser.add_argument("--base-url", default="", help="OpenAI-compatible Qwen base URL.")
    parser.add_argument("--model", default="", help="Vision model, e.g. qwen-vl-max or qwen3-vl-plus.")
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true", help="Ask the model to return a JSON object.")
    parser.add_argument("--output", type=Path, help="Optional output file for the model response.")
    parser.add_argument("--debug-request", type=Path, help="Optional redacted request preview JSON.")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------

def load_env_file(path: Path) -> None:
    """Load KEY=value pairs from an env file into ``os.environ``.

    Only sets variables that are NOT already in the environment
    (``os.environ.setdefault``), so real environment variables always take
    precedence over the file.

    Handles:
    * UTF-8 BOM (``utf-8-sig`` encoding).
    * Blank lines and ``#`` comments — both are skipped.
    * Quoted values — surrounding single or double quotes are stripped.
    * Lines without ``=`` — silently skipped.

    Parameters
    ----------
    path:
        Path to the env file (e.g. ``vlm/config/api.env``).  If the file does
        not exist, the function returns without error — this is intentional so
        that missing config is reported later by ``require_value`` with a clear
        message.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        # Skip blank lines and comments.
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        # Split on the first '=' only; values may contain '=' themselves.
        key, value = stripped.split("=", 1)
        key = key.strip()
        # Strip surrounding quotes that some editors add automatically.
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def require_value(cli_value: str, env_name: str, default: str = "") -> str:
    """Resolve a configuration value with a clear three-level fallback.

    Resolution order:
    1. ``cli_value`` (non-empty string passed from argparse).
    2. Environment variable named ``env_name``.
    3. ``default`` (may be an empty string).

    Raises ``SystemExit`` if the resolved value is empty, printing a message
    that tells the user exactly which env var or CLI flag to set.

    Parameters
    ----------
    cli_value:
        Value from the CLI argument (may be ``""`` if not provided).
    env_name:
        Name of the environment variable to check as fallback.
    default:
        Hard-coded default used when both CLI and env are absent.

    Returns
    -------
    str
        The resolved, non-empty configuration value.
    """
    value = cli_value.strip() or os.environ.get(env_name, "").strip() or default
    if not value:
        raise SystemExit(f"{env_name} is required. Set it in {DEFAULT_ENV_FILE} or pass the CLI flag.")
    return value


# ---------------------------------------------------------------------------
# Image encoding
# ---------------------------------------------------------------------------

def media_type(path: Path) -> str:
    """Return the MIME type string for a supported image file extension.

    DashScope's image_url format requires an accurate MIME type in the
    ``data:<mime>;base64,`` data-URI prefix.

    Parameters
    ----------
    path:
        Image file path.  Only the suffix is inspected.

    Returns
    -------
    str
        MIME type string, e.g. ``"image/jpeg"``.

    Raises
    ------
    SystemExit
        For unsupported extensions (anything other than jpg/jpeg/png/webp/gif).
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
    """Read an image file and return it as a base64 data-URI string.

    The resulting string has the form::

        data:<mime-type>;base64,<base64-encoded-bytes>

    This format is accepted by DashScope's ``image_url`` content block and
    avoids any dependency on a publicly accessible URL.

    Parameters
    ----------
    path:
        Absolute or relative path to the image file.  Must exist.

    Returns
    -------
    str
        Data-URI string ready to embed in an ``image_url`` message block.

    Raises
    ------
    SystemExit
        If the file does not exist.
    """
    if not path.exists():
        raise SystemExit(f"Image not found: {path}")
    # Read raw bytes and base64-encode; decode to ASCII str for JSON embedding.
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type(path)};base64,{data}"


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------

def build_messages(prompt: str, image_paths: list[Path], want_json: bool) -> list[dict[str, Any]]:
    """Build the OpenAI-style messages list for the chat/completions API call.

    The message structure follows the OpenAI vision format:
    a single user turn whose ``content`` is a list of typed blocks:
    one ``text`` block (the prompt) followed by one ``image_url`` block per
    image.  This is the format DashScope accepts for Qwen-VL models.

    If ``want_json`` is True, a Chinese instruction asking for a JSON object
    (with suggested field names) is appended to the prompt text.  This
    supplements the ``response_format`` parameter set in ``call_qwen``; the
    in-prompt instruction helps the model produce well-named keys even when
    the caller did not specify field names in their own prompt.

    Parameters
    ----------
    prompt:
        User instruction string.
    image_paths:
        Ordered list of image files to include.  Each becomes one
        ``image_url`` content block after base64-encoding.
    want_json:
        Whether to append a JSON-output instruction to the prompt.

    Returns
    -------
    list[dict[str, Any]]
        A one-element list containing the user message dict.
    """
    if want_json:
        # Append a Chinese hint for the field names Qwen should use.  Keeping
        # the hint in Chinese matches the rest of the default prompt and avoids
        # language-switching artefacts in the model output.
        prompt = (
            prompt.rstrip()
            + "\n\n请返回一个 JSON object，字段建议包含 visual_summary, views, visible_features, issues, confidence。"
        )
    # Start content with the text prompt block.
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    # Append one image_url block per image, in order.
    for image_path in image_paths:
        content.append({"type": "image_url", "image_url": {"url": encode_image_data_url(image_path)}})
    return [{"role": "user", "content": content}]


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def call_qwen(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    timeout: int,
    want_json: bool,
) -> str:
    """Send a chat/completions request to the Qwen (DashScope) API.

    Uses ``requests.post`` directly rather than the OpenAI SDK to avoid
    adding a heavyweight dependency.  The Authorization header uses the
    ``Bearer <api_key>`` scheme that DashScope's compatible-mode endpoint
    expects.

    JSON output mode
    ~~~~~~~~~~~~~~~~
    When ``want_json=True`` the payload includes
    ``response_format={"type": "json_object"}``.  DashScope honours this flag
    for Qwen-VL models and guarantees a parseable JSON string in the response.

    Parameters
    ----------
    api_key:
        DashScope API key.
    base_url:
        Base URL, e.g. ``"https://dashscope.aliyuncs.com/compatible-mode/v1"``.
        A trailing slash is stripped automatically.
    model:
        Model identifier, e.g. ``"qwen-vl-max"`` or ``"qwen3-vl-plus"``.
    messages:
        Pre-built messages list as returned by ``build_messages``.
    max_tokens:
        Maximum number of tokens in the model's reply.
    temperature:
        Sampling temperature.  0.0 is deterministic and recommended for
        structured extraction tasks.
    timeout:
        Seconds to wait for a response before raising a ``Timeout`` error.
    want_json:
        If True, adds ``response_format`` to the payload.

    Returns
    -------
    str
        The model's reply text (choices[0].message.content).

    Raises
    ------
    requests.HTTPError
        For any non-2xx HTTP status code.
    RuntimeError
        If the response JSON does not contain the expected
        ``choices[0].message.content`` path.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if want_json:
        # Constrain model output to a JSON object at the API level.
        payload["response_format"] = {"type": "json_object"}

    response = requests.post(
        # Construct the full endpoint URL from the base URL.
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        # Serialize with ensure_ascii=False to correctly handle any Unicode
        # characters in the prompt (e.g. Chinese text).
        data=json.dumps(payload, ensure_ascii=False),
        timeout=timeout,
    )
    # Raise immediately for HTTP 4xx/5xx errors so the caller sees a clear
    # exception rather than an opaque empty string.
    response.raise_for_status()
    result = response.json()
    try:
        # Standard OpenAI response shape: choices[0].message.content
        return str(result["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Qwen response missing choices[0].message.content: {result}") from exc


# ---------------------------------------------------------------------------
# Debug helper
# ---------------------------------------------------------------------------

def write_debug_request(path: Path, *, model: str, base_url: str, image_paths: list[Path], prompt: str) -> None:
    """Write a redacted request preview to a JSON file for debugging.

    The preview intentionally omits the API key and image bytes (which can be
    megabytes each) so the file is safe to share or commit.  It records enough
    metadata to verify that the correct model, endpoint, and images are being
    used.

    Parameters
    ----------
    path:
        Output file path for the preview JSON.
    model:
        Resolved model name that will be sent.
    base_url:
        Resolved base URL that will be used.
    image_paths:
        List of image file paths (recorded as strings, not encoded).
    prompt:
        The full prompt string; only its character count is recorded to keep
        the file compact.
    """
    preview = {
        "base_url": base_url,
        "model": model,
        "image_paths": [str(path) for path in image_paths],
        "prompt_chars": len(prompt),
        "note": "Image bytes and API key are intentionally omitted.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse arguments, load credentials, call Qwen, and print the result.

    Execution flow:
    1. Parse CLI arguments.
    2. Load api.env so that QWEN_API_KEY / QWEN_BASE_URL / QWEN_VISION_MODEL
       are available in the environment.
    3. Resolve the three required config values (api_key, base_url, model)
       using the CLI-then-env fallback chain.
    4. Resolve absolute paths for all image arguments.
    5. Optionally write a redacted debug preview to ``--debug-request``.
    6. Build the OpenAI-style messages list (encodes images as data-URIs).
    7. POST to the DashScope chat/completions endpoint.
    8. Print the model's reply to stdout (always).
    9. Optionally also save the reply to ``--output``.
    """
    args = parse_args()

    # Step 2: populate os.environ from the api.env file without overriding
    # any variables already set in the shell environment.
    load_env_file(args.env_file)

    # Step 3: resolve credentials; raises SystemExit if any required value
    # cannot be found.
    api_key = require_value(args.api_key, "QWEN_API_KEY")
    base_url = require_value(args.base_url, "QWEN_BASE_URL", DEFAULT_BASE_URL)
    model = require_value(args.model, "QWEN_VISION_MODEL", DEFAULT_MODEL)

    # Step 4: resolve paths to absolute so they work regardless of cwd.
    image_paths = [path.resolve() for path in args.images]

    # Step 5: optional debug output — written before the API call so the
    # caller can inspect configuration even if the request fails.
    if args.debug_request:
        write_debug_request(args.debug_request, model=model, base_url=base_url, image_paths=image_paths, prompt=args.prompt)

    # Step 6-7: build messages and call the API.
    messages = build_messages(args.prompt, image_paths, args.json)
    text = call_qwen(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        timeout=args.timeout,
        want_json=args.json,
    )

    # Step 8-9: output the response.
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    # Always print to stdout so Claude Code can capture the text.
    print(text)


if __name__ == "__main__":
    main()
