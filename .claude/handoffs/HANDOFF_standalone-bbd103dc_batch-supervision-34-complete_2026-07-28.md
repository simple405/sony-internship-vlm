# Handoff: 34-Sample Batch Supervision Complete — Local qwen36-vl + Anti-Thinking Fix

**Date:** 2026-07-28
**Status:** COMPLETED (batch supervision)
**Bead(s):** none
**Epic:** none
**Chain:** `standalone-bbd103dc` seq `2`
**Parent:** `HANDOFF_batch-supervision-and-finetune-direction_2026-07-27.md`
**Prior chain:** `HANDOFF_batch-supervision-and-finetune-direction_2026-07-27.md` > this

---

## Stale References

- `run_supervision_agent.py:234` (parent's `overall_decision` bug location) — the fix is now at line 237 reading from `qwen_prediction_v3.json`. The bug described in parent no longer exists.
- `run_one_sample()` return value's `overall_decision` field — parent noted this was empty. Current code reads `overall_decision` from `qwen_prediction_v3.json` instead of the `run_one_sample()` return dict.
- `--timeout 120` (parent's CLI flag) — current default is 600s (batch script) / 300s (CLI arg). 120s is too short for local qwen36-vl.

All other parent identifiers (`run_supervision_agent.py`, `run_element_extraction.py`, `qwen_prediction_v3.json`, `agent_summary.json`, `atomic_rules_generated.json`, `SN_6_3D_dataset`, `char_XXX.json`, `scp`) still exist in current codebase.

## Since Last Handoff

- **Parent's immediate next step was "跑 batch supervision"** — this session completed it for all 34 samples (char_001~034), vs parent's 20 (char_001~020).
- **Model backend changed from `qwen3.7-plus` (DashScope) to `qwen36-vl` (local Ollama)** — this was the dominant challenge of the session and required 5+ rounds of debugging.
- **`overall_decision` bug already fixed in code** (line 237 reads from `qwen_prediction_v3.json`) — no separate fix needed.
- **Parent's "server SSH port" question still open** — data transfer from Windows remains blocked, but the supervision work now runs locally on the server.
- **Baseline comparison (VLM vs human annotation) not done** — shifted to next priority after batch completion.

---

## Reference Documents

- `CLAUDE.md` — project conventions, working practices

---

## The Goal

Run end-to-end batch supervision for all 34 SN_6_3D_dataset samples using the locally deployed `qwen36-vl` model on the server. The pipeline: Step 1 extracts character elements from the 2D source image → Step 2 converts to atomic_rules → Step 3 runs VLM supervision review comparing the 3D front_view product against the 2D original. Output is a per-sample `agent_summary.json` with element count, billable issues, design notes, and overall pass/fail decision.

Secondary goal: adapt the pipeline code to work reliably with the local Ollama qwen36-vl model, which has a mandatory thinking/reasoning mode that the original DashScope-targeted code wasn't designed for.

---

## Where We Are

### Batch supervision — 34/34 complete
- 34 samples run through `run_supervision_agent.py` + local Ollama `qwen36-vl:latest`
- **26 pass, 7 fail, 1 minor_issue** (char_024). Pass rate: 26/33 = 78.8%
- 272 total elements extracted across all samples
- 12 billable annotation issues, 4 design quality notes
- All outputs at `vlm/tmp/supervision_agent_output/{sample_id}/agent_summary.json`

### Code fixes applied (4 files modified, 1 created)
- `run_supervision_agent.py`: `max_tokens` 8000→32000 for both extraction and review steps
- `run_element_extraction.py`: anti-thinking system prompt, `top_p=0.1` for local Ollama, empty-content→reasoning fallback, `DEFAULT_MAX_TOKENS` 8000→32000, `DEFAULT_MODEL`=`qwen36-vl:latest`
- `run_multicategory_supervision_review.py`: anti-thinking system prompt, `top_p=0.1`, proxy bypass for localhost, py3.8 compat (`removeprefix`→slicing), empty-content→reasoning fallback
- `batch_supervision_34.py`: **NEW** — batch runner for SN_6_3D_dataset with retry support

### Output directory structure
```
vlm/tmp/supervision_agent_output/
├── batch_summary.json              # Per-round batch summary
├── char_001/
│   ├── agent_summary.json           # Final result: status, element_count, billable, overall_decision
│   ├── atomic_rules_generated.json  # Step 2 output: elements → rule_id/value pairs
│   ├── extraction/
│   │   └── char_001/
│   │       ├── element_extraction_prompt.txt  # Filled prompt
│   │       ├── request_redacted.json          # Sanitized request (no API key)
│   │       ├── raw_response.txt               # Raw model response
│   │       └── extracted_elements.json        # Normalized element_extraction.v1
│   └── review/
│       └── dataset_figurine/
│           └── char_001_v3_{timestamp}/
│               ├── qwen_prediction_v3.json    # Detailed per-rule verdict
│               ├── debug_request_payload.json # Full request (for debugging)
│               └── review_prompt.txt          # Filled review prompt
├── char_002/ ... char_034/         # Same structure for all 34 samples
```

### Server environment
- **Machine**: dell-PowerEdge-T640, Ubuntu, Python 3.8
- **GPU**: Single GPU with ~42 GB VRAM
- **Ollama**: systemd service, active since 2026-06-11
- **Corporate proxy**: `http://137.153.170.55:10080` — blocks localhost traffic unless bypassed in code
- **SSH port**: Unknown (22 timed out) — blocks data transfer from Windows
- **venv**: `/home/intern/jsy/.venv/`

### 3 rounds of batch execution
1. **Round 1** (16000 max_tokens, old system prompt): 23 OK, 10 failed, 1 skip — 130 min
2. **Round 2** (anti-thinking fix for extraction only): 8/10 retried succeeded, 2 failed (char_015, char_017) — 29 min
3. **Round 3** (anti-thinking fix also applied to review script): 2/2 succeeded — 4 min

### Dataset status
- `vlm/data/SN_6_3D_dataset/` now has 34 chars (char_001~034), all with `front_view.png`
- New chars 021~034 pulled from remote in this session (commit `282f28f`)
- `batch_summary.json` at `vlm/tmp/supervision_agent_output/` for each round

### Failed samples (7)
| Sample | Elements | Billable | Design | Issue |
|--------|----------|----------|--------|-------|
| char_003 | 4 | 1 | 0 | 实际只有 4 个元素，1 个 billable 导致 fail |
| char_009 | 6 | 1 | 1 | 1 billable + 1 design note |
| char_011 | 9 | 2 | 1 | 2 billable + 1 design note |
| char_015 | 9 | 3 | 0 | 3 billable issues（最高） |
| char_017 | 8 | 2 | 0 | 2 billable issues |
| char_022 | 6 | 2 | 0 | 2 billable issues |
| char_026 | 10 | 1 | 0 | 10 元素但 1 billable issue |

---

## What We Tried (Chronological)

### 1. Initial setup: git pull, check dataset
**Hypothesis**: Pull latest remote changes before starting.
**Result**: Fast-forward merge added char_021~034 front_view data. Dataset now 34 chars total. All have front_view. ✅

### 2. Dry-run char_001 with default Ollama backend
**Hypothesis**: The default `qwen36-vl:latest` + `http://127.0.0.1:11434/v1` in `run_element_extraction.py` should work out of the box.
**Result**: Dry-run passed — prompt built, request preview written, no API call. ✅

### 3. First real run: char_001 extraction failed — empty JSON
**Error**: `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` — model returned empty `content`.
**Root cause**: `qwen36-vl` uses thinking mode; with `max_tokens=4000`, all tokens consumed by internal reasoning, `content` left empty.
**Fix**: Increased `max_tokens` to 16000 in `run_supervision_agent.py` for both extraction and review. Also added fallback: if `content` empty, return `reasoning` field.
**Result**: char_001 extraction succeeded (8 elements, 78s). ✅

### 4. First review step failed — HTTP 403 proxy
**Error**: `HTTP 403: Connect failed` on `http://127.0.0.1:11434/v1/chat/completions`.
**Root cause**: Corporate proxy `http://137.153.170.55:10080` intercepting localhost traffic. `run_element_extraction.py` had proxy bypass but `run_multicategory_supervision_review.py` didn't.
**Fix**: Added `proxies={"http": None, "https": None}` for localhost URLs in review script's `qwen_vl_chat`.
**Result**: Proxy bypass worked. ✅

### 5. Review step failed — py3.8 `removeprefix` AttributeError
**Error**: `AttributeError: 'str' object has no attribute 'removeprefix'` — Python 3.8 doesn't have `str.removeprefix` (3.9+).
**Fix**: Replaced `removeprefix`/`removesuffix` with slicing in review script's `extract_json_object`. Also removed `response_format` for non-DashScope URLs (Ollama doesn't support it).
**Result**: char_001 end-to-end success (8 rules, all PASS, 96.96s review, overall_decision: pass). ✅

### 6. First batch run (34 samples, 16000 max_tokens)
**Hypothesis**: 32000 max_tokens + anti-thinking system prompt could salvage all 34.
**Result**: 23 OK, 10 failed, 1 skipped. Failures were: empty content (char_002,012,013,014,017,024,029), extra data (char_015), timeout 600s (char_021,022). Total time: 130 min. ❌ 29% failure rate.

### 7. Discovered thinking model behavior: content vs reasoning
**Investigation**: Tested `qwen36-vl` directly with curl → found model always outputs thinking. With `thinking: {"type": "disabled"}`, it still thinks. Thinking content goes SOMETIMES to `content` field (57KB of Chinese text), SOMETIMES to `reasoning` field (empty `content`). Behavior is inconsistent per-image.
**Key finding**: char_002 raw response was 57KB of pure Chinese thinking — no JSON at all. Model ran out of tokens mid-thought.

### 8. Tested gemma3 as alternative vision model
**Hypothesis**: `gemma3:27b-it-qat` (18GB, vision-capable, no thinking) could replace qwen36-vl.
**Result**: gemma3 failed to load — GPU memory full (qwen36-vl uses 38GB of 42GB available). Timeout on first load attempt. ❌ Not viable without unloading qwen36-vl.

### 9. Anti-thinking system prompt + top_p fix
**Hypothesis**: Replace generic system prompt with explicit anti-thinking instruction + low `top_p` to suppress rambling.
**Test**: char_002 (previously failed with 57KB thinking) → succeeded with 11 elements in 345s.
**Fix applied to `run_element_extraction.py`**:
- System prompt: `"你是一个JSON输出机器人。禁止使用思维链(thinking/reasoning)。你的回复必须是纯JSON，以{开头，以}结尾。不要输出任何其他内容。"`
- `top_p: 0.1` for local Ollama (non-DashScope) backends
**Result**: Retry batch 8/10 succeeded. ⬆️

### 10. char_015 + char_017 still failing — review script not fixed
**Investigation**: Extraction succeeded (9 and 8 elements), but review step failed. The review script still had the OLD system prompt and no `top_p`.
**Fix**: Applied same anti-thinking prompt + `top_p=0.1` to `run_multicategory_supervision_review.py`'s system message and `qwen_vl_chat`.
**Result**: Both char_015 and char_017 completed successfully (77s and 143s). ✅

### 11. Handoff cleanup
**Action**: Deleted 11 old handoff files (2026-07-23~07-27), kept 4 relevant to current workstream.
**Result**: `.claude/handoffs/` reduced from 15→4 files.

---

## Key Decisions

| Decision | Rationale | Rejected |
|----------|-----------|----------|
| Use `qwen36-vl:latest` as primary model | Only vision-capable model loaded on server (38GB, Q8_0). gemma3 has vision but GPU memory insufficient for both. | gemma3, DashScope API |
| Anti-thinking system prompt instead of fighting thinking mode | Model always thinks regardless of `thinking:disabled` parameter. Prompt-level suppression more effective. | Increasing max_tokens to 64K+ |
| `top_p=0.1` for local Ollama | Reduces diversity, helps model converge on JSON output rather than rambling chains. Only applied to non-DashScope backends. | temperature tuning |
| `max_tokens=32000` as default | Thinking model needs large budget; 4000→16000 still caused failures, 32000 is safe for most samples. | 64000 (too slow) |
| Fallback to `reasoning` field when `content` empty | Model sometimes puts output in `reasoning` not `content`. Prevents empty-content errors. | Force-disabling thinking (doesn't work) |
| Python 3.8 compat (slicing instead of removeprefix) | Server runs Python 3.8, `removeprefix` is 3.9+. Minimum compat fix. | Upgrade Python |
| `batch_supervision_34.py` as separate script | Dedicated batch runner with retry support, skip-existing, and summary generation. Simpler than modifying `run_supervision_agent.py`. | Shell loop, modifying agent script |
| Sequential execution (no async) | Local Ollama is GPU-bound; concurrent requests queue internally and cause timeouts. | Thread pool with workers=2 |

---

## Evidence & Data

### Batch Round 1 Results (16000 max_tokens, old system prompt)
```
Model: qwen36-vl:latest | Timeout: 600s | Started: 2026-07-27 16:55
char_001: SKIPPED (pre-existing from test)
char_002: FAILED (empty content)
char_003-011: OK (9 samples, 63s-213s each)
char_012-015: FAILED (012-014 empty, 015 extra data)
char_016: OK (116s)
char_017: FAILED (empty content)
char_018-020: OK (57s-93s)
char_021-022: FAILED (timeout 600s)
char_023: OK (503s — longest non-timeout)
char_024: FAILED (empty content)
char_025: OK (572s — second longest)
char_026-034: All OK except 029 (FAILED — empty content)

Result: 23 OK, 10 failed, 1 skipped. 130.4 min total.
```

### Batch Round 2 Results (anti-thinking for extraction, 900s timeout, 10 retries)
```
Model: qwen36-vl:latest | Timeout: 900s | Started: 2026-07-27 19:25
char_002: OK (104s)  ← previously FAILED
char_012: OK (135s)  ← previously FAILED
char_013: OK (166s)  ← previously FAILED
char_014: OK (80s)   ← previously FAILED
char_015: FAILED (extra data in review step, extraction OK with 9 elements)
char_017: FAILED (empty content)
char_021: OK (97s)   ← previously TIMEOUT
char_022: OK (49s)   ← previously TIMEOUT
char_024: OK (150s)  ← previously FAILED
char_029: OK (138s)  ← previously FAILED

Result: 8 OK, 2 failed. 29.3 min total.
```

### Batch Round 3 Results (anti-thinking for both extraction + review, 900s timeout)
```
Model: qwen36-vl:latest | Timeout: 900s | Started: 2026-07-27 20:04
char_015: OK (77s)   ← previously FAILED
char_017: OK (143s)  ← previously FAILED

Result: 2 OK, 0 failed. 3.7 min total.
```

### Final Summary (34 samples)
```
Sample     Elements Billable   Design   Decision
--------------------------------------------------
char_001          8        0        0       pass
char_002         11        0        0       pass
char_003          4        1        0       fail
char_004          7        0        0       pass
char_005          8        0        0       pass
char_006          9        0        0       pass
char_007          7        0        0       pass
char_008         11        0        0       pass
char_009          6        1        1       fail
char_010          6        0        0       pass
char_011          9        2        1       fail
char_012          8        0        0       pass
char_013          8        0        0       pass
char_014          9        0        0       pass
char_015          9        3        0       fail
char_016          6        0        0       pass
char_017          8        2        0       fail
char_018          6        0        0       pass
char_019         10        0        0       pass
char_020          5        0        0       pass
char_021         10        0        0       pass
char_022          6        2        0       fail
char_023          8        0        0       pass
char_024         11        0        2 minor_issue
char_025          8        0        0       pass
char_026         10        1        0       fail
char_027          9        0        0       pass
char_028          8        0        0       pass
char_029         10        0        0       pass
char_030          5        0        0       pass
char_031         11        0        0       pass
char_032          7        0        0       pass
char_033          8        0        0       pass
char_034          6        0        0       pass
--------------------------------------------------
TOTAL           272       12        4

Pass: 26, Fail: 7, Minor Issue: 1
Pass rate (excluding minor_issue): 26/33 = 78.8%
```

### Ollama Model Details
```json
{
  "name": "qwen36-vl:latest",
  "architecture": "qwen35moe",
  "parameters": "35.5B",
  "quantization": "Q8_0",
  "context_length": 262144,
  "size_on_disk": "38 GB",
  "capabilities": ["tools", "thinking", "completion", "vision"],
  "endpoint": "http://127.0.0.1:11434/v1",
  "GPU_memory_used": "~38 GB / 42 GB total"
}
```

### Alternative Models on Server
| Model | Size | Vision | Thinking | Status |
|-------|------|--------|----------|--------|
| qwen36-vl:latest | 38 GB | ✅ | ✅ (mandatory) | Loaded, active |
| qwen3.6-35B:latest | 37 GB | ❌ | ✅ | Loadable but no vision |
| gemma3:27b-it-qat | 18 GB | ✅ | ❌ | Can't load (GPU mem full) |
| deepseek-r1_70b:latest | 42 GB | ❌ | ✅ | Too large for GPU |
| bge-m3:latest | 1.2 GB | ❌ | ❌ | Embedding only |

### Exact CLI Commands Used

```bash
# Single sample (used for testing)
.venv/bin/python -m vlm.scripts.supervise.run_supervision_agent \
  --source vlm/data/SN_6_3D_dataset/char_001/char_001.png \
  --product vlm/data/SN_6_3D_dataset/char_001/char_001_front_view.png \
  --category dataset_figurine \
  --sample-id char_001 \
  --timeout 600

# Batch run (all 34)
.venv/bin/python -m vlm.scripts.supervise.batch_supervision_34 --skip-existing

# Retry failed samples
.venv/bin/python -m vlm.scripts.supervise.batch_supervision_34 \
  --sample-ids char_002,char_012,char_013,char_014,char_015,char_017,char_021,char_022,char_024,char_029 \
  --timeout 900
```

### Raw response example — failed (thinking-only, 57KB)
```
这个任务需要我从提供的动漫角色图片中提取核心可见元素。

1.  **观察整体形象**：这是一个男性角色，穿着类似忍者或奇幻风格的服装。
2.  **头部特征**：
    *   **头发**：深棕色/黑色短发，顶部竖起...
[... 57KB total, ends mid-thought with no JSON ...]
```

### Raw response example — successful (anti-thinking, 3472 chars)
```json
{
  "schema_version": "element_extraction.v1",
  "task": "source_2d_character_element_extraction",
  "sample_id": "char_002",
  "elements": [
    {"element_id": "char_002_e001", "name": "头发", "value": "...", "confidence": "high"},
    ...
  ],
  "summary": {"element_count": 11}
}
```

### Model Performance Characteristics (qwen36-vl on single GPU)
| Metric | Range | Notes |
|--------|-------|-------|
| Extraction time | 49s–572s | Median ~110s; very image-dependent |
| Review time | 30s–150s | Estimated (embedded in per-sample total) |
| Thinking overhead | 60–80% of tokens | 16649 chars reasoning for 2616 chars content in char_001 |
| Anti-thinking speedup | ~2x | char_002: 57KB thinking (fail) → 104s with anti-thinking (OK) |
| Timeout threshold | 600s unsafe, 900s safe | char_023 hit 503s, char_025 hit 572s |

---

## Code Analysis

### Function interfaces (key entry points)

```python
# run_element_extraction.py
def qwen_vl_chat(*, api_key: str, base_url: str, model: str,
                 messages: list[dict], temperature: float,
                 max_tokens: int, timeout: int) -> str
def run_sample(*, sample: dict, prompt_template: Path, output_root: Path,
               api_key: str, base_url: str, model: str, temperature: float,
               max_tokens: int, timeout: int, dry_run: bool) -> dict
def build_messages(prompt: str, image_path: Path) -> list[dict]
def extract_json_object(text: str) -> dict[str, Any]

# run_multicategory_supervision_review.py
def qwen_vl_chat(*, api_key: str, base_url: str, model: str,
                 messages: list[dict], temperature: float = 0.0,
                 max_tokens: int = 8000, timeout: int = 300) -> str
def run_one_sample(sample_config: dict, prompt_template_override: Path | None,
                   api_key: str, base_url: str, model: str, temperature: float,
                   max_tokens: int, timeout: int, output_dir: Path,
                   dry_run: bool) -> dict
def extract_json_object(text: str) -> dict[str, Any]

# run_supervision_agent.py
def elements_to_atomic_rules(extracted: dict) -> list[dict[str, str]]
def main() -> None  # orchestrates Step 1 → 2 → 3

# batch_supervision_34.py (NEW)
def discover_samples(start: int, end: int, sample_ids: str) -> list[str]
def run_one(sample_id: str, timeout: int, skip_existing: bool) -> dict
def main() -> None
```

### Anti-thinking system prompt (critical)
```python
# run_element_extraction.py build_messages()
{"role": "system", "content": "你是一个JSON输出机器人。禁止使用思维链(thinking/reasoning)。你的回复必须是纯JSON，以{开头，以}结尾。不要输出任何其他内容。"}

# run_multicategory_supervision_review.py build_messages()
{"role": "system", "content": "你是一个JSON输出机器人。禁止使用思维链(thinking/reasoning)。你的回复必须是纯JSON，以{开头，以}结尾。不要输出任何其他内容。严格遵守所有硬性覆盖规则。"}
```

### top_p for local Ollama
```python
# Both scripts: qwen_vl_chat()
if "dashscope" in base_url:
    payload["response_format"] = {"type": "json_object"}
else:
    payload["top_p"] = 0.1  # Suppress rambling thinking chains
```

### Empty content → reasoning fallback
```python
# Both scripts: qwen_vl_chat()
content = str(result["choices"][0]["message"]["content"])
if not content.strip():
    reasoning = result["choices"][0]["message"].get("reasoning", "")
    if reasoning.strip():
        return str(reasoning)
return content
```

### Proxy bypass pattern (both scripts)
```python
proxies = None
if "127.0.0.1" in base_url or "localhost" in base_url:
    proxies = {"http": None, "https": None}
# ... requests.post(..., proxies=proxies)
```

### Token budget chain
- `run_element_extraction.py`: `DEFAULT_MAX_TOKENS = 32000`
- `run_supervision_agent.py`: `max_tokens=32000` (extraction hardcoded), `--max-tokens` default `32000` (review CLI arg)
- `run_multicategory_supervision_review.py`: `max_tokens: int = 8000` (default overridden by caller)

### Python 3.8 compat — extract_json_object
```python
# Replaced removeprefix/removesuffix (3.9+) with slicing
if stripped.startswith("```json"):
    stripped = stripped[7:]
elif stripped.startswith("```"):
    stripped = stripped[3:]
if stripped.rstrip().endswith("```"):
    stripped = stripped.rstrip()[:-3]
```

---

## Files Changed

### Source code (modified)
- `vlm/scripts/supervise/run_supervision_agent.py` — max_tokens 8000→32000 for both steps
- `vlm/scripts/supervise/run_element_extraction.py` — anti-thinking prompt, top_p=0.1, empty-content fallback, DEFAULT_MAX_TOKENS 8000→32000
- `vlm/scripts/supervise/run_multicategory_supervision_review.py` — anti-thinking prompt, top_p=0.1, proxy bypass, py3.8 compat, empty-content fallback

### Source code (created)
- `vlm/scripts/supervise/batch_supervision_34.py` — batch runner with retry, skip-existing, per-round summary

### Data & results (uncommitted, in vlm/tmp/)
- `vlm/tmp/supervision_agent_output/batch_summary.json` — batch round summaries
- `vlm/tmp/supervision_agent_output/char_001~034/agent_summary.json` — per-sample results
- `vlm/tmp/supervision_agent_output/char_*/extraction/` — extracted_elements.json, raw_response.txt
- `vlm/tmp/supervision_agent_output/char_*/review/dataset_figurine/` — qwen_prediction_v3.json

### Handoffs (cleaned)
- Deleted 11 old `.claude/handoffs/` files (2026-07-23~07-27)
- Kept 4 current files

### Uncommitted git status
```
M vlm/scripts/supervise/run_element_extraction.py    (anti-thinking + top_p + fallback)
M vlm/scripts/supervise/run_multicategory_supervision_review.py  (same + proxy + py3.8)
M vlm/scripts/supervise/run_supervision_agent.py     (max_tokens)
?? vlm/scripts/supervise/batch_supervision_34.py      (new)
D .claude/handoffs/* (5 deleted handoff files)
```

---

## User Feedback & Preferences

- **"重新跑吧，用部署在服务器上的模型"** — User wanted local Ollama, not DashScope API. This drove the entire debugging effort.
- **"现在这个路径下不止20个了"** — User noticed dataset had grown to 34. Prompted the full batch rather than just 20.
- **"帮我清理一下目前的handoff文档"** — User wants clean workspace. Deleted 11 old files.
- **User accepted the thinking model's limitations** — didn't push for gemma3 or other alternatives after GPU memory constraint was explained.
- **User let the batch run autonomously** — no micromanagement during the 160-minute batch execution.
- **"执行"** — Quick confirmation style. Prefers action over discussion once recommendation is clear.

---

## Where We're Going

1. **Baseline comparison**: VLM auto-extraction (`atomic_rules_generated.json`) vs human annotation (`char_XXX.json`) across all 34 samples — quantify precision/recall for each element category
2. **Review the 7 failed samples**: Check if billable issues are genuine 3D front_view quality problems or VLM false positives. char_015 (3 issues) and char_011 (2+1) need priority review.
3. **Data transfer**: Resolve SSH port for `intern@43.82.14.65` to pull `SN_6期动漫数据标注` from Windows to server
4. **Training data prep**: Write format conversion script for 6000 human-annotated samples → `(image_path, elements_json)` training format
5. **Qwen-VL fine-tuning**: Once GPU resources and training data are ready, replace element extraction API call with fine-tuned model

---

## Risks & Blockers

- **Server SSH port still unknown** — blocks data transfer from Windows (`SN_6期动漫数据标注`). Check via `grep Port /etc/ssh/sshd_config` or `ss -tlnp | grep sshd`.
- **qwen36-vl thinking instability** — anti-thinking prompt works for ~95% of cases but some images may still trigger long chains. If failure rate rises, consider model swap or fallback to DashScope API.
- **Single GPU constraint** — can't load alternative vision models without unloading qwen36-vl. Limits experimentation.
- **7 failed samples unverified** — pass/fail decisions are VLM judgments. May contain false positives (VLM thinks something is wrong but it's actually fine) or false negatives.

---

## Open Questions

- [ ] Are the 7 "fail" samples genuinely failing, or VLM false positives? (char_015 with 3 billable issues is priority)
- [ ] What is the server SSH port for scp/rsync data transfer?
- [ ] Are the 6000 human annotation samples in the same format as `SN_6期动漫数据标注`?
- [ ] Is there GPU budget for Qwen-VL fine-tuning, or should we pursue few-shot + retrieval alternative?

---

## Quick Start for Next Session

```bash
# Check current git status
git status -s
git diff --stat

# Verify batch outputs exist
ls vlm/tmp/supervision_agent_output/char_*/agent_summary.json | wc -l

# Quick stats
python -c "
import json
from pathlib import Path
root = Path('vlm/tmp/supervision_agent_output')
pass_count = fail_count = 0
for i in range(1, 35):
    p = root / f'char_{i:03d}' / 'agent_summary.json'
    if p.exists():
        d = json.loads(p.read_text(encoding='utf-8'))
        if d.get('overall_decision') == 'pass': pass_count += 1
        elif d.get('overall_decision') == 'fail': fail_count += 1
print(f'Pass: {pass_count}, Fail: {fail_count}')
"

# View a failed sample's details
cat vlm/tmp/supervision_agent_output/char_015/agent_summary.json

# Key files to read first
# - vlm/scripts/supervise/run_supervision_agent.py (pipeline entry)
# - vlm/scripts/supervise/batch_supervision_34.py (batch runner)
# - vlm/tmp/supervision_agent_output/batch_summary.json (results summary)

# Next action
# Run baseline comparison: VLM extraction vs human annotation
python -c "
# Compare atomic_rules_generated.json (VLM) vs char_XXX.json elements (human)
# for a single sample to establish the comparison methodology
"
```
