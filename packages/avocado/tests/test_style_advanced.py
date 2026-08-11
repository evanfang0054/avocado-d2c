"""P0 visual-detail tests: stroke_align three states, gradient, blur, rotation,
blendMode, multi-layer fills, dashPattern."""

from __future__ import annotations

from avocado.model.scene_node import Paint, SceneNode
from avocado.parser.style import style_from_scene


def _frame(**kw) -> SceneNode:
    base = dict(id="n", name="n", type="FRAME")
    base.update(kw)
    return SceneNode.from_dict(base)


# ── strokeAlign three states ────────────────────────────────────────


def test_stroke_inside_emits_inset_ring():
    node = _frame(
        strokes=[{"type": "SOLID", "color": {"r": 1, "g": 0, "b": 0, "a": 1}}],
        strokeWeight=2,
        strokeAlign="INSIDE",
    )
    s = style_from_scene(node)
    # INSIDE stroke → inset ring (no layout effect, keeps children flush with
    # the border-box edge as in Figma) instead of a CSS border.
    assert s.get("box-shadow") == "inset 0 0 0 2px #ff0000"
    assert "border" not in s
    assert "outline" not in s


def test_stroke_center_emits_inset_ring():
    node = _frame(
        strokes=[{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
        strokeWeight=4,
        strokeAlign="CENTER",
    )
    s = style_from_scene(node)
    assert s.get("box-shadow") == "inset 0 0 0 4px #000000"
    assert "border" not in s


def test_stroke_outside_emits_outline():
    node = _frame(
        strokes=[{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
        strokeWeight=3,
        strokeAlign="OUTSIDE",
    )
    s = style_from_scene(node)
    assert s.get("outline") == "3px solid #000000"
    assert "border" not in s


# ── gradient ────────────────────────────────────────────────────────


def test_linear_gradient_angle_from_handles():
    paint = Paint(
        type="GRADIENT_LINEAR",
        gradient_handle_positions=[
            {"x": 0.0, "y": 0.0},
            {"x": 1.0, "y": 0.0},  # horizontal → 90deg in CSS
        ],
        gradient_stops=[
            {"position": 0.0, "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
            {"position": 1.0, "color": {"r": 0, "g": 0, "b": 1, "a": 1}},
        ],
    )
    from avocado.parser.style import _gradient_to_css

    out = _gradient_to_css(paint)
    assert out is not None
    assert out.startswith("linear-gradient(90deg,")
    assert "#ff0000 0%" in out
    assert "#0000ff 100%" in out


# ── LAYER_BLUR ──────────────────────────────────────────────────────


def test_layer_blur_emits_filter():
    node = _frame(
        effects=[{"type": "LAYER_BLUR", "radius": 4, "visible": True}],
    )
    s = style_from_scene(node)
    # Figma blur × 1.136364 = CSS blur (bjango.com blur radius comparison)
    assert s.get("filter") == "blur(4.55px)"


def test_background_blur_emits_backdrop_filter():
    node = _frame(
        effects=[{"type": "BACKGROUND_BLUR", "radius": 8, "visible": True}],
    )
    s = style_from_scene(node)
    assert s.get("backdrop-filter") == "blur(9.09px)"


# ── rotation from relative_transform ────────────────────────────────


def test_rotation_uses_relative_transform():
    # 90° rotation matrix: [[0,-1,tx],[1,0,ty]]
    rt = [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0]]
    node = _frame(relativeTransform=rt)
    s = style_from_scene(node)
    assert "transform" in s
    # Should be ~90 degrees.
    assert "rotate(90deg)" == s["transform"] or "rotate(89deg)" == s["transform"]


# ── blendMode ───────────────────────────────────────────────────────


def test_blend_mode_multiply_emits_mix_blend_mode():
    node = _frame(blendMode="MULTIPLY")
    s = style_from_scene(node)
    assert s.get("mix-blend-mode") == "multiply"


def test_blend_mode_pass_through_is_skipped():
    node = _frame(blendMode="PASS_THROUGH")
    s = style_from_scene(node)
    assert "mix-blend-mode" not in s


# ── multi-layer fills ───────────────────────────────────────────────


def test_multi_layer_solid_plus_gradient_uses_background():
    node = _frame(
        fills=[
            {
                "type": "GRADIENT_LINEAR",
                "gradientHandlePositions": [{"x": 0, "y": 0}, {"x": 1, "y": 0}],
                "gradientStops": [
                    {"position": 0, "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
                    {"position": 1, "color": {"r": 0, "g": 0, "b": 1, "a": 1}},
                ],
            },
            {"type": "SOLID", "color": {"r": 0.5, "g": 0.5, "b": 0.5, "a": 1}},
        ],
    )
    s = style_from_scene(node)
    # Multi-layer should land in `background` (comma-separated).
    assert "background" in s
    assert "linear-gradient" in s["background"]
    assert "#808080" in s["background"]


# ── dashPattern ─────────────────────────────────────────────────────


def test_dash_pattern_emits_dashed_border_style():
    node = _frame(
        strokes=[{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
        strokeWeight=1,
        strokeAlign="INSIDE",
        dashPattern=[4, 2],
    )
    s = style_from_scene(node)
    assert s.get("border") == "1px dashed #000000"


# ── clipsContent → overflow:hidden ──────────────────────────────────
# Figma `clipsContent:true` clips children to the node's bbox, independent
# of corner radius. Without overflow:hidden on a clips-only frame,
# absolutely-positioned children (e.g. a 702px banner inside a 375px page
# root — sample_page_001) spill past the parent bbox and overwrite
# neighbouring pixels. See pitfall figma_clips_overflow.


def test_clips_content_alone_emits_overflow_hidden():
    """clipsContent=true without cornerRadius must still emit overflow:hidden.

    Regression: sample_page_001 homepage root has clipsContent=true,
    cornerRadius=None. Child Frame 1912054427 is 702px wide (banner
    carousel with two slides side-by-side). Without overflow:hidden on
    the root, the second slide spills past the 375px page width and
    renders black pixels over the white background.
    """
    node = _frame(clipsContent=True)
    s = style_from_scene(node)
    assert s.get("overflow") == "hidden"


def test_clips_content_with_corner_radius_emits_both():
    """clipsContent + cornerRadius emits border-radius + overflow:hidden.

    This case already worked before the fix; included to lock in the
    combined behaviour (rounded clip shape).
    """
    node = _frame(clipsContent=True, cornerRadius=8)
    s = style_from_scene(node)
    assert s.get("border-radius") == "8px"
    assert s.get("overflow") == "hidden"


def test_no_clips_content_no_overflow():
    """Sanity: a frame with neither clips nor radius emits neither rule."""
    node = _frame()
    s = style_from_scene(node)
    assert "overflow" not in s
    assert "border-radius" not in s


# ── ELLIPSE → border-radius:50% ────────────────────────────────────
# Figma ELLIPSE nodes are circular. Mapping them to <div> without
# border-radius renders them as squares — visually wrong for any
# ellipse used as a decorative shape (sample_page_001 banner "Ellipse 2"
# is a 165px black-20% circle, but the d2c output paints a square that
# covers most of the slide). The fix: emit border-radius:50% on
# ELLIPSE nodes (unless an explicit corner_radius is already set).


def test_ellipse_emits_border_radius_50_percent():
    """ELLIPSE nodes must render as circles, not squares.

    Regression: sample_page_001 banner "Ellipse 2" (165x165, fill
    rgba(0,0,0,0.2)) rendered as a black square that covered the
    slide content. Figma draws it as a circle so the slide shows
    through the corners.
    """
    node = _frame(type="ELLIPSE")
    s = style_from_scene(node)
    assert s.get("border-radius") == "50%"


def test_ellipse_with_explicit_corner_radius_wins():
    """A Figma ELLIPSE with a manual cornerRadius override (rare) keeps it."""
    node = _frame(type="ELLIPSE", cornerRadius=4)
    s = style_from_scene(node)
    assert s.get("border-radius") == "4px"


def test_rectangle_does_not_get_50_percent():
    """Sanity: RECTANGLE/FRAME must not become circular."""
    node = _frame(type="RECTANGLE")
    s = style_from_scene(node)
    assert s.get("border-radius") != "50%"


# ── multi-fill IMAGE paint → background-size ──────────────────────
# When a RECTANGLE has SOLID + IMAGE fills (multi-fill), is_image_node
# returns False (requires exactly one IMAGE fill). The IMAGE layer then
# emits as a CSS background-image url(...) — but without background-size,
# the browser renders the source image at its natural pixel size. For a
# 3840x2508 source displayed in a 297x140 box, that shows only the top-left
# corner of the image rather than covering the box (Figma scaleMode=FILL
# = CSS background-size:cover). Regression: sample_page_001 "Product Card"
# image RECTANGLE — cards showed a magnified corner instead of the full
# option photo, contributing ~80% of the page diff.


def test_multi_fill_image_with_fill_scale_mode_emits_background_size_cover():
    """SOLID + IMAGE(scaleMode=FILL) → background + background-size:cover."""
    node = _frame(
        type="RECTANGLE",
        fills=[
            {"type": "SOLID", "color": {"r": 0.85, "g": 0.85, "b": 0.85, "a": 1}},
            {"type": "IMAGE", "scaleMode": "FILL", "imageRef": "ref-A"},
        ],
    )
    s = style_from_scene(node, image_fills_map={"ref-A": "/cache/A.png"})
    # The IMAGE layer must cover the bbox.
    assert s.get("background-size") == "cover"


def test_multi_fill_image_with_crop_scale_mode_emits_background_size_cover():
    """scaleMode=CROP also maps to background-size:cover (Figma CROP = cover)."""
    node = _frame(
        type="RECTANGLE",
        fills=[
            {"type": "SOLID", "color": {"r": 0.85, "g": 0.85, "b": 0.85, "a": 1}},
            {"type": "IMAGE", "scaleMode": "CROP", "imageRef": "ref-A"},
        ],
    )
    s = style_from_scene(node, image_fills_map={"ref-A": "/cache/A.png"})
    assert s.get("background-size") == "cover"


def test_multi_fill_image_with_fit_scale_mode_emits_background_size_contain():
    """scaleMode=FIT maps to background-size:contain (whole image visible)."""
    node = _frame(
        type="RECTANGLE",
        fills=[
            {"type": "SOLID", "color": {"r": 0.85, "g": 0.85, "b": 0.85, "a": 1}},
            {"type": "IMAGE", "scaleMode": "FIT", "imageRef": "ref-A"},
        ],
    )
    s = style_from_scene(node, image_fills_map={"ref-A": "/cache/A.png"})
    assert s.get("background-size") == "contain"


def test_multi_fill_image_with_stretch_scale_mode_emits_background_size_100_100():
    """scaleMode=STRETCH maps to background-size:100% 100% (distort to fill)."""
    node = _frame(
        type="RECTANGLE",
        fills=[
            {"type": "SOLID", "color": {"r": 0.85, "g": 0.85, "b": 0.85, "a": 1}},
            {"type": "IMAGE", "scaleMode": "STRETCH", "imageRef": "ref-A"},
        ],
    )
    s = style_from_scene(node, image_fills_map={"ref-A": "/cache/A.png"})
    assert s.get("background-size") == "100% 100%"


def test_multi_fill_image_without_scale_mode_defaults_to_cover():
    """scaleMode missing → default to cover (Figma's default behaviour)."""
    node = _frame(
        type="RECTANGLE",
        fills=[
            {"type": "SOLID", "color": {"r": 0.85, "g": 0.85, "b": 0.85, "a": 1}},
            {"type": "IMAGE", "imageRef": "ref-A"},
        ],
    )
    s = style_from_scene(node, image_fills_map={"ref-A": "/cache/A.png"})
    assert s.get("background-size") == "cover"
