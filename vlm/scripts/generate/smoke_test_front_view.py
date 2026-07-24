"""Smoke test: convert a single char_* image to front-view 3D PVC figurine via RunningHub.

This script provides a minimal end-to-end validation of the RunningHub API workflow
for generating front-view PVC figurine renderings from anime character reference images.
It processes a single sample (default: char_001) through the complete pipeline to verify
that API integration, prompt loading, and result processing are functioning correctly.

Purpose:
    - Verify RunningHub API connectivity and authentication
    - Test the upload→submit→poll→download workflow on a single sample
    - Validate prompt file loading and encoding (utf-8-sig for Excel compatibility)
    - Confirm output directory structure and file naming conventions
    - Generate a result summary JSON for downstream validation

Workflow:
    1. Load the frozen prompt file (same prompt used in batch processing)
    2. Locate the source character image (char_*.png/jpg/jpeg/webp/gif)
    3. Upload the image to RunningHub's CDN
    4. Submit a generation task with the prompt and uploaded image URL
    5. Poll the task until completion
    6. Download the generated front-view figurine image
    7. Save metadata (upload/submit responses, result summary)

Output Structure:
    {output_root}/{sample_id}/
        ├── prompt.txt                  # Copy of the generation prompt
        ├── upload_response.json        # Raw upload API response
        ├── submit_response.json        # Raw submit API response
        ├── {sample_id}_front_view.png  # Generated figurine image
        └── smoke_test_result.json      # Test result summary with status/size

This smoke test is used for:
    - Quick validation after prompt changes
    - Verifying API credentials before batch runs
    - Debugging generation issues on a single sample
    - Documentation and onboarding (shows complete workflow in ~90 lines)
"""

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

# Frozen prompt file path — shared with batch generation script to ensure consistency.
# Using the same prompt file guarantees smoke test results match batch behavior.
PROMPT_FILE = GENERATION_PROMPTS_DIR / "runninghub_g2_figurine_front_view_user_cn.txt"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the smoke test.

    Returns:
        argparse.Namespace: Parsed arguments with:
            - sample_id (str): Character sample ID (e.g., "char_001")
            - source_root (Path): Root directory containing character subdirectories
            - output_root (Path): Root directory for test outputs
    """
    parser = argparse.ArgumentParser(description="Smoke-test RunningHub front-view figurine generation on one sample.")
    parser.add_argument("--sample-id", default="char_001", help="Sample ID to process (default: char_001)")
    parser.add_argument("--source-root", type=Path, default=SN_6_ANNOTATION_ROOT)
    parser.add_argument("--output-root", type=Path, default=SMOKE_TEST_ROOT)
    return parser.parse_args()


def main() -> None:
    """Execute the smoke test workflow.

    This function orchestrates the complete RunningHub generation pipeline:
    1. Load API credentials and generation prompt
    2. Locate the source character image
    3. Upload → Submit → Poll → Download (the core API workflow)
    4. Save all intermediate responses and final result summary

    The workflow mirrors the batch processing script but operates on a single sample
    for rapid iteration and debugging.

    Raises:
        SystemExit: If prompt file is empty, source image not found, or task returns no results.
    """
    args = parse_args()

    # Load API credentials from vlm/config/api.env (not committed to git)
    load_api_env(API_ENV_FILE)
    api_key = require_api_key()

    # Load the frozen prompt file with utf-8-sig encoding (strips BOM, Excel-compatible)
    # This prompt is shared with the batch script to ensure smoke test results match production
    prompt = PROMPT_FILE.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise SystemExit(f"Prompt file is empty: {PROMPT_FILE}")

    # Locate the source character image
    # The image filename follows the pattern: {sample_id}{extension}
    # e.g., char_001.png, char_002.jpg
    sample_id = args.sample_id
    src_dir = args.source_root / sample_id
    img_path = next(
        (src_dir / f"{sample_id}{s}" for s in IMAGE_SUFFIXES if (src_dir / f"{sample_id}{s}").exists()),
        None,
    )
    if img_path is None:
        raise SystemExit(f"No source image found for {sample_id} under {src_dir}")

    # Create output directory: {output_root}/{sample_id}/
    out_dir = args.output_root / sample_id
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Source: {img_path}  ({img_path.stat().st_size} bytes)")
    print(f"Output: {out_dir}")

    # Save a copy of the prompt used for this test (for reproducibility)
    (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    # ═══════════════════════════════════════════════════════════════════
    # RunningHub API Workflow: Upload → Submit → Poll → Download
    # ═══════════════════════════════════════════════════════════════════

    # Step 1: Upload the source image to RunningHub's CDN
    # Returns: {"download_url": "https://...", ...}
    upload = upload_image(api_key, img_path)
    print(f"Uploaded → download_url length={len(str(upload['download_url']))}")

    # Step 2: Submit a generation task with the prompt and uploaded image URL
    # Returns: {"taskId": "...", "status": "pending", ...}
    submit = submit_task(api_key, prompt, [str(upload["download_url"])])
    task_id = str(submit["taskId"])
    print(f"Submitted → taskId={task_id}")

    # Save raw API responses for debugging and auditing
    (out_dir / "upload_response.json").write_text(json.dumps(upload, ensure_ascii=False, indent=2))
    (out_dir / "submit_response.json").write_text(json.dumps(submit, ensure_ascii=False, indent=2))

    # Step 3: Poll the task until completion (with exponential backoff in poll_task)
    # Returns: {"taskId": "...", "status": "completed", "results": [{"url": "...", "outputType": "png"}]}
    final = poll_task(api_key, task_id)
    results = final.get("results") or []
    if not results:
        raise SystemExit(f"Task {task_id} returned no result URLs.")

    # Step 4: Download the generated figurine image
    # Output filename convention: {sample_id}_front_view.{ext}
    # e.g., char_001_front_view.png
    # The extension is derived from the API's outputType field (default: png)
    ext = str(results[0].get("outputType") or "png").strip(".") or "png"
    out_path = out_dir / f"{sample_id}_front_view.{ext.lower()}"
    download_result(results[0], out_path)

    # Verify the downloaded image and extract dimensions
    with Image.open(out_path) as img:
        w, h = img.size
    print(f"Done: {out_path.name}  {w}×{h}")

    # Generate result summary JSON for downstream validation and reporting
    # This JSON provides a standardized interface for checking smoke test success
    # Fields:
    #   - sample_id: Input character ID
    #   - task_id: RunningHub task ID (for API audit trail)
    #   - status: "completed" (indicates successful end-to-end execution)
    #   - output: Absolute path to the generated image
    #   - size: Image dimensions in "WxH" format
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
