"""Shared style key ordering for stable output (golden file friendliness).

Used by both css.render_inline_style (HTML style attr) and react_style.render_react_style
(React style object) so the two output forms emit properties in the same order.
"""

from __future__ import annotations

# Display-first ordering for readability: layout → box → bg → text.
_PRIORITY = [
    "display",
    "flex-direction",
    "justify-content",
    "align-items",
    "gap",
    "flex-grow",
    "position",
    "top",
    "right",
    "bottom",
    "left",
    "width",
    "height",
    "min-width",
    "max-width",
    "padding",
    "padding-top",
    "padding-right",
    "padding-bottom",
    "padding-left",
    "margin",
    "background-color",
    "background-image",
    "background",
    "border",
    "border-radius",
    "border-width",
    "border-style",
    "border-color",
    "box-shadow",
    "color",
    "font-family",
    "font-size",
    "font-weight",
    "font-style",
    "text-align",
    "text-decoration",
    "text-transform",
    "letter-spacing",
    "line-height",
    "white-space",
    "opacity",
    "mix-blend-mode",
    "filter",
    "transform",
    "overflow",
    "box-sizing",
]


def ordered_style(s: dict[str, str | float]) -> dict[str, str | float]:
    """Sort keys for stable output (golden file friendliness)."""
    seen: set[str] = set()
    out: dict[str, str | float] = {}
    for k in _PRIORITY:
        if k in s:
            out[k] = s[k]
            seen.add(k)
    for k, v in sorted(s.items()):
        if k not in seen:
            out[k] = v
    return out
