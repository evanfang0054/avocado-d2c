"""Convert Figma visual properties to a CSS style dict.

Solid fills, corner radius, opacity, simple effects.
IndividualStrokeWeights per-edge borders.
strokeAlign three states / gradient fills / LAYER_BLUR+BACKGROUND_BLUR /
     rotation (relative_transform first) / blendMode / multi-layer fills /
     dashPattern.
"""

from __future__ import annotations

import math

from avocado.model.scene_node import (
    Color,
    Effect,
    Paint,
    SceneNode,
)

# Figma blendMode → CSS mix-blend-mode. PASS_THROUGH has no CSS equivalent
# (it means "do not isolate, blend as a group with backdrop"); we skip it
# so the element composites normally with its parent stacking context.
_FIGMA_TO_CSS_BLEND: dict[str, str] = {
    "NORMAL": "normal",
    "MULTIPLY": "multiply",
    "SCREEN": "screen",
    "OVERLAY": "overlay",
    "DARKEN": "darken",
    "LIGHTEN": "lighten",
    "COLOR_DODGE": "color-dodge",
    "COLOR_BURN": "color-burn",
    "HARD_LIGHT": "hard-light",
    "SOFT_LIGHT": "soft-light",
    "DIFFERENCE": "difference",
    "EXCLUSION": "exclusion",
    "HUE": "hue",
    "SATURATION": "saturation",
    "COLOR": "color",
    "LUMINOSITY": "luminosity",
}


def _image_divider_needs_border(node: SceneNode) -> bool:
    """True when an image-rendered node needs a real `border` stroke.

    Image nodes (rendered as `<img>`) that are 0-height divider lines keep
    `border`: under box-sizing:border-box a 0-height box with `border: 1px`
    paints a 1px line, but an inset box-shadow ring on a 0-height box renders
    nothing. Normal-height images use the inset ring instead (the stroke
    overlaps the image edge, as in Figma).

    Imported lazily to avoid pulling image.py's requests/FigmaClient deps
    into style.py at module load time.
    """
    from avocado.parser.image import is_image_node  # noqa: PLC0415

    if not is_image_node(node):
        return False
    height = (node.box.height if node.box else None) or 0.0
    return height < 0.5


