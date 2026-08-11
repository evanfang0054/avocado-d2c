"""Layout strategy: Figma Auto Layout → CSS Flexbox.

(see project design docs)

Figma Auto Layout fields (REST API):
  layoutMode                 → HORIZONTAL | VERTICAL | NONE
  primaryAxisAlignItems      → MIN | CENTER | MAX | SPACE_BETWEEN  (justify-content)
  counterAxisAlignItems      → MIN | CENTER | MAX                  (align-items)
  itemSpacing                → gap (px)
  paddingTop/Right/Bottom/Left → padding
  layoutWrap                 → NO_WRAP | WRAP
  layoutSizingHorizontal     → FIXED | HUG | FILL  (newer field, replaces primaryAxisSizingMode)
  layoutSizingVertical       → FIXED | HUG | FILL
  layoutAlign                → INHERIT | STRETCH   (per-child)
  layoutGrow                 → 0 | 1                (per-child, flex-grow)
  layoutPositioning          → AUTO | ABSOLUTE      (per-child, position:absolute)

Mapping (design docs):
  HORIZONTAL → display:flex; flex-direction:row
  VERTICAL   → display:flex; flex-direction:column
"""

from __future__ import annotations

from avocado.model.scene_node import SceneNode
from avocado.model.tree_node import TreeNode

# ── alignment maps ──
# Figma primaryAxisAlignItems → justify-content
_JUSTIFY = {
    "MIN": "flex-start",
    "CENTER": "center",
    "MAX": "flex-end",
    "SPACE_BETWEEN": "space-between",
}
# Figma counterAxisAlignItems → align-items
_ALIGN = {
    "MIN": "flex-start",
    "CENTER": "center",
    "MAX": "flex-end",
}


def is_auto_layout(scene: SceneNode) -> bool:
    """True if this node uses Auto Layout (HORIZONTAL or VERTICAL)."""
    return scene.layout_mode in ("HORIZONTAL", "VERTICAL")


