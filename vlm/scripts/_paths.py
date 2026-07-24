"""Centralized path constants for the VLM supervision project.

All scripts should import from this module instead of hardcoding paths.
Usage:
    from vlm.scripts._paths import DATASET_ROOT, GENERATED_ROOT, API_ENV_FILE, load_api_env
"""

import os
from pathlib import Path
from typing import Optional


def load_api_env(path: Optional[Path] = None) -> None:
    """Load key=value pairs from api.env into os.environ (no overwrite).

    Args:
        path: Path to api.env. Defaults to API_ENV_FILE from this module.
    """
    env_path = path or API_ENV_FILE
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value

# Workspace root: D:\索尼实习
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# VLM package root
VLM_ROOT = PROJECT_ROOT / "vlm"

# Data directories
DATA_ROOT = VLM_ROOT / "data"
DATASET_ROOT = DATA_ROOT / "safebooru_2d" / "japanese_anime_turnaround_pilot_20"
GENERATED_ROOT = DATASET_ROOT / "generated"
ATOMIC_RULES_ROOT = DATASET_ROOT / "atomic_rules"
IMAGE_ROOT = DATASET_ROOT / "image"
MULTI_VIEW_ROOT = DATASET_ROOT / "multi_view试标数据集"
LEGACY_DATA_ROOT = DATA_ROOT / "legacy"
RAW_TRIALS_ROOT = DATA_ROOT / "raw_trials"

# Config
CONFIG_DIR = VLM_ROOT / "config"
API_ENV_FILE = CONFIG_DIR / "api.env"
SUPERVISION_CONFIG_DIR = CONFIG_DIR / "supervision"

# Prompts
PROMPTS_DIR = VLM_ROOT / "prompts"
SUPERVISION_PROMPTS_DIR = PROMPTS_DIR / "supervision"
GENERATION_PROMPTS_DIR = PROMPTS_DIR / "generation" / "runninghub"

# Output
TMP_DIR = VLM_ROOT / "tmp"
ARCHIVE_DIR = VLM_ROOT / "archive"

# Docs
DOCS_DIR = VLM_ROOT / "docs"
EXPERIMENTS_DIR = VLM_ROOT / "experiments"
