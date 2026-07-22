#!/usr/bin/env python3
"""Create a reproducible JSONL manifest for paired image/JSON generation jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return str(path.resolve())


def git_state(repo_root: Path) -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return commit, bool(status.strip())
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None, None


def parse_parameter(raw: str) -> tuple[str, Any]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("parameters must use KEY=VALUE")
    key, value = raw.split("=", 1)
    if not key:
        raise argparse.ArgumentTypeError("parameter key cannot be empty")
    try:
        parsed: Any = json.loads(value)
    except json.JSONDecodeError:
        parsed = value
    return key, parsed


def load_samples(data_root: Path) -> list[tuple[str, Path, Path]]:
    samples: list[tuple[str, Path, Path]] = []
    seen_ids: set[str] = set()
    for metadata_path in sorted(data_root.rglob("*.json")):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSON {metadata_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"JSON root must be an object: {metadata_path}")
        sample_id = payload.get("sample_id")
        source_image = payload.get("source_image")
        if not isinstance(sample_id, str) or not sample_id.strip():
            raise ValueError(f"missing sample_id: {metadata_path}")
        if sample_id in seen_ids:
            raise ValueError(f"duplicate sample_id {sample_id!r}")
        if not isinstance(source_image, str) or not source_image.strip():
            raise ValueError(f"missing source_image: {metadata_path}")
        image_path = Path(source_image)
        if not image_path.is_absolute():
            image_path = metadata_path.parent / image_path
        image_path = image_path.resolve()
        if not image_path.is_file():
            raise ValueError(f"missing source image for {sample_id}: {image_path}")
        seen_ids.add(sample_id)
        samples.append((sample_id, metadata_path.resolve(), image_path))
    if not samples:
        raise ValueError(f"no sample JSON files found under {data_root}")
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[0])
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id")
    parser.add_argument("--prompt-version")
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--force", action="store_true", help="Replace an existing manifest")
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    prompt_file = args.prompt_file.resolve()
    output = args.output.resolve()
    output_root = args.output_root.resolve()
    repo_root = args.repo_root.resolve()
    if not data_root.is_dir():
        parser.error(f"data root is not a directory: {data_root}")
    if not prompt_file.is_file():
        parser.error(f"prompt file does not exist: {prompt_file}")
    if output.exists() and not args.force:
        parser.error(f"manifest already exists; pass --force to replace it: {output}")
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("seeds must be unique")

    try:
        parameters = dict(parse_parameter(item) for item in args.param)
        samples = load_samples(data_root)
    except (ValueError, argparse.ArgumentTypeError) as exc:
        parser.error(str(exc))

    prompt_hash = sha256_file(prompt_file)
    created_at = datetime.now(timezone.utc).isoformat()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = args.run_id or f"{timestamp}-{prompt_hash[:8]}"
    prompt_version = args.prompt_version or prompt_file.stem
    code_commit, code_dirty = git_state(repo_root)

    rows = []
    for sample_id, metadata_path, image_path in samples:
        for seed in args.seeds:
            expected_output = output_root / run_id / sample_id / f"seed_{seed}.png"
            rows.append(
                {
                    "run_id": run_id,
                    "job_id": f"{run_id}:{sample_id}:seed-{seed}",
                    "sample_id": sample_id,
                    "source_image": portable(image_path, repo_root),
                    "metadata_json": portable(metadata_path, repo_root),
                    "source_sha256": sha256_file(image_path),
                    "metadata_sha256": sha256_file(metadata_path),
                    "provider": args.provider,
                    "model": args.model,
                    "prompt_file": portable(prompt_file, repo_root),
                    "prompt_sha256": prompt_hash,
                    "prompt_version": prompt_version,
                    "parameters": parameters,
                    "seed": seed,
                    "code_commit": code_commit,
                    "code_dirty": code_dirty,
                    "status": "pending",
                    "attempt": 0,
                    "output_image": portable(expected_output, repo_root),
                    "created_at": created_at,
                    "started_at": None,
                    "finished_at": None,
                    "latency_seconds": None,
                    "cost": None,
                    "provider_request_id": None,
                    "error": None,
                }
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"run_id": run_id, "jobs": len(rows), "manifest": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
