"""Inherit-promote optimization pass.

Walks the tree and lifts inheritable CSS properties (color, font-*,
text-align, ...) from descendants to ancestors when every leaf in the
subtree agrees on the value. This is a "render cost" pass:
consolidating inherited properties at the parent means the
browser only resolves them once per subtree rather than re-declaring
them on every leaf.

Stops at subtree boundaries that isolate inheritance:
  - components (INSTANCE recognized as business component)
  - images (is_img — <img> has no text children)
  - absolute-positioned subtrees (layout_positioning == "ABSOLUTE")
"""

from __future__ import annotations

from avocado.model.tree_node import TreeNode

# CSS properties that inherit per the CSS spec. Lifted to a parent when
# all leaves in a subtree share the same value.
#
# NOTE: ordered tuple (not frozenset). `promote_inherited_styles` iterates
# this to decide insertion order into root.style — a frozenset would make
# output non-deterministic across runs (set iteration order depends on the
# per-process hash seed). Deterministic output is required for regression
# comparison (odiff tooling diffs regenerated JSX).
INHERITABLE_CSS_PROPS: tuple[str, ...] = (
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
    "visibility",
    "cursor",
)


def _is_boundary(n: TreeNode) -> bool:
    """Subtree boundary across which we do not promote inherited styles."""
    return n.is_component or n.is_img or n.props.get("layoutPositioning") == "ABSOLUTE"


def _leaves(n: TreeNode) -> list[TreeNode]:
    """Return all leaf descendants (no children) under n.

    Respects subtree boundaries: descendants of a boundary node
    (component / image / absolute) are excluded so their inheritable
    styles are not pulled out across the boundary.
    """
    out: list[TreeNode] = []
    stack = [n]
    while stack:
        cur = stack.pop()
        if cur is not n and _is_boundary(cur):
            # Treat the boundary node itself as an opaque leaf — its
            # inherited styles stay local to its subtree.
            out.append(cur)
            continue
        if not cur.children:
            out.append(cur)
            continue
        stack.extend(cur.children)
    return out


def promote_inherited_styles(root: TreeNode) -> None:
    """In-place: lift common inheritable styles up the tree.

    Two-phase:
      Phase 1 (post-order DFS): original behavior. For each subtree,
      promote a prop ONLY when all leaves that declared it agree. Strip
      matching descendants. This is the well-tested conservative path that
      preserves per-subtree intermediate node semantics.

      Phase 2 (root-only enhancement): for `font-family` specifically,
      do a majority-vote lift from root's leaves — designs typically use
      1-2 families (body + heading), so a clear majority (e.g. 18 of 23
      leaves) can safely lift the dominant family to root even when a few
      leaves use the other family. Minority leaves keep their override.
      Other props
      (text-align, font-size, line-height, color, etc.) are NOT
      majority-voted — they would pollute non-declaring leaves via CSS
      inheritance and cause fidelity regression.
    """
    # Phase 1: standard post-order promotion (original behavior).
    _post_order_promote(root)

    # Phase 2: root-only font-family majority vote.
    _root_font_family_majority(root)


def _post_order_promote(root: TreeNode) -> None:
    """Standard post-order DFS. Promote a prop to subtree root when all
    declaring leaves agree. Original behavior, preserved verbatim."""
    for c in root.children:
        _post_order_promote(c)

    if _is_boundary(root) or not root.children:
        return

    leaves = _leaves(root)
    if not leaves:
        return

    for prop in INHERITABLE_CSS_PROPS:
        values = [lf.style.get(prop) for lf in leaves if prop in lf.style]
        if not values:
            continue
        first = values[0]
        if any(v != first for v in values[1:]):
            continue
        root.style[prop] = first
        for c in root.children:
            _strip_inherited(c, prop, first)


def _root_font_family_majority(root: TreeNode) -> None:
    """At the outermost root, lift the majority font-family to root.

    After phase 1, font-family values have been promoted to intermediate
    nodes (each subtree's root), and leaves are empty. So we count ALL
    nodes' font-family across the tree (not just leaves). The clear
    majority (> 50% of declared nodes) is lifted to root — the JSX output
    declares font-family once at the top level (D2C convention).
    Minority sub-trees (e.g. a heading subtree in the other family) keep their explicit
    font-family on intermediate nodes, so they still render correctly via
    CSS cascade.
    """
    if _is_boundary(root) or not root.children:
        return

    # Count font-family across ALL nodes (intermediate + leaves), since
    # phase 1 already promoted sub-tree values to intermediate nodes.
    counts: dict[str, int] = {}
    declared_total = 0
    stack = [root]
    while stack:
        n = stack.pop()
        if "font-family" in n.style:
            v = str(n.style["font-family"])
            counts[v] = counts.get(v, 0) + 1
            declared_total += 1
        stack.extend(n.children or [])
    if declared_total == 0 or not counts:
        return

    sorted_vals = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top_val_str, top_count = sorted_vals[0]
    # Strict majority (> 50%) of declared nodes.
    if top_count * 2 <= declared_total:
        return

    # Find typed value.
    top_val = None
    stack = [root]
    while stack:
        n = stack.pop()
        if "font-family" in n.style and str(n.style["font-family"]) == top_val_str:
            top_val = n.style["font-family"]
            break
        stack.extend(n.children or [])
    if top_val is None:
        return

    # Promote to root and strip matching descendants. _strip_inherited
    # correctly preserves minority sub-trees because their font-family
    # doesn't match the promoted value.
    root.style["font-family"] = top_val
    for c in root.children:
        _strip_inherited(c, "font-family", top_val)


def _strip_inherited(n: TreeNode, prop: str, promoted_value=None) -> None:
    """Remove `prop` from n and descendants, stopping at boundaries.

    If `promoted_value` is given, only strip nodes whose value equals it —
    descendants that independently declared a DIFFERENT value (e.g. an
    intermediate node whose value was lifted from a deeper divergent leaf)
    keep their value, so the promote does not silently clobber them.
    """
    if _is_boundary(n):
        return
    if prop in n.style:
        if promoted_value is None or n.style[prop] == promoted_value:
            del n.style[prop]
    for c in n.children:
        _strip_inherited(c, prop, promoted_value)
