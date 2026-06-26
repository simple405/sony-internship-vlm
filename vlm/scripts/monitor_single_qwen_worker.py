"""Start one Qwen atomic-rules worker and monitor duplicate launches.

This wrapper intentionally does not change extraction behavior. It starts one
`extract_atomic_rules_with_qwen.py` child process, then periodically records all
Python processes that look like Qwen atomic-rules workers. The log is meant to
answer where duplicate workers came from: same terminal, a second terminal,
system Python vs .venv Python, or an old scheduler process.
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


DEFAULT_METADATA = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/metadata.jsonl")
DEFAULT_OUT_DIR = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/atomic_rules")
DEFAULT_LOG_DIR = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/logs")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one Qwen extraction worker and log duplicate Python workers."
    )
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--model", default="qwen3.5-plus")
    parser.add_argument("--start-offset", type=int, default=15)
    parser.add_argument("--limit", type=int, default=85)
    parser.add_argument("--image-source", choices=("url", "local"), default="url")
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--guidance-file", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--interval", type=float, default=15.0, help="Monitor interval in seconds.")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    return parser.parse_args()


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def file_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def extraction_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "scripts/extract_atomic_rules_with_qwen.py",
        "--metadata",
        str(args.metadata),
        "--out-dir",
        str(args.out_dir),
        "--model",
        args.model,
        "--offset",
        str(args.start_offset),
        "--limit",
        str(args.limit),
        "--image-source",
        args.image_source,
        "--sleep",
        str(args.sleep),
    ]
    if args.guidance_file:
        command.extend(["--guidance-file", str(args.guidance_file)])
    if args.overwrite:
        command.append("--overwrite")
    if args.stop_on_error:
        command.append("--stop-on-error")
    return command


def load_process_snapshot() -> list[dict[str, Any]]:
    powershell = (
        "Get-CimInstance Win32_Process "
        "| Select-Object ProcessId,ParentProcessId,CreationDate,Name,ExecutablePath,CommandLine "
        "| ConvertTo-Json -Depth 3"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", powershell],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    data = json.loads(result.stdout)
    if isinstance(data, dict):
        return [data]
    return data


def is_atomic_worker(process: dict[str, Any]) -> bool:
    name = str(process.get("Name") or "").lower()
    executable = str(process.get("ExecutablePath") or "").lower()
    if name != "python.exe" and not executable.endswith("\\python.exe"):
        return False
    command_line = str(process.get("CommandLine") or "")
    return "extract_atomic_rules_with_qwen.py" in command_line


def is_old_scheduler(process: dict[str, Any]) -> bool:
    name = str(process.get("Name") or "").lower()
    executable = str(process.get("ExecutablePath") or "").lower()
    if name != "python.exe" and not executable.endswith("\\python.exe"):
        return False
    command_line = str(process.get("CommandLine") or "")
    return "qwen_offset_worker.py" in command_line or "run_atomic_rules_qwen_two_workers.py" in command_line


def worker_key(process: dict[str, Any]) -> str:
    command = str(process.get("CommandLine") or "")
    script_name = "extract_atomic_rules_with_qwen.py"
    index = command.lower().find(script_name.lower())
    if index >= 0:
        command = command[index:]
    return " ".join(command.lower().replace('"', "").split())


def logical_worker_count(workers: list[dict[str, Any]]) -> int:
    """Count independent worker roots, not Windows venv launcher children.

    On Windows, `.venv\\Scripts\\python.exe` can appear as a launcher process
    that immediately starts the real base Python interpreter. Those two process
    rows share the same script/args and are parent-child, so they count as one
    logical Qwen worker.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for worker in workers:
        groups.setdefault(worker_key(worker), []).append(worker)

    total = 0
    for group in groups.values():
        pids = {int(item.get("ProcessId") or 0) for item in group}
        roots = [
            item
            for item in group
            if int(item.get("ParentProcessId") or 0) not in pids
        ]
        total += max(1, len(roots))
    return total