def style_from_scene(
    node: SceneNode,
    *,
    image_fills_map: dict[str, str] | None = None,
) -> dict[str, str | float]:
    """Build CSS declarations from a SceneNode's visual fields."""
    out: dict[str, str | float] = {}

    # ── background: multi-layer fills ──
    # All visible fills are layered as a comma-separated `background` value.
    # Gradient paints come first (drawn above solids in CSS stacking within
    # the same property), SOLID paints become background-color layers.
    bg_layers: list[str] = []
    bg_sizes: list[str] = []
    # CSS `background` shorthand requires <color> to be the last layer (or
    # standalone). If a SOLID color is appended before an IMAGE/gradient layer,
    # the whole `background` declaration is invalid and browsers ignore it —
    # leaving the node unrendered (white). Figma fills often list SOLID first
    # (e.g. Product Card "image" RECTANGLE with [#d9d9d9 SOLID, IMAGE] →
    # `background: #d9d9d9, url(...)` is invalid; correct is `url(...), #d9d9d9`
    # or just `url(...)` since the image covers the SOLID). Track SOLID colors
    # separately and append them at the end so the layer order is valid.
    solid_color: str | None = None
    for p in node.fills:
        if not p.visible:
            continue
        if p.type == "SOLID":
            css_col = paint_color_to_css(p)
            if css_col:
                solid_color = css_col
        elif p.type.startswith("GRADIENT_"):
            g = _gradient_to_css(p)
            if g:
                bg_layers.append(g)
        elif p.type == "IMAGE" and image_fills_map is not None:
            # INSTANCE: skip IMAGE fills that are component-set preview
            # thumbnails (marked by non-zero rotation or filters). These
            # don't represent the actual instance visual — children render
            # the truth. INSTANCE without rotation/filters (e.g. a Header
            # with a real bg image + Status Bar overlay) keeps the layer.
            if node.type == "INSTANCE" and (p.rotation or p.filters):
                continue
            # Multi-fill nodes (e.g. iPhone Inner screen with [IMAGE, SOLID,
            # IMAGE]) don't qualify as is_image_node (which requires exactly
            # one IMAGE fill). Without this branch the IMAGE layers would be
            # silently dropped — for nodes where the image carries essential
            # visuals ( screenshots, illustrations), losing it tanks fidelity.
            # Resolve the imageRef via the file-level image fills map and
            # emit a CSS background-image layer (covers the bbox, like Figma).
            ref = getattr(p, "image_ref", None)
            url = image_fills_map.get(ref) if ref else None
            if url:
                # pre-crop/scale local image files (offline/cache mode)
                # to match Figma's cover rendering. RECTANGLE+IMAGE paint fills
                # go through this path (not render_as_image), and without
                # pre-cropping the browser-vs-Figma resampling diverges by
                # 3-5% per image — accumulating to >10% on image-heavy pages
                # like sample_page_001's Product Card scroller (3 cards × ~140px
                # images displayed from 3840x2508 sources). See memory
                # pil_cover_precrop.
                if isinstance(url, str) and not url.startswith(("http://", "https://")):
                    try:
                        from .image import _preprocess_cover_image

                        new_url, ok = _preprocess_cover_image(
                            url, node, None, scale_mode=(getattr(p, "scale_mode", None))
                        )
                        if ok:
                            url = new_url
                            # cover already baked into the pixels; drop the
                            # CSS keyword so the browser renders 1:1.
                            scale_mode_override = "_none"
                        else:
                            scale_mode_override = None
                    except Exception:
                        scale_mode_override = None
                else:
                    scale_mode_override = None
                bg_layers.append(f"url('{url}')")
                # Multi-fill IMAGE layers need an explicit background-size to
                # cover the bbox (Figma scaleMode semantics). Without this, a
                # 3840x2508 source displayed in a 297x140 box renders at natural
                # size and only the top-left corner is visible. Pick the CSS
                # keyword matching the paint's scaleMode; default to cover
                # (Figma's default for IMAGE fills).
                if scale_mode_override == "_none":
                    # pre-crop already baked exact pixels; no CSS bg-size.
                    pass
                else:
                    scale_mode = (getattr(p, "scale_mode", None) or "FILL").upper()
                    if scale_mode == "STRETCH":
                        bg_size = "100% 100%"
                    elif scale_mode == "FIT":
                        bg_size = "contain"
                    else:
                        # FILL / CROP / unknown → cover
                        bg_size = "cover"
                    bg_sizes.append(bg_size)
    if bg_layers or solid_color:
        # Append SOLID color at the end so the layer order is valid CSS
        # (`<image>... , <color>`). If bg_layers is empty (SOLID-only node),
        # use the dedicated `background-color` property.
        if solid_color is not None:
            bg_layers.append(solid_color)
        if len(bg_layers) == 1:
            # Prefer the more specific property for the single-layer case so
            # downstream tailwind/default-stripping passes can match exactly.
            first = node.fills[0] if node.fills else None
            if first and first.type == "SOLID":
                out["background-color"] = bg_layers[0]
            else:
                out["background"] = bg_layers[0]
        else:
            out["background"] = ", ".join(bg_layers)
        # background-size: one value per layer (comma-separated). Only emit
        # when at least one IMAGE layer contributed a size — SOLID/gradient
        # layers don't need it (no implicit cover), and emitting an empty
        # string pollutes downstream renders (React renders `backgroundSize:"
        # ""` which has no effect but bloats output and confuses passes).
        if bg_sizes:
            out["background-size"] = ", ".join(bg_sizes)

    # ── corner radius + clip content ──
    # Figma `clipsContent:true` clips children to the node's bbox, regardless
    # of corner radius. CSS needs `overflow:hidden` for this; `border-radius`
    # alone does not clip children. Without overflow:hidden, absolutely-
    # positioned children that extend past the parent bbox (e.g. a 702px-wide
    # banner FRAME inside a 375px page root, or an out-of-bounds <img>) spill
    # out and overwrite neighbouring pixels — see pitfall figma_clips_overflow
    # and regression sample_page_001 (clipsContent=true, cornerRadius=None on
    # the homepage root; 2nd carousel slide bled into the white background).
    if node.corner_radius is not None and node.corner_radius > 0:
        out["border-radius"] = f"{_num(node.corner_radius)}px"
    elif node.type == "ELLIPSE":
        # ELLIPSE → <div> needs border-radius:50% to render as a circle.
        # Without this, ellipse fills (e.g. sample_page_001 banner "Ellipse 2",
        # a 165px rgba(0,0,0,0.2) circle) paint as squares that cover the
        # underlying content.
        out["border-radius"] = "50%"
    if node.clips_content:
        out["overflow"] = "hidden"

    # ── overflowDirection (Figma scroll/clip) ──
    # Figma frames with overflowDirection != NONE clip children to the bbox
    # along the scroll axis (the bbox is the visible viewport; children can
    # extend past it but only the visible part renders). Without this,
    # children outside the bbox show through (e.g. sample_page_001 horizontal
    # scroller with 4 cards — only 1 should be visible, but without
    # overflow-x:hidden all 4 spill past the 343px container width).
    od = (node.overflow_direction or "NONE").upper()
    if od == "HORIZONTAL_SCROLLING":
        out["overflow-x"] = "hidden"
    elif od == "VERTICAL_SCROLLING":
        out["overflow-y"] = "hidden"
    elif od == "HORIZONTAL_AND_VERTICAL_SCROLLING":
        out["overflow"] = "hidden"

    # ── opacity ──
    if node.opacity < 1.0:
        out["opacity"] = _num(node.opacity)

    # ── effects: shadow / blur / backdrop-blur ──
    shadows = _shadow_str(node.effects)
    if shadows:
        out["box-shadow"] = shadows
    blur = _filter_str(node.effects)
    if blur:
        out["filter"] = blur
    backdrop = _backdrop_filter_str(node.effects)
    if backdrop:
        out["backdrop-filter"] = backdrop

    # ── stroke: strokeAlign three states + per-edge + dashPattern ──
    _apply_stroke(node, out)

    # ── rotation → transform ──
    deg = _rotation_deg(node)
    if deg:
        out["transform"] = f"rotate({_num(deg)}deg)"

    # ── blendMode ──
    if node.blend_mode and node.blend_mode != "PASS_THROUGH":
        css_blend = _FIGMA_TO_CSS_BLEND.get(node.blend_mode)
        if css_blend:
            out["mix-blend-mode"] = css_blend

    return out


