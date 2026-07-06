"""VLM client abstraction for supervision review.

Only the dry-run provider is implemented in v1. Real providers must be added
after model, budget, and image upload approval.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def run_vlm_json(
    *,
    prompt: str,
    image_paths: list[Path],
    expected_schema_name: str,
    output_path: Path,
    debug_dir: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    # Note 1: The v1 tool is intentionally dry-run only. Raising here is a hard
    # safety guard against accidentally uploading images to a real VLM provider
    # before model, budget, and data-sharing approval are recorded.
    if not dry_run:
        raise NotImplementedError("Only dry-run VLM calls are implemented. Pass --dry-run.")

    # Note 2: The debug directory mirrors how real providers should be wired:
    # keep raw provider responses separate from parsed JSON so failures can be
    # audited without losing the exact model output.
    debug_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Note 3: This payload is deliberately honest. It records prompts and image
    # paths as provenance, but it does not invent visual observations or findings.
    payload: dict[str, Any] = {
        "schema_version": f"{expected_schema_name}.dry_run.v1",
        "review_status": "dry_run_placeholder",
        "expected_schema_name": expected_schema_name,
        "image_paths": [str(path) for path in image_paths],
        "prompt_chars": len(prompt),
        "created_at": datetime.now().astimezone().isoformat(),
        "message_cn": "dry-run 占位输出；未调用真实 VLM，未进行视觉判断。",
    }

    raw_path = debug_dir / f"{expected_schema_name}_raw_response.json"
    # Note 4: In dry-run mode the raw and parsed payloads are the same. Real VLM
    # integrations should keep this two-file pattern even when parsing fails.
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
