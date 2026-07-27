# Handoff: Project Debt Elimination + Documentation Infrastructure

**Created:** 2026-07-24
**Branch:** main (3 commits ahead of origin/main)
**Session Duration:** ~2-3 hours

---

## Summary

This session eliminated all technical debt in the VLM supervision project: fixed hardcoded paths, extracted duplicated RunningHub API code, added full English docstrings to all 23 Python files, and established automatic documentation enforcement via pre-commit hooks + CLAUDE.md standards. The working tree is clean; one manual activation step remains for the user.

---

## Work Completed

### Changes Made

- [x] Extracted `vlm/scripts/generate/runninghub_client.py` as shared API module (eliminated ~150 lines of duplication)
- [x] Fixed hardcoded Linux path in `review_local_comfyui_output.py` (`/home/intern/...` → `_paths.py`)
- [x] Fixed `parents[3]` → `_paths.py` bug in `batch_front_view.py` (was causing `RUNNINGHUB_API_KEY is not set`)
- [x] Added `SN_6_ANNOTATION_ROOT`, `SMOKE_TEST_ROOT`, `ELEMENT_EXTRACTION_ROOT` to `_paths.py`
- [x] Refactored `smoke_test_front_view.py` to load prompt from frozen file instead of hardcoded string
- [x] Added Google-style docstrings + inline comments to all 23 Python scripts (+6448 lines, commit `8551247`)
- [x] Created `.pre-commit-config.yaml` with pydocstyle + pre-commit-hooks + gitleaks
- [x] Added `/write-documented-code` skill at `.claude/commands/write-documented-code.md`
- [x] Added "Code Documentation Standards" section to `CLAUDE.md`
- [x] Updated `vlm/docs/workflows/process.md` (date, batch status, script list)

### Key Decisions

| Decision | Rationale | Alternatives Considered |
|---|---|---|
| Extract `runninghub_client.py` | DRY: two scripts had identical API code | Keep duplication, use inheritance |
| `_paths.py` for all path constants | Single source of truth, fixes cross-OS path bugs | `os.environ`, per-script relative paths |
| pydocstyle Google convention with D104/D105/D107 ignored | Matches existing project style; D104=package, D105=magic, D107=`__init__` rarely need docstrings | Numpy, PEP257 conventions |
| `no-commit-to-branch main` hook | Encourage feature branches for future work | Warn only, not block |

---

## Files Affected

### Created

- `vlm/scripts/generate/runninghub_client.py` — shared RunningHub API helpers (upload, submit, poll, download)
- `.pre-commit-config.yaml` — pydocstyle + file hygiene + gitleaks hooks
- `.claude/commands/write-documented-code.md` — reusable `/write-documented-code` skill

### Modified

- `vlm/scripts/_paths.py` — added `SN_6_ANNOTATION_ROOT`, `SMOKE_TEST_ROOT`, `ELEMENT_EXTRACTION_ROOT`
- `vlm/scripts/generate/batch_front_view.py` — refactored: import `runninghub_client`, use `_paths.py`, move `api_key` init into `main()`
- `vlm/scripts/generate/smoke_test_front_view.py` — load prompt from frozen file, import `runninghub_client` + `_paths.py`, add `--sample-id`/`--output-root` CLI args
- `vlm/scripts/supervise/review_local_comfyui_output.py` — fix hardcoded Linux path
- `vlm/docs/workflows/process.md` — date update, batch status, script list, Phase 4 plan reference
- `CLAUDE.md` — added "Code Documentation Standards" section
- 23 Python files — full Google-style docstrings added (commit `8551247`)

---

## Technical Context

### Architecture

- **`_paths.py` pattern**: all path constants live in `vlm/scripts/_paths.py`. New scripts MUST import from there, never compute `PROJECT_ROOT` inline.
- **`runninghub_client.py`**: the shared API layer for all RunningHub generate scripts. Any new generate script should import from it.
- **3-layer documentation enforcement**: CLAUDE.md rules (AI behavior) → `/write-documented-code` skill (per-task checklist) → pre-commit hooks (git gate).

### Configuration Changes

- `.pre-commit-config.yaml` created — hooks are defined but NOT yet activated
- `vlm/config/api.env` — never commit; excluded via `.gitignore`

---

## Things to Know

### Gotchas & Pitfalls

