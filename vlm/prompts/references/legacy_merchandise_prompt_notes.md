# Legacy Merchandise Prompt Notes

The old `vlm/reference/ip_review_project` prompt generators are useful as references, but they were designed for `normalized_rules`, not the current `atomic_rules` batch format.

Reusable ideas:

- Use the 2D image as the primary identity reference.
- Use generated text prompts only as secondary constraints.
- For review-friendly outputs, ask for front, side, and back views in a clean horizontal layout.
- Keep the product type explicit, such as PVC figurine, plush doll, head keychain, backpack, or cake-roll plush.
- Add negative constraints for text, logos, watermarks, extra characters, cropped body, malformed hands, extra fingers, and missing fingers.
- Preserve hairstyle, colors, accessories, outfit structure, and signature features.

Do not directly reuse the old scripts for the current pipeline without adaptation, because they expect `normalized_rules` instead of `{code, atomic_rules}` JSON.
