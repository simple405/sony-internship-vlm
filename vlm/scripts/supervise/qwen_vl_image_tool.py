"""Claude Code-safe Qwen image understanding CLI.

Claude Code's native Read tool can return images as Anthropic tool_result image
blocks. DashScope's Anthropic-compatible endpoint rejects that message shape, so
Claude Code should call this script for image understanding and receive plain
text or JSON instead.
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

warnings.filterwarnings("ignore", category=RequestsDependencyWarning)

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))


DEFAULT_ENV_FILE = Path("vlm/config/api.env")
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-vl-max"
DEFAULT_PROMPT = """你是动漫 IP 商品监修流程中的图片理解助手。
请只基于图片可见内容进行观察，不要猜测不可见细节。
输出中文，结构清晰，重点包含：主体/商品类型、视角、角色关键外观、服装配饰、明显缺失或异常。"""


def parse_args() -> argparse.Namespace:
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


def load_env_file(path: Path) -> None:
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
    value = cli_value.strip() or os.environ.get(env_name, "").strip() or default
    if not value:
        raise SystemExit(f"{env_name} is required. Set it in {DEFAULT_ENV_FILE} or pass the CLI flag.")
    return value


def media_type(path: Path) -> str:
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
    if not path.exists():
        raise SystemExit(f"Image not found: {path}")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type(path)};base64,{data}"


def build_messages(prompt: str, image_paths: list[Path], want_json: bool) -> list[dict[str, Any]]:
    if want_json:
        prompt = (
            prompt.rstrip()
            + "\n\n请返回一个 JSON object，字段建议包含 visual_summary, views, visible_features, issues, confidence。"
        )
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        content.append({"type": "image_url", "image_url": {"url": encode_image_data_url(image_path)}})
    return [{"role": "user", "content": content}]


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
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if want_json:
        payload["response_format"] = {"type": "json_object"}

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


def write_debug_request(path: Path, *, model: str, base_url: str, image_paths: list[Path], prompt: str) -> None:
    preview = {
        "base_url": base_url,
        "model": model,
        "image_paths": [str(path) for path in image_paths],
        "prompt_chars": len(prompt),
        "note": "Image bytes and API key are intentionally omitted.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)

    api_key = require_value(args.api_key, "QWEN_API_KEY")
    base_url = require_value(args.base_url, "QWEN_BASE_URL", DEFAULT_BASE_URL)
    model = require_value(args.model, "QWEN_VISION_MODEL", DEFAULT_MODEL)
    image_paths = [path.resolve() for path in args.images]

    if args.debug_request:
        write_debug_request(args.debug_request, model=model, base_url=base_url, image_paths=image_paths, prompt=args.prompt)

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

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
