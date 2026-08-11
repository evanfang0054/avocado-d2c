"""CSS rendering: TreeNode.style dict → inline style string."""

from __future__ import annotations

from avocado.generator._style_order import ordered_style as _ordered_style
from avocado.model.tree_node import TreeNode

# Re-export for backwards compatibility (css.py used to own _ordered_style).
# Importers should prefer generator._style_order directly going forward.
__all__ = ["render_inline_style", "_ordered_style"]


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
    parts = [f"{k}: {v}" for k, v in _ordered_style(node.style).items()]
    raw = "; ".join(parts)
    # FIX: `"` inside HTML attribute values must be escaped as `&quot;` (required by the HTML5 spec)
    safe = raw.replace('"', "&quot;")
    return f'style="{safe}"'
