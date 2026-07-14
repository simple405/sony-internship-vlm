# VLM Supervision Project

## Project Overview
Anime IP merchandise supervision VLM pipeline. See `vlm/docs/workflows/process.md` for current status and next steps.

## Installed Skills

This project has the following engineering skills installed. **Always check if a skill applies before starting work.**

### Superpowers (methodology)
- `brainstorming` — use before writing code/prompts/rules. Refines ideas through questions.
- `writing-plans` — use after brainstorming. Breaks work into small tasks.
- `subagent-driven-development` — dispatches subagents per task with two-stage review.
- `test-driven-development` — RED-GREEN-REFACTOR for implementation.
- `requesting-code-review` — review between tasks.
- `verification-before-completion` — verify before declaring done.
- `using-git-worktrees` — isolated workspace for features.
- `systematic-debugging` — four-phase debugging methodology.

### GSD Core (project management)
- `/gsd-new-project` — initialize project with deep context gathering.
- `/gsd-plan-phase N` — plan a phase.
- `/gsd-execute-phase N` — execute a phase.
- `/gsd-progress` — check project progress.
- `/gsd-workspace` — manage isolated workspaces.

### Custom Commands
- `/atomic-commit` — split current changes into minimal atomic commits.
- `/handoff` — generate session handoff document before ending.

## Working Conventions
- Run commands from workspace root (`D:\索尼实习`).
- Use `vlm/tmp/` for scratch outputs, `vlm/data/` for durable datasets.
- Use `utf-8-sig` encoding for CSV files (Excel compatibility).
- API keys are in `vlm/config/api.env` — do NOT commit this file.
- See `vlm/docs/workflows/process.md` for the current RunningHub merchandise process.

## Qwen Image Understanding In Claude Code

Do not use the native `Read` tool on image files (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.bmp`, `.tif`, `.tiff`). The DashScope Anthropic-compatible endpoint rejects Claude Code's image `tool_result` message shape with `Unexpected item type in content`.

When image understanding is needed, call the project CLI instead and use its text/JSON output:

```powershell
.\.venv\Scripts\python.exe -m vlm.scripts.supervise.qwen_vl_image_tool `
  --model qwen-vl-max `
  --json `
  --prompt "请分析这张图中可见的角色/商品特征，输出用于监修的结构化 JSON。" `
  "path\to\image.png"
```

This keeps Claude Code's context text-only while still using Qwen VL for visual understanding.

## Claude Code DeepSeek Model Switching

Claude Code is configured in `C:\Users\ZhuanZ\.claude\settings.json` to use the DeepSeek Anthropic-compatible gateway:

- `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`
- `ANTHROPIC_AUTH_TOKEN` is synced from `vlm/config/api.env` (`DEEPSEEK_API_KEY`; quotes are stripped automatically)
- Default model: `deepseek-v4-pro[1m]`
- Subagent/fast model: `deepseek-v4-flash`

If the key in `vlm/config/api.env` changes, sync it again:

```powershell
.\vlm\scripts\dev\sync_claude_code_deepseek.ps1
```

Switch models for one launch:

```powershell
claude --model "deepseek-v4-pro[1m]"
claude --model deepseek-v4-pro
claude --model deepseek-v4-flash
```

Inside an interactive Claude Code session, use `/model` and select or type one of:

- `deepseek-v4-pro[1m]` — strongest/long-context DeepSeek option for complex code/reasoning
- `deepseek-v4-pro` — standard DeepSeek Pro option
- `deepseek-v4-flash` — fastest/cheapest option for short checks

Qwen models require switching the gateway back to DashScope first; this DeepSeek setup uses the real `DEEPSEEK_API_KEY`.