def apply_container_layout(scene: SceneNode, tree: TreeNode) -> None:
    """Set Flex CSS on a container TreeNode when it uses Auto Layout.

    Call this after _base_style() and visual styles are populated.
    """
    if not is_auto_layout(scene):
        tree.layout_strategy = "leaf" if not scene.children else "auto_group"
        return

    tree.layout_strategy = "auto_layout"
    s = tree.style
    s["display"] = "flex"
    s["flex-direction"] = "row" if scene.layout_mode == "HORIZONTAL" else "column"

    # justify-content / align-items
    if scene.primary_axis_align_items in _JUSTIFY:
        s["justify-content"] = _JUSTIFY[scene.primary_axis_align_items]
    if scene.counter_axis_align_items in _ALIGN:
        s["align-items"] = _ALIGN[scene.counter_axis_align_items]

    # gap (itemSpacing). Some Figma files omit it → default 0.
    # When justify-content is space-between / space-around / space-evenly,
    # CSS spec says `gap` is *added* on top of the distributed free space —
    # which double-counts the spacing and can blow total width past the
    # container (e.g. iOS status bar row: 3 children + 134px gap + 375px
    # width → last child pushed off-screen). Figma's `itemSpacing` with
    # SPACE_BETWEEN means "minimum gap if there's slack", which is already
    # what space-between distributes. So skip `gap` for distributed modes.
    if (
        scene.item_spacing
        and scene.item_spacing > 0
        and scene.primary_axis_align_items not in ("SPACE_BETWEEN",)
        # NOTE: Figma only exposes SPACE_BETWEEN for primaryAxisAlignItems,
        # not SPACE_AROUND/SPACE_EVENLY, so we only need to skip that one.
    ):
        s["gap"] = f"{_num(scene.item_spacing)}px"

    # padding (concatenated shorthand when all 4 are present and equal-ish)
    pt, pr, pb, pl = (
        scene.padding_top,
        scene.padding_right,
        scene.padding_bottom,
        scene.padding_left,
    )
    non_zero = [x for x in (pt, pr, pb, pl) if x and x > 0]
    if non_zero:
        # Use 4-value form for accuracy
        s["padding"] = f"{_num(pt)}px {_num(pr)}px {_num(pb)}px {_num(pl)}px"

    # flex-wrap
    if scene.layout_mode and getattr(scene, "layout_wrap", None) == "WRAP":
        s["flex-wrap"] = "wrap"

    # Layout fix: when a FRAME has layoutPositioning=ABSOLUTE children,
    # position:relative is needed as the positioning anchor for the absolute
    # children. Otherwise absolute children position against a higher
    # ancestor, breaking Bottom Sheet/overlay layers.
    has_absolute_children = any(
        getattr(c, "raw", {}) and c.raw.get("layoutPositioning") == "ABSOLUTE"
        for c in (scene.children or [])
    )
    if has_absolute_children:
        s["position"] = "relative"

    # ── overflow detection ──
    # When in-flow children's main-axis positions indicate a scroller (e.g.
    # horizontal card list: 3 cards at x=0, 323, 646 in a 327-wide parent),
    # Figma renders them as overflowing. CSS flex would shrink them by
    # default; we emit overflow + nowrap so the layout matches Figma.
    # Detection: only look at in-flow children (those positioned sequentially
    # by Auto Layout, i.e. their main-axis positions form a sequence
    # 0, size+gap, 2*(size+gap), …). Absolutely-positioned siblings are
    # excluded to avoid false positives.
    #
    # WRAP short-circuit: a Figma `layoutWrap: WRAP` container is meant to
    # wrap children onto multiple lines, not scroll. The 1.3× overflow
    # heuristic below would falsely flag a wrapped row (e.g. 6 logos in a
    # 2-column wrap) as a scroller, override flex-wrap to nowrap, and push
    # children off-screen. Skip the heuristic entirely when the source node
    # opted into wrap.
    is_wrap = getattr(scene, "layout_wrap", None) == "WRAP"
    # If the node explicitly declares an overflowDirection (Figma scroll
    # container), style_from_scene already emitted the matching
    # overflow-x/y:hidden. Skip the 1.3× heuristic — it would overwrite
    # that with overflow-x:visible and re-introduce the spillover bug
    # (sample_page_001 horizontal scroller: 4 cards declared as
    # HORIZONTAL_SCROLLING, Figma clips to viewport, but heuristic sets
    # overflow-x:visible and shows all 4).
    has_explicit_overflow = bool(getattr(scene, "overflow_direction", None))
    if (
        scene.box
        and scene.children
        and len(scene.children) >= 2
        and not is_wrap
        and not has_explicit_overflow
    ):
        pb_x, pb_y = scene.box.x, scene.box.y
        pb_w, pb_h = scene.box.width, scene.box.height
        # Identify in-flow children: their main-axis position is within
        # [parent_origin, parent_origin + parent_size] (not floating far away)
        if scene.layout_mode == "HORIZONTAL":
            in_flow = [
                c
                for c in scene.children
                if c.box and abs(c.box.x - pb_x) < pb_w  # starts near parent's left
            ]
            if len(in_flow) >= 2:
                # Check if children are laid out sequentially (each starts
                # after previous one ends)
                sorted_cf = sorted(in_flow, key=lambda c: c.box.x)
                # If the LAST child ends way beyond parent's right, it's a scroller
                last_end = sorted_cf[-1].box.x + sorted_cf[-1].box.width
                if last_end > pb_x + pb_w * 1.3:
                    # overflow:visible lets children extend past parent's edge
                    # (matching Figma's clipsContent:false semantics — only
                    # ancestor frames with clipsContent:true cut them off).
                    # The root element's overflow:hidden provides the final clip.
                    # NOTE: We tested overflow:hidden as part of the fidelity work
                    # and it made things WORSE because Figma's PNG export of
                    # the node includes overflowed siblings (they're rendered
                    # to the canvas before clipping). Matching that requires
                    # visible. See ADR in CLAUDE.md.
                    s["overflow-x"] = "visible"
                    s["flex-wrap"] = "nowrap"
                    # Remove min-width:0 so the flex container can grow to
                    # fit its in-flow children (otherwise the parent's FILL
                    # min-width:0 keeps it at zero and the cards collapse).
                    s.pop("min-width", None)
        elif scene.layout_mode == "VERTICAL":
            in_flow = [
                c
                for c in scene.children
                if c.box and abs(c.box.y - pb_y) < pb_h  # starts near parent's top
            ]
            if len(in_flow) >= 2:
                sorted_cf = sorted(in_flow, key=lambda c: c.box.y)
                last_end = sorted_cf[-1].box.y + sorted_cf[-1].box.height
                if last_end > pb_y + pb_h * 1.3:
                    s["overflow-y"] = "auto"
                    s["flex-wrap"] = "nowrap"


# ── container sizing ──
# Always preserve absoluteBoundingBox dimensions for containers. FILL/HUG
# in Figma describe how the node resizes in editor; for CSS rendering we
# want the actual bbox to be the rendered size. This avoids flex-collapse
# in deeply nested FILL chains.
# We do NOT remove width/height from _base_style.
#
# Note: layoutSizingHorizontal/Vertical from raw are intentionally NOT read
# here — _base_style already set width/height from bbox. If HUG, the bbox
# is what the browser would compute anyway but explicit is safer for nested
# flex. If FILL, bbox is what Figma measured for the rendered output — keep
# it. Only if width/height is truly absent (e.g. text node without bbox) do
# we let the browser compute.
# → No-op here: _base_style already set width/height from bbox.


def _apply_container_sizing(scene: SceneNode, tree: TreeNode) -> None:
    """Deprecated stub. Sizing now handled by _base_style (always uses bbox).

    Kept for backward compat with any external callers; no-op.
    """
    return None


