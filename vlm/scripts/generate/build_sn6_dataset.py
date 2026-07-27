"""Build SN_6期动漫数据标注 complete dataset with original 2D images, JSON, and 3D front views.

This script assembles a complete dataset for the SN_6期动漫数据标注 batch, combining:
1. Original 2D character images (char_*.png)
2. Description JSON files (char_*.json)
3. Generated 3D front-view PVC figurine images (char_*_front_view.png)

The script is idempotent: samples with existing front_view images are skipped during
generation, and the final assembly copies all three files to the output directory.

Output Structure:
    {output_root}/
        char_001/
            char_001.png              # Original 2D character image
            char_001.json             # Character description JSON
            char_001_front_view.png   # Generated 3D front-view figurine
        char_002/
            ...
        (20 total character folders)

Workflow:
    1. Load API credentials and frozen prompt
    2. For each char_* in source directory:
       a. Check if front_view already exists in intermediate output
       b. If missing, generate via RunningHub API (upload → submit → poll → download)
       c. Copy original 2D image to final output directory
       d. Copy description JSON to final output directory
       e. Copy generated front_view image to final output directory

Usage:
    python -m vlm.scripts.generate.build_sn6_dataset --output-dir "vlm/data/SN_6_3D_dataset"
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

from vlm.scripts._paths import (
    API_ENV_FILE,
    DATA_ROOT,
    GENERATION_PROMPTS_DIR,
    SN_6_ANNOTATION_ROOT,
)
from vlm.scripts.generate.runninghub_client import (
    IMAGE_SUFFIXES,
    download_result,
    load_api_env,
    poll_task,
    require_api_key,
    submit_task,
    upload_image,
)

# Frozen prompt file — same as batch_front_view.py
PROMPT_FILE = GENERATION_PROMPTS_DIR / "runninghub_g2_figurine_front_view_user_cn.txt"

# Intermediate generation output (RunningHub API responses + generated images)
INTERMEDIATE_ROOT = DATA_ROOT / "sn6_intermediate_gen"

# Conservative concurrency to avoid RunningHub rate limits
WORKERS = 4


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments with:
            - source_root (Path): Source directory with char_*/ folders
            - intermediate_root (Path): Intermediate generation output directory
            - output_root (Path): Final assembled dataset directory
    """
    parser = argparse.ArgumentParser(
        description="Build complete SN_6 dataset with 2D images, JSON, and 3D front views"
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=SN_6_ANNOTATION_ROOT,
        help="Source directory containing char_*/ folders (default: SN_6_ANNOTATION_ROOT)",
    )
    parser.add_argument(
        "--intermediate-root",
        type=Path,
        default=INTERMEDIATE_ROOT,
        help="Intermediate output for generation artifacts (default: vlm/data/sn6_intermediate_gen)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DATA_ROOT / "SN_6_3D_dataset",
        help="Final assembled dataset output directory (default: vlm/data/SN_6_3D_dataset)",
    )
    return parser.parse_args()


def has_intermediate_output(sample_id: str, intermediate_root: Path) -> bool:
    """Check if front_view image already exists in intermediate output.

    Args:
        sample_id: Character ID (e.g., "char_001")
        intermediate_root: Intermediate generation output directory

    Returns:
        bool: True if any {sample_id}_front_view.* file exists
    """
    inter_dir = intermediate_root / sample_id
    return any((inter_dir / f"{sample_id}_front_view{s}").exists() for s in IMAGE_SUFFIXES)


