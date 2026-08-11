"""Gap → margin optimization pass.

Converts flex `gap` into per-child `margin-right` / `margin-bottom`.
CSS gap is well-supported today, but some downstream consumers (older
email clients, certain React Native renderers) handle margin more
reliably than gap. This pass is opt-in via `--gap-to-margin`.

Skips:
  - absolute-positioned children (out of flow; gap doesn't apply)
  - last in-flow child (no trailing margin needed)
"""

from __future__ import annotations

from avocado.model.tree_node import TreeNode


def gap_to_margin(root: TreeNode) -> None:
    """In-place: replace flex gap with per-child margins."""
    for n in _walk(root):
        gap = n.style.get("gap")
        if gap is None:
            gap = n.style.get("row-gap") or n.style.get("column-gap")
        if gap is None:
            continue

        # flex-direction:row → children laid out horizontally → margin-right.
        # flex-direction:column → vertically → margin-bottom.
        is_column = n.style.get("flex-direction") == "column"
        margin_prop = "margin-bottom" if is_column else "margin-right"

        in_flow = [
            c
            for c in n.children
            if c.props.get("layoutPositioning") != "ABSOLUTE"
            and c.style.get("position") != "absolute"
        ]
        for c in in_flow[:-1]:
            c.style[margin_prop] = gap
        # Drop all gap variants on the parent.
        for k in ("gap", "row-gap", "column-gap"):
            n.style.pop(k, None)


def _walk(root: TreeNode):
    stack = [root]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.children)
