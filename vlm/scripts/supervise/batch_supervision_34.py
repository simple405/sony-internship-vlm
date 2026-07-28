"""Batch runner: run supervision agent for all 34 SN_6_3D_dataset samples.

Uses the local Ollama qwen36-vl model via OpenAI-compatible endpoint.
Runs samples sequentially to avoid overloading the GPU.

Usage:
    python -m vlm.scripts.supervise.batch_supervision_34
    python -m vlm.scripts.supervise.batch_supervision_34 --start 1 --end 10
    python -m vlm.scripts.supervise.batch_supervision_34 --sample-ids char_001,char_005,char_010
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_ROOT = Path("vlm/data/SN_6_3D_dataset")
OUTPUT_ROOT = Path("vlm/tmp/supervision_agent_output")
CATEGORY = "dataset_figurine"


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the batch runner.

    Returns:
        Parsed namespace with fields: start, end, sample_ids, timeout, skip_existing.
    """
    parser = argparse.ArgumentParser(
        description="Batch run supervision agent for SN_6_3D_dataset samples."
    )
    parser.add_argument("--start", type=int, default=1, help="Start index (1-based, default 1).")
    parser.add_argument("--end", type=int, default=34, help="End index inclusive (default 34).")
    parser.add_argument("--sample-ids", default="", help="Comma-separated sample IDs (overrides --start/--end).")
    parser.add_argument("--timeout", type=int, default=600, help="Per-sample timeout in seconds.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip samples that already have agent_summary.json.")
    return parser.parse_args()


def discover_samples(start: int = 1, end: int = 34, sample_ids: str = "") -> list[str]:
    """Discover and validate sample directories.

    Args:
        start: Start index (1-based).
        end: End index inclusive.
        sample_ids: Comma-separated sample IDs to override range.

    Returns:
        Sorted list of valid sample_id strings.
    """
    if sample_ids.strip():
        ids = [s.strip() for s in sample_ids.split(",") if s.strip()]
        # Validate each ID exists
        for sid in ids:
            sample_dir = DATA_ROOT / sid
            if not sample_dir.exists():
                print(f"WARNING: {sid} not found, skipping")
            source = sample_dir / f"{sid}.png"
            product = sample_dir / f"{sid}_front_view.png"
            if not source.exists() or not product.exists():
                print(f"WARNING: {sid} missing images, skipping")
        return ids

    samples = []
    for i in range(start, end + 1):
        sid = f"char_{i:03d}"
        sample_dir = DATA_ROOT / sid
        if not sample_dir.exists():
            continue
        source = sample_dir / f"{sid}.png"
        product = sample_dir / f"{sid}_front_view.png"
        if not source.exists() or not product.exists():
            print(f"WARNING: {sid} missing images, skipping")
            continue
        samples.append(sid)
    return samples


def run_one(sample_id: str, timeout: int, skip_existing: bool) -> dict[str, Any]:
    """Run supervision agent for one sample via subprocess.

    Args:
        sample_id: Sample identifier (e.g. char_001).
        timeout: Per-sample subprocess timeout in seconds.
        skip_existing: If True and agent_summary.json exists, skip this sample.

    Returns:
        Result dict with keys: sample_id, status, elapsed_seconds, error (if any).
    """
    output_dir = OUTPUT_ROOT / sample_id
    summary_path = output_dir / "agent_summary.json"

    if skip_existing and summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return {
            "sample_id": sample_id,
            "status": "skipped",
            "elapsed_seconds": 0,
            "summary": summary,
        }

    sample_dir = DATA_ROOT / sample_id
    source = sample_dir / f"{sample_id}.png"
    product = sample_dir / f"{sample_id}_front_view.png"

    cmd = [
        sys.executable, "-m", "vlm.scripts.supervise.run_supervision_agent",
        "--source", str(source),
        "--product", str(product),
        "--category", CATEGORY,
        "--sample-id", sample_id,
        "--timeout", str(timeout),
    ]

    started = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 120,  # Extra buffer for subprocess overhead
            cwd=Path(__file__).resolve().parents[3],
        )
        elapsed = time.time() - started

        if result.returncode == 0:
            return {
                "sample_id": sample_id,
                "status": "ok",
                "elapsed_seconds": round(elapsed, 1),
                "stdout": result.stdout.strip().split("\n")[-1] if result.stdout else "",
            }
        else:
            return {
                "sample_id": sample_id,
                "status": "error",
                "elapsed_seconds": round(elapsed, 1),
                "error": result.stderr.strip().split("\n")[-5:] if result.stderr else str(result.returncode),
            }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - started
        return {
            "sample_id": sample_id,
            "status": "timeout",
            "elapsed_seconds": round(elapsed, 1),
            "error": f"Timed out after {timeout}s",
        }


def write_json(path: Path, payload: Any) -> None:
    """Write payload as pretty-printed UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    """Batch run supervision agent for all discovered samples, then print summary."""
    args = parse_args()
    samples = discover_samples(args.start, args.end, args.sample_ids)

    if not samples:
        print("No valid samples found.")
        return

    print(f"Running supervision for {len(samples)} samples...")
    print(f"Model: qwen36-vl:latest (local Ollama)")
    print(f"Timeout per sample: {args.timeout}s")
    print(f"Skip existing: {args.skip_existing}")
    print(f"Started: {datetime.now().astimezone().isoformat()}")
    print("=" * 60)

    results = []
    ok_count = 0
    fail_count = 0
    skip_count = 0
    total_started = time.time()

    for i, sid in enumerate(samples, 1):
        print(f"\n[{i}/{len(samples)}] {sid} ... ", end="", flush=True)
        result = run_one(sid, args.timeout, args.skip_existing)
        results.append(result)

        if result["status"] == "ok":
            ok_count += 1
            print(f"OK ({result['elapsed_seconds']:.0f}s)")
        elif result["status"] == "skipped":
            skip_count += 1
            print("SKIPPED (exists)")
        else:
            fail_count += 1
            print(f"FAILED: {result.get('error', 'unknown')}")

    total_elapsed = time.time() - total_started

    # ── Summary ───────────────────────────────────────────────────────
    summary = {
        "batch": "SN_6_3D_dataset",
        "total_samples": len(samples),
        "ok": ok_count,
        "failed": fail_count,
        "skipped": skip_count,
        "total_elapsed_seconds": round(total_elapsed, 1),
        "started_at": total_started,
        "results": results,
    }
    write_json(OUTPUT_ROOT / "batch_summary.json", summary)

    print("\n" + "=" * 60)
    print(f"BATCH COMPLETE: {ok_count} ok, {fail_count} failed, {skip_count} skipped / {len(samples)} total")
    print(f"Total time: {total_elapsed/60:.1f} min")
    print(f"Summary: {OUTPUT_ROOT / 'batch_summary.json'}")

    # Print failed samples for easy retry
    if fail_count > 0:
        failed_ids = [r["sample_id"] for r in results if r["status"] not in ("ok", "skipped")]
        print(f"\nFailed samples: {', '.join(failed_ids)}")
        print(f"Retry with: --sample-ids {','.join(failed_ids)} --skip-existing")


if __name__ == "__main__":
    main()
