# VLM Development Workspace

This directory contains the active development assets for the Anime IP supervision VLM pipeline.

Run commands from the workspace root (`D:\索尼实习`) so relative data paths such as `vlm/data/safebooru_2d/...` continue to resolve correctly.

## Structure

- `scripts/_paths.py` - centralized path constants (import from here, not hardcoded paths).
- `scripts/supervise/` - supervision review, annotation, and evaluation pipeline.
- `scripts/data/` - dataset assignment and maintenance scripts.
- `scripts/generate/` - RunningHub image-generation runners.
- `scripts/orchestrate/` - higher-level batch runners.
- `config/` - runtime configuration (schemas, sample configs, API keys).
- `config/supervision/` - review sample configs, v3 schema, category rules.
- `prompts/supervision/` - Qwen VL supervision prompt templates (per category).
- `prompts/generation/runninghub/` - RunningHub generation prompt templates.

## Data and Docs

- `data/` - datasets, generated outputs, and raw trials (gitignored).
- `data/safebooru_2d/japanese_anime_turnaround_pilot_20/generated/` - flattened per-category generated images.
- `data/safebooru_2d/japanese_anime_turnaround_pilot_20/multi_view试标数据集/` - multi-category review package.
- `experiments/` - experiment notes, manifests, and eval specs.
- `docs/` - workflow documentation, context summaries, source PDFs, and diagrams.
- `docs/supervision/` - annotation CSV schema definitions.
- `archive/` - historical artifacts including legacy ip_review_project (gitignored).
- `tmp/` - scratch outputs, auto-created at runtime (gitignored).

## Current Entry Points

- RunningHub process: `docs/workflows/process.md`
- Multi-category supervision review: `scripts/supervise/run_multicategory_supervision_review.py`
- Full RunningHub batch runner: `scripts/orchestrate/run_runninghub_merchandise_full_batch.py`
- Single/small batch RunningHub runner: `scripts/generate/generate_head_keychain_with_runninghub_g2.py`
- Category assignment: `scripts/data/assign_merchandise_categories.py`
- Qwen VL image CLI (for Claude Code): `scripts/supervise/qwen_vl_image_tool.py`
