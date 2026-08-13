"""Convert SceneNode tree → TreeNode tree.

Scope: FRAME/RECTANGLE/TEXT/INSTANCE basic mapping. Layout strategy
is a separate concern — here we just dump children as flat div nesting.

(see project design docs):
  FRAME      → <div> + recurse children
  RECTANGLE  → <div> with bg/radius; OR <img> if ImagePaint
  TEXT       → <span> with characters
  INSTANCE   → <div> for now
  GROUP      → wrapper <div> with position:relative
  VECTOR etc → <div> fallback
"""

from __future__ import annotations

from avocado.api.figma import FigmaClient
from avocado.model.scene_node import SceneNode
from avocado.model.tree_node import TreeNode
from avocado.parser.absolute_layout import apply_absolute_layout
from avocado.parser.component import ComponentMapping, apply_component
from avocado.parser.image import is_image_node, render_as_image
from avocado.parser.layout import (
    apply_child_layout,
    apply_container_layout,
    is_auto_layout,
)
from avocado.parser.style import style_from_scene
from avocado.parser.text import render_text_node

# ── per-type tag selection ────────────────────────────────────────────────────


def _tag_for(scene: SceneNode) -> str:
    """Map Figma node type → JSX tag name."""
    if scene.type == "TEXT":
        return "span"
    if scene.type == "RECTANGLE":
        return "div"
    if scene.type == "ELLIPSE":
        # This becomes div with border-radius:50%. Plain div fallback is fine.
        return "div"
    if scene.type in ("FRAME", "GROUP", "COMPONENT", "INSTANCE", "SLOT"):
        return "div"
    if scene.type == "SECTION":
        return "section"
    if scene.type in ("VECTOR", "LINE", "STAR", "POLYGON"):
        return "img"
    return "div"


# Figma sometimes records OS-specific font names that Chrome headless cannot
# resolve without a fallback chain, so it falls back to generic sans with
# different metrics. Mapping known names to OS stacks was considered — see the
# note below.
_FONT_SYSTEM_MAP = {
    # Intentionally empty: remapping known OS font names to their system
    # stack makes things WORSE on macOS Chrome (the stack resolves to a
    # different face with different metrics than the real font). Keep
    # Figma's name verbatim.
}


def _font_family_with_fallback(name: str) -> str:
    """Wrap font name with proper quoting + sans-serif fallback (unused stub)."""
    if not name:
        return name
    return f'"{name}", sans-serif'


