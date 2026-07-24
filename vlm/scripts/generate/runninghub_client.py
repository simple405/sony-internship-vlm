"""Shared RunningHub API client for G-2.0 image-to-image generation.

Provides the full upload → submit → poll → download pipeline. Used by:
- smoke_test_front_view.py (single sample)
- batch_front_view.py (multi-sample, ThreadPoolExecutor)
- retry_char_008.py (single sample retry)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import requests
from PIL import Image

from vlm.scripts._paths import API_ENV_FILE, load_api_env


# ── Constants ──────────────────────────────────────────────────────────
API_BASE = "https://www.runninghub.cn"
ENDPOINT = f"{API_BASE}/openapi/v2/rhart-image-g-2/image-to-image"
UPLOAD_URL = f"{API_BASE}/openapi/v2/media/upload/binary"
QUERY_URL = f"{API_BASE}/openapi/v2/query"

DEFAULT_ASPECT_RATIO = "21:9"
DEFAULT_RESOLUTION = "1k"
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_TIMEOUT = 900


# ── Configuration ──────────────────────────────────────────────────────
def init_client(env_path: Optional[Path] = None) -> str:
    """Load api.env and return the RunningHub API key.

    Args:
        env_path: Path to api.env. Defaults to API_ENV_FILE from _paths.

    Returns:
        RunningHub API key string.

    Raises:
        RuntimeError: If RUNNINGHUB_API_KEY is not set.
    """
    load_api_env(env_path or API_ENV_FILE)
    api_key = os.environ.get("RUNNINGHUB_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RUNNINGHUB_API_KEY is not set.")
    return api_key


# ── HTTP helpers ───────────────────────────────────────────────────────
def _get_api_key() -> str:
    """Return the RunningHub API key from environment."""
    key = os.environ.get("RUNNINGHUB_API_KEY", "").strip()
    if not key:
        raise RuntimeError("RUNNINGHUB_API_KEY is not set. Call init_client() or load_api_env() first.")
    return key


def auth_headers(*, json_content: bool = True) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {_get_api_key()}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


# ── Pipeline steps ─────────────────────────────────────────────────────
def upload_image(image_path: Path) -> dict[str, Any]:
    """Upload a local image. Returns the ``data`` dict with ``download_url``."""
    with image_path.open("rb") as fh:
        resp = requests.post(
            UPLOAD_URL,
            headers={"Authorization": f"Bearer {_get_api_key()}"},
            files={"file": (image_path.name, fh)},
            timeout=120,
        )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    if data.get("code") not in (0, "0", None):
        raise RuntimeError(f"Upload failed: {data}")
    url = data.get("data", {}).get("download_url", "")
    if not url:
        raise RuntimeError(f"No download_url in upload response: {data}")
    return data["data"]


def submit_task(
    image_url: str,
    prompt: str,
    *,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    resolution: str = DEFAULT_RESOLUTION,
) -> dict[str, Any]:
    """Submit an image-to-image task. Returns the full response dict."""
    payload = {
        "prompt": prompt,
        "imageUrls": [image_url],
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
    }
    resp = requests.post(ENDPOINT, headers=auth_headers(), data=json.dumps(payload), timeout=120)
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    if data.get("errorCode") or str(data.get("status", "")).upper() == "FAILED":
        raise RuntimeError(f"Submit failed: {data}")
    if not data.get("taskId"):
        raise RuntimeError(f"No taskId in submit response: {data}")
    return data


def poll_task(
    task_id: str,
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Poll until SUCCESS. Raises RuntimeError on FAILED, TimeoutError if expired."""
    deadline = time.time() + timeout
    while True:
        resp = requests.post(
            QUERY_URL,
            headers=auth_headers(),
            data=json.dumps({"taskId": task_id}),
            timeout=30,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        status = str(data.get("status", "")).upper()
        if status == "SUCCESS":
            return data
        if status not in ("QUEUED", "RUNNING"):
            raise RuntimeError(f"Task failed: {data}")
        if time.time() >= deadline:
            raise TimeoutError(f"Timeout waiting for task {task_id}. Last status: {status}")
        time.sleep(poll_interval)


def download_result(
    result: dict[str, Any],
    out_dir: Path,
    sample_id: str,
    *,
    label: str = "front_view",
) -> Path:
    """Download a single result image. Returns the output path."""
    url = result.get("url")
    if not url:
        raise RuntimeError(f"No URL in result: {result}")
    ext = str(result.get("outputType") or "png").strip(".") or "png"
    out_path = out_dir / f"{sample_id}_{label}.{ext.lower()}"
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if chunk:
                    fh.write(chunk)
    tmp.replace(out_path)
    return out_path


def get_image_size(image_path: Path) -> tuple[int, int]:
    """Return (width, height) for a local image."""
    with Image.open(image_path) as img:
        return img.size
