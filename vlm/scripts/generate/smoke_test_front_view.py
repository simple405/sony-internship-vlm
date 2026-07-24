"""Smoke test: convert a single char_* 2D image to front-view 3D PVC figurine via RunningHub."""

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


PROJECT_ROOT = Path(__file__).resolve().parents[3]  # -> /home/intern/jsy
init_client()

# Default: char_001
SOURCE_IMAGE = PROJECT_ROOT / "vlm" / "data" / "SN_6期动漫数据标注" / "char_001" / "char_001.png"
OUTPUT_ROOT = PROJECT_ROOT / "vlm" / "data" / "smoke_test"
PROMPT_FILE = PROJECT_ROOT / "vlm" / "prompts" / "generation" / "runninghub" / "runninghub_g2_figurine_front_view_user_cn.txt"


def main() -> None:
    prompt = PROMPT_FILE.read_text(encoding="utf-8-sig").strip()
    sample_id = "char_001"
    out_dir = OUTPUT_ROOT / sample_id
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f" Smoke Test: {sample_id} 2D → Front-View 3D PVC Figurine")
    print(f" Source: {SOURCE_IMAGE}")
    print(f" Output: {out_dir}")
    print("=" * 60)

    if not SOURCE_IMAGE.exists():
        raise SystemExit(f"Source image not found: {SOURCE_IMAGE}")

    # Save the prompt for audit
    (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    # Upload
    print(f"[1/4] Uploading {SOURCE_IMAGE.name} ({SOURCE_IMAGE.stat().st_size} bytes)...")
    upload = upload_image(SOURCE_IMAGE)
    print(f"  ✅ uploaded, download_url length={len(str(upload['download_url']))}")

    # Submit
    print("[2/4] Submitting image-to-image task...")
    submit = submit_task(str(upload["download_url"]), prompt)
    task_id = str(submit["taskId"])
    print(f"  ✅ taskId={task_id}")

    # Save intermediate responses
    (out_dir / "upload_response.json").write_text(json.dumps(upload, ensure_ascii=False, indent=2))
    (out_dir / "submit_response.json").write_text(json.dumps(submit, ensure_ascii=False, indent=2))

    # Poll
    print(f"[3/4] Polling task {task_id} ...")
    final = poll_task(task_id)
    results = final.get("results") or []
    print(f"  ✅ task completed, {len(results)} result(s)")

    # Download
    downloaded = []
    for idx, result in enumerate(results, start=1):
        label = "front_view" if idx == 1 else f"front_view_{idx}"
        out_path = download_result(result, out_dir, sample_id, label=label)
        print(f"[4/4] Downloaded result {idx} -> {out_path}")
        downloaded.append(out_path)

    summary = {
        "sample_id": sample_id,
        "task_id": task_id,
        "status": "completed" if downloaded else "no_output",
        "downloaded": [str(p) for p in downloaded],
    }
    (out_dir / "smoke_test_result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n{'=' * 60}")
    print(f" Done! Output: {out_dir}")
    print(f" Files: {[p.name for p in out_dir.iterdir()]}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
