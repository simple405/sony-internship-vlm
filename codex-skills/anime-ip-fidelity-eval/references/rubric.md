# Anime IP Fidelity Rubric

The default 100-point score is a starting contract. Calibrate it against human approvals before production use.

## Element fidelity: 60 points

For each annotated element:

- `preserved`: factor 1.0.
- `partial`: factor 0.5.
- `missing`: factor 0.0.
- `contradicted`: factor 0.0 and retain the contradiction label for error analysis.
- `unverifiable`: exclude from the denominator and require review.

Compute the weighted mean using the record's positive `weight` values, then multiply by 60. Default weight is 1. Define weights before generation.

## Output specification: 20 points

- Front view: 5.
- Full body: 4.
- Single subject: 3.
- White or required plain background: 2.
- Visibly three-dimensional product design: 4.
- No added text or watermark: 2.

Set a check to false when it fails and to null only when evidence is genuinely unavailable.

## Identity coherence: 15 points

Provide `identity_match` from 0 to 1 with evidence about face, silhouette, hair, color blocking, and distinctive structures. Multiply by 15.

## Visual quality: 5 points

Provide `visual_quality` from 0 to 1 for structural integrity, rendering artifacts, clipping, extra limbs, and usable presentation. Multiply by 5.

## Hallucination penalties

- Minor: 2 points, such as a small non-identity decoration.
- Major: 8 points, such as an unsupported prominent accessory or changed pattern.
- Critical: 20 points and automatic failure, such as wrong character-defining anatomy or weapon.

## Hard gates and decisions

Automatic failure occurs for false `front_view`, `full_body`, `single_subject`, or `three_dimensional`, identity below 0.5, or a critical hallucination.

- `pass`: score at least 85, no hard-gate failure, no unverifiable element.
- `review`: score 70-84, or any unverifiable element, with no hard-gate failure.
- `fail`: score below 70 or any hard-gate failure.

For a task that intentionally permits crops, multiple subjects, or a non-front view, version the rubric and remove that gate before evaluation. Do not alter gates record by record.