def generate_front_view(
    sample_id: str,
    source_root: Path,
    intermediate_root: Path,
    prompt: str,
    api_key: str,
) -> dict:
    """Generate 3D front-view image via RunningHub API (upload → submit → poll → download).

    Args:
        sample_id: Character ID (e.g., "char_001")
        source_root: Source directory containing char_*/ folders
        intermediate_root: Intermediate output directory
        prompt: Generation prompt text
        api_key: RunningHub API key

    Returns:
        dict: Result summary with status, task_id, elapsed_s, size (or error message)
    """
    src_dir = source_root / sample_id
    img_path = next(
        (src_dir / f"{sample_id}{s}" for s in IMAGE_SUFFIXES if (src_dir / f"{sample_id}{s}").exists()),
        None,
    )
    if img_path is None:
        return {"sample_id": sample_id, "status": "skipped", "reason": "no source image"}

    inter_dir = intermediate_root / sample_id
    inter_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    try:
        # Stage 1: Upload source image to RunningHub CDN
        upload = upload_image(api_key, img_path)

        # Stage 2: Submit generation task
        submit = submit_task(api_key, prompt, [str(upload["download_url"])])
        task_id = str(submit["taskId"])

        # Save API responses for debugging
        (inter_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        (inter_dir / "upload_response.json").write_text(json.dumps(upload, ensure_ascii=False, indent=2))
        (inter_dir / "submit_response.json").write_text(json.dumps(submit, ensure_ascii=False, indent=2))

        # Stage 3: Poll until completion
        final = poll_task(api_key, task_id)
        results = final.get("results") or []
        if not results:
            return {
                "sample_id": sample_id,
                "task_id": task_id,
                "status": "no_results",
                "elapsed_s": round(time.time() - t0, 1),
            }

        # Stage 4: Download generated image
        ext = str(results[0].get("outputType") or "png").strip(".") or "png"
        out_path = inter_dir / f"{sample_id}_front_view.{ext.lower()}"
        download_result(results[0], out_path)

        # Verify image and extract dimensions
        with Image.open(out_path) as img:
            w, h = img.size

        return {
            "sample_id": sample_id,
            "task_id": task_id,
            "status": "completed",
            "elapsed_s": round(time.time() - t0, 1),
            "size": f"{w}x{h}",
        }
    except Exception as exc:
        return {"sample_id": sample_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def assemble_final_output(sample_id: str, source_root: Path, intermediate_root: Path, output_root: Path) -> dict:
    """Copy original 2D image, JSON, and generated front_view to final output directory.

    Args:
        sample_id: Character ID (e.g., "char_001")
        source_root: Source directory with char_*/ folders
        intermediate_root: Intermediate generation output directory
        output_root: Final assembled dataset directory

    Returns:
        dict: Assembly result with status and copied files count
    """
    src_dir = source_root / sample_id
    inter_dir = intermediate_root / sample_id
    out_dir = output_root / sample_id
    out_dir.mkdir(parents=True, exist_ok=True)

    copied = 0

    # Copy original 2D image
    src_img = next(
        (src_dir / f"{sample_id}{s}" for s in IMAGE_SUFFIXES if (src_dir / f"{sample_id}{s}").exists()),
        None,
    )
    if src_img:
        shutil.copy2(src_img, out_dir / src_img.name)
        copied += 1

    # Copy description JSON
    src_json = src_dir / f"{sample_id}.json"
    if src_json.exists():
        shutil.copy2(src_json, out_dir / src_json.name)
        copied += 1

    # Copy generated front_view image
    front_view = next(
        (inter_dir / f"{sample_id}_front_view{s}" for s in IMAGE_SUFFIXES if (inter_dir / f"{sample_id}_front_view{s}").exists()),
        None,
    )
    if front_view:
        shutil.copy2(front_view, out_dir / front_view.name)
        copied += 1

    return {"sample_id": sample_id, "status": "assembled", "copied_files": copied}


def main() -> None:
    """Execute the complete dataset build workflow.

    Workflow:
        1. Load API credentials and prompt
        2. Enumerate all char_* samples
        3. Generate missing front_view images (concurrent, resume-safe)
        4. Assemble final output (copy 2D image + JSON + front_view for each sample)
        5. Write generation and assembly summaries
    """
    args = parse_args()

    # Load API credentials from vlm/config/api.env
    load_api_env(API_ENV_FILE)
    api_key = require_api_key()

    # Load frozen prompt (utf-8-sig for Excel compatibility)
    prompt = PROMPT_FILE.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise SystemExit(f"Prompt file is empty: {PROMPT_FILE}")

    # Enumerate all char_* sample IDs
    sample_ids = sorted(
        d.name for d in args.source_root.iterdir() if d.is_dir() and d.name.startswith("char_")
    )
    if not sample_ids:
        raise SystemExit(f"No char_* folders found under {args.source_root}")

    print(f"Found {len(sample_ids)} samples: {', '.join(sample_ids[:5])}{'...' if len(sample_ids) > 5 else ''}")

    # ═══════════════════════════════════════════════════════════════════
    # Phase 1: Generate missing front_view images via RunningHub API
    # ═══════════════════════════════════════════════════════════════════
    pending_gen = [sid for sid in sample_ids if not has_intermediate_output(sid, args.intermediate_root)]
    print(f"\nPhase 1: Generate front_view images")
    print(f"  Total: {len(sample_ids)}, Already generated: {len(sample_ids) - len(pending_gen)}, Pending: {len(pending_gen)}")

    gen_results: list[dict] = []
    if pending_gen:
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            future_map = {
                executor.submit(generate_front_view, sid, args.source_root, args.intermediate_root, prompt, api_key): sid
                for sid in pending_gen
            }
            for future in as_completed(future_map):
                sid = future_map[future]
                try:
                    r = future.result()
                except Exception as exc:
                    r = {"sample_id": sid, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                print(json.dumps(r, ensure_ascii=False), flush=True)
                gen_results.append(r)

    # ═══════════════════════════════════════════════════════════════════
    # Phase 2: Assemble final output (copy 2D + JSON + front_view)
    # ═══════════════════════════════════════════════════════════════════
    print(f"\nPhase 2: Assemble final dataset to {args.output_root}")
    assembly_results: list[dict] = []
    for sid in sample_ids:
        r = assemble_final_output(sid, args.source_root, args.intermediate_root, args.output_root)
        print(json.dumps(r, ensure_ascii=False), flush=True)
        assembly_results.append(r)

    # ═══════════════════════════════════════════════════════════════════
    # Write summaries
    # ═══════════════════════════════════════════════════════════════════
    gen_completed = sum(1 for r in gen_results if r.get("status") == "completed")
    gen_failed = sum(1 for r in gen_results if r.get("status") == "failed")
    assembly_completed = sum(1 for r in assembly_results if r.get("status") == "assembled")

    gen_summary = {
        "phase": "generation",
        "total": len(sample_ids),
        "skipped": len(sample_ids) - len(pending_gen),
        "pending": len(pending_gen),
        "completed": gen_completed,
        "failed": gen_failed,
        "results": gen_results,
    }
    (args.intermediate_root / "generation_summary.json").write_text(json.dumps(gen_summary, ensure_ascii=False, indent=2))

    assembly_summary = {
        "phase": "assembly",
        "total": len(sample_ids),
        "assembled": assembly_completed,
        "results": assembly_results,
    }
    (args.output_root / "assembly_summary.json").write_text(json.dumps(assembly_summary, ensure_ascii=False, indent=2))

    print(f"\n{'='*60}")
    print(f"Generation: {gen_completed}/{len(pending_gen)} completed, {gen_failed} failed")
    print(f"Assembly: {assembly_completed}/{len(sample_ids)} assembled")
    print(f"Output: {args.output_root}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
