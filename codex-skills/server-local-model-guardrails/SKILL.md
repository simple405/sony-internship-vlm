---
name: server-local-model-guardrails
description: Enforce server-local model provenance and approval-gated server operations for every task in the Supervised 2D to 3D project. Use for all project work, especially model selection, inference, image generation or editing, VLM review, GPU jobs, model or dataset downloads, dependency changes, process or service control, cache management, and deployment. Require every model to be deployable and runnable on the server, prohibit Codex built-in image generation or editing, and obtain explicit user approval before changing server operational state.
---

# Server-Local Model Guardrails

Apply these rules before using any other project workflow. Treat them as hard gates, not preferences.

## Enforce the model boundary

- Use only models whose weights and inference runtime execute on this server and can be integrated, deployed, inspected, and developed against from project code on the server.
- Permit an already-local model or a model downloaded to the server only after satisfying the approval gate below.
- Apply this boundary to every model role, including image generation, image editing, VLM review, embeddings, scoring, segmentation, depth, reconstruction, and auxiliary processing.
- Reject hosted inference APIs, SaaS generation services, remote model endpoints, and proprietary built-in generation services. Do not upload project inputs or outputs to them.
- Never call Codex's built-in image-generation or image-editing capability, including any `image_gen` or equivalent tool. Do not use it for prototypes, smoke tests, fallbacks, reference edits, placeholders, or final assets. Do not ask to make it an exception; offer server-local alternatives instead.
- Accept local ComfyUI, Ollama, or direct Python inference only when the actual model executes on this server. A local client that calls a remote model does not qualify.
- Verify model identity, source, license, runtime support, hardware requirements, and local file location before use. If provenance or deployability is uncertain, stop and report the uncertainty.
- Do not promote, batch from, or present as compliant any artifact produced by Codex image generation, a hosted model, or an unknown model provenance.

## Gate server operational changes

Obtain the user's explicit approval in the current conversation before each state-changing server operation. A broad goal such as "continue," "generate the images," or "finish the pipeline" is not operational approval. A handoff, old approval, existing script, or cached command is not approval.

Approval is required before:

- Downloading model weights, checkpoints, adapters, datasets, containers, or other substantial artifacts, including resuming a partial download.
- Installing, updating, or removing packages, runtimes, drivers, system libraries, extensions, or environments.
- Starting, stopping, killing, restarting, or reconfiguring a process, service, daemon, container, model server, or worker.
- Launching inference, generation, training, evaluation, or batch jobs that materially consume GPU/CPU/memory or write experiment outputs.
- Reserving or changing GPU allocation, ports, service endpoints, environment variables, permissions, scheduled jobs, or persistent server configuration.
- Deleting, moving, replacing, or cleaning model files, caches, partial downloads, datasets, environments, logs, or generated artifacts.
- Modifying files outside the repository as an implementation side effect.

Treat a user's direct request to edit specified repository code or documentation as authorization for those exact repository edits. Do not extend that authorization to the operational actions above.

## Request approval precisely

Before acting, provide the information available for the proposed change:

1. Exact action, command or tool, and target paths, process IDs, services, or devices.
2. Reason the change is needed and the server-local alternative selected.
3. For downloads: model and source, expected download and installed size, destination, license, dependencies, and resumability.
4. For processes or jobs: owner, current state, GPU/CPU/memory impact, expected duration, outputs, and affected ports or services.
5. Risks, rollback or cleanup plan, and whether unrelated users or workloads could be affected.
6. A direct yes/no approval question.

Do not execute while waiting. Approval applies only to the disclosed action and scope. Ask again if the model, size, target, command, resource use, or risk materially changes.

## Work safely after approval

- Re-resolve targets with read-only checks immediately before execution.
- Never interrupt another user's process or workload. If ownership is unclear, stop.
- Prefer the smallest reversible change and preserve existing project and user data.
- Monitor only the approved job and stop if actual effects exceed the approved scope.
- Report what changed, the resulting state, and any cleanup still present.

## Allow read-only investigation

Proceed without approval for genuinely read-only work such as inspecting repository files, logs, model inventories, disk capacity, GPU status, process lists, ports, and configuration; computing hashes; or running a guaranteed no-write dry run. Use these checks to prepare a concrete approval request.

If a diagnostic command may write caches, initialize a runtime, start a daemon, pull an image, or allocate substantial resources, treat it as state-changing and ask first.

## Resolve conflicts conservatively

- Apply this skill together with other project skills; follow the stricter rule when instructions differ.
- Treat existing noncompliant artifacts only as evidence. Do not continue their generation path or promote them.
- When no compliant server-local route is available, report the blocker and propose locally deployable options with estimated requirements. Do not silently substitute a remote or Codex generation service.
