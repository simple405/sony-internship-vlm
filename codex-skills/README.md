# Codex VLM Skills

This bundle makes the project's five VLM skills reproducible across Codex hosts.

## Included sources

- Custom skills stored in this repository:
  - `anime-ip-fidelity-eval`
  - `vlm-generation-experiment`
  - `vlm-dataset-audit`
- Official upstream skills pinned in `sources.lock.json`:
  - `huggingface-datasets` from `huggingface/skills`
  - `wandb-primary` from `wandb/skills`

The official skills are installed from their original repositories rather than copied here. This preserves attribution and keeps the source boundary clear.

## Install on another server

Install Codex first, clone this repository, and run:

```bash
cd sony-internship-vlm
python3 codex-skills/install.py
```

The destination is `$CODEX_HOME/skills` when `CODEX_HOME` is set, otherwise `~/.codex/skills`. Existing skill directories are skipped and never overwritten.

Preview the exact commands without installing:

```bash
python3 codex-skills/install.py --dry-run
```

Install into an isolated directory for verification:

```bash
python3 codex-skills/install.py --dest /tmp/codex-vlm-skills
```

Start a new Codex session after installation so the five skills are discovered. Installing `wandb-primary` does not upload data by itself; W&B operations still require explicit use, credentials, and authorization for the target project.

## Update policy

Edit custom skills in this directory, validate them with `quick_validate.py`, and then commit them. Update an upstream `ref` in `sources.lock.json` only after validating the new official version.
