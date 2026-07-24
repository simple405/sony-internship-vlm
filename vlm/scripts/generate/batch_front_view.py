"""Batch convert all 2D images in SN_6期动漫数据标注 to front-view 3D PVC figurines."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

from vlm.scripts._paths import API_ENV_FILE, GENERATION_PROMPTS_DIR, SN_6_ANNOTATION_ROOT, SMOKE_TEST_ROOT
from vlm.scripts.generate.runninghub_client import (
    IMAGE_SUFFIXES,
    download_result,
    load_api_env,
    poll_task,
    require_api_key,
    submit_task,
    upload_image,
)

PROMPT_FILE = GENERATION_PROMPTS_DIR / "runninghub_g2_figurine_front_view_user_cn.txt"
SOURCE_ROOT = SN_6_ANNOTATION_ROOT
OUTPUT_ROOT = SMOKE_TEST_ROOT
WORKERS = 4


def has_output(sample_id: str) -> bool:
    out_dir = OUTPUT_ROOT / sample_id
    return any((out_dir / f"{sample_id}_front_view{s}").exists() for s in IMAGE_SUFFIXES)


def process_one(sample_id: str, prompt: str, api_key: str) -> dict:
    src_dir = SOURCE_ROOT / sample_id
    img_path = next(
        (src_dir / f"{sample_id}{s}" for s in IMAGE_SUFFIXES if (src_dir / f"{sample_id}{s}").exists()),
        None,
    )
    if img_path is None:
        return {"sample_id": sample_id, "status": "skipped", "reason": "no source image"}

    out_dir = OUTPUT_ROOT / sample_id
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    upload = upload_image(api_key, img_path)
    submit = submit_task(api_key, prompt, [str(upload["download_url"])])
    task_id = str(submit["taskId"])

    (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (out_dir / "upload_response.json").write_text(json.dumps(upload, ensure_ascii=False, indent=2))
    (out_dir / "submit_response.json").write_text(json.dumps(submit, ensure_ascii=False, indent=2))

    final = poll_task(api_key, task_id)
    results = final.get("results") or []
    if not results:
        return {"sample_id": sample_id, "task_id": task_id, "status": "no_results",
                "elapsed_s": round(time.time() - t0, 1)}

    ext = str(results[0].get("outputType") or "png").strip(".") or "png"
    out_path = out_dir / f"{sample_id}_front_view.{ext.lower()}"
    download_result(results[0], out_path)
    with Image.open(out_path) as img:
        w, h = img.size

    return {"sample_id": sample_id, "task_id": task_id, "status": "completed",
            "elapsed_s": round(time.time() - t0, 1), "size": f"{w}x{h}"}


def main() -> None:
    load_api_env(API_ENV_FILE)
    api_key = require_api_key()

    prompt = PROMPT_FILE.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise SystemExit(f"Prompt file is empty: {PROMPT_FILE}")

    sample_ids = sorted(d.name for d in SOURCE_ROOT.iterdir() if d.is_dir() and d.name.startswith("char_"))
    if not sample_ids:
        raise SystemExit(f"No char_* folders found under {SOURCE_ROOT}")

    pending = [sid for sid in sample_ids if not has_output(sid)]
    skipped = len(sample_ids) - len(pending)

    print(json.dumps({
        "status": "batch_started", "total": len(sample_ids), "skipped": skipped,
        "pending": len(pending), "workers": WORKERS,
        "prompt_file": str(PROMPT_FILE), "source_root": str(SOURCE_ROOT), "output_root": str(OUTPUT_ROOT),
    }, ensure_ascii=False), flush=True)

    if not pending:
        print(json.dumps({"status": "all_done", "message": "All samples already have output."}, ensure_ascii=False))
        return

    batch_results: list[dict] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        future_map = {executor.submit(process_one, sid, prompt, api_key): sid for sid in pending}
        for future in as_completed(future_map):
            sid = future_map[future]
            try:
                r = future.result()
            except Exception as exc:
                r = {"sample_id": sid, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            print(json.dumps(r, ensure_ascii=False), flush=True)
            batch_results.append(r)

    completed = sum(1 for r in batch_results if r.get("status") == "completed")
    failed = sum(1 for r in batch_results if r.get("status") == "failed")
    no_results = sum(1 for r in batch_results if r.get("status") == "no_results")
    summary = {
        "status": "batch_finished", "total": len(sample_ids), "skipped": skipped,
        "pending": len(pending), "completed": completed, "failed": failed,
        "no_results": no_results, "results": batch_results,
    }
    (OUTPUT_ROOT / "batch_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
