"""Unit tests for generator/react_style.py — React style object rendering."""

from __future__ import annotations

from avocado.generator.react_style import (
    _format_value,
    _to_camel_case,
    render_react_style,
)
from avocado.model.tree_node import TreeNode

# ── _to_camel_case ──


def test_camel_case_basic() -> None:
    assert _to_camel_case("background-color") == "backgroundColor"
    assert _to_camel_case("flex-direction") == "flexDirection"
    assert _to_camel_case("font-size") == "fontSize"


def test_camel_case_single_word() -> None:
    assert _to_camel_case("color") == "color"
    assert _to_camel_case("display") == "display"


def test_camel_case_vendor_webkit() -> None:
    # React convention: -webkit-X → WebkitX (capital W), NOT webkitX
    assert _to_camel_case("-webkit-transform") == "WebkitTransform"
    assert _to_camel_case("-webkit-user-select") == "WebkitUserSelect"


def test_camel_case_vendor_moz() -> None:
    assert _to_camel_case("-moz-box-flex") == "MozBoxFlex"


def test_camel_case_vendor_ms() -> None:
    assert _to_camel_case("-ms-flex-align") == "MsFlexAlign"


# ── _format_value ──


def test_format_line_height_string_px() -> None:
    # Critical: lineHeight MUST be "Npx" string, never bare number.
    # Bare numbers are interpreted by CSS/React as a multiplier (× font-size).
    assert _format_value("lineHeight", "24px") == '"24px"'
    assert _format_value("lineHeight", 24) == '"24px"'
    assert _format_value("lineHeight", "24") == '"24px"'


def test_format_unitless_props_bare_number() -> None:
    # opacity, fontWeight, flexGrow: bare numeric value (no quotes)
    assert _format_value("opacity", 0.5) == "0.5"
    assert _format_value("fontWeight", 500) == "500"
    assert _format_value("flexGrow", 1) == "1"
    assert _format_value("zIndex", 10) == "10"


def test_format_unitless_props_string_value_stays_string() -> None:
    # A unitless prop given a "Npx" string keeps string form — bare would
    # change semantics (e.g. lineHeight bare = multiplier).
    assert _format_value("opacity", "0.5") == '"0.5"'
    # fontWeight "500" string is interpreted as bare because pure-digit
    # string short-circuits to bare numeric.
    assert _format_value("fontWeight", "500") == "500"


def test_format_px_value_for_non_unitless() -> None:
    # width, height, padding: number → "Npx"
    assert _format_value("width", 100) == '"100px"'
    assert _format_value("height", 50) == '"50px"'
    assert _format_value("fontSize", 14) == '"14px"'


def test_format_named_value() -> None:
    assert _format_value("fontFamily", "Inter") == '"Inter"'
    assert _format_value("textAlign", "center") == '"center"'
    assert _format_value("display", "flex") == '"flex"'


def test_format_color() -> None:
    assert _format_value("color", "#faf8f7") == '"#faf8f7"'
    assert _format_value("backgroundColor", "rgb(255,0,0)") == '"rgb(255,0,0)"'


def test_format_compound_padding() -> None:
    # Compound value preserved, but standalone 0px tokens normalized to 0
    # (a zero length never needs a unit per the CSS Values & Units spec).
    assert _format_value("padding", "64px 0px 64px 0px") == '"64px 0 64px 0"'
    assert _format_value("padding", "0px 0px 12px 0px") == '"0 0 12px 0"'
    assert _format_value("padding", "0px") == '"0"'
    # Composite values that are a single non-"0px" token are left alone.
    assert _format_value("transform", "translateX(0px)") == '"translateX(0px)"'


def test_format_css_var() -> None:
    assert _format_value("color", "var(--x, #faf8f7)") == '"var(--x, #faf8f7)"'


def test_format_float_strips_trailing_zero() -> None:
    # :g format — 12.0 → "12", 12.5 → "12.5"
    assert _format_value("opacity", 1.0) == "1"
    assert _format_value("width", 12.0) == '"12px"'


# ── render_react_style (end-to-end on a TreeNode) ──


def _make_node(style: dict) -> TreeNode:
    n = TreeNode(id="1:1", name="X", source_type="FRAME")
    n.style = style
    return n


def test_render_empty_style() -> None:
    n = _make_node({})
    assert render_react_style(n) == ""


def test_render_simple_dict() -> None:
    n = _make_node({"width": "100px", "height": 50, "color": "#fff"})
    out = render_react_style(n)
    assert out.startswith("style={{")
    assert out.endswith("}}")
    assert 'width: "100px"' in out
    assert 'height: "50px"' in out
    assert 'color: "#fff"' in out


def test_render_line_height_is_string_not_bare() -> None:
    # The whole point: lineHeight must never be a bare number.
    n = _make_node({"line-height": "24px", "font-size": "14px"})
    out = render_react_style(n)
    assert 'lineHeight: "24px"' in out
    # Negative assertion: no `lineHeight: 24` bare form
    assert "lineHeight: 24}" not in out
    assert "lineHeight: 24," not in out


def test_render_camel_case_applied() -> None:
    n = _make_node(
        {
            "background-color": "red",
            "flex-direction": "row",
            "justify-content": "center",
        }
    )
    out = render_react_style(n)
    assert "backgroundColor:" in out
    assert "flexDirection:" in out
    assert "justifyContent:" in out
    # kebab names should not leak
    assert "background-color" not in out


def test_render_unitless_props_bare() -> None:
    n = _make_node({"opacity": 0.5, "font-weight": 500, "flex-grow": 1})
    out = render_react_style(n)
    assert "opacity: 0.5" in out
    assert "fontWeight: 500" in out
    assert "flexGrow: 1" in out


def test_render_follows_priority_order() -> None:
    # display should come before width; width before color
    n = _make_node(
        {
            "color": "#fff",
            "width": "100px",
            "display": "flex",
        }
    )
    out = render_react_style(n)
    # Extract key order from the rendered string
    import re

    keys = re.findall(r"(\w+):", out)
    assert keys.index("display") < keys.index("width")
    assert keys.index("width") < keys.index("color")
