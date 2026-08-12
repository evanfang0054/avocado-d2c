"""Unwrap-single-child optimization pass.

A FRAME/GROUP wrapper with one child and no visual style of its own
contributes nothing but an extra DOM node — its child can take its
place. This structural simplification yields ~30% render-layer savings.

Unwrap is blocked when:
  - the wrapper has any visual style (background, border, shadow,
    opacity, padding, blur) — removing it would lose the paint.
  - the wrapper is itself a recognized component or image.
  - the subtree contains an absolute-positioned node — unwrapping
    changes the containing-block ancestor and shifts all absolute
    children. We play it safe and keep the wrapper.

Returns the (possibly new) root of the tree, since the original root
may itself be unwrappable.
"""

from __future__ import annotations

from avocado.model.tree_node import TreeNode

_VISUAL_STYLE_KEYS: frozenset[str] = frozenset(
    {
        "background",
        "background-color",
        "backgroundColor",
        "border",
        "border-top",
        "border-right",
        "border-bottom",
        "border-left",
        "box-shadow",
        "boxShadow",
        "outline",
        "filter",
        "backdrop-filter",
        "opacity",
        "padding",
        "padding-top",
        "padding-right",
        "padding-bottom",
        "padding-left",
        "border-radius",
        "borderRadius",
        "mix-blend-mode",
    }
)

# Inheritable CSS properties (mirror of inherit_promote.INHERITABLE_CSS_PROPS).
# When unwrapping a wrapper that carries these (typically lifted there by
# inherit_promote), we must push them onto the merged child so the browser
# keeps inheriting them. Without this, checkout Alert INSTANCE → "top" FRAME
# lost its font-size/line-height after unwrap, and the subtitle span rendered
# with the default font (diff >100px in that region).
_INHERITABLE_CSS_PROPS: frozenset[str] = frozenset(
    {
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
    }
)


def _has_visual_style(n: TreeNode) -> bool:
    return any(k in n.style for k in _VISUAL_STYLE_KEYS)


def _subtree_has_absolute(n: TreeNode) -> bool:
    stack = [n]
    while stack:
        cur = stack.pop()
        if cur.props.get("layoutPositioning") == "ABSOLUTE":
            return True
        # style-side absolute signal (parser/absolute_layout.py)
        if "position" in cur.style and cur.style["position"] == "absolute":
            return True
        stack.extend(cur.children)
    return False


def _is_positioned(n: TreeNode) -> bool:
    return n.style.get("position") not in (None, "static")


def _can_unwrap(n: TreeNode) -> bool:
    if n.source_type not in {"FRAME", "GROUP"}:
        return False
    if len(n.children) != 1:
        return False
    if n.is_component or n.is_img:
        return False
    if _has_visual_style(n):
        return False
    # Absolute descendants: unwrapping a *positioned* wrapper changes their
    # containing block (the wrapper participates in absolute resolution), so
    # keep it. A static wrapper does not participate in containing-block
    # resolution — removing it leaves every absolute descendant's containing
    # block untouched, so unwrapping it is safe.
    # (FIX #26: the old blanket check kept 4+ consecutive static single-child
    # wrappers, inflating nesting depth to 18 on complex pages.)
    if _is_positioned(n) and _subtree_has_absolute(n):
        return False
    # Don't unwrap when the single child has `flex-grow: 1` (FILL semantics).
    # The wrapper's width/height is the FILL reference; removing the wrapper
    # re-parents the FILL child, which then resolves against a different
    # (usually larger) parent and grows to cover sibling content.
    # Regression: sample_page_002 "Primary Button" (FILL, layoutGrow=1) nested in
    # a FIXED-width "buttons" wrapper got unwrapped → button grew from 155px
    # to 272px and overwrote the $49 label area.
    child = n.children[0]
    if "flex-grow" in child.style and child.style["flex-grow"] not in (0, "0"):
        return False
    return True


def _merge_into(parent: TreeNode, child: TreeNode) -> TreeNode:
    """Return a merged node that takes the parent's place.

    The child's tag/props/style win where they overlap; the parent's
    layout_strategy is preserved (it's what node_mapper/layout decided
    for this container). The child's children become the merged node's
    children.

    Inheritable CSS properties (font-*, line-height, color, text-*, ...)
    lifted onto `parent` by `inherit_promote` are pushed onto the merged
    node if the child doesn't already declare them — otherwise the merged
    subtree loses its inheritance chain and renders with browser defaults.
    """
    merged_style = dict(child.style)
    for k, v in parent.style.items():
        if k in _INHERITABLE_CSS_PROPS and k not in merged_style:
            merged_style[k] = v
    merged = TreeNode(
        id=child.id,
        name=child.name,
        source_type=child.source_type,
        tag_name=child.tag_name,
        props=dict(child.props),
        children=list(child.children),
        style=merged_style,
        class_name=child.class_name,
        text_content=child.text_content,
        is_img=child.is_img,
        is_component=child.is_component,
        component_package=child.component_package,
        # Parent's layout strategy is more authoritative for the container
        # role; but if the child already has a non-leaf strategy (e.g. an
        # auto-layout FRAME that was wrapped by a plain GROUP), keep the
        # child's — it carries the actual flex/absolute decision.
        layout_strategy=(
            child.layout_strategy if child.layout_strategy != "leaf" else parent.layout_strategy
        ),
        figma_id=child.figma_id or parent.figma_id,
        to_template=child.to_template,
        inspect=parent.inspect + child.inspect,
    )
    return merged


def unwrap_single_child(root: TreeNode) -> TreeNode:
    """Return the (possibly new) root with single-child wrappers collapsed."""
    # First recurse so children collapse bottom-up.
    new_children: list[TreeNode] = []
    for c in root.children:
        new_children.append(unwrap_single_child(c))
    root.children = new_children

    # Then try to collapse this node if it qualifies and has one child.
    if _can_unwrap(root):
        only = root.children[0]
        return _merge_into(root, only)
    return root
