"""Batch convert all 2D images in SN_6期动漫数据标注 to front-view 3D PVC figurines."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from vlm.scripts.generate.runninghub_client import (
    init_client,
    upload_image,
    submit_task,
    poll_task,
    download_result,
    get_image_size,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]  # -> /home/intern/jsy
init_client()

PROMPT_FILE = PROJECT_ROOT / "vlm" / "prompts" / "generation" / "runninghub" / "runninghub_g2_figurine_front_view_user_cn.txt"
SOURCE_ROOT = PROJECT_ROOT / "vlm" / "data" / "SN_6期动漫数据标注"
OUTPUT_ROOT = PROJECT_ROOT / "vlm" / "data" / "smoke_test"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def has_output(sample_id: str) -> bool:
    out_dir = OUTPUT_ROOT / sample_id
    for suffix in IMAGE_SUFFIXES:
        if (out_dir / f"{sample_id}_front_view{suffix}").exists():
            return True
    return False


def process_one(sample_id: str, prompt: str) -> dict:
    """Process a single char_* sample. Returns status dict."""
    src_dir = SOURCE_ROOT / sample_id

    # Locate source image
    img_path = None
    for suffix in IMAGE_SUFFIXES:
        candidate = src_dir / f"{sample_id}{suffix}"
        if candidate.exists():
            img_path = candidate
            break
    if img_path is None:
        return {"sample_id": sample_id, "status": "skipped", "reason": "no source image"}

    out_dir = OUTPUT_ROOT / sample_id
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # Upload
    upload = upload_image(img_path)
    image_url = str(upload["download_url"])

    # Submit
    submit = submit_task(image_url, prompt)
    task_id = str(submit["taskId"])

    # Save provenance
    (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (out_dir / "upload_response.json").write_text(json.dumps(upload, ensure_ascii=False, indent=2))
    (out_dir / "submit_response.json").write_text(json.dumps(submit, ensure_ascii=False, indent=2))

    # Poll
    final = poll_task(task_id)
    results = final.get("results") or []
    if not results:
        return {"sample_id": sample_id, "task_id": task_id, "status": "no_results",
                "elapsed_s": round(time.time() - t0, 1)}

    # Download
    downloaded = download_result(results[0], out_dir, sample_id)
    w, h = get_image_size(downloaded)

    elapsed = round(time.time() - t0, 1)
    return {"sample_id": sample_id, "task_id": task_id, "status": "completed",
            "elapsed_s": elapsed, "size": f"{w}x{h}"}


def main() -> None:
    prompt = PROMPT_FILE.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise SystemExit(f"Prompt file is empty: {PROMPT_FILE}")

    # Discover samples
    sample_ids = sorted(
        d.name for d in SOURCE_ROOT.iterdir()
        if d.is_dir() and d.name.startswith("char_")
    )
    if not sample_ids:
        raise SystemExit(f"No char_* folders found under {SOURCE_ROOT}")

    # Filter already-done
    pending = [sid for sid in sample_ids if not has_output(sid)]
    skipped = len(sample_ids) - len(pending)

    WORKERS = 4

    print(json.dumps({
        "status": "batch_started",
        "total": len(sample_ids),
        "skipped": skipped,
        "pending": len(pending),
        "workers": WORKERS,
        "prompt_file": str(PROMPT_FILE),
        "source_root": str(SOURCE_ROOT),
        "output_root": str(OUTPUT_ROOT),
    }, ensure_ascii=False), flush=True)

    if not pending:
        print(json.dumps({"status": "all_done", "message": "All samples already have output."}, ensure_ascii=False))
        return

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        future_map = {executor.submit(process_one, sid, prompt): sid for sid in pending}
        for future in as_completed(future_map):
            sid = future_map[future]
            try:
                r = future.result()
            except Exception as exc:
                r = {"sample_id": sid, "status": "failed",
                     "error": f"{type(exc).__name__}: {exc}"}
            print(json.dumps(r, ensure_ascii=False), flush=True)
            results.append(r)

    # Summary
    completed = sum(1 for r in results if r.get("status") == "completed")
    failed = sum(1 for r in results if r.get("status") == "failed")
    no_results = sum(1 for r in results if r.get("status") == "no_results")
    summary = {
        "status": "batch_finished",
        "total": len(sample_ids),
        "skipped": skipped,
        "pending": len(pending),
        "completed": completed,
        "failed": failed,
        "no_results": no_results,
        "results": results,
    }
    (OUTPUT_ROOT / "batch_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
