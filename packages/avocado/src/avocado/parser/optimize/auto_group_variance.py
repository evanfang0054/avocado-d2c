"""Auto-group variance-based orientation detection.

For nodes produced by the `auto_group` layout strategy (a fallback when
Figma provides no Auto Layout), guess the primary axis from child
bounding-box variance: if x-coordinates vary far less than
y-coordinates, the children are stacked vertically → flex column;
otherwise row. Threshold is intentionally conservative — when both
axes vary comparably we leave the node alone.
"""

from __future__ import annotations

import statistics

from avocado.model.tree_node import TreeNode


def apply_auto_group_variance(root: TreeNode) -> None:
    """In-place: orient auto_group nodes based on child position variance."""
    for n in _walk(root):
        if n.layout_strategy != "auto_group":
            continue
        if len(n.children) < 2:
            continue
        # Children must carry bounding-box info to make a decision. We
        # accept either explicit width/height styles or fall back to
        # skipping the node when no positional data is available.
        xs: list[float] = []
        ys: list[float] = []
        for c in n.children:
            # Auto-group children get left/top inline styles from the
            # absolute_layout parser. Use those if present.
            lx = _to_float(c.style.get("left"))
            ly = _to_float(c.style.get("top"))
            if lx is None or ly is None:
                continue
            xs.append(lx)
            ys.append(ly)
        if len(xs) < 2:
            continue
        var_x = statistics.pvariance(xs)
        var_y = statistics.pvariance(ys)
        if var_x == 0 and var_y == 0:
            continue
        # If one axis has zero variance and the other non-zero, the
        # orientation is unambiguous. Otherwise require a 0.3 ratio
        # between the smaller and the larger variance.
        if var_x == 0:
            n.style["display"] = "flex"
            n.style["flex-direction"] = "column"
            continue
        if var_y == 0:
            n.style["display"] = "flex"
            n.style["flex-direction"] = "row"
            continue
        ratio = min(var_x, var_y) / max(var_x, var_y)
        if ratio < 0.3:
            if var_x < var_y:
                n.style["display"] = "flex"
                n.style["flex-direction"] = "column"
            else:
                n.style["display"] = "flex"
                n.style["flex-direction"] = "row"


def _to_float(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s.endswith("px"):
        s = s[:-2]
    try:
        return float(s)
    except ValueError:
        return None


def _walk(root: TreeNode):
    stack = [root]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.children)
