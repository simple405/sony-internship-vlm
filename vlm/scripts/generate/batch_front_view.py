"""Batch convert all 2D character images in SN_6期动漫数据标注 to front-view 3D PVC figurine renders.

This script drives the RunningHub ComfyUI workflow that takes a 2D anime character illustration
and synthesises a photorealistic front-view PVC figurine image.  It is designed to be run
repeatedly (idempotent): samples that already have a ``_front_view.*`` output file are silently
skipped so interrupted batches can be resumed without re-spending API quota.

Inputs
------
SOURCE_ROOT/
    char_XXXX/
        char_XXXX.<ext>   # source 2D illustration (any IMAGE_SUFFIXES format)

PROMPT_FILE               # plain-text RunningHub user prompt (UTF-8 BOM tolerated)

Outputs
-------
OUTPUT_ROOT/
    char_XXXX/
        char_XXXX_front_view.<ext>   # generated figurine render (extension from API response)
        prompt.txt                   # prompt snapshot for reproducibility
        upload_response.json         # raw RunningHub upload API response
        submit_response.json         # raw RunningHub task-submit API response
    batch_summary.json               # machine-readable run summary with per-sample outcomes

Usage
-----
Run from the workspace root::

    python -m vlm.scripts.generate.batch_front_view

Environment / secrets are loaded from ``vlm/config/api.env`` automatically.
"""

from __future__ import annotations

import argparse
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

# WORKERS=4 is intentionally conservative.  RunningHub's free/standard tier enforces
# per-account concurrent-task limits and rate limits on the upload/submit endpoints.
# Four threads keeps throughput high while staying well below those ceilings and
# avoiding 429 / "task queue full" errors that would require manual retry.
WORKERS = 4


def has_output(sample_id: str) -> bool:
    """Return True if a front-view output file already exists for *sample_id*.

    Resume / idempotency logic: before submitting a sample to the expensive RunningHub
    workflow, we check whether a previous run already produced a result.  The output
    filename convention is ``<sample_id>_front_view.<ext>`` where ``<ext>`` can be any
    format in IMAGE_SUFFIXES (jpg, png, webp, …).  We check every possible extension so
    the guard works regardless of which format the API returned last time.

    Parameters
    ----------
    sample_id:
        Folder/file stem for the sample, e.g. ``"char_0042"``.

    Returns
    -------
    bool
        ``True`` when at least one ``<sample_id>_front_view.*`` file exists in
        ``OUTPUT_ROOT/<sample_id>/``, ``False`` otherwise.
    """
    out_dir = OUTPUT_ROOT / sample_id
    # Check every recognised image extension so we don't re-run if the API previously
    # returned, say, .jpg when we now default to .png.
    return any((out_dir / f"{sample_id}_front_view{s}").exists() for s in IMAGE_SUFFIXES)


