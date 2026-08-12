"""P1 optimization-pass tests."""

from __future__ import annotations

from avocado.model.tree_node import TreeNode
from avocado.parser.optimize.auto_group_variance import apply_auto_group_variance
from avocado.parser.optimize.gap_to_margin import gap_to_margin
from avocado.parser.optimize.inherit_promote import promote_inherited_styles
from avocado.parser.optimize.reround import reround_styles
from avocado.parser.optimize.semantic_tags import apply_semantic_tags
from avocado.parser.optimize.strip_defaults import strip_default_styles
from avocado.parser.optimize.unwrap_single_child import unwrap_single_child


def _node(name="n", source_type="FRAME", **kw) -> TreeNode:
    base = dict(id=name, name=name, source_type=source_type)
    base.update(kw)
    return TreeNode(**base)


# ── inherit_promote ────────────────────────────────────────────────


def test_inherit_promote_lifts_common_color():
    root = _node(style={})
    leaf1 = _node("a", source_type="TEXT", style={"color": "#ff0000"})
    leaf2 = _node("b", source_type="TEXT", style={"color": "#ff0000"})
    root.children = [leaf1, leaf2]
    promote_inherited_styles(root)
    assert root.style.get("color") == "#ff0000"
    assert "color" not in leaf1.style
    assert "color" not in leaf2.style


def test_inherit_promote_skips_when_values_differ():
    """50/50 tie: no strict majority → skip promotion."""
    root = _node(style={})
    leaf1 = _node("a", source_type="TEXT", style={"color": "#ff0000"})
    leaf2 = _node("b", source_type="TEXT", style={"color": "#00ff00"})
    root.children = [leaf1, leaf2]
    promote_inherited_styles(root)
    assert "color" not in root.style


def test_inherit_promote_majority_vote():
    """Only font-family uses majority vote.

    3 leaves with Inter + 1 with Roboto → root gets Inter (75% majority),
    Roboto leaf keeps its override.
    """
    root = _node(style={})
    p1 = _node("a", source_type="TEXT", style={"font-family": "Inter"})
    p2 = _node("b", source_type="TEXT", style={"font-family": "Inter"})
    p3 = _node("c", source_type="TEXT", style={"font-family": "Inter"})
    other = _node("d", source_type="TEXT", style={"font-family": "Roboto"})
    root.children = [p1, p2, p3, other]
    promote_inherited_styles(root)
    assert root.style.get("font-family") == "Inter"
    assert "font-family" not in p1.style
    assert "font-family" not in p2.style
    assert "font-family" not in p3.style
    assert other.style.get("font-family") == "Roboto"  # minority override kept


def test_inherit_promote_non_font_props_require_unanimous():
    """Non-font props (color, text-align, etc.) keep unanimous-only.

    3 leaves with `center` + 1 with `left` for text-align → NOT promoted
    (would pollute the 1 left-aligned leaf via inheritance).
    """
    root = _node(style={})
    a = _node("a", source_type="TEXT", style={"text-align": "center"})
    b = _node("b", source_type="TEXT", style={"text-align": "center"})
    c = _node("c", source_type="TEXT", style={"text-align": "center"})
    d = _node("d", source_type="TEXT", style={"text-align": "left"})
    root.children = [a, b, c, d]
    promote_inherited_styles(root)
    # Not promoted (not unanimous, not font-family)
    assert "text-align" not in root.style


def test_inherit_promote_majority_with_implicit_leaves():
    """Leaves without the prop don't constrain promotion (CSS inheritance).

    2 Inter + 1 Roboto + 1 plain div → Inter wins (2/3 declared = 67%).
    """
    root = _node(style={})
    p1 = _node("a", source_type="TEXT", style={"font-family": "Inter"})
    p2 = _node("b", source_type="TEXT", style={"font-family": "Inter"})
    other = _node("c", source_type="TEXT", style={"font-family": "Roboto"})
    plain = _node("d", source_type="FRAME", style={"width": "100px"})
    root.children = [p1, p2, other, plain]
    promote_inherited_styles(root)
    assert root.style.get("font-family") == "Inter"