# ── stroke application ──────────────────────────────────────────────


def _apply_stroke(node: SceneNode, out: dict[str, str | float]) -> None:
    """Emit border/outline/box-shadow based on strokeAlign + per-edge weights.

    strokeAlign three-state mapping:
      - INSIDE / CENTER → `box-shadow: inset 0 0 0 Npx col` ring (does not
        affect layout). Under box-sizing:border-box a CSS `border` insets the
        content box by the stroke width, squeezing children away from the
        frame edge — but Figma lays children out in the full frame bounds
        (the stroke overlaps edge-touching children). The inset ring draws
        the stroke without participating in layout, so children stay flush
        with the border-box edge. Kept as `border` for dashed strokes
        (box-shadow cannot render dashes). For CENTER the visual is
        ~half-spread but the ring is the closest CSS primitive.
      - OUTSIDE uniform  → `outline: Npx solid col` (does not affect layout).
      - OUTSIDE per-edge → `box-shadow: 0 0 0 Npx col` spread rings per edge.
    """
    if not node.strokes:
        return
    solid_stroke = next(
        (p for p in node.strokes if p.visible and p.type == "SOLID"),
        None,
    )
    if not solid_stroke or not solid_stroke.color:
        return
    stroke_css_col = paint_color_to_css(solid_stroke)
    if not stroke_css_col:
        return

    isw = node.individual_stroke_weights
    has_isw = bool(isw and any(v and v > 0 for v in isw.values()))
    align = node.stroke_align or "INSIDE"

    # dashPattern → override border-style to dashed
    style_kind = "dashed" if node.dash_pattern else "solid"

    if has_isw:
        # Per-edge weights
        if align == "OUTSIDE":
            # Per-edge outside ring via box-shadow offsets.
            shadows = []
            for edge in ("top", "right", "bottom", "left"):
                w = isw.get(edge, 0) or 0
                if w <= 0:
                    continue
                off_y = -w if edge == "top" else (w if edge == "bottom" else 0)
                off_x = -w if edge == "left" else (w if edge == "right" else 0)
                shadows.append(f"{_num(off_x)}px {_num(off_y)}px 0 {_num(w)}px {stroke_css_col}")
            if shadows:
                # Merge with any existing box-shadow.
                if "box-shadow" in out:
                    out["box-shadow"] = out["box-shadow"] + ", " + ", ".join(shadows)
                else:
                    out["box-shadow"] = ", ".join(shadows)
        else:
            for edge in ("top", "right", "bottom", "left"):
                w = isw.get(edge, 0) or 0
                if w > 0:
                    out[f"border-{edge}"] = f"{_num(w)}px {style_kind} {stroke_css_col}"
        return

    if not (node.stroke_weight and node.stroke_weight > 0):
        return
    w = node.stroke_weight
    if align == "OUTSIDE":
        out["outline"] = f"{_num(w)}px {style_kind} {stroke_css_col}"
    elif style_kind == "dashed":
        # Dashed strokes need CSS `border` (box-shadow cannot render dashes).
        out["border"] = f"{_num(w)}px {style_kind} {stroke_css_col}"
    else:
        # INSIDE / CENTER uniform solid stroke → inset ring (no layout effect),
        # so children stay flush with the border-box edge as in Figma.
        # 0-height image divider lines keep `border` (an inset ring on a
        # 0-height box renders nothing).
        if _image_divider_needs_border(node):
            out["border"] = f"{_num(w)}px {style_kind} {stroke_css_col}"
            return
        shadow = f"inset 0 0 0 {_num(w)}px {stroke_css_col}"
        if "box-shadow" in out:
            out["box-shadow"] = out["box-shadow"] + ", " + shadow
        else:
            out["box-shadow"] = shadow