def _apply_boolean_mask(scene: SceneNode, tree: TreeNode) -> None:
    """Color a BOOLEAN_OPERATION icon via CSS mask.

    Figma API renders the boolean's descendant VECTOR as SVG with
    fill="black", regardless of the boolean's own SOLID fill color. We
    keep the boolean's fill color as background-color and use the SVG as
    a mask, so the color only shows through the icon shape. The child
    <img> (which would draw black) is hidden via display:none.

    Skips silently when the boolean has no SOLID fill or no descendant img.
    """
    # Find first visible SOLID fill color.
    target_hex = None
    for paint in scene.fills or []:
        if not getattr(paint, "visible", True):
            continue
        if getattr(paint, "type", None) != "SOLID":
            continue
        col = getattr(paint, "color", None)
        if col is None:
            continue
        r = int(round(col.r * 255))
        g = int(round(col.g * 255))
        b = int(round(col.b * 255))
        target_hex = f"#{r:02x}{g:02x}{b:02x}"
        break
    if target_hex is None:
        return
    # Black fills: no mask needed (SVG already renders black).
    if target_hex.lower() == "#000000":
        # Still drop background-color to avoid the rectangle occlusion.
        tree.style.pop("background-color", None)
        tree.style.pop("background", None)
        return
    # Find first descendant <img> src to use as mask.
    svg_src = None
    stack = list(tree.children or [])
    while stack:
        node = stack.pop()
        if getattr(node, "is_img", False) and node.props.get("src"):
            svg_src = node.props["src"]
            break
        stack.extend(node.children or [])
    if not svg_src:
        # No child SVG — drop bg as before to avoid rectangle occlusion.
        tree.style.pop("background-color", None)
        tree.style.pop("background", None)
        return
    # Convert SVG file path to data URI — `file://` mask URLs are blocked
    # by Chrome's CORS policy in headless mode (verified: data URIs work,
    # absolute file paths render nothing). Inline the SVG as base64.
    # Also: SVG paths use fill="black" by default, but CSS mask defaults to
    # luminance mode where black=luminance 0=fully transparent (icon shape
    # hidden). Replace fill="black" → fill="white" so the path becomes
    # opaque in luminance mode. (mask-mode:alpha has spotty browser
    # support; rewriting fill is more reliable.)
    mask_url = svg_src
    try:
        import base64 as _b64
        import re as _re
        from pathlib import Path as _P

        p = _P(svg_src)
        if p.exists() and p.is_file():
            data = p.read_text(encoding="utf-8")
            data = _re.sub(r'fill="black"', 'fill="white"', data)
            data = _re.sub(r'fill="#000000"', 'fill="white"', data)
            data = _re.sub(r'fill="#000"', 'fill="white"', data)
            data_bytes = data.encode("utf-8")
            mask_url = f"data:image/svg+xml;base64,{_b64.b64encode(data_bytes).decode('ascii')}"
    except Exception:
        pass
    # Apply mask + bg color; hide the child img (mask already draws shape).
    tree.style["background-color"] = target_hex
    # CSS mask: reference the SVG via data URI (file:// blocked by CORS).
    # NOTE: the value is later quoted by the style renderer; here we just
    # store the URL body without outer quotes — codegen wraps the entire
    # `mask-image: ...` value. We use single quotes inside to survive HTML
    # attribute parsing (the outer style="..." uses double quotes).
    tree.style["-webkit-mask-image"] = f"url('{mask_url}')"
    tree.style["mask-image"] = f"url('{mask_url}')"
    tree.style["-webkit-mask-size"] = "100% 100%"
    tree.style["mask-size"] = "100% 100%"
    tree.style["-webkit-mask-position"] = "center"
    tree.style["mask-position"] = "center"
    tree.style["-webkit-mask-repeat"] = "no-repeat"
    tree.style["mask-repeat"] = "no-repeat"

    # Hide all child img nodes (they would draw black on top of the mask).
    def _hide_imgs(n: TreeNode) -> None:
        if getattr(n, "is_img", False):
            n.style["display"] = "none"
        for c in n.children or []:
            _hide_imgs(c)

    for c in tree.children or []:
        _hide_imgs(c)


# ── per-type base style ───────────────────────────────────────────────────────


def _base_style(scene: SceneNode) -> dict[str, str | float]:
    """Size + box positioning for any node."""
    out: dict[str, str | float] = {}
    if scene.box:
        out["width"] = f"{_num(scene.box.width)}px"
        out["height"] = f"{_num(scene.box.height)}px"
    return out


