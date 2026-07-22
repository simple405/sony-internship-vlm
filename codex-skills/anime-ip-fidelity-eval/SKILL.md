---
name: anime-ip-fidelity-eval
description: Evaluate generated anime or character-product 3D designs against a 2D source image and element annotations. Use for front-view or multi-view fidelity review, element preservation scoring, hallucination detection, identity consistency, output-spec compliance, human review queues, prompt comparisons, or IP supervision reports.
---

# Anime IP Fidelity Evaluation

Evaluate visible evidence, not semantic similarity alone. Keep source ambiguity separate from model failure and preserve one row per generated candidate.

## Inputs

Require:

- Original 2D source image.
- Element annotation JSON used for generation.
- Generated 3D front view or multi-view design.
- Target contract: product type, required view, framing, pose, background, and material.
- Model, prompt version, run ID, and seed when available.

Never score from filenames or element text alone. Inspect both images. If the source does not reveal a detail, mark it `unverifiable` instead of rewarding an invented answer or penalizing a conservative omission.

## Workflow

1. Validate that all inputs belong to the same sample and that the generated image is readable.
2. Apply hard output gates first: correct identity, requested view, full-body framing when required, one subject, and a visibly 3D product design.
3. Evaluate every annotated element independently as `preserved`, `partial`, `missing`, `contradicted`, or `unverifiable`. Cite the visible region and observed difference.
4. Record additions not supported by the source as hallucinations. Distinguish minor decoration from identity-changing additions.
5. Evaluate composition, identity coherence, and rendering quality separately. Do not let attractive rendering hide missing identity elements.
6. Run the deterministic scorer:

   ```bash
   python <skill-dir>/scripts/score_evaluation.py <evaluation.json> --output <scored.json>
   ```

7. Route `review` records and all critical failures to a human. Calibrate thresholds on approved examples before treating the score as a production gate.
8. Aggregate by failure bucket, element type, source condition, prompt version, and model. Keep completion failures in the denominator.

## Evaluation Record

Use the structure in [references/evaluation-record.example.json](references/evaluation-record.example.json). The scoring model is defined in [references/rubric.md](references/rubric.md).

Element weights default to `1`. Use stable annotation policy for other weights; do not change weights after seeing generated results. `unverifiable` elements are excluded from the element denominator and force human review.

## Review Principles

- Identity fidelity outranks polish.
- Missing and contradicted details are different failure modes even when both score zero.
- Penalize new salient ears, horns, tails, weapons, symbols, or accessories when unsupported.
- Do not demand invented back-side detail from a source that only shows the front.
- A VLM judge may propose findings, but evidence and final approval must remain inspectable.
- Keep source, candidate, assessment JSON, scorer version, and human correction together.

## Resources

- `scripts/score_evaluation.py`: validate assessment records and compute consistent scores and decisions.
- `references/rubric.md`: scoring weights, gates, and calibration guidance.
- `references/evaluation-record.example.json`: machine-readable example record.