def test_inherit_promote_skips_component_boundary():
    comp = _node("c", source_type="INSTANCE", is_component=True, style={})
    leaf = _node("a", source_type="TEXT", style={"color": "#ff0000"})
    comp.children = [leaf]
    # Wrap in a parent that itself has the same color, so without the
    # boundary check, promotion would lift it to a grandparent root.
    root = _node(style={"color": "#ff0000"})
    root.children = [comp]
    promote_inherited_styles(root)
    # Component child should keep its color (boundary respected).
    assert leaf.style.get("color") == "#ff0000"


# ── strip_defaults ─────────────────────────────────────────────────


def test_strip_defaults_drops_flex_direction_row():
    n = _node(style={"flex-direction": "row", "color": "#fff"})
    strip_default_styles(n)
    assert "flex-direction" not in n.style
    assert n.style.get("color") == "#fff"


def test_strip_defaults_keeps_non_default_flex_direction():
    n = _node(style={"flex-direction": "column"})
    strip_default_styles(n)
    assert n.style.get("flex-direction") == "column"


# ── unwrap_single_child ────────────────────────────────────────────


def test_unwrap_single_child_collapses_plain_wrapper():
    inner = _node(
        "inner", source_type="RECTANGLE", tag_name="div", style={"background-color": "#fff"}
    )
    wrapper = _node("wrap", source_type="FRAME", children=[inner])
    out = unwrap_single_child(wrapper)
    # The wrapper (no visual style) should be gone; the inner div wins.
    assert out.style == {"background-color": "#fff"}
    assert out.source_type == "RECTANGLE"


def test_unwrap_blocked_by_visual_style():
    inner = _node("inner", source_type="RECTANGLE", style={"background-color": "#fff"})
    wrapper = _node(
        "wrap", source_type="FRAME", style={"background-color": "#000"}, children=[inner]
    )
    out = unwrap_single_child(wrapper)
    # Wrapper keeps its place because it has a background.
    assert out is wrapper
    assert out.style.get("background-color") == "#000"


def test_unwrap_blocked_by_absolute_in_subtree():
    inner = _node("inner", source_type="RECTANGLE", props={"layoutPositioning": "ABSOLUTE"})
    wrapper = _node(
        "wrap",
        source_type="FRAME",
        style={"position": "relative"},
        children=[inner],
    )
    out = unwrap_single_child(wrapper)
    # Positioned wrapper participates in absolute containing-block resolution
    # → kept.
    assert out is wrapper


def test_unwrap_static_wrapper_with_absolute_subtree():
    """A static (non-positioned) wrapper does not affect absolute descendants'
    containing block — unwrapping it is safe (issue #26 flat-nesting)."""
    inner = _node("inner", source_type="RECTANGLE", props={"layoutPositioning": "ABSOLUTE"})
    wrapper = _node("wrap", source_type="FRAME", children=[inner])
    out = unwrap_single_child(wrapper)
    assert out is not wrapper
    assert out.source_type == "RECTANGLE"
    assert out.props.get("layoutPositioning") == "ABSOLUTE"


def test_unwrap_blocked_by_style_positioned_wrapper():
    """Positioned wrapper (style-side `position: absolute`) with an absolute
    child must be kept — unwrapping would change the containing block."""
    inner = _node("inner", source_type="RECTANGLE", style={"position": "absolute"})
    wrapper = _node(
        "wrap",
        source_type="FRAME",
        style={"position": "relative"},
        children=[inner],
    )
    out = unwrap_single_child(wrapper)
    assert out is wrapper


def test_unwrap_blocked_by_flex_grow_child():
    """A wrapper whose only child has `flex-grow: 1` must not be unwrapped.

    Regression: sample_page_002 "Primary Button" (layoutGrow=1, FILL) was nested
    inside a FIXED-width "buttons" wrapper. Unwrapping the wrapper promoted
    the FILL child into the parent (a 327px row containing $49 + the button).
    FILL then resolved against the larger parent, growing the button from
    155px to ~272px and overwriting the $49 area with the dark button fill.
    The wrapper's width constraint is what made FILL well-defined; removing
    it changes FILL's reference and breaks the layout.
    """
    inner = _node("fill-child", source_type="FRAME", style={"flex-grow": 1})
    wrapper = _node("buttons-wrap", source_type="FRAME", style={"width": "155px"}, children=[inner])
    out = unwrap_single_child(wrapper)
    # Wrapper retained — its width is the FILL reference for the child.
    assert out is wrapper


