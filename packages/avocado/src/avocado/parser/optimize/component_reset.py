"""Component style reset optimization pass.

Component-library components (e.g. a mobile Divider) ship css-in-js default
styles — most notably a default ``margin``. d2c passes the Figma-derived
style as an inline ``style`` prop, which overrides the library defaults for
declared properties, but *undeclared* properties (margin) keep the library
default, so the rendered layout diverges from the Figma spec.

Concrete case: a Figma 0px divider line recognized as a mobile ``<Divider>``
component rendered its library's default horizontal margin, shifting the
Accordion section below it down by 27px. The HTML preview had no React
runtime so the tag rendered bare (no library margin) and "happened" to match.

This pass sets ``margin: 0`` on component nodes that carry no margin in the
Figma data — making component rendering fully Figma-driven. A Figma node
without a margin means "no margin", so zeroing is zero-visual. Nodes with an
explicit Figma margin keep it.
"""

from __future__ import annotations

from avocado.model.tree_node import TreeNode


def apply_component_style_reset(root: TreeNode) -> None:
    """In-place: give component nodes without a Figma margin ``margin: 0``."""
    stack = [root]
    while stack:
        n = stack.pop()
        if n.is_component and not any(
            k == "margin" or k.startswith("margin-") for k in n.style
        ):
            n.style["margin"] = "0"
        stack.extend(n.children or [])
