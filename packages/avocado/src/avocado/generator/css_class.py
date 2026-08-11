"""CSS class extraction — collect repeated inline styles into named classes.

Given a TreeNode tree, walk it and replace per-node `style` dicts with
a `className` reference that points into a globally-deduplicated class
map. Output form mirrors what a designer would hand-write: a small set
of `.foo { ... }` rules referenced by `className="foo"`.

Naming:
  - Node names containing non-ASCII (Chinese, emoji, ...) or characters
    invalid in CSS identifiers fall back to `<source_type>.lower()`
    (e.g. "frame"), so a Chinese-named node maps to `frame`.
  - Names are truncated to 20 chars to keep DOM output scannable.
  - Duplicate style-signatures reuse the same class; collisions on the
    derived name (two distinct styles fighting for `frame`) get a
    `-2`, `-3`, ... suffix.
"""

from __future__ import annotations

import re

from avocado.model.tree_node import TreeNode

# A valid CSS identifier (very permissive: letters, digits, -, _, \-escapes).
# We use this to decide whether the source node name can be used directly
# as a class name (after kebab-casing).
_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _sanitize_name(raw: str, source_type: str) -> str:
    """Turn a Figma node name into a CSS-class-friendly slug.

    Rules:
      1. Strip leading/trailing whitespace.
      2. Replace runs of [^A-Za-z0-9_-] with a single `-`.
      3. If the result is empty or contains non-ASCII fallback chars,
         use `source_type.lower()` instead (e.g. a Chinese name → "frame").
      4. Lowercase to match kebab-case convention.
      5. Truncate to 20 chars.
    """
    raw = raw.strip()
    # ASCII-only check: any non-ASCII char triggers the source_type fallback.
    if not raw or not raw.isascii():
        return source_type.lower()[:20]
    # Replace disallowed runs with `-`.
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-").lower()
    if not slug:
        return source_type.lower()[:20]
    if not slug[0].isalpha():
        # CSS class names technically allow leading digit, but it's fragile
        # in selector contexts — prefix with the source type.
        slug = f"{source_type.lower()}-{slug}"
    return slug[:20]


def get_node_class_name(node: TreeNode, case_style: str = "kebab") -> str:
    """Derive a class name for a node (does not mutate the node)."""
    if case_style != "kebab":
        # Currently only kebab-case is supported; other strategies reserved.
        case_style = "kebab"
    return _sanitize_name(node.name, node.source_type)


def apply_css_class(
    root: TreeNode,
    case_style: str = "kebab",
) -> dict[str, dict[str, str]]:
    """Extract styles into a class map; mutate nodes to use className.

    Returns `{class_name: {prop: value, ...}, ...}` — the deduplicated
    style map. Nodes are mutated in place: `props["className"]` is set
    to the assigned class name, and `style` is cleared.

    Dedup key = `tuple(sorted(style.items()))`. When two distinct
    style-signatures collide on the derived name, the second one gets
    `-2`, then `-3`, etc.
    """
    class_map: dict[str, dict[str, str]] = {}
    sig_to_name: dict[tuple, str] = {}

    stack = [root]
    while stack:
        n = stack.pop()
        # Only extract when there are styles worth extracting.
        if n.style:
            sig = tuple(sorted(n.style.items()))
            if sig in sig_to_name:
                name = sig_to_name[sig]
            else:
                base = get_node_class_name(n, case_style=case_style)
                name = base
                # Resolve collisions: if `base` is already used by a
                # different signature, append -2 / -3 / ...
                suffix = 2
                while name in class_map and tuple(sorted(class_map[name].items())) != sig:
                    name = f"{base}-{suffix}"
                    suffix += 1
                class_map[name] = dict(n.style)
                sig_to_name[sig] = name
            # Merge into existing className if the node already has one
            # (e.g. tailwind pass may have set one).
            existing = n.props.get("className")
            n.props["className"] = f"{existing} {name}".strip() if existing else name
            n.style = {}
        stack.extend(n.children)

    return class_map


def render_css_block(class_map: dict[str, dict[str, str]]) -> str:
    """Render a class map as a CSS string: `.foo { prop: value; ... }` blocks."""
    blocks: list[str] = []
    for name, styles in class_map.items():
        # Deterministic property ordering for stable diffs.
        body = "".join(f"  {k}: {v};\n" for k, v in sorted(styles.items()))
        blocks.append(f".{name} {{\n{body}}}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")
