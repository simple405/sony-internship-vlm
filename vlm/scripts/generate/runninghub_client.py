"""Shared RunningHub API helpers used by all generate scripts.

Import this module instead of duplicating upload/submit/poll/download logic.
Caller is responsible for calling load_api_env() before require_api_key().
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from PIL import Image


IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
RESULT_CONTENT_TYPES = {
    "application/octet-stream",
    "image/jpeg",
    "image/png",
    "image/webp",
}
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
RUNNINGHUB_HOSTS = {"runninghub.cn", "www.runninghub.cn"}

UPLOAD_URL = "https://www.runninghub.cn/openapi/v2/media/upload/binary"
QUERY_URL = "https://www.runninghub.cn/openapi/v2/query"
DEFAULT_ENDPOINT = "https://www.runninghub.cn/openapi/v2/rhart-image-g-2/image-to-image"


def _validate_https_url(url: str, *, allowed_hosts: set[str] | None = None) -> str:
    """Validate a remote HTTPS URL before sending credentials or downloading data."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise ValueError(f"Only absolute HTTPS URLs are allowed: {url}")
    if allowed_hosts is not None and host not in allowed_hosts:
        raise ValueError(f"Unexpected API host: {host}")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if host == "localhost" or (address is not None and not address.is_global):
        raise ValueError(f"Private or local URL hosts are not allowed: {host}")
    if allowed_hosts is None and address is None:
        try:
            resolved = {
                ipaddress.ip_address(sockaddr[0].split("%", 1)[0])
                for *_, sockaddr in socket.getaddrinfo(
                    host, 443, type=socket.SOCK_STREAM
                )
            }
        except (OSError, ValueError) as exc:
            raise ValueError(f"Unable to resolve result URL host: {host}") from exc
        if not resolved or any(not item.is_global for item in resolved):
            raise ValueError(f"Private or local URL hosts are not allowed: {host}")
    return url


def safe_result_extension(value: Any, *, default: str = ".png") -> str:
    """Map a provider output type to a fixed image extension allowlist."""
    extension = "." + str(value or "").strip().lstrip(".").lower()
    return extension if extension in IMAGE_SUFFIXES else default


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
    """Return the configured RunningHub key or raise when absent."""
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
            allow_redirects=False,
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
    _validate_https_url(endpoint, allowed_hosts=RUNNINGHUB_HOSTS)
    payload = {
        "prompt": prompt,
        "imageUrls": image_urls,
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
    }
    resp = requests.post(
        endpoint,
        headers=_auth_headers(api_key),
        data=json.dumps(payload),
        timeout=120,
        allow_redirects=False,
    )
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
            allow_redirects=False,
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
    url = str(result.get("url") or "")
    if not url:
        raise RuntimeError(f"No URL in result entry: {result}")
    _validate_https_url(url)
    tmp = output_path.with_suffix(output_path.suffix + ".part")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    try:
        with requests.get(
            url,
            stream=True,
            timeout=120,
            allow_redirects=False,
        ) as r:
            r.raise_for_status()
            content_length = r.headers.get("Content-Length", "")
            if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
                raise RuntimeError(
                    f"RunningHub result exceeds {MAX_DOWNLOAD_BYTES} bytes"
                )
            content_type = r.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type and content_type not in RESULT_CONTENT_TYPES:
                raise RuntimeError(f"Unexpected result content type: {content_type}")
            with tmp.open("wb") as fh:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError(
                            f"RunningHub result exceeds {MAX_DOWNLOAD_BYTES} bytes"
                        )
                    fh.write(chunk)
        with Image.open(tmp) as image:
            image.verify()
            if str(image.format or "").upper() not in {"JPEG", "PNG", "WEBP"}:
                raise RuntimeError(f"Unexpected result image format: {image.format}")
        tmp.replace(output_path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    return output_path
