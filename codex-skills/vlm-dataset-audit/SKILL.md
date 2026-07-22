---
name: vlm-dataset-audit
description: Audit paired image-text and VLM datasets before training, prompting, or evaluation. Use when checking image/JSON pairing, annotation schemas, duplicate samples, missing assets, split leakage, visual coverage, provenance, licensing, or dataset readiness for multimodal experiments.
---

# VLM Dataset Audit

Audit data without modifying source assets. Separate deterministic structural checks from visual and provenance review.

## Workflow

1. Discover the dataset contract from sample files, project docs, and downstream readers. Do not assume every JSON file is a sample.
2. Run the deterministic audit on the intended dataset root:

   ```bash
   python <skill-dir>/scripts/audit_dataset.py --root <dataset-root> --output <audit.json>
   ```

3. Resolve every structural error before launching paid inference or training. Treat warnings as review items, not automatic failures.
4. Read [references/audit-rubric.md](references/audit-rubric.md) and visually inspect a stratified sample. The script cannot reliably judge crop quality, pose, watermarks, occlusion, or annotation truth.
5. Freeze train, development, and test splits only after duplicate and leakage checks. Keep prompt-tuning examples out of the final test split.
6. Save the audit report with the dataset version, source revision, and reviewer decision.

## Default Pair Contract

The bundled script supports the common local layout in which each sample JSON contains:

```json
{
  "sample_id": "char_001",
  "source_image": "char_001.png",
  "elements": [{"name": "hair", "value": "long blond hair"}]
}
```

`source_image` is resolved relative to its JSON file. Extend the project validator when the repository uses a different explicit schema; do not silently coerce incompatible data.

## Required Evidence

Report these separately:

- Structural validity: readable JSON, unique IDs, valid element records, resolvable image paths.
- Asset integrity: readable dimensions, duplicate hashes, orphan images, unexpected formats.
- Coverage: view, crop, pose, occlusion, visual complexity, character type, and failure-prone edge cases.
- Split integrity: no exact or near duplicate identity crossing development and test sets.
- Provenance: source, license or authorization, privacy constraints, and allowed model/API destinations.

Never infer permission to upload private images to a hosted dataset or model API. Surface the destination and authorization requirement before transfer.

## Resources

- `scripts/audit_dataset.py`: deterministic JSON/image pairing and duplicate audit.
- `references/audit-rubric.md`: visual coverage, leakage, and readiness rubric.
