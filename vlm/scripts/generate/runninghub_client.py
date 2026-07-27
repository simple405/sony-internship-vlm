"""Shared RunningHub API helpers used by all generate scripts.

Import this module instead of duplicating upload/submit/poll/download logic.
Caller is responsible for calling load_api_env() before require_api_key().
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests


IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

UPLOAD_URL = "https://www.runninghub.cn/openapi/v2/media/upload/binary"
QUERY_URL = "https://www.runninghub.cn/openapi/v2/query"
DEFAULT_ENDPOINT = "https://www.runninghub.cn/openapi/v2/rhart-image-g-2/image-to-image"


def load_api_env(env_path: Path | None = None) -> None:
    """Load key=value pairs from api.env into os.environ (does not overwrite existing vars)."""
    if env_path is None:
        from vlm.scripts._paths import API_ENV_FILE
        env_path = API_ENV_FILE
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def require_api_key() -> str:
    api_key = os.environ.get("RUNNINGHUB_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RUNNINGHUB_API_KEY is not set. Check vlm/config/api.env.")
    return api_key


def _auth_headers(api_key: str, *, json_content: bool = True) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


def upload_image(api_key: str, image_path: Path) -> dict[str, Any]:
    """Upload a local image and return the RunningHub data payload (contains download_url)."""
    with image_path.open("rb") as fh:
        resp = requests.post(
            UPLOAD_URL,
            headers=_auth_headers(api_key, json_content=False),
            files={"file": (image_path.name, fh)},
            timeout=120,
        )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") not in (0, "0", None):
        raise RuntimeError(f"RunningHub upload failed: {data}")
    payload = data.get("data") or {}
    if not payload.get("download_url"):
        raise RuntimeError(f"No download_url in upload response: {data}")
    return payload


def submit_task(
    api_key: str,
    prompt: str,
    image_urls: list[str],
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    aspect_ratio: str = "21:9",
    resolution: str = "1k",
) -> dict[str, Any]:
    """Submit an image-to-image task and return the API response (contains taskId)."""
    payload = {
        "prompt": prompt,
        "imageUrls": image_urls,
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
    }
    resp = requests.post(endpoint, headers=_auth_headers(api_key), data=json.dumps(payload), timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errorCode") or str(data.get("status") or "").upper() == "FAILED":
        raise RuntimeError(f"RunningHub submission failed: {data}")
    if not data.get("taskId"):
        raise RuntimeError(f"No taskId in submit response: {data}")
    return data


def poll_task(
    api_key: str,
    task_id: str,
    *,
    poll_interval: int = 6,
    timeout: int = 900,
) -> dict[str, Any]:
    """Poll until task reaches SUCCESS. Raises RuntimeError on failure, TimeoutError on timeout."""
    deadline = time.time() + timeout
    while True:
        resp = requests.post(
            QUERY_URL,
            headers=_auth_headers(api_key),
            data=json.dumps({"taskId": task_id}),
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        status = str(data.get("status") or "").upper()
        if status == "SUCCESS":
            return data
        if status not in ("QUEUED", "RUNNING"):
            raise RuntimeError(f"Task {task_id} failed: {data}")
        if time.time() >= deadline:
            raise TimeoutError(f"Timeout waiting for task {task_id}. Last: {data}")
        time.sleep(poll_interval)


def download_result(result: dict[str, Any], output_path: Path) -> Path:
    """Download a single result entry to output_path. Uses .part temp file for atomicity."""
    url = result.get("url")
    if not url:
        raise RuntimeError(f"No URL in result entry: {result}")
    tmp = output_path.with_suffix(output_path.suffix + ".part")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if chunk:
                    fh.write(chunk)
    tmp.replace(output_path)
    return output_path
