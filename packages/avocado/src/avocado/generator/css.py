"""CSS rendering: TreeNode.style dict → inline style string."""

from __future__ import annotations

from avocado.generator._style_order import ordered_style as _ordered_style
from avocado.model.tree_node import TreeNode

# Re-export for backwards compatibility (css.py used to own _ordered_style).
# Importers should prefer generator._style_order directly going forward.
__all__ = ["render_inline_style", "_ordered_style", "normalize_css_value"]


def normalize_css_value(value: str | int | float) -> str:
    """Normalize a CSS value: standalone ``0px`` tokens → ``0``.

    Per the CSS Values & Units spec a zero length never needs a unit
    (``0px`` ≡ ``0``), so ``padding: 0px 0px 12px 0px`` reads cleaner as
    ``padding: 0 0 12px 0``. Only whitespace-separated tokens that are
    exactly ``0px`` are rewritten — composite values like ``translateX(0px)``
    or ``-0px`` (a single non-``0px`` token) are left untouched so valid CSS
    is never broken.

    Accepts ``str | int | float`` (style dict values are usually strings but
    unitless numbers like ``flex-grow: 0`` occur); non-strings pass through
    as their string form.

    Returns the (possibly unchanged) normalized string.
    """
    if not isinstance(value, str):
        return str(value)
    if "0px" not in value:
        return value
    tokens = value.split(" ")
    if not any(t == "0px" for t in tokens):
        return value
    return " ".join("0" if t == "0px" else t for t in tokens)


def render_inline_style(node: TreeNode) -> str:
    """Build the `style="..."` attribute string from node.style.

    Returns empty string if no styles.

    FIX: escape `"` in style attribute values as `&quot;` so the HTML
    parser doesn't truncate the style attribute at `font-family: "SF Pro",
    sans-serif` (affects all nodes with quoted font names like SF Pro /
    Cabin / Poppins).
    """
    if not node.style:
        return ""
    parts = [f"{k}: {normalize_css_value(v)}" for k, v in _ordered_style(node.style).items()]
    raw = "; ".join(parts)
    # FIX: `"` inside HTML attribute values must be escaped as `&quot;` (required by the HTML5 spec)
    safe = raw.replace('"', "&quot;")
    return f'style="{safe}"'