- **pre-commit hooks are NOT active yet** — the config file exists but `.venv/Scripts/pre-commit.exe install` has not been run. See "Immediate Next Steps".
- **`no-commit-to-branch main` hook**: once activated, direct commits to `main` will be blocked. User must work on feature branches or temporarily disable this hook.
- **DashScope image constraint**: never use Claude Code's native `Read` tool on image files (`.png`, `.jpg`, `.jpeg`, `.webp`, etc.) — DashScope rejects the `image tool_result` message shape with `Unexpected item type in content`. Use `qwen_vl_image_tool.py` instead.
- **`smoke_test_front_view.py` prompt source**: prompt is now loaded from `vlm/prompts/generation/runninghub/runninghub_g2_figurine_front_view_user_cn.txt`. Do not edit the script to change the prompt — edit the `.txt` file.

### Known Issues

- `char_008` is permanently blocked by RunningHub content moderation (errorCode 1501). 19/20 batch complete.
- 3 local commits not yet pushed to `origin/main`.

---

## Current State

### What's Working

- All 23 Python files: fully documented with Google-style docstrings
- `runninghub_client.py`: shared API module, tested via refactored scripts
- `_paths.py`: complete with all required path constants
- `batch_front_view.py` / `smoke_test_front_view.py`: refactored, paths fixed
- pre-commit config: defined and installed in `.venv` (pydocstyle + pre-commit-hooks + gitleaks)
- Working tree: clean

### What's Not Working / Pending

- pre-commit hooks: **not yet registered** (need `pre-commit install`)
- `char_008` RunningHub generation: permanently blocked by content moderation

---

## Next Steps

### Immediate (Start Here)

1. **Activate pre-commit hooks** (one-time, 30 seconds):
   ```powershell
   cd "D:\索尼实习"
   .venv\Scripts\pre-commit.exe install
   ```
   After this, every `git commit` will auto-check docstrings and scan for secrets.

2. **Push the 3 unpushed commits** when ready:
   ```powershell
   git push
   ```

3. **Test hooks** (optional, but recommended):
   ```powershell
   .venv\Scripts\pre-commit.exe run --all-files
   ```

### Subsequent

- Phase 1 of RunningHub post-processing plan: write `vlm/scripts/supervise/batch_review_runninghub.py` to Qwen-evaluate the 19 generated front-view images
- New element extraction batch (40-50 images, human annotation gold) — see `process.md` section 6b for exact commands
- Phase 4 (conditional, needs user approval): RunningHub vs IC-Light quality comparison

### Blocked On

- Nothing blocking immediate work
- `char_008` RunningHub content moderation: flag as permanently excluded unless Sony decides to provide alternative source image

---

## Related Resources

### Key Files

- [vlm/docs/workflows/process.md](vlm/docs/workflows/process.md) — current status, all phase plans
- [vlm/scripts/_paths.py](vlm/scripts/_paths.py) — all path constants
- [vlm/scripts/generate/runninghub_client.py](vlm/scripts/generate/runninghub_client.py) — shared API module
- [.pre-commit-config.yaml](.pre-commit-config.yaml) — hook definitions
- [.claude/commands/write-documented-code.md](.claude/commands/write-documented-code.md) — documentation skill

### Commits This Session

```
4b24fd7  chore: add code documentation standards and pre-commit enforcement
8551247  docs: add detailed English docstrings and inline comments to all scripts
d0e06b6  refactor: extract RunningHub client + fix paths + update docs
```

### Commands

```powershell
# Activate pre-commit hooks (do this first)
.venv\Scripts\pre-commit.exe install

# Run all hooks against existing files
.venv\Scripts\pre-commit.exe run --all-files

# Run Qwen VL on an image (never use Read tool on images)
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.qwen_vl_image_tool `
  --model qwen-vl-max --json `
  --prompt "请分析这张图中可见的角色/商品特征，输出用于监修的结构化 JSON。" `
  "path\to\image.png"

# RunningHub smoke test (single sample)
.\.venv\Scripts\python.exe -m vlm.scripts.generate.smoke_test_front_view --sample-id char_001

# RunningHub batch (resume-safe)
.\.venv\Scripts\python.exe -m vlm.scripts.generate.batch_front_view
```

---

## Open Questions

- [ ] Does the `no-commit-to-branch main` hook fit the team's workflow, or should it be removed from `.pre-commit-config.yaml`?
- [ ] Should the 3 local commits be pushed now or held until Phase 1 Qwen evaluation is complete?
- [ ] Is `char_008` permanently excluded, or will a replacement source image be provided?

---

_This handoff was generated at context window capacity. Start a new session and use this document as your initial context._
