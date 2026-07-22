# Dataset Audit Rubric

## Blocking structural checks

- Every sample has a unique, non-empty `sample_id`.
- Every `source_image` resolves to a readable file.
- Every `elements` value is a list of objects with non-empty `name` and `value` strings.
- JSON decoding and image dimension probing complete without errors.
- Exact duplicate samples do not cross frozen data splits.

## Visual review buckets

Sample each bucket deliberately rather than reviewing only easy examples:

- View: front, three-quarter, side, back, mixed or ambiguous.
- Framing: full body, partial body, close crop, clipped accessories.
- Pose: neutral, action, seated, tilted, foreshortened.
- Visibility: clean, occluded, overlapping props, dense hair or clothing layers.
- Character type: human, kemonomimi, non-human, mechanical, tail or wing structures.
- Detail: flat colors, gradients, local patterns, transparent parts, fine accessories.
- Source quality: low resolution, compression, watermark, text, complex background.

For every weak bucket, either add representative data or document that it is outside the supported input contract.

## Annotation review

- Verify that each element is visible or explicitly marked uncertain.
- Split compound elements when they can fail independently.
- Preserve location, color, topology, count, material, and asymmetry when they are identity-bearing.
- Do not describe hidden back-side details as facts.
- Use a stable importance field when downstream scoring needs weighted elements.

## Leakage review

- Hash files for exact duplicates.
- Group alternate crops, resolutions, and edits of the same character identity.
- Keep prompt-development characters out of the locked test set.
- Record the split policy and random seed; do not reshuffle after reading test outcomes.

## Provenance review

Record source URI or owner, acquisition date, copyright or license basis, privacy classification, retention rules, and whether hosted APIs are allowed. A public URL does not by itself grant training, redistribution, or commercial-generation rights.

## Readiness decision

- `ready`: no structural errors, reviewed warnings, representative coverage, frozen split, documented provenance.
- `conditional`: usable for a bounded pilot with explicit unsupported buckets.
- `blocked`: missing pairs, invalid annotations, unresolved leakage, or unclear authorization for the intended destination.
