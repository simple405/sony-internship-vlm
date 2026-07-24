#!/usr/bin/env python3
"""Retry char_008 which failed content moderation (errorCode 1501).

Tries the original prompt first; if content moderation blocks again, falls back
to softened and minimal prompt variants.
"""

from __future__ import annotations

import json
from pathlib import Path

from vlm.scripts.generate.runninghub_client import (
    init_client,
    upload_image,
    submit_task,
    poll_task,
    download_result,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
init_client()

PROMPT_PATH = PROJECT_ROOT / "vlm" / "prompts" / "generation" / "runninghub" / "runninghub_g2_figurine_front_view_user_cn.txt"
SOURCE_IMAGE = PROJECT_ROOT / "vlm" / "data" / "SN_6期动漫数据标注" / "char_008" / "char_008.png"
OUTPUT_DIR = PROJECT_ROOT / "vlm" / "data" / "smoke_test" / "char_008"


def try_generate(prompt: str, label: str) -> bool:
    """Attempt a full upload→submit→poll→download cycle. Returns True on success."""
    print(f"\n[{label}]")
    try:
        # Upload
        print("  Uploading...", end=" ", flush=True)
        upload_data = upload_image(SOURCE_IMAGE)
        image_url = upload_data["download_url"]
        print(f"OK ({upload_data['fileName']})")

        # Submit
        print("  Submitting...", end=" ", flush=True)
        submit_data = submit_task(image_url, prompt)
        task_id = submit_data.get("taskId", "")
        print(f"OK (taskId={task_id})")

        # Save provenance
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "upload_response.json").write_text(
            json.dumps(upload_data, ensure_ascii=False, indent=2), encoding="utf-8")
        (OUTPUT_DIR / "submit_response.json").write_text(
            json.dumps(submit_data, ensure_ascii=False, indent=2), encoding="utf-8")
        (OUTPUT_DIR / "prompt.txt").write_text(prompt, encoding="utf-8")

        # Poll
        print("  Polling...", end=" ", flush=True)
        result = poll_task(task_id)

        # Download
        img_url = result["results"][0]["url"]
        download_result(result["results"][0], OUTPUT_DIR, "char_008")
        print(f"  ✅ Success!")
        return True

    except RuntimeError as e:
        print(f"\n  ❌ {e}")
        return False


def main():
    prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    print(f"Source: {SOURCE_IMAGE}")
    print(f"Prompt: {PROMPT_PATH} ({len(prompt)} chars)")

    # Attempt 1: Original prompt
    if try_generate(prompt, "Attempt 1: Original prompt"):
        return

    # Attempt 2: Softened prompt (less aggressive prohibition language)
    softened = prompt.replace(
        "禁止新增原图没有的兽耳、角、帽子、蝴蝶结、尾巴、翅膀、武器或装饰。不要把头发尖角、发饰、帽檐、衣服边缘误生成兽耳、角或尾巴。",
        "输出内容仅保留原图已有元素，头发和衣物装饰与原图严格一致。"
    )
    if try_generate(softened, "Attempt 2: Softened prompt"):
        return

    # Attempt 3: Minimal prompt
    minimal = "你是一位将二次元 IP 角色设计为 3D PVC 收藏手办的二创周边设计师。请只根据输入的 2D 角色图，生成一张同角色 PVC 手办正面视角设计图。输出必须是一张白底设计图，只展示手办的正面全身视角。材质为哑光喷涂 PVC，细节为雕刻和上色效果。"
    if try_generate(minimal, "Attempt 3: Minimal prompt"):
        return

    print("\n❌ All 3 attempts failed. char_008 needs manual investigation.")


if __name__ == "__main__":
    main()
