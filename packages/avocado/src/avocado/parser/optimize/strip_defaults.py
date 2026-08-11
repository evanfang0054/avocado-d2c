"""Strip-defaults optimization pass.

Removes CSS properties whose value equals the spec default — these cost
bytes in the output and time in the browser's style resolver for zero
visual effect. Cleanup pass before codegen.
"""

from __future__ import annotations

from avocado.model.tree_node import TreeNode

# Property → set of default values that should be stripped.
# Values are kept as strings because TreeNode.style values may be str or
# numeric (we str them before comparison).
DEFAULT_VALUES: dict[str, set[str]] = {
    "align-items": {"stretch"},
    "flex-direction": {"row"},
    "flex-wrap": {"nowrap"},
    "justify-content": {"flex-start"},
    "font-weight": {"400", "normal"},
    "font-style": {"normal"},
    "opacity": {"1", "1.0"},
    "text-decoration": {"none"},
    "text-transform": {"none"},
    "text-align": {"start", "left"},
    "letter-spacing": {"0", "0px", "normal"},
    "line-height": {"normal"},
    "white-space": {"normal"},
    "visibility": {"visible"},
    "cursor": {"auto"},
    "border-style": {"none"},
    "outline-style": {"none"},
    "background-repeat": {"repeat"},
    "overflow": {"visible"},
    "display": {"block"},
    # Readability: extend defaults (D2C style-optimization parity)
    # These are CSS initial values that produce no visual effect.
    "padding": {"0", "0px", "0px 0px 0px 0px"},
    "padding-top": {"0", "0px"},
    "padding-right": {"0", "0px"},
    "padding-bottom": {"0", "0px"},
    "padding-left": {"0", "0px"},
    "margin": {"0", "0px", "0px 0px 0px 0px"},
    "margin-top": {"0", "0px"},
    "margin-right": {"0", "0px"},
    "margin-bottom": {"0", "0px"},
    "margin-left": {"0", "0px"},
    "flex-basis": {"auto"},
    "background": {"transparent"},
    "background-color": {"transparent"},
    "min-width": {"0", "0px", "auto"},
    "min-height": {"0", "0px", "auto"},
    "border-width": {"0", "0px"},
    "border-top-width": {"0", "0px"},
    "border-right-width": {"0", "0px"},
    "border-bottom-width": {"0", "0px"},
    "border-left-width": {"0", "0px"},
    "outline-width": {"0", "0px"},
    "box-shadow": {"none"},
    "text-shadow": {"none"},
    "transform": {"none"},
    "filter": {"none"},
    "backdrop-filter": {"none"},
    "z-index": {"auto"},
    "overflow-x": {"visible"},
    "overflow-y": {"visible"},
}


def strip_default_styles(root: TreeNode) -> None:
    """In-place: remove default-valued CSS properties from every node."""
    stack = [root]
    while stack:
        n = stack.pop()
        for prop, defaults in DEFAULT_VALUES.items():
            if prop in n.style:
                val = n.style[prop]
                if isinstance(val, (int, float)):
                    sval = str(val)
                else:
                    sval = str(val).strip().lower()
                if sval in defaults:
                    del n.style[prop]
        stack.extend(n.children)
