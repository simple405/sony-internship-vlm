# VLM Development Workspace

This directory contains the active development assets for the Anime IP supervision VLM pipeline.

Run commands from the workspace root (`D:\索尼实习`) so relative data paths such as `vlm/data/safebooru_2d/...` continue to resolve correctly.

## Structure

- `scripts/` - active pipeline scripts.
  - `crawl_safebooru.py` - collect 2D reference images and metadata.
  - `extract_atomic_rules_with_qwen.py` - extract atomic rules from 2D images with Qwen.
  - `atomic_rules_qwen_shared.py` - shared Qwen prompt, parsing, and normalization.
  - `qa_atomic_rules_batch.py` - offline QA harness for atomic rules.
  - `monitor_single_qwen_worker.py` - worker monitoring helper.
  - `compare_raw_trials_with_qwen.py` - compare Qwen outputs with raw trial data.
- `config/` - active run contracts and batch defaults.
- `prompts/` - active prompt templates and prompt notes.

## Data and Docs

- `data/` - datasets, generated JSON, logs, reports, and raw trials.
- `docs/` - workflow documentation, context summaries, source PDFs, and diagrams.
- `reference/` - older prototype projects retained for reference.