# ── gradient ──────────────────────────────────────────────────────────


def _gradient_to_css(paint: Paint) -> str | None:
    """Convert a Figma gradient paint to a CSS gradient string.

    Figma encodes the gradient line via `gradientHandlePositions`: a 3-point
    frame where handle[0] is the start point and handle[1] is the end point
    (handle[2] is the rotation center for radial/conic). We derive the CSS
    angle from the vector handle[0]→handle[1].

    CSS gradient angle convention: 0deg points up, 90deg points right. The
    atan2(dy, dx)*180/π gives the math angle, and CSS uses (90 - math_angle)
    mod 360, but the common Figma→CSS recipe simplifies to atan2(dx, -dy).
    """
    handles = paint.gradient_handle_positions
    stops = paint.gradient_stops
    if not handles or not stops:
        return None

    deg: float | None = None
    if len(handles) >= 2:
        h0 = handles[0].get("x", 0), handles[0].get("y", 0)
        h1 = handles[1].get("x", 0), handles[1].get("y", 0)
        dx = h1[0] - h0[0]
        dy = h1[1] - h0[1]
        if dx or dy:
            deg = math.degrees(math.atan2(dx, -dy))

    stop_strs = []
    for s in stops:
        pos = s.get("position", 0)
        c = s.get("color", {})
        col = Color.from_dict(c)
        stop_strs.append(f"{col.to_rgba_str() if col else 'transparent'} {_num(pos * 100)}%")

    gtype = paint.type
    if gtype == "GRADIENT_LINEAR":
        angle = _num(deg) if deg is not None else 90
        return f"linear-gradient({angle}deg, {', '.join(stop_strs)})"
    if gtype == "GRADIENT_RADIAL":
        return f"radial-gradient(circle, {', '.join(stop_strs)})"
    if gtype == "GRADIENT_ANGULAR":
        return f"conic-gradient(from {(_num(deg) if deg is not None else 0)}deg, {', '.join(stop_strs)})"
    if gtype == "GRADIENT_DIAMOND":
        # CSS has no diamond gradient primitive; fall back to linear.
        angle = _num(deg) if deg is not None else 90
        return f"linear-gradient({angle}deg, {', '.join(stop_strs)})"
    return None


# ── effects ──────────────────────────────────────────────────────────