def apply_child_layout(
    scene: SceneNode,
    tree: TreeNode,
    parent_layout_mode: str | None = None,
    parent_box=None,
) -> None:
    """Set per-child flex props based on layoutAlign / layoutGrow / sizing.

    Empirically-tuned final: the over-eager flex-grow both directions
    gives the best odiff score on the Confirm fixture (~73%). More refined
    main/cross distinction regressed to ~65% because cross-axis width-drop
    left nodes without any width reference.

    Known limitation: for designs where this is wrong, use --layout=absolute
    or post-process the output.
    """
    raw = scene.raw or {}
    h_size = raw.get("layoutSizingHorizontal")  # FIXED / HUG / FILL
    v_size = raw.get("layoutSizingVertical")

    # layoutGrow (Figma native signal)
    if scene.layout_grow and scene.layout_grow > 0:
        tree.style["flex-grow"] = _num(scene.layout_grow)

    # FILL → flex-grow:1 + drop dimension on the MAIN axis only.
    # Cross-axis FILL (e.g. horizontal FILL inside a VERTICAL parent) means
    # "stretch to parent width" and is handled by align-self:stretch (set
    # from layoutAlign=STRETCH below). Adding flex-grow on cross-axis FILL
    # was the root cause of H5 layout drift: it made HUG-height children
    # expand vertically and pushed siblings out of position.
    is_main_h = parent_layout_mode == "HORIZONTAL"
    is_main_v = parent_layout_mode == "VERTICAL"

    if h_size == "FILL":
        if is_main_h:
            tree.style["flex-grow"] = 1
            tree.style["flex-basis"] = "0"
            tree.style.pop("width", None)
            tree.style["min-width"] = "0"
    if v_size == "FILL":
        if is_main_v:
            tree.style["flex-grow"] = 1
            tree.style["flex-basis"] = "0"
            tree.style.pop("height", None)
            tree.style["min-height"] = "0"

    # Main-axis FIXED or HUG sizing → flex-shrink:0 so the child's main-axis
    # dimension (width/height) is respected by the flex algorithm. Without this,
    # a flex container that overflows would shrink FIXED/HUG children.
    #
    # originally used `flex: none` (= grow:0; shrink:0; basis:auto) for
    # stronger protection, but empirical testing showed it's unnecessary:
    # FIXED/HUG children have explicit width/height, and their default
    # flex-basis:auto is computed from that size — FILL siblings with
    # flex-basis:0 + flex-grow:1 only consume leftover space, they don't
    # steal from FIXED siblings. `flex-shrink:0` alone is sufficient and
    # produces much cleaner output (96 `flex:none` → 0 per confirm fixture).
    # See readability optimization plan for regression methodology.
    if parent_layout_mode == "HORIZONTAL" and h_size in ("FIXED", "HUG") and "width" in tree.style:
        tree.style["flex-shrink"] = 0
    elif parent_layout_mode == "VERTICAL" and v_size in ("FIXED", "HUG") and "height" in tree.style:
        tree.style["flex-shrink"] = 0

    # layoutAlign STRETCH → align-self: stretch — BUT only when the cross-axis
    # dimension is NOT explicitly set. Figma's STRETCH + explicit width means
    # "use this width, centered" (the stretch is advisory). CSS align-self:
    # stretch would override align-items:center and left-align the element,
    # breaking the layout for centered cards with explicit widths.
    if scene.layout_align == "STRETCH":
        # Cross-axis dimension check: horizontal parent → width is cross-axis;
        # vertical parent → height is cross-axis.
        cross_has_size = (parent_layout_mode == "HORIZONTAL" and "width" in tree.style) or (
            parent_layout_mode == "VERTICAL" and "height" in tree.style
        )
        if not cross_has_size:
            tree.style["align-self"] = "stretch"

    # layoutPositioning ABSOLUTE → position:absolute + top/left from bbox
    if raw.get("layoutPositioning") == "ABSOLUTE":
        tree.style["position"] = "absolute"
        tree.layout_strategy = "absolute_position"
        # Compute coords relative to parent's padding box (like Figma)
        if parent_box and scene.box:
            tree.style["top"] = f"{_num(scene.box.y - parent_box.y)}px"
            _left_rel = scene.box.x - parent_box.x
            # FIX:：detect "absolute + negative left = centered title" pattern.
            # Figma designers sometimes use absolute positioning with negative left to
            # visually center a title wider than its parent. Raw `left: -51px` clips the
            # text. Heuristic: if left is negative AND the child appears horizontally
            # centered (left ≈ (parent_w - child_w) / 2), emit align-self:center instead
            # of negative left. Only applies to cross-axis (horizontal) centering.
            _parent_w = parent_box.width or 0
            _child_w = scene.box.width or 0
            if (
                _left_rel < 0
                and _child_w > 0
                and _parent_w > 0
                and _child_w > _parent_w  # child wider than parent (overflow = centering)
            ):
                _expected_center = (_parent_w - _child_w) / 2
                if abs(_left_rel - _expected_center) <= 5:  # 5px tolerance
                    # Convert to centered layout instead of negative offset
                    tree.style["align-self"] = "center"
                    tree.style["left"] = "50%"
                    tree.style["transform"] = "translateX(-50%)"
                    tree.style.pop("position", None)
                    tree.style.pop("top", None)
                    tree.layout_strategy = "flex_centered"
                    return
            tree.style["left"] = f"{_num(_left_rel)}px"


def _num(v: float, ndigits: int = 2) -> float | int:
    rounded = round(float(v), ndigits)
    if rounded == int(rounded):
        return int(rounded)
    return rounded