def test_unwrap_preserves_inherited_styles_on_child():
    """A wrapper carrying inheritable styles (font/line-height/color) must
    push them onto the merged child before disappearing.

    Regression: checkout Alert INSTANCE → "top" FRAME had `font-size: 12px`
    and `line-height: 18px` (lifted from the subtitle span by inherit_promote).
    Unwrapping "top" discarded those properties; the merged span ended up
    with no font-size/line-height, so browsers rendered it with the default
    font, blowing the diff at that region from <1px to >100px.
    """
    inner = _node(
        "text", source_type="TEXT", tag_name="span", style={"width": "100px", "height": "20px"}
    )
    wrapper = _node(
        "top",
        source_type="FRAME",
        style={
            "font-size": "12px",
            "line-height": "18px",
            "color": "#4b4a4a",
            "font-family": "Inter, sans-serif",
        },
        children=[inner],
    )
    out = unwrap_single_child(wrapper)
    # Wrapper is gone; merged node carries the inherited styles.
    assert out.id == "text"
    assert out.style.get("font-size") == "12px"
    assert out.style.get("line-height") == "18px"
    assert out.style.get("color") == "#4b4a4a"
    assert out.style.get("font-family") == "Inter, sans-serif"
    # And original child styles are preserved.
    assert out.style.get("width") == "100px"
    assert out.style.get("height") == "20px"


# ── gap_to_margin ──────────────────────────────────────────────────


def test_gap_to_margin_row_direction():
    root = _node(style={"display": "flex", "flex-direction": "row", "gap": "8px"})
    children = [_node(f"c{i}", source_type="RECTANGLE") for i in range(3)]
    root.children = children
    gap_to_margin(root)
    assert "gap" not in root.style
    assert children[0].style.get("margin-right") == "8px"
    assert children[1].style.get("margin-right") == "8px"
    assert "margin-right" not in children[2].style  # last gets no margin


def test_gap_to_margin_column_direction():
    root = _node(style={"display": "flex", "flex-direction": "column", "gap": "4px"})
    children = [_node(f"c{i}", source_type="RECTANGLE") for i in range(2)]
    root.children = children
    gap_to_margin(root)
    assert children[0].style.get("margin-bottom") == "4px"
    assert "margin-bottom" not in children[1].style


# ── reround ────────────────────────────────────────────────────────


def test_reround_precision_2_truncates_decimal():
    n = _node(style={"width": "12.34567px", "opacity": 0.5})
    reround_styles(n, 2)
    assert n.style.get("width") == "12.35px"


def test_reround_precision_0_drops_decimal():
    n = _node(style={"width": "12.34567px"})
    reround_styles(n, 0)
    assert n.style.get("width") == "12px"


def test_reround_keeps_non_numeric_strings():
    n = _node(style={"color": "rgba(1,2,3,0.5)"})
    reround_styles(n, 2)
    assert n.style.get("color") == "rgba(1,2,3,0.5)"


# ── auto_group_variance ────────────────────────────────────────────


def test_auto_group_variance_picks_row_for_stacked_x():
    # Children with similar x but very different y → column.
    root = _node(layout_strategy="auto_group")
    children = [
        _node(f"c{i}", source_type="RECTANGLE", style={"left": "0px", "top": f"{i * 10}px"})
        for i in range(4)
    ]
    root.children = children
    apply_auto_group_variance(root)
    assert root.style.get("flex-direction") == "column"
    assert root.style.get("display") == "flex"


def test_auto_group_variance_picks_row_for_spread_x():
    # Children spread on x but constant y → row.
    root = _node(layout_strategy="auto_group")
    children = [
        _node(f"c{i}", source_type="RECTANGLE", style={"left": f"{i * 10}px", "top": "0px"})
        for i in range(4)
    ]
    root.children = children
    apply_auto_group_variance(root)
    assert root.style.get("flex-direction") == "row"


