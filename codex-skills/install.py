#!/usr/bin/env python3
"""Install this repository's VLM skill set with Codex's skill installer."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def default_skills_dir() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home.expanduser().resolve() / "skills"


def load_lock(path: Path) -> list[dict[str, str]]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("sources.lock.json must contain version 1")
    skills = payload.get("skills")
    if not isinstance(skills, list) or not skills:
        raise ValueError("sources.lock.json must contain a non-empty skills list")

    required = {"name", "repo", "ref", "path", "source"}
    result: list[dict[str, str]] = []
    names: set[str] = set()
    for index, item in enumerate(skills):
        if not isinstance(item, dict) or not required.issubset(item):
            raise ValueError(f"skills[{index}] is missing required fields")
        normalized = {key: item[key] for key in required}
        if not all(isinstance(value, str) and value for value in normalized.values()):
            raise ValueError(f"skills[{index}] fields must be non-empty strings")
        if normalized["name"] in names:
            raise ValueError(f"duplicate skill name: {normalized['name']}")
        names.add(normalized["name"])
        result.append(normalized)
    return result


def build_commands(
    skills: list[dict[str, str]], installer: Path, destination: Path
) -> tuple[list[str], list[list[str]]]:
    skipped: list[str] = []
    grouped: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for skill in skills:
        if (destination / skill["name"]).exists():
            skipped.append(skill["name"])
        else:
            grouped[(skill["repo"], skill["ref"])].append(skill)

    commands = []
    for (repo, ref), items in grouped.items():
        command = [
            sys.executable,
            str(installer),
            "--repo",
            repo,
            "--ref",
            ref,
            "--dest",
            str(destination),
            "--path",
        ]
        command.extend(item["path"] for item in items)
        commands.append(command)
    return skipped, commands


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=default_skills_dir(),
        help="Skills directory; defaults to $CODEX_HOME/skills or ~/.codex/skills",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without installing")
    args = parser.parse_args()

    lock_path = Path(__file__).with_name("sources.lock.json")
    destination = args.dest.expanduser().resolve()
    system_skills = default_skills_dir()
    installer = system_skills / ".system" / "skill-installer" / "scripts" / "install-skill-from-github.py"
    if not installer.is_file():
        parser.error(f"Codex skill installer not found: {installer}")

    try:
        skills = load_lock(lock_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    destination.mkdir(parents=True, exist_ok=True)
    skipped, commands = build_commands(skills, installer, destination)
    for name in skipped:
        print(f"skip existing: {name}")
    for command in commands:
        print("run:", subprocess.list2cmdline(command))
        if not args.dry_run:
            completed = subprocess.run(command, check=False)
            if completed.returncode != 0:
                return completed.returncode

    if args.dry_run:
        print("dry run complete")
    else:
        print("installation complete; start a new Codex session to load the skills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
