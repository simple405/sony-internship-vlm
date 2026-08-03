# Sony Internship VLM Workspace

This repository is organized as a VLM development workspace for Anime IP merchandise supervision.

## Active Workspace

- `vlm/scripts/` - runnable pipeline code, grouped by role:
  - `data/` - dataset assignment and dataset maintenance helpers.
  - `generate/` - RunningHub image generation runners.
  - `orchestrate/` - batch runners that call lower-level scripts.
- `vlm/prompts/` - RunningHub prompt assets.
- `vlm/data/` - local datasets, generated rules, reports, logs, and model outputs.
- `vlm/experiments/` - lightweight experiment notes, frozen manifests, and small eval specs.
- `vlm/docs/` - workflow notes, source PDFs, and diagrams.
- `vlm/archive/` - local-only historical artifacts; ignored by git.
- `vlm/reference/` - older prototype projects retained for reference.

## Current Workflow

Use `vlm/docs/workflows/process.md` as the current RunningHub merchandise process. Qwen/Wan scripts and obsolete atomic-rules workflows have been removed from the active tracked workspace.

## Working Convention

- Run active commands from this workspace root so relative paths such as `vlm/data/safebooru_2d/...` resolve correctly.
- Keep durable datasets under `vlm/data/`; keep scratch or rerun logs under `vlm/tmp/`.
- Put experiment designs and small reproducible manifests in `vlm/experiments/`; keep large generated artifacts in ignored data/tmp paths.
- Put retired code or whole workflow snapshots under `vlm/archive/`.
