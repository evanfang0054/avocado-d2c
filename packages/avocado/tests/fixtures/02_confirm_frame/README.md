# 02: Confirm Frame

Sample Figma "Confirm" dialog (synthetic data, originally derived from a real
Figma node, then desensitized: all PII, brand names, and business terms
replaced with generic placeholders).

## What this tests

- Multi-frame nesting with text + image-fill + VECTOR (svg) nodes
- basic pipeline + inline style
- Auto Layout → flex, text color/line-height
- image nodes → `<img src=...>`, VECTOR → svg export URL,
  absolute positioning (when no Auto Layout)

## Files

- `input.json` — raw Figma API response (sample fixture)
- `expected_react.jsx` — golden snapshot: React output after beautify (used by test_beautify_integration)
- `expected_react_beautified.jsx` — golden snapshot: React raw (unbeautified) output

## Notes

- Most nodes in the source tree are inside invisible variant INSTANCE components;
  the output correctly reflects only the visible tree.
- `<img>` tags cover VECTOR export and image-fill FRAMEs.
- BOOLEAN_OPERATION nodes that contain children are kept as `<div>` wrappers
  (not promoted to `<img>`).
