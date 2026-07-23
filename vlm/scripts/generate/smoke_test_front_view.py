"""Smoke test: convert char_001 2D image to front-view 3D PVC figurine via RunningHub."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests
from PIL import Image


def load_api_env(env_path: Path) -> None:
    """Load key=value pairs from api.env into os.environ (no overwrite)."""
    if not env_path.exists():
        print(f"[WARN] api.env not found: {env_path}")
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


API_ENV = Path(__file__).resolve().parents[2] / "config" / "api.env"
load_api_env(API_ENV)

API_KEY = os.environ.get("RUNNINGHUB_API_KEY", "").strip()
if not API_KEY:
    raise SystemExit("RUNNINGHUB_API_KEY is not set. Check vlm/config/api.env")

ENDPOINT = "https://www.runninghub.cn/openapi/v2/rhart-image-g-2/image-to-image"
UPLOAD_URL = "https://www.runninghub.cn/openapi/v2/media/upload/binary"
QUERY_URL = "https://www.runninghub.cn/openapi/v2/query"

# --- Prompt: front-view only ---
PROMPT = """假设你是一位将二次元 IP 角色设计为 3D PVC 收藏手办的二创周边设计师。请只根据输入的 2D 角色图，生成一张同角色 PVC 手办**正面视角**设计图。

输出必须是一张白底设计图，只展示手办的正面全身视角。角色必须保持中性站姿，双脚落地，身体直立，可以轻微 Q 版化，但仍然是 PVC 手办。

所有身份细节都要严格尊重原图：发型轮廓、发色、刘海、侧发、后发、眼睛、表情、服装结构、配色、图案、饰品、武器或道具都必须和原图对得上。只允许保留原图可见元素，禁止新增原图没有的兽耳、角、帽子、蝴蝶结、尾巴、翅膀、武器或装饰。不要把头发尖角、发饰、帽檐、衣服边缘误生成兽耳、角或尾巴。

材质为哑光喷涂 PVC，细节为雕刻和上色效果。不要生成展示台、包装盒、文字、标签、水印、尺寸标注，也不要把原图直接贴到结果里。"""

# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # -> /home/intern/jsy
SOURCE_IMAGE = PROJECT_ROOT / "vlm" / "data" / "SN_6期动漫数据标注" / "char_001" / "char_001.png"
OUTPUT_DIR = PROJECT_ROOT / "vlm" / "data" / "smoke_test" / "char_001"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def auth_headers(*, json_content: bool = True) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {API_KEY}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


def upload_image(image_path: Path) -> dict:
    print(f"[1/4] Uploading {image_path.name} ({image_path.stat().st_size} bytes)...")
    with image_path.open("rb") as fh:
        resp = requests.post(
            UPLOAD_URL,
            headers={"Authorization": f"Bearer {API_KEY}"},
            files={"file": (image_path.name, fh)},
            timeout=120,
        )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") not in (0, "0", None):
        raise RuntimeError(f"Upload failed: {data}")
    download_url = data.get("data", {}).get("download_url", "")
    if not download_url:
        raise RuntimeError(f"No download_url in upload response: {data}")
    print(f"  ✅ uploaded, download_url length={len(download_url)}")
    return data["data"]


def submit_task(image_url: str) -> dict:
    print("[2/4] Submitting image-to-image task...")
    payload = {
        "prompt": PROMPT,
        "imageUrls": [image_url],
        "aspectRatio": "21:9",
        "resolution": "1k",
    }
    resp = requests.post(ENDPOINT, headers=auth_headers(), data=json.dumps(payload), timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errorCode") or str(data.get("status", "")).upper() == "FAILED":
        raise RuntimeError(f"Submit failed: {data}")
    task_id = data.get("taskId", "")
    if not task_id:
        raise RuntimeError(f"No taskId in submit response: {data}")
    print(f"  ✅ taskId={task_id}")
    return data


def poll_and_download(task_id: str, poll_interval: int = 5, timeout: int = 600) -> list[Path]:
    print(f"[3/4] Polling task {task_id} (interval={poll_interval}s, timeout={timeout}s)...")
    deadline = time.time() + timeout
    last_status = ""
    while True:
        resp = requests.post(
            QUERY_URL,
            headers=auth_headers(),
            data=json.dumps({"taskId": task_id}),
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        status = str(data.get("status", "")).upper()
        if status != last_status:
            print(f"  status={status}")
            last_status = status
        if status == "SUCCESS":
            break
        if status not in ("QUEUED", "RUNNING"):
            raise RuntimeError(f"Task failed: {data}")
        if time.time() >= deadline:
            raise TimeoutError(f"Timeout waiting for task {task_id}. Last: {data}")
        time.sleep(poll_interval)

    results = data.get("results") or []
    print(f"  ✅ task completed, {len(results)} result(s)")
    return _download_results(results)


def _download_results(results: list[dict]) -> list[Path]:
    downloaded: list[Path] = []
    for idx, result in enumerate(results, start=1):
        url = result.get("url")
        if not url:
            continue
        ext = str(result.get("outputType") or "png").strip(".") or "png"
        name = f"char_001_front_view{'' if idx == 1 else f'_{idx}'}.{ext.lower()}"
        out_path = OUTPUT_DIR / name
        print(f"[4/4] Downloading result {idx} -> {out_path}")
        tmp = out_path.with_suffix(out_path.suffix + ".part")
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        fh.write(chunk)
        tmp.replace(out_path)
        with Image.open(out_path) as img:
            print(f"  ✅ {name} — size={img.size}, mode={img.mode}")
        downloaded.append(out_path)
    return downloaded


def main() -> None:
    print("=" * 60)
    print(" Smoke Test: char_001 2D → Front-View 3D PVC Figurine")
    print(f" Source: {SOURCE_IMAGE}")
    print(f" Output: {OUTPUT_DIR}")
    print("=" * 60)

    if not SOURCE_IMAGE.exists():
        raise SystemExit(f"Source image not found: {SOURCE_IMAGE}")

    # Save the prompt for audit
    (OUTPUT_DIR / "prompt.txt").write_text(PROMPT, encoding="utf-8")

    upload = upload_image(SOURCE_IMAGE)
    submit = submit_task(str(upload["download_url"]))
    task_id = str(submit["taskId"])

    # Save intermediate responses
    (OUTPUT_DIR / "upload_response.json").write_text(json.dumps(upload, ensure_ascii=False, indent=2))
    (OUTPUT_DIR / "submit_response.json").write_text(json.dumps(submit, ensure_ascii=False, indent=2))

    downloaded = poll_and_download(task_id)

    summary = {
        "sample_id": "char_001",
        "task_id": task_id,
        "status": "completed" if downloaded else "no_output",
        "downloaded": [str(p) for p in downloaded],
    }
    (OUTPUT_DIR / "smoke_test_result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n{'=' * 60}")
    print(f" Done! Output: {OUTPUT_DIR}")
    print(f" Files: {[p.name for p in OUTPUT_DIR.iterdir()]}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