def _text_style(scene: SceneNode) -> dict[str, str | float]:
    """TEXT-only style. (see project design docs)"""
    if not scene.text_style:
        return {}
    ts = scene.text_style
    out: dict[str, str | float] = {}

    # Text color = first SOLID fill on the TEXT node
    for p in scene.fills:
        if p.visible and p.type == "SOLID" and p.color:
            col = p.color
            # paint opacity applies to alpha
            if p.opacity < 1.0 and col.a >= 1.0:
                from avocado.model.scene_node import Color

                col = Color(col.r, col.g, col.b, p.opacity)
            out["color"] = col.to_rgba_str()
            break

    if ts.font_family:
        # Quote multi-word family names + add a sans-serif generic fallback.
        # We do NOT remap known OS font names to their system stack: tests
        # show the stack resolves to a different face with different metrics
        # than the original name (which the browser can resolve via the OS
        # font registry when installed). Keep the original name verbatim.
        fam = ts.font_family.strip()
        if " " in fam or fam.lower() not in ("serif", "sans-serif", "monospace"):
            # Quote if multi-word or not a generic family keyword.
            fam = f'"{fam}", sans-serif' if " " in fam else f"{fam}, sans-serif"
        out["font-family"] = fam
    if ts.font_size is not None:
        out["font-size"] = f"{_num(ts.font_size)}px"
    if ts.font_weight is not None:
        out["font-weight"] = (
            int(ts.font_weight) if float(ts.font_weight).is_integer() else _num(ts.font_weight)
        )
    if ts.font_style == "Italic":
        out["font-style"] = "italic"
    if ts.text_align_horizontal and ts.text_align_horizontal != "LEFT":
        out["text-align"] = ts.text_align_horizontal.lower()
    if ts.text_decoration == "UNDERLINE":
        out["text-decoration"] = "underline"
    elif ts.text_decoration == "STRIKETHROUGH":
        out["text-decoration"] = "line-through"
    if ts.text_case == "UPPER":
        out["text-transform"] = "uppercase"
    elif ts.text_case == "LOWER":
        out["text-transform"] = "lowercase"
    elif ts.text_case == "TITLE":
        out["text-transform"] = "capitalize"
    if ts.letter_spacing is not None:
        out["letter-spacing"] = f"{_num(ts.letter_spacing)}px"
    # lineHeight: all 4 units per design docs
    if ts.line_height_unit == "PIXELS" and ts.line_height_px is not None:
        out["line-height"] = f"{_num(ts.line_height_px)}px"
    elif ts.line_height_unit == "PERCENT" and ts.line_height_percent is not None:
        # Figma percent is 0-100 → CSS percent
        out["line-height"] = f"{_num(ts.line_height_percent)}%"
    elif ts.line_height_unit == "INSIDE" and ts.line_height_percent is not None:
        # "Inside" auto-resizes box to fit; CSS approximation: percent of fontSize
        out["line-height"] = f"{_num(ts.line_height_percent)}%"
    # AUTO or unit=None: omit line-height (browser default)
    return out


# ── main mapper ───────────────────────────────────────────────────────────────


