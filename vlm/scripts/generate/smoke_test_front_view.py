"""Smoke test: convert a single char_* image to front-view 3D PVC figurine via RunningHub."""

from __future__ import annotations

import argparse
import json
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test RunningHub front-view figurine generation on one sample.")
    parser.add_argument("--sample-id", default="char_001", help="Sample ID to process (default: char_001)")
    parser.add_argument("--source-root", type=Path, default=SN_6_ANNOTATION_ROOT)
    parser.add_argument("--output-root", type=Path, default=SMOKE_TEST_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_api_env(API_ENV_FILE)
    api_key = require_api_key()

    prompt = PROMPT_FILE.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise SystemExit(f"Prompt file is empty: {PROMPT_FILE}")

    sample_id = args.sample_id
    src_dir = args.source_root / sample_id
    img_path = next(
        (src_dir / f"{sample_id}{s}" for s in IMAGE_SUFFIXES if (src_dir / f"{sample_id}{s}").exists()),
        None,
    )
    if img_path is None:
        raise SystemExit(f"No source image found for {sample_id} under {src_dir}")

    out_dir = args.output_root / sample_id
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Source: {img_path}  ({img_path.stat().st_size} bytes)")
    print(f"Output: {out_dir}")

    (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    upload = upload_image(api_key, img_path)
    print(f"Uploaded → download_url length={len(str(upload['download_url']))}")

    submit = submit_task(api_key, prompt, [str(upload["download_url"])])
    task_id = str(submit["taskId"])
    print(f"Submitted → taskId={task_id}")

    (out_dir / "upload_response.json").write_text(json.dumps(upload, ensure_ascii=False, indent=2))
    (out_dir / "submit_response.json").write_text(json.dumps(submit, ensure_ascii=False, indent=2))

    final = poll_task(api_key, task_id)
    results = final.get("results") or []
    if not results:
        raise SystemExit(f"Task {task_id} returned no result URLs.")

    ext = str(results[0].get("outputType") or "png").strip(".") or "png"
    out_path = out_dir / f"{sample_id}_front_view.{ext.lower()}"
    download_result(results[0], out_path)

    with Image.open(out_path) as img:
        w, h = img.size
    print(f"Done: {out_path.name}  {w}×{h}")

    result_summary = {
        "sample_id": sample_id,
        "task_id": task_id,
        "status": "completed",
        "output": str(out_path),
        "size": f"{w}x{h}",
    }
    (out_dir / "smoke_test_result.json").write_text(json.dumps(result_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
