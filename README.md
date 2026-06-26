# Sony Internship VLM Workspace

This workspace is organized as a VLM development workspace for Anime IP supervision.

## Active VLM Workspace

- `vlm/` - active VLM development assets.
  - `vlm/scripts/` - active Python scripts for crawling Safebooru data, extracting Qwen atomic rules, comparing trials, monitoring workers, and running QA.
  - `vlm/config/` - run contracts and batch defaults.
  - `vlm/prompts/` - active prompt templates and prompt notes.
  - `vlm/data/` - current datasets, generated atomic rules, reports, logs, and raw trial data.
  - `vlm/docs/` - workflow notes, context summaries, source PDFs, and diagrams.
  - `vlm/reference/` - archived prototype projects and their historical assets.
- `vlm/requirements.txt` - dependencies for the active scripts.

The main active workflow is documented in:

- `vlm/docs/workflows/atomic_rules_vlm_workflow.md`
- `vlm/docs/workflows/atomic_rules_vlm_context_summary_2026-06-24.md`

## Legacy Prototype

- `vlm/reference/ip_review_project/` - earlier prototype project for character-profile extraction, prompt generation, and annotation dataset construction.

Keep this project as a reference unless you are specifically working on the old GPT Vision / merchandise-prompt pipeline. Useful prompt ideas from that project should be adapted into `vlm/prompts/` before being used in the active workflow.

## Working Convention

- Run active commands from this workspace root so relative paths such as `vlm/data/safebooru_2d/...` resolve correctly.
- Do not move `vlm/` without updating script defaults and workflow docs.
- Put historical or experimental whole-project snapshots under `vlm/reference/`.
- Put temporary scratch outputs under `vlm/tmp/`.
