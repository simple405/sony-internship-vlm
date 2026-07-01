# VLM Development Workspace

This directory contains the active development assets for the Anime IP supervision VLM pipeline.

Run commands from the workspace root (`D:\索尼实习`) so relative data paths such as `vlm/data/safebooru_2d/...` continue to resolve correctly.

## Structure

- `scripts/data/` - dataset assignment and maintenance scripts.
- `scripts/generate/` - RunningHub image-generation runners.
- `scripts/orchestrate/` - higher-level batch runners.
- `prompts/` - active RunningHub prompt templates and prompt notes.

## Data and Docs

- `data/` - datasets, generated JSON, logs, reports, and raw trials.
- `experiments/` - small experiment notes, manifests, and eval specs.
- `docs/` - workflow documentation, context summaries, source PDFs, and diagrams.
- `archive/` - local-only historical artifacts; ignored by git.
- `reference/` - older prototype projects retained for reference.

## Current Entry Points

- RunningHub process: `docs/workflows/process.md`
- Full RunningHub batch runner: `scripts/orchestrate/run_runninghub_merchandise_full_batch.py`
- Single/small batch RunningHub runner: `scripts/generate/generate_head_keychain_with_runninghub_g2.py`
- Category assignment: `scripts/data/assign_merchandise_categories.py`
