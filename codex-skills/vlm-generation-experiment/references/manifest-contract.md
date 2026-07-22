# Generation Manifest Contract

Each JSONL row represents exactly one input and one seed.

## Identity fields

- `run_id`: immutable identifier shared by one experiment variant.
- `job_id`: unique `<run_id>:<sample_id>:seed-<seed>` identifier.
- `sample_id`: stable dataset identifier.
- `source_image`, `metadata_json`: portable paths when they are inside `repo_root`.
- `source_sha256`, `metadata_sha256`: immutable input fingerprints.

## Experiment fields

- `provider`, `model`: exact backend and model IDs.
- `prompt_file`, `prompt_sha256`, `prompt_version`: exact prompt identity.
- `parameters`: structured generation parameters, excluding secrets.
- `seed`: requested seed, even when a provider does not guarantee determinism.
- `code_commit`, `code_dirty`: source revision evidence.

## Execution fields

- `status`: `pending`, `running`, `succeeded`, `failed`, or `skipped`.
- `attempt`: number of provider submissions.
- `output_image`: expected durable result path.
- `created_at`, `started_at`, `finished_at`: UTC timestamps.
- `latency_seconds`, `cost`, `provider_request_id`, `error`: populate during execution.

Never store credentials, authorization headers, session cookies, private signed URLs, or base64 image payloads.

## Lifecycle rules

1. Create and freeze the manifest before full execution.
2. Transition `pending -> running -> succeeded|failed`.
3. On process restart, inspect `running` jobs and reconcile provider state before retrying.
4. Retry only classified transient failures and increment `attempt`.
5. Never mutate input hashes, prompt hashes, model, or parameters within a run. Start a new run instead.
6. Save aggregate summaries as derived artifacts; the manifest remains the row-level source of truth.

## Fair comparisons

Use identical sample IDs and seeds across variants. Report completion rate, invalid-output rate, latency, cost, fidelity score, critical failure rate, and human-review rate. Keep missing jobs visible instead of dropping them from averages.
