"""Tests for TEXT node conversion"""

from __future__ import annotations

from avocado.model.scene_node import SceneNode
from avocado.parser.node_mapper import map_node
from avocado.parser.text import has_style_overrides, is_multiline


def _text(**overrides) -> dict:
    base = {
        "id": "1:1",
        "name": "T",
        "type": "TEXT",
        "characters": "hello",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 50, "height": 24},
        "style": {"fontFamily": "Inter", "fontSize": 14, "fontWeight": 400},
        "fills": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
    }
    base.update(overrides)
    return base


def test_simple_text_color_from_first_solid_fill() -> None:
    scene = SceneNode.from_dict(_text())
    tree = map_node(scene)
    assert tree.style.get("color") == "#000000"


def test_text_color_with_paint_opacity() -> None:
    scene = SceneNode.from_dict(
        _text(
            fills=[{"type": "SOLID", "color": {"r": 1, "g": 0, "b": 0, "a": 1}, "opacity": 0.5}],
        )
    )
    tree = map_node(scene)
    assert tree.style["color"] == "rgba(255, 0, 0, 0.5)"


def test_line_height_pixels() -> None:
    scene = SceneNode.from_dict(
        _text(
            style={
                "fontFamily": "Inter",
                "fontSize": 14,
                "lineHeightPx": 20,
                "lineHeightUnit": "PIXELS",
            },
        )
    )
    tree = map_node(scene)
    assert tree.style["line-height"] == "20px"


def test_line_height_percent() -> None:
    scene = SceneNode.from_dict(
        _text(
            style={
                "fontFamily": "Inter",
                "fontSize": 14,
                "lineHeightPercent": 150,
                "lineHeightUnit": "PERCENT",
            },
        )
    )
    tree = map_node(scene)
    assert tree.style["line-height"] == "150%"


def test_line_height_auto_omitted() -> None:
    scene = SceneNode.from_dict(
        _text(
            style={"fontFamily": "Inter", "fontSize": 14, "lineHeightUnit": "AUTO"},
        )
    )
    tree = map_node(scene)
    assert "line-height" not in tree.style


def test_line_height_inside() -> None:
    scene = SceneNode.from_dict(
        _text(
            style={
                "fontFamily": "Inter",
                "fontSize": 14,
                "lineHeightPercent": 120,
                "lineHeightUnit": "INSIDE",
            },
        )
    )
    tree = map_node(scene)
    assert tree.style["line-height"] == "120%"


def test_multiline_preserves_newlines() -> None:
    scene = SceneNode.from_dict(_text(characters="line1\nline2"))
    assert is_multiline(scene)
    tree = map_node(scene)
    assert tree.text_content == "line1\nline2"
    assert tree.style["white-space"] == "pre-line"


def test_multiline_u2028_normalized_to_lf() -> None:
    """Regression: Figma REST API uses U+2028 (LINE SEPARATOR) for
    multi-line text nodes — d2c must detect it AND normalize to \\n,
    because CSS `white-space: pre-line` only honors \\n.

    Real-world case: H5 page2 "John Doe\\u2028email\\u2028phone" was
    rendered as a single line that overflowed its 60px-tall container,
    contributing ~0.5pp of fidelity loss.
    """
    scene = SceneNode.from_dict(_text(characters="line1\u2028line2"))
    assert is_multiline(scene)
    tree = map_node(scene)
    # Normalized to \n for CSS white-space: pre-line to work
    assert tree.text_content == "line1\nline2"
    assert tree.style["white-space"] == "pre-line"


def test_multiline_u2029_paragraph_separator() -> None:
    """U+2029 (PARAGRAPH SEPARATOR) is rarer but should also be detected."""
    scene = SceneNode.from_dict(_text(characters="para1\u2029para2"))
    assert is_multiline(scene)
    tree = map_node(scene)
    assert tree.text_content == "para1\npara2"


def test_single_line_no_whitespace_prop() -> None:
    scene = SceneNode.from_dict(_text(characters="single"))
    tree = map_node(scene)
    assert "white-space" not in tree.style


def test_style_overrides_detected() -> None:
    scene = SceneNode.from_dict(
        _text(
            characters="Bold Normal",
            styleOverrideTable={"1": {"fontWeight": 700}},
            characterStyleOverrides=[1, 1, 1, 1, 17, 0, 0, 0, 0, 0, 0],  # approximate
        )
    )
    assert has_style_overrides(scene)


def test_no_style_overrides_when_empty() -> None:
    scene = SceneNode.from_dict(_text())
    assert not has_style_overrides(scene)


def test_rich_text_produces_nested_spans() -> None:
    """Multi-style text → multiple child spans, each with own style."""
    scene = SceneNode.from_dict(
        _text(
            characters="BoldNormal",
            styleOverrideTable={"1": {"fontWeight": 700}},
            characterStyleOverrides=[1, 1, 1, 1, 0, 0, 0, 0, 0, 0],
        )
    )
    tree = map_node(scene)
    # tree.text_content should be None (children carry text)
    assert tree.text_content is None
    # Should have 2 children (Bold run + Normal run)
    assert len(tree.children) == 2
    bold = tree.children[0]
    normal = tree.children[1]
    assert bold.text_content == "Bold"
    assert bold.style["font-weight"] == 700
    assert normal.text_content == "Normal"
    assert "font-weight" not in normal.style


def test_rich_text_with_color_override() -> None:
    scene = SceneNode.from_dict(
        _text(
            characters="ab",
            styleOverrideTable={"1": {"color": {"r": 1, "g": 0, "b": 0, "a": 1}}},
            characterStyleOverrides=[1, 0],
        )
    )
    tree = map_node(scene)
    assert len(tree.children) == 2
    assert tree.children[0].style["color"] == "#ff0000"
    # Second char inherits parent color (no override)
    assert "color" not in tree.children[1].style


def test_italic_style() -> None:
    scene = SceneNode.from_dict(
        _text(
            style={"fontFamily": "Inter", "fontSize": 14, "fontStyle": "Italic"},
        )
    )
    tree = map_node(scene)
    assert tree.style["font-style"] == "italic"


def test_text_transform_upper() -> None:
    scene = SceneNode.from_dict(
        _text(
            style={"fontFamily": "Inter", "fontSize": 14, "textCase": "UPPER"},
        )
    )
    tree = map_node(scene)
    assert tree.style["text-transform"] == "uppercase"


def test_text_decoration() -> None:
    for figma_val, css_val in [
        ("UNDERLINE", "underline"),
        ("STRIKETHROUGH", "line-through"),
    ]:
        scene = SceneNode.from_dict(
            _text(
                style={"fontFamily": "Inter", "fontSize": 14, "textDecoration": figma_val},
            )
        )
        tree = map_node(scene)
        assert tree.style["text-decoration"] == css_val


def test_real_text_node_renders_correctly() -> None:
    """Real TEXT from Confirm fixture — should include color, font-size, line-height."""
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).parent / "fixtures" / "02_confirm_frame" / "input.json").read_text()
    )
    doc = data["nodes"]["1732:4245"]["document"]

    def find_text(n):
        if n.get("type") == "TEXT":
            return n
        for c in n.get("children", []):
            r = find_text(c)
            if r:
                return r
        return None

    text_node = find_text(doc)
    scene = SceneNode.from_dict(text_node)
    tree = map_node(scene)
    # Should have font-family (Inter), font-size, color, line-height
    assert "Inter" in str(tree.style.get("font-family", ""))
    assert "font-size" in tree.style
    assert "line-height" in tree.style