# ── semantic_tags (issue #28: semantic HTML at zero visual cost) ──


def test_semantic_root_becomes_main():
    """The page root FRAME maps to <main> (zero-visual landmark, all CSS forms)."""
    root = _node("Payment", source_type="FRAME", style={"width": "1440px"})
    child = _node("body", source_type="FRAME", style={"width": "1168px"})
    root.children = [child]
    apply_semantic_tags(root)  # default inline — main is always safe
    assert root.tag_name == "main"


def test_semantic_heading_by_name_and_font_size():
    """Tailwind: exact 'Title' name + font-size → h2/h3 (preflight resets UA)."""
    root = _node("Page", source_type="FRAME")
    title = _node("Title", source_type="FRAME", style={"font-size": "22px"})
    small = _node("Heading", source_type="FRAME", style={"font-size": "16px"})
    root.children = [title, small]
    apply_semantic_tags(root, css_form="tailwind")
    assert title.tag_name == "h2"
    assert small.tag_name == "h3"


def test_semantic_inline_keeps_ua_styled_as_div():
    """Inline/class emit only zero-visual tags; h2/button/ul stay div.

    No CSS reset is injected (issue #30), so UA-styled content tags would
    render with browser defaults — they stay div to keep zero-visual.
    Landmark tags (main) are unaffected.
    """
    root = _node("Page", source_type="FRAME")
    title = _node("Title", source_type="FRAME", style={"font-size": "22px"})
    btn = _node("Button", source_type="FRAME", style={"background-color": "#006b99"})
    overview = _node("Overview", source_type="FRAME")
    overview.children = [_node(f"Item {i}", source_type="FRAME") for i in range(1, 4)]
    root.children = [title, btn, overview]
    apply_semantic_tags(root, css_form="inline")
    assert title.tag_name == "div"
    assert btn.tag_name == "div"
    assert overview.tag_name == "div"
    assert root.tag_name == "main"


def test_semantic_heading_requires_font_size():
    """A node named 'Title' without font-size is left as div (宁少勿错)."""
    root = _node("Page", source_type="FRAME")
    title = _node("Title", source_type="FRAME", style={"width": "100px"})
    root.children = [title]
    apply_semantic_tags(root, css_form="tailwind")
    assert title.tag_name == "div"


def test_semantic_button_by_name():
    """Tailwind: exact 'Button' name on a non-component node → <button>."""
    root = _node("Page", source_type="FRAME")
    btn = _node("Button", source_type="FRAME", style={"background-color": "#006b99"})
    root.children = [btn]
    apply_semantic_tags(root, css_form="tailwind")
    assert btn.tag_name == "button"


def test_semantic_skips_components_and_images():
    """Recognized components and images keep their tags."""
    root = _node("Page", source_type="FRAME")
    comp = _node("Button", source_type="INSTANCE", is_component=True, tag_name="Button")
    img = _node("Image", source_type="RECTANGLE", is_img=True, tag_name="img")
    root.children = [comp, img]
    apply_semantic_tags(root, css_form="tailwind")
    assert comp.tag_name == "Button"  # component preserved
    assert img.tag_name == "img"


def test_semantic_list_group_to_ul_li():
    """Tailwind: a list container with 3+ same-prefix children → <ul> + <li>."""
    root = _node("Page", source_type="FRAME")
    overview = _node("Overview", source_type="FRAME")
    overview.children = [
        _node(f"Item {i}", source_type="FRAME") for i in range(1, 4)
    ]
    root.children = [overview]
    apply_semantic_tags(root, css_form="tailwind")
    assert overview.tag_name == "ul"
    assert all(c.tag_name == "li" for c in overview.children)


def test_semantic_text_nodes_kept_as_span():
    """Text nodes (tag_name == 'span') are left alone."""
    root = _node("Page", source_type="FRAME")
    text = _node("Your total", source_type="TEXT", tag_name="span", text_content="Your total")
    root.children = [text]
    apply_semantic_tags(root, css_form="tailwind")
    assert text.tag_name == "span"
