"""Absolute positioning strategy: when sibling nodes overlap or are
scattered without Auto Layout, wrap them in a relative-positioned
container and absolutely-position each child.

(see project design docs)

Trigger conditions:
  - Parent has NO Auto Layout (layout_mode not in HORIZONTAL/VERTICAL)
  - AND children have non-trivial bounding boxes
  - AND EITHER children overlap OR children are not naturally arranged

Coordinate system:
  Each child's top/left is computed RELATIVE TO PARENT (subtract parent
  box.x/y from child box.x/y). This matches Figma's absoluteBoundingBox
  convention (which is in file-absolute coords).

  For multi-level nesting, each child gets coordinates relative to its
  DIRECT parent (not grandparent). This keeps the output DRY and matches
  what D2C does.
"""

from __future__ import annotations

from avocado.model.scene_node import Box, SceneNode
from avocado.model.tree_node import TreeNode

# Minimum overlap area (px²) to consider siblings "overlapping"
OVERLAP_THRESHOLD = 100.0


def needs_absolute_strategy(scene: SceneNode) -> bool:
    """True if this FRAME/GROUP should use absolute positioning.

    (see project design docs):
      - has children
      - no Auto Layout
      - children have bounding boxes
    """
    if scene.type not in ("FRAME", "GROUP", "COMPONENT", "INSTANCE", "SLOT"):
        return False
    if scene.layout_mode in ("HORIZONTAL", "VERTICAL"):
        return False
    if not scene.children:
        return False
    # At least 1 child with a box (single child can still need absolute
    # positioning, e.g. an icon placed at a specific corner).
    with_boxes = [c for c in scene.children if c.box]
    return len(with_boxes) >= 1


def children_overlap(children: list[SceneNode]) -> bool:
    """Pairwise check: do any two siblings overlap significantly?"""
    boxes = [(c, c.box) for c in children if c.box]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _overlap_area(boxes[i][1], boxes[j][1]) > OVERLAP_THRESHOLD:
                return True
    return False


def _overlap_area(a: Box, b: Box) -> float:
    ox = max(0.0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x))
    oy = max(0.0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))
    return ox * oy


def apply_absolute_layout(scene: SceneNode, tree: TreeNode) -> bool:
    """If scene needs absolute positioning, mutate tree.style and tree.children.

    Returns True if applied, False otherwise.

    Note: if this node is itself an absolute child of a parent (its
    tree.style['position'] already == 'absolute'), we don't promote it to
    'relative' — that would break the parent's coordinate system. The node
    keeps its absolute position; its own children become absolute relative
    to IT, which works because the node has its own box.

    Side effects when applied:
      - tree.style["position"] = "relative"
      - each child.style["position"] = "absolute"
      - each child.style["top"]/["left"] = computed coords
      - each child.style drops width/height? NO — keep for absolute box size
      - tree.layout_strategy = "absolute_position"
    """
    if not needs_absolute_strategy(scene):
        return False

    parent_box = scene.box
    if not parent_box:
        # No box to anchor to — can't compute coords
        return False

    # Promote THIS container to relative — UNLESS it's already 'absolute'
    # from a parent's absolute strategy. In that case keep position:absolute
    # (which is also a valid positioning context in CSS for children).
    if tree.style.get("position") != "absolute":
        tree.style["position"] = "relative"
    tree.layout_strategy = "absolute_position"

    for child in tree.children:
        # Find matching scene child for box data
        scene_child = next((c for c in scene.children if c.id == child.figma_id), None)
        if not scene_child or not scene_child.box:
            continue
        cb = scene_child.box
        # Unconditionally mark as absolute. Even if the child recursively
        # applied absolute_layout to ITSELF earlier (turning itself into a
        # 'relative' positioning context for its own children), the parent
        # here overrides to 'absolute' — the child's own children's coords
        # are still relative to the child's box (which is correct in CSS:
        # an absolutely-positioned element is also a containing block for
        # its absolutely-positioned descendants).
        child.style["position"] = "absolute"
        child.style["top"] = f"{_num(cb.y - parent_box.y)}px"
        child.style["left"] = f"{_num(cb.x - parent_box.x)}px"
    # width/height stay (they describe the absolute box size)

    return True


def _num(v: float, ndigits: int = 2) -> float | int:
    rounded = round(float(v), ndigits)
    if rounded == int(rounded):
        return int(rounded)
    return rounded