def worker_group_summary(workers: list[dict[str, Any]]) -> list[str]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for worker in workers:
        groups.setdefault(worker_key(worker), []).append(worker)

    summary: list[str] = []
    for key, group in groups.items():
        pids = sorted(int(item.get("ProcessId") or 0) for item in group)
        pid_set = set(pids)
        roots = sorted(
            int(item.get("ProcessId") or 0)
            for item in group
            if int(item.get("ParentProcessId") or 0) not in pid_set
        )
        summary.append(f"WORKER_GROUP roots={roots} pids={pids} key={key}")
    return summary


def process_line(process: dict[str, Any], process_by_pid: dict[int, dict[str, Any]]) -> str:
    pid = int(process.get("ProcessId") or 0)
    parent_pid = int(process.get("ParentProcessId") or 0)
    parent = process_by_pid.get(parent_pid, {})
    parent_name = str(parent.get("Name") or "")
    parent_command = str(parent.get("CommandLine") or "")
    command = str(process.get("CommandLine") or "")
    executable = str(process.get("ExecutablePath") or "")
    created = str(process.get("CreationDate") or "")
    return (
        f"PID={pid} PPID={parent_pid} CREATED={created}\n"
        f"  EXE={executable}\n"
        f"  CMD={command}\n"
        f"  PARENT={parent_name} {parent_command}\n"
    )


def append_log(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def monitor(child: subprocess.Popen[Any], monitor_log: Path, run_log: Path, interval: float) -> int:
    last_duplicate_signature = ""
    while True:
        snapshot = load_process_snapshot()
        process_by_pid = {int(item.get("ProcessId") or 0): item for item in snapshot}
        workers = [item for item in snapshot if is_atomic_worker(item)]
        old_schedulers = [item for item in snapshot if is_old_scheduler(item)]
        logical_count = logical_worker_count(workers)

        lines = [
            f"[{timestamp()}] child_pid={child.pid} child_status={child.poll()} "
            f"physical_atomic_process_count={len(workers)} "
            f"logical_worker_count={logical_count} old_scheduler_count={len(old_schedulers)}",
            f"run_log={run_log}",
        ]
        lines.extend(worker_group_summary(workers))
        for worker in workers:
            lines.append(process_line(worker, process_by_pid).rstrip())
        for scheduler in old_schedulers:
            lines.append("OLD_SCHEDULER " + process_line(scheduler, process_by_pid).rstrip())

        duplicate_signature = "|".join(worker_group_summary(workers))
        if logical_count > 1 and duplicate_signature != last_duplicate_signature:
            lines.append(
                "DUPLICATE_DETECTED: More than one logical "
                "extract_atomic_rules_with_qwen.py worker is active. Compare roots, "
                "PID/PPID/EXE/CMD above to identify which terminal or scheduler "
                "launched the later worker."
            )
            last_duplicate_signature = duplicate_signature

        append_log(monitor_log, "\n".join(lines) + "\n\n")

        status = child.poll()
        if status is not None:
            return int(status)
        time.sleep(max(1.0, interval))


if __name__ == "__main__":
    args = parse_args()
    args.log_dir.mkdir(parents=True, exist_ok=True)
    stamp = file_timestamp()
    monitor_log = args.log_dir / f"qwen_single_worker_monitor_{stamp}.log"
    run_log = args.log_dir / f"qwen_single_worker_run_{stamp}.log"
    command = extraction_command(args)

    append_log(monitor_log, f"[{timestamp()}] START\nCMD={' '.join(command)}\n")
    with run_log.open("w", encoding="utf-8") as run_handle:
        child = subprocess.Popen(command, stdout=run_handle, stderr=subprocess.STDOUT)
        exit_code = monitor(child, monitor_log, run_log, args.interval)

    append_log(monitor_log, f"[{timestamp()}] EXIT child_pid={child.pid} exit_code={exit_code}\n")
    print(f"Worker exit code: {exit_code}")
    print(f"Monitor log: {monitor_log}")
    print(f"Worker log: {run_log}")
    raise SystemExit(exit_code)
