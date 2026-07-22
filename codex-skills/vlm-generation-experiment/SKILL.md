---
name: vlm-generation-experiment
description: Design and run reproducible multimodal generation experiments across image-generation or image-editing models and prompts. Use when building batch generation scripts, comparing prompt or model variants, recording seeds and parameters, resuming failed jobs, estimating cost, or preserving manifests and outputs for later evaluation.
---

# VLM Generation Experiment

Turn prompt-driven image generation into a reproducible experiment. Keep provider calls in a project CLI or tool; use this skill to define the contract, manifest, execution controls, and evidence.

## Workflow

1. Audit inputs with `$vlm-dataset-audit`. Do not spend API credits on structurally invalid samples.
2. Write the hypothesis and change only one primary factor per comparison: prompt, model, preprocessing, or decoding parameters.
3. Freeze the output contract, including view, framing, medium, background, resolution, and forbidden content.
4. Create a manifest before generation:

   ```bash
   python <skill-dir>/scripts/create_manifest.py \
     --data-root <dataset-root> \
     --prompt-file <prompt.txt> \
     --provider <provider> \
     --model <model-id> \
     --seeds 0 1 2 \
     --output-root <generated-root> \
     --output <run-manifest.jsonl> \
     --repo-root <repository-root>
   ```

5. Run a 5-20 sample pilot. Verify payload structure, image decoding, output naming, latency, cost recording, and retry behavior before scaling.
6. Execute one manifest job at a time through the existing provider client. Never place API keys, cookies, or signed URLs in the manifest.
7. Persist raw provider metadata needed for reproduction, but keep large binary responses outside JSONL.
8. Resume only `pending` or retryable `failed` records. Never overwrite a successful output unless the user explicitly starts a new run.
9. Evaluate the same frozen jobs with `$anime-ip-fidelity-eval`; compare aggregate scores and failure buckets, not cherry-picked images.

## Required Controls

- Record exact model ID, provider, prompt bytes and hash, code commit, parameters, seed, source hashes, timestamps, attempts, latency, and cost when available.
- Use one job per input and seed. Multiple candidates from one input are separate records.
- Use bounded retries with exponential backoff for transient failures. Do not retry policy, authentication, or invalid-request errors blindly.
- Write structured JSONL status updates atomically or through a run database when concurrent workers are used.
- Preserve the original prompt and manifest after results have been reviewed. A prompt change creates a new run ID.
- Keep a locked test set separate from prompt-development samples.

## Provider Boundary

Use repository helpers and official SDKs already present. Apply `$api-request-safety` before adding or changing third-party batch requests, credential handling, proxies, scraping, or retry policy. Do not embed provider-specific request code inside this skill.

## Resources

- `scripts/create_manifest.py`: build a portable, hash-pinned JSONL job manifest.
- `references/manifest-contract.md`: required fields, lifecycle, and comparison rules.