def process_one(sample_id: str, prompt: str, api_key: str) -> dict:
    """Run the full upload → submit → poll → download pipeline for a single sample.

    This function executes synchronously and is intended to be called from a worker
    thread inside a ``ThreadPoolExecutor``.  It follows the four-stage RunningHub flow:

    1. **Upload** – POST the source image to RunningHub's file-storage endpoint and
       receive a ``download_url`` that identifies the asset on their side.
    2. **Submit** – POST a task to the ComfyUI workflow, supplying the prompt text and
       the uploaded image URL.  RunningHub returns a ``taskId``.
    3. **Poll** – Repeatedly GET the task status until the workflow completes (or fails).
       ``poll_task`` handles the retry/backoff loop internally.
    4. **Download** – Fetch the first result file and save it locally.  Read the image
       with Pillow to record its pixel dimensions in the return dict.

    Intermediate API responses (upload, submit) are saved as JSON files in the output
    directory so runs can be audited and failures debugged without re-running.

    Parameters
    ----------
    sample_id:
        Folder/file stem, e.g. ``"char_0042"``.  Both the source directory
        ``SOURCE_ROOT/<sample_id>/`` and the output directory
        ``OUTPUT_ROOT/<sample_id>/`` are derived from this value.
    prompt:
        The RunningHub user-prompt string loaded from ``PROMPT_FILE``.
    api_key:
        RunningHub API key loaded from ``api.env``.

    Returns
    -------
    dict
        Always contains ``"sample_id"`` and ``"status"``.  Additional keys by status:

        * ``status="skipped"`` – ``"reason"`` (source image not found).
        * ``status="no_results"`` – ``"task_id"``, ``"elapsed_s"`` (workflow returned
          an empty results list; the task ran but produced no output file).
        * ``status="completed"`` – ``"task_id"``, ``"elapsed_s"``, ``"size"``
          (``"<width>x<height>"`` pixel dimensions of the downloaded image).
        * ``status="failed"`` – set by the ``main()`` caller when this function raises;
          includes ``"error"`` with the exception type and message.
    """
    src_dir = SOURCE_ROOT / sample_id

    # Find the source image by trying each recognised extension in order.  This handles
    # datasets where images may be .jpg, .png, or .webp without enforcing a single format.
    img_path = next(
        (src_dir / f"{sample_id}{s}" for s in IMAGE_SUFFIXES if (src_dir / f"{sample_id}{s}").exists()),
        None,
    )
    if img_path is None:
        return {"sample_id": sample_id, "status": "skipped", "reason": "no source image"}

    out_dir = OUTPUT_ROOT / sample_id
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Stage 1: upload the source image and retrieve the asset URL for the workflow.
    upload = upload_image(api_key, img_path)

    # Stage 2: submit the ComfyUI task, injecting the uploaded image URL into the prompt.
    submit = submit_task(api_key, prompt, [str(upload["download_url"])])
    task_id = str(submit["taskId"])

    # Persist intermediate API responses alongside the output so individual steps can be
    # debugged (e.g. wrong upload URL, malformed submit payload) without re-running.
    (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (out_dir / "upload_response.json").write_text(json.dumps(upload, ensure_ascii=False, indent=2))
    (out_dir / "submit_response.json").write_text(json.dumps(submit, ensure_ascii=False, indent=2))

    # Stage 3: block until the RunningHub workflow finishes (poll_task handles retries).
    final = poll_task(api_key, task_id)
    results = final.get("results") or []
    if not results:
        # Workflow completed but produced no output files – surface this as its own
        # status so the summary can distinguish "API error" from "empty generation".
        return {"sample_id": sample_id, "task_id": task_id, "status": "no_results",
                "elapsed_s": round(time.time() - t0, 1)}

    # Extension handling: the API returns an ``outputType`` field (e.g. "png", "jpg",
    # ".webp") that may include a leading dot or be absent entirely.  We normalise it:
    #   1. Cast to str and strip any leading "." to get a clean bare extension.
    #   2. Fall back to "png" if the field is missing or empty after stripping.
    # Note: we do NOT write a ".part" temporary file here; download_result writes
    # directly to the final path.  The extension logic purely determines the filename.
    ext = str(results[0].get("outputType") or "png").strip(".") or "png"
    out_path = out_dir / f"{sample_id}_front_view.{ext.lower()}"

    # Stage 4: download the first result file to the computed output path.
    download_result(results[0], out_path)

    # Open the downloaded image with Pillow to verify it is a valid image and to read
    # pixel dimensions for the summary record.  The context manager ensures the file
    # handle is released immediately after reading the size.
    with Image.open(out_path) as img:
        w, h = img.size

    return {"sample_id": sample_id, "task_id": task_id, "status": "completed",
            "elapsed_s": round(time.time() - t0, 1), "size": f"{w}x{h}"}


def main() -> None:
    """Orchestrate the batch front-view generation run.

    Responsibilities
    ----------------
    1. Load credentials and the prompt text.
    2. Enumerate all ``char_*`` sample directories under ``SOURCE_ROOT``.
    3. Filter out samples that already have output (idempotent resume).
    4. Dispatch pending samples concurrently via ``ThreadPoolExecutor``.
    5. Collect results as futures complete and print each one as a JSON line (suitable
       for log aggregation or ``tee``-ing to a file).
    6. Write ``batch_summary.json`` to ``OUTPUT_ROOT`` for post-run analysis.

    ThreadPoolExecutor / as_completed pattern
    -----------------------------------------
    All ``process_one`` calls are submitted up-front to the executor, building a
    ``future → sample_id`` mapping.  ``as_completed`` then yields each future in the
    order it *finishes* (not submission order), so results stream in as soon as they are
    ready rather than waiting for the slowest sample in each "wave".  Exceptions raised
    inside a worker are caught here and converted to ``{"status": "failed"}`` dicts so
    one bad sample does not abort the whole batch.

    Error handling
    --------------
    Any exception from ``process_one`` (network error, API error, Pillow decode error,
    etc.) is caught, serialised as ``{status: failed, error: "<ExcType>: <message>"}``
    and appended to ``batch_results``.  The batch continues for all remaining samples.
    """
    parser = argparse.ArgumentParser(description="Batch generate front-view images via RunningHub")
    parser.add_argument("--source-root", type=Path, help="Source directory containing char_* folders")
    parser.add_argument("--output-root", type=Path, help="Output directory for generated images")
    args = parser.parse_args()

    # Override defaults if CLI args provided
    global SOURCE_ROOT, OUTPUT_ROOT
    if args.source_root:
        SOURCE_ROOT = args.source_root
    if args.output_root:
        OUTPUT_ROOT = args.output_root

    load_api_env(API_ENV_FILE)
    api_key = require_api_key()

    # Read the prompt file with UTF-8 BOM support (utf-8-sig) because some editors on
    # Windows save plain-text files with a BOM that would otherwise appear as a stray
    # character at the start of the prompt string.
    prompt = PROMPT_FILE.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise SystemExit(f"Prompt file is empty: {PROMPT_FILE}")

    # Collect all char_* subdirectories and sort them for deterministic ordering across
    # runs (useful when comparing logs or resuming from a known point).
    sample_ids = sorted(d.name for d in SOURCE_ROOT.iterdir() if d.is_dir() and d.name.startswith("char_"))
    if not sample_ids:
        raise SystemExit(f"No char_* folders found under {SOURCE_ROOT}")

    # Resume detection: exclude any sample that already has a _front_view.* output file.
    # This makes re-running safe and cheap – only genuinely missing outputs are processed.
    pending = [sid for sid in sample_ids if not has_output(sid)]
    skipped = len(sample_ids) - len(pending)

    # Emit a structured start banner so callers / log aggregators can record batch metadata.
    print(json.dumps({
        "status": "batch_started", "total": len(sample_ids), "skipped": skipped,
        "pending": len(pending), "workers": WORKERS,
        "prompt_file": str(PROMPT_FILE), "source_root": str(SOURCE_ROOT), "output_root": str(OUTPUT_ROOT),
    }, ensure_ascii=False), flush=True)

    if not pending:
        print(json.dumps({"status": "all_done", "message": "All samples already have output."}, ensure_ascii=False))
        return

    batch_results: list[dict] = []

    # Submit all pending samples to the thread pool up-front, then drain results with
    # as_completed so each result is printed and recorded as soon as it arrives.
    # This is preferable to map() because map() buffers all results and raises on the
    # first exception, whereas as_completed lets us handle per-sample failures gracefully.
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        future_map = {executor.submit(process_one, sid, prompt, api_key): sid for sid in pending}
        for future in as_completed(future_map):
            sid = future_map[future]
            try:
                r = future.result()
            except Exception as exc:
                # Convert any unhandled exception to a structured failure record so the
                # batch can continue and the summary accurately reflects all outcomes.
                r = {"sample_id": sid, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            # Print each result immediately (flush=True) so progress is visible in real
            # time even when stdout is redirected to a file.
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

    # Write batch_summary.json so downstream tools (quality checks, monitoring dashboards,
    # the next pipeline stage) can read structured outcomes without parsing stdout logs.
    # The full per-sample ``results`` list is included for traceability; the console print
    # below omits it to keep terminal output concise.
    (OUTPUT_ROOT / "batch_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    # Print the aggregate totals without the verbose per-sample list.
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