# Figma's blur radius uses a different Gaussian sigma than CSS box-shadow.
# Per bjango.com's "Blur radius comparison" (2024), the conversion factor is:
# CSS box-shadow blur = Figma blur × 1.136364
# This is the single biggest source of shadow fidelity loss across D2C tools.
_FIGMA_BLUR_TO_CSS_SHADOW = 1.136364
# Figma layer blur / background blur use a different scale:
# CSS filter:blur = Figma layer blur × 1.136364 (same factor per bjango)
_FIGMA_BLUR_TO_CSS_FILTER = 1.136364


def _shadow_str(effects: list[Effect]) -> str | None:
    """Build box-shadow value from DROP_SHADOW / INNER_SHADOW effects.

    Applies the Figma→CSS blur radius conversion factor (×1.136364) so the
    rendered shadow matches Figma's visual appearance. Without this, CSS
    shadows appear ~12% smaller than the Figma design.
    """
    parts: list[str] = []
    for e in effects:
        if not e.visible:
            continue
        if e.type not in ("DROP_SHADOW", "INNER_SHADOW"):
            continue
        x = e.offset.get("x", 0) if e.offset else 0
        y = e.offset.get("y", 0) if e.offset else 0
        col = e.color.to_rgba_str() if e.color else "rgba(0,0,0,0.25)"
        prefix = "inset " if e.type == "INNER_SHADOW" else ""
        # Convert Figma blur radius to CSS box-shadow blur
        css_blur = e.radius * _FIGMA_BLUR_TO_CSS_SHADOW
        parts.append(f"{prefix}{_num(x)}px {_num(y)}px {_num(css_blur)}px {_num(e.spread)}px {col}")
    return ", ".join(parts) if parts else None


def _filter_str(effects: list[Effect]) -> str | None:
    """filter: blur(...) from LAYER_BLUR effects.

    Applies Figma→CSS blur conversion (×1.136364).
    """
    parts = [
        f"blur({_num(e.radius * _FIGMA_BLUR_TO_CSS_FILTER)}px)"
        for e in effects
        if e.visible and e.type == "LAYER_BLUR" and e.radius > 0
    ]
    return ", ".join(parts) if parts else None


def _backdrop_filter_str(effects: list[Effect]) -> str | None:
    """backdrop-filter: blur(...) from BACKGROUND_BLUR effects.

    Applies Figma→CSS blur conversion (×1.136364).
    """
    parts = [
        f"blur({_num(e.radius * _FIGMA_BLUR_TO_CSS_FILTER)}px)"
        for e in effects
        if e.visible and e.type == "BACKGROUND_BLUR" and e.radius > 0
    ]
    return ", ".join(parts) if parts else None


# ── rotation ─────────────────────────────────────────────────────────


def _rotation_deg(node: SceneNode) -> float | None:
    """Return visual rotation in degrees, preferring relative_transform.

    `relativeTransform` is a 2×3 matrix [[a, b, tx], [c, d, ty]] where
    (a, c) is the rotated X-axis basis. The rotation angle is
    atan2(c, a) (standard 2D rotation extraction). We fall back to the
    scalar `rotation` field when the matrix is absent.
    """
    rt = node.relative_transform
    if rt and len(rt) >= 2 and len(rt[0]) >= 1 and len(rt[1]) >= 1:
        a = rt[0][0]
        c = rt[1][0]
        return math.degrees(math.atan2(c, a))
    if node.rotation:
        return node.rotation
    return None


def _num(v: float, ndigits: int = 2) -> float | int:
    """Round to N decimals; return int if whole number for cleaner output."""
    rounded = round(float(v), ndigits)
    if rounded == int(rounded):
        return int(rounded)
    return rounded


def paint_color_to_css(paint: Paint) -> str | None:
    """Convert a SOLID paint's color to a CSS color string.

    Handles opacity composition: when paint.opacity < 1 and the paint's
    own alpha is 1, apply paint opacity as the alpha channel.
    Returns None if paint has no color.
    """
    if not paint.color:
        return None
    col = paint.color
    if paint.opacity < 1.0 and col.a >= 1.0:
        col = Color(col.r, col.g, col.b, paint.opacity)
    return col.to_rgba_str()