def map_node(
    scene: SceneNode,
    parent_auto_layout: bool = False,
    parent_layout_mode: str | None = None,
    *,
    client: FigmaClient | None = None,
    file_key: str | None = None,
    component_mapping: list[ComponentMapping] | None = None,
    layout_mode: str = "flex",
    parent_box=None,
    parent_visible: bool = True,
    trace_path: list[str] | None = None,
    _trace_on: bool | None = None,
) -> TreeNode:
    """Recursively convert a SceneNode tree into a TreeNode tree.

    Args:
        parent_auto_layout: True if parent uses Auto Layout.
        client: optional FigmaClient for image export. If None, image nodes
            emit placeholder src.
        file_key: Figma file key for image export (required if client given).
        component_mapping: optional list of ComponentMapping entries for
            INSTANCE → business component recognition.
        layout_mode: 'flex' (default) or 'absolute' (every node
            uses position:absolute with bbox coords, bypassing flex nesting).
        parent_box: parent's Box (internal use for absolute mode).
        parent_visible: True if all ancestors are visible (fix for
            Figma INSTANCE overrides where INSTANCE is hidden but child
            marked visible=True — we treat such children as hidden).
    """
    import os as _os

    mapping = component_mapping or []

    # Trace enablement is computed once at the root and threaded down via the
    # private _trace_on flag — recursion reuses it instead of querying the
    # trace registry on every node (zero-overhead when trace is disabled).
    if _trace_on is None:
        from avocado.parser.trace import is_enabled as _trace_enabled

        _trace_on = _trace_enabled("preset_matches")

    # Inherited visibility. Drop node entirely if any ancestor is hidden.
    effective_visible = parent_visible and scene.visible
    if not effective_visible:
        return None  # type: ignore[return-value]

    style: dict[str, str | float] = {}
    style.update(_base_style(scene))
    # TEXT nodes: fills are the text COLOR, not background — skip style_from_scene's
    # background-color logic for them. text color is set in _text_style.
    if scene.type != "TEXT":
        # Resolve image fills map (lazily per call) so nodes with mixed
        # IMAGE+SOLID fills can emit background-image layers for the IMAGE
        # paints. Single-IMAGE nodes are handled by render_as_image below
        # and don't need this — we only need the map when the node has >1
        # fill or mixed types.
        image_fills_map: dict[str, str] | None = None
        # Single-IMAGE-fill nodes: if they have visible
        # children, is_image_node returns False, so they don't go through
        # render_as_image and need style.py's IMAGE-fill background-image
        # path instead.
        # These nodes therefore also need image_fills_map (previously skipped
        # by the single-IMAGE-fill condition at lines 295-298).
        _has_visible_children = any(c.visible for c in (scene.children or []))
        if (
            client is not None
            and file_key
            and any(p.visible and p.type == "IMAGE" for p in scene.fills)
            and not (
                len([p for p in scene.fills if p.visible]) == 1
                and scene.fills[0].type == "IMAGE"
                and not _has_visible_children  # single IMAGE fill with children also needs the fills map
            )
        ):
            _os.environ.setdefault("FIGMA_FILE_KEY", file_key)
            try:
                image_fills_map = client.get_image_fills(file_key)
            except Exception:
                image_fills_map = None
        style.update(style_from_scene(scene, image_fills_map=image_fills_map))

    # BOOLEAN_OPERATION: handled below — bg is dropped to avoid rectangle
    # occlusion (the SVG child already draws the icon shape).

    tag = _tag_for(scene)
    text_content: str | None = None
    if scene.type == "TEXT":
        text_content = scene.characters or ""
        style.update(_text_style(scene))

    children = [
        n
        for n in (
            map_node(
                c,
                parent_auto_layout=is_auto_layout(scene),
                parent_layout_mode=scene.layout_mode,
                client=client,
                file_key=file_key,
                component_mapping=mapping,
                layout_mode=layout_mode,
                parent_box=scene.box,
                parent_visible=effective_visible,
                trace_path=([*(trace_path or []), scene.name] if _trace_on else None),
                _trace_on=_trace_on,
            )
            for c in scene.children
        )
        if n is not None
    ]

    # Leaf components may have stashed "extra" subtrees (helper
    # text / error message / etc.) that the component itself does NOT
    # render. Promote them to siblings of the leaf node so they still
    # appear in the output. They live in node.props as a list.
    extra_added: list[TreeNode] = []
    for child in children:
        extras = child.props.pop("_leaf_extras", None)
        if extras:
            extra_added.extend(extras)
    if extra_added:
        children.extend(extra_added)

    # BOOLEAN_OPERATION children: when the parent is a Boolean op (Union /
    # Subtract / Intersect / Exclude), Figma composes the children's vector
    # geometry into a single shape. RECTANGLE children inside it represent
    # the rectangle's geometry as input to the boolean op — NOT a visible
    # filled rectangle. Without this drop, d2c emits a solid grey <div>
    # that occludes the icon path (observed on sample_page_002 'Rectangle 14'
    # inside Union: parent fill is white, child Rectangle 14 fill is grey,
    # Figma shows only the union's outline shape but d2c paints the full
    # 327×323 grey rectangle, costing ~9% fidelity on sample_page_002).
    if scene.type == "BOOLEAN_OPERATION":
        for child in children:
            if child.source_type == "RECTANGLE":
                child.style.pop("background-color", None)
                child.style.pop("background", None)

    if not scene.visible:
        style["display"] = "none"

    tree = TreeNode(
        id=scene.id,
        name=scene.name,
        source_type=scene.type,
        tag_name=tag,
        style=style,
        children=children,
        text_content=text_content,
        figma_id=scene.id,
    )

    # Rich text: split characters into nested spans per style override.
    # This overrides the simple text_content with structured children.
    if scene.type == "TEXT":
        render_text_node(scene, tree)

    # Image: if this node has a single IMAGE paint, render as <img>.
    # Must happen before layout so layout doesn't add bg-color etc.
    if is_image_node(scene) and scene.type != "TEXT":
        if file_key:
            _os.environ.setdefault("FIGMA_FILE_KEY", file_key)
        render_as_image(scene, tree, client=client)

    # The childless FRAME/INSTANCE → img approach was rolled back — too
    # aggressive and repeatedly regressed (cancel_modal -41.7%,
    # detail/sample_page_002/map -7~11%). It's impossible to tell which should
    # convert and which shouldn't.
    # Empty nodes (Figma API returns no children) are instead handled
    # case-by-case by the AI fidelity-boost skill.

    # BOOLEAN_OPERATION: drop bg (it would draw a solid rectangle that
    # occludes the icon shape). The SVG child already carries the shape.
    # We attempted a CSS mask + bg color scheme to also recover the
    # correct icon color (Figma API renders SVG with fill=black), but
    # the per-icon contribution to overall odiff is < 0.01% — not worth
    # the complexity. Sticking with the simple "drop bg" fix.
    if scene.type == "BOOLEAN_OPERATION":
        tree.style.pop("background-color", None)
        tree.style.pop("background", None)

    # Component recognition: if INSTANCE matches user mapping, swap tag.
    # Skip for image nodes (image always wins).
    if not tree.is_img and scene.type == "INSTANCE":
        if apply_component(scene, tree, mapping, trace_path=trace_path):
            pass  # recognized — tag_name etc. already set
        else:
            # Not in mapping → emit warning
            tree.add_inspect(
                severity="info",
                code="instance-not-recognized",
                message=f"INSTANCE {scene.name!r} (componentId={scene.component_id!r}) "
                "not in component mapping table; rendering as <div>.",
            )
            # Fallback for childless INSTANCE with a TEXT componentProperty
            # (e.g. Badge/Label whose internal DOM lives in the component
            # definition, which offline mode doesn't fetch). Without this the
            # node renders as an empty <div> and its label text vanishes,
            # exposing whatever sits behind it (card images, etc.). We only
            # synthesize text — visual styling (bg/radius) stays to the
            # component's own style so we don't fabricate colors.
            if not tree.children and not tree.text_content:
                cp = scene.component_properties or {}
                label = next(
                    (
                        v.get("value")
                        for v in cp.values()
                        if isinstance(v, dict) and v.get("type") == "TEXT" and v.get("value")
                    ),
                    None,
                )
                if label:
                    tree.text_content = label

    # empty_divs fix already extracted to a shared location (after
    # is_image_node, all childless INSTANCE/FRAME/RECTANGLE ≥40×40
    # go through render_as_image). Not repeated here.

    # ── absolute layout mode ──
    # In absolute mode, ALL non-root nodes get position:absolute with
    # coords relative to ROOT (not direct parent). This requires each
    # absolute parent to be `position: relative` (which absolute also is).
    # CSS rule: position:absolute is relative to nearest positioned ancestor,
    # and an absolute element IS positioned, so nested absolutes use the
    # direct parent. To make all absolutes relative to ROOT, intermediate
    # containers must NOT be positioned — but they need to be for their own
    # children. Solution: compute top/left relative to ROOT here, and
    # intermediate positioned ancestors are still OK because they ARE the
    # root's positioned chain (each child's bbox subtract parent's bbox,
    # which gives "relative to direct parent" coords — these chain up
    # correctly through absolute ancestors).
    #
    # In short: existing "relative to direct parent" logic IS
    # correct for nested absolute containers. The 56% bug was elsewhere.
    if layout_mode == "absolute" and parent_box is not None and scene.box:
        tree.style["position"] = "absolute"
        tree.style["top"] = f"{_num(scene.box.y - parent_box.y)}px"
        tree.style["left"] = f"{_num(scene.box.x - parent_box.x)}px"
        tree.layout_strategy = "absolute_position"
    elif layout_mode == "absolute" and parent_box is None:
        # root: position:relative so children's absolute coords resolve to it
        tree.style["position"] = "relative"
        tree.layout_strategy = "absolute_position"
    else:
        # flex mode: Apply layout strategy
        apply_container_layout(scene, tree)
        if parent_auto_layout:
            apply_child_layout(
                scene, tree, parent_layout_mode=parent_layout_mode, parent_box=parent_box
            )
        if tree.layout_strategy != "auto_layout":
            apply_absolute_layout(scene, tree)

        # ── Scroller fix-up: if apply_container_layout marked this node as
        # overflow-x/y:visible (a horizontal/vertical card scroller), drop
        # the min-width:0 / min-height:0 that apply_child_layout added for
        # FILL. Otherwise the scroller collapses to 0 and cards disappear.
        if tree.style.get("overflow-x") == "visible":
            tree.style.pop("min-width", None)
            tree.style.pop("flex-basis", None)
            tree.style["flex-grow"] = 0
            tree.style["flex-shrink"] = 0
        if tree.style.get("overflow-y") == "visible":
            tree.style.pop("min-height", None)
            tree.style.pop("flex-basis", None)
            tree.style["flex-grow"] = 0
            tree.style["flex-shrink"] = 0

        # ── Image nodes: strip flex props after layout ──
        # render_as_image ran earlier (before layout), but apply_child_layout
        # just re-added flex-grow / flex-basis / etc. for THIS node as if it
        # were a regular flex child. <img> tags must honor their explicit
        # width/height; flex-grow:1 + flex-basis:0 would override that.
        if tree.is_img:
            for k in (
                "flex-grow",
                "flex-basis",
                "align-self",
                "min-width",
                "min-height",
                "display",
                "flex-direction",
                "gap",
                "justify-content",
                "align-items",
                "padding",
            ):
                tree.style.pop(k, None)
            tree.style["flex-shrink"] = 0
            tree.style["flex-grow"] = 0
            # ── Restore width/height for non-FILL image dimensions ──
            # If the source FRAME had layoutSizing=FILL, apply_child_layout
            # popped the dimension and we want to keep it as 100% so the
            # image fills its parent's content box (matches Figma FILL
            # semantics, and avoids the 2-3px size drift when the parent
            # has a border that shrinks the content area).
            # For FIXED/HUG, restore from bbox so the <img> honors its
            # declared size.
            raw_scene = scene.raw or {}
            h_size = raw_scene.get("layoutSizingHorizontal")
            v_size = raw_scene.get("layoutSizingVertical")
            if h_size == "FILL" and "width" not in tree.style:
                tree.style["width"] = "100%"
            elif "width" not in tree.style and scene.box and scene.box.width:
                tree.style["width"] = f"{_num(scene.box.width)}px"
            if v_size == "FILL" and "height" not in tree.style:
                tree.style["height"] = "100%"
            elif "height" not in tree.style and scene.box and scene.box.height:
                tree.style["height"] = f"{_num(scene.box.height)}px"

    # Inspect warnings (minimal for now; will expand)
    if scene.type == "FRAME" and scene.layout_mode not in ("HORIZONTAL", "VERTICAL"):
        # No Auto Layout — D2C recommends Auto Layout for frames
        tree.add_inspect(
            severity="info",
            code="no-auto-layout",
            message=f"Frame {scene.name!r} has no Auto Layout; "
            "will fall back to absolute positioning.",
        )

    if scene.type == "INSTANCE" and not scene.component_id:
        tree.add_inspect(
            severity="warning",
            code="instance-no-component",
            message=f"INSTANCE {scene.name!r} has no componentId.",
        )

    return tree


def _should_include(scene: SceneNode) -> bool:
    """Filter out nodes D2C drops (only hide invisible)."""
    return scene.visible


def _num(v: float, ndigits: int = 2) -> float | int:
    """Round to N decimals; return int if whole number for cleaner output."""
    rounded = round(float(v), ndigits)
    if rounded == int(rounded):
        return int(rounded)
    return rounded
