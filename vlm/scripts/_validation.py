"""Validation helpers for identifiers, manifest paths, and provider URLs."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse


_INVALID_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
QWEN_HOSTS = {"dashscope.aliyuncs.com"}


def validate_path_component(value: str, label: str = "path component") -> str:
    """Return a safe single path component or raise ``ValueError``."""
    component = str(value).strip()
    if (
        not component
        or component in {".", ".."}
        or component.endswith((" ", "."))
        or _INVALID_COMPONENT.search(component)
        or component.split(".", 1)[0].upper() in _WINDOWS_RESERVED
    ):
        raise ValueError(f"Invalid {label}: {value!r}")
    return component


def resolve_manifest_path(root: Path, value: str, label: str) -> Path:
    """Resolve a relative manifest path and require it to remain below ``root``."""
    relative = Path(str(value).strip())
    if not str(relative) or relative.is_absolute():
        raise ValueError(f"{label} must be relative to {root}: {value!r}")
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"{label} escapes {root}: {value!r}")
    return candidate


def require_within(root: Path, candidate: Path, label: str) -> Path:
    """Resolve ``candidate`` and require it to be a strict child of ``root``."""
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    if candidate_resolved == root_resolved or root_resolved not in candidate_resolved.parents:
        raise ValueError(f"{label} must be below {root_resolved}: {candidate}")
    return candidate_resolved


def validate_qwen_base_url(value: str) -> str:
    """Allow credentials to be sent only to the official DashScope HTTPS API."""
    url = str(value).strip().rstrip("/")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() not in QWEN_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Qwen base URL must use the official DashScope HTTPS host")
    return url
