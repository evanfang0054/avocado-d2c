"""Semantic-HTML optimization pass.

Rewrites `tag_name` for nodes whose Figma `name` clearly indicates a
semantic HTML landmark (<header>, <nav>, <main>, <article>, ...). The
default tag stays `div` for unmatched nodes.

Why:Semantic tags improve SEO, screen-reader navigation, and JSX
readability ("which part of the page is this?") at zero visual cost —
CSS layout treats <header> and <div> identically when styled. This pass
runs *after* all style/layout passes so it cannot break layout.

Safety:
- Only applies to non-component, non-image nodes (we don't want to
  overwrite <Button> or <img>).
- Match is case-insensitive on the Figma node name, with whole-word
  boundary check to avoid false positives like "Header Icon" matching
  "header".
- Conservative keyword set — only W3C HTML5 landmark/section tags that
  are unambiguous in design-tool naming.
"""

from __future__ import annotations

import re

from avocado.model.tree_node import TreeNode

# Figma node name (lowercased) → JSX tag name.
# Restricted to HTML5 landmark + sectioning tags — these have clear
# semantic meaning and are routinely named this way in Figma designs.
_SEMANTIC_MAP: dict[str, str] = {
    "header": "header",
    "nav": "nav",
    "navbar": "nav",
    "navigation": "nav",
    "main": "main",
    "footer": "footer",
    "aside": "aside",
    "sidebar": "aside",
    "article": "article",
    "section": "section",
}


def _match_semantic(name: str) -> str | None:
    """Return the semantic tag if `name` is a clear landmark keyword.

    Uses word-boundary regex to avoid false positives. "Header Icon"
    does NOT match "header" because the boundary check requires the
    keyword to appear as a standalone token (or the entire string).
    """
    if not name:
        return None
    nm = name.lower().strip()
    # Direct exact match (most common in well-organized designs).
    if nm in _SEMANTIC_MAP:
        return _SEMANTIC_MAP[nm]
    # Whole-word match within compound names like "Main Header" → header.
    # Avoids "Header Icon" → header (icon part is the noun, header is
    # the modifier). We require the keyword to be the LAST token
    # (English head noun convention) to reduce false positives.
    tokens = re.split(r"[\s\-_/]+", nm)
    if len(tokens) >= 2:
        last = tokens[-1]
        if last in _SEMANTIC_MAP:
            return _SEMANTIC_MAP[last]
    return None


def apply_semantic_tags(root: TreeNode) -> None:
    """In-place: rewrite tag_name for nodes whose name maps to a landmark.

    Skips:
    - component nodes (is_component) — don't override <Button>/<Steps>/...
    - image nodes (is_img) — keep <img>
    - text nodes — keep <span>
    """
    stack = [root]
    while stack:
        n = stack.pop()
        # Skip nodes whose tag was already decided by an earlier pass.
        if n.is_component or n.is_img:
            pass  # fall through to children iteration below
        elif n.tag_name == "span":
            pass  # text node — leave alone
        else:
            tag = _match_semantic(n.name or "")
            if tag:
                n.tag_name = tag
        stack.extend(n.children or [])
