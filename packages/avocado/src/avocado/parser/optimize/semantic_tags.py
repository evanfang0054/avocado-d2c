"""Semantic-HTML optimization pass.

Rewrites `tag_name` for nodes whose structure or Figma `name` clearly
indicates a semantic HTML element (<header>, <nav>, <main>, <h2>, <button>,
...). The default tag stays `div` for unmatched nodes.

Why:Semantic tags improve SEO, screen-reader navigation, and JSX
readability ("which part of the page is this?") at zero visual cost —
CSS layout treats semantic tags and <div> identically when styled. This pass
runs *after* all style/layout passes so it cannot break layout.

Safety (issue #28 acceptance: 宁少勿错 — a wrong semantic tag is worse than
none, it misleads screen readers / SEO):
- Only applies to non-component, non-image, non-text nodes (we don't want
  to overwrite <Button> or <img> or <span>).
- Landmark tags (header/nav/main/...) match a conservative Figma-name
  keyword set, whole-word / trailing-token, to avoid false positives.
- Content tags (h1-h3/p/ul/li/button) use *exact* name matches + structural
  signals (font-size, sibling counts) to stay reliable.

Zero-visual guarantee: tags with UA default styling (h1-h6/p/ul/li/button/
input/label) are neutralized by a companion CSS reset injected by the
generator (see ``UA_STYLED_SEMANTIC_TAGS``). Landmark tags need no reset —
they are display:block with no UA styling.
"""

from __future__ import annotations

import re

from avocado.model.tree_node import TreeNode

# Semantic tags that carry UA default styles (font-size/margin/list-style/
# button chrome). Replacing <div> with these changes rendering unless a CSS
# reset neutralizes the defaults — the generator injects one when any of
# these appear in the tree. Landmark tags (header/nav/main/section/footer/
# aside/article) are display:block with no UA styling and need no reset.
UA_STYLED_SEMANTIC_TAGS = frozenset(
    {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "ul",
        "li",
        "button",
        "input",
        "label",
    }
)

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

# Exact Figma node names that reliably denote a heading. Mapped to h2/h3 by
# font-size (no reliable h1 signal from a layer name; the page title is the
# design's top frame, handled as <main>).
_HEADING_NAMES = frozenset({"title", "heading", "headline", "section title"})

# Exact / trailing-token names that denote an interactive button (non-
# component nodes only — recognized INSTANCE components are already <Button>).
_BUTTON_NAMES = frozenset({"button", "btn"})

# Exact / trailing-token names that denote a list group.
_LIST_NAMES = frozenset({"list", "items", "overview", "menu"})


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


def _font_size_px(n: TreeNode) -> float | None:
    """Parse the node's font-size style value to px (or None)."""
    raw = n.style.get("font-size")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    m = re.match(r"^(-?\d+(?:\.\d+)?)px$", str(raw).strip())
    return float(m.group(1)) if m else None


def _looks_like_heading(n: TreeNode) -> str | None:
    """Return 'h2'/'h3' for a heading container (exact name + font-size)."""
    nm = (n.name or "").strip().lower()
    if nm not in _HEADING_NAMES:
        return None
    fs = _font_size_px(n)
    if fs is None:
        return None  # no font-size signal — don't guess
    if fs >= 20:
        return "h2"
    if fs >= 16:
        return "h3"
    return None


def _looks_like_button(n: TreeNode) -> bool:
    """Exact / trailing-token name 'button'/'btn' on a non-component node."""
    nm = (n.name or "").strip().lower()
    if nm in _BUTTON_NAMES:
        return True
    tokens = re.split(r"[\s\-_/]+", nm)
    return len(tokens) >= 2 and tokens[-1] in _BUTTON_NAMES


def _looks_like_list(n: TreeNode) -> str | None:
    """Return 'ul' for a list group (name hint + 3+ same-prefix children).

    Conservative: requires the node name to hint at a list AND at least 3
    children sharing a common word-prefix (e.g. "Item 1" / "Item 2" / "Item 3").
    """
    nm = (n.name or "").strip().lower()
    if nm not in _LIST_NAMES and not (nm.endswith(" list") or nm.endswith(" menu")):
        return None
    children = [c for c in n.children if not c.is_img]
    if len(children) < 3:
        return None
    prefixes: set[str] = set()
    for c in children:
        cnm = (c.name or "").strip()
        # First word as prefix signal (e.g. "Item" from "Item 1").
        prefix = re.split(r"[\s\-_/]+", cnm)[0].lower() if cnm else ""
        if prefix:
            prefixes.add(prefix)
    # 3+ children but only a single shared prefix → likely a list.
    return "ul" if len(prefixes) == 1 and len(children) >= 3 else None


def _is_page_root(n: TreeNode) -> bool:
    """True for the page's top-level container (candidate for <main>)."""
    return n.source_type in {"FRAME", "GROUP"} and not n.is_component and not n.is_img


def apply_semantic_tags(root: TreeNode) -> None:
    """In-place: rewrite tag_name for nodes that clearly map to a semantic tag.

    Matches, in order of safety:
      1. <main> for the page root frame (top-level container).
      2. Landmark name keywords (header/nav/main/footer/aside/article/section).
      3. h2/h3 for exact heading names (Title/Heading/Headline) w/ font-size.
      4. button for exact 'Button'/'btn' names on non-component nodes.
      5. ul for list-group containers (name + 3+ same-prefix children); the
         list children become li.

    Skips:
    - component nodes (is_component) — don't override <Button>/<Steps>/...
    - image nodes (is_img) — keep <img>
    - text nodes (tag_name == 'span') — keep <span>
    """
    is_root = True
    stack = [(root, is_root)]
    while stack:
        n, is_page_root = stack.pop()
        # Skip nodes whose tag was already decided by an earlier pass.
        if n.is_component or n.is_img:
            stack.extend((c, False) for c in n.children)
            continue
        if n.tag_name == "span":
            stack.extend((c, False) for c in n.children)
            continue

        tag: str | None = None
        if is_page_root and _is_page_root(n):
            tag = "main"
        elif not is_page_root:
            tag = _match_semantic(n.name or "")
            if tag is None:
                tag = _looks_like_heading(n)
            if tag is None and _looks_like_button(n):
                tag = "button"
            if tag is None:
                tag = _looks_like_list(n)
        if tag:
            n.tag_name = tag
            if tag == "ul":
                # children become list items (skip components/images)
                for c in n.children:
                    if not c.is_component and not c.is_img and c.tag_name != "span":
                        c.tag_name = "li"
        stack.extend((c, False) for c in n.children)
