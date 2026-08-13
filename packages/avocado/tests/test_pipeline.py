"""End-to-end pipeline test: SceneNode JSON → TreeNode → JSX string.

This is the acceptance test per design docs
"""

from __future__ import annotations

import json
from pathlib import Path

from avocado.generator.codegen import render_jsx
from avocado.generator.tailwind import style_to_tailwind
from avocado.model.scene_node import SceneNode
from avocado.parser.node_mapper import map_node

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> SceneNode:
    with (FIXTURES / name / "input.json").open() as f:
        return SceneNode.from_dict(json.load(f))


# ── 01 simple text ──


def test_01_simple_text_renders_to_span() -> None:
    scene = _load("01_simple_text")
    tree = map_node(scene)
    jsx = render_jsx(tree)

    # Should produce a self-closing or text-bearing <span>
    assert "<span" in jsx
    assert "Back" in jsx
    # Text content must be inside the span, not as attribute
    assert ">Back" in jsx or ">Back " in jsx


def test_01_simple_text_has_font_size() -> None:
    scene = _load("01_simple_text")
    tree = map_node(scene)
    jsx = render_jsx(tree)
    # Button labels in this design have a font-size
    assert "font-size" in jsx


# ── Synthetic cases (no Figma call) ──


def test_synthetic_rectangle_with_solid_fill() -> None:
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Box",
            "type": "RECTANGLE",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
            "fills": [
                {"type": "SOLID", "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
            ],
            "cornerRadius": 8,
        }
    )
    tree = map_node(scene)
    jsx = render_jsx(tree)
    assert "<div" in jsx
    assert "width: 100px" in jsx
    assert "height: 50px" in jsx
    assert "background-color: #ff0000" in jsx
    assert "border-radius: 8px" in jsx


def test_synthetic_non_uniform_corner_radius() -> None:
    """rectangleCornerRadii → 4-value border-radius through the pipeline.

    Regression for bottom sheets / panels whose top corners are rounded
    ([topLeft, topRight, bottomRight, bottomLeft]) but cornerRadius is null —
    previously the node lost its border-radius entirely.
    """
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Sheet",
            "type": "FRAME",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 375, "height": 118},
            "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1, "a": 1}}],
            "rectangleCornerRadii": [16.0, 16.0, 0.0, 0.0],
        }
    )
    tree = map_node(scene)
    # HTML/CSS form
    jsx = render_jsx(tree)
    assert "border-radius: 16px 16px 0 0" in jsx
    # React style-object form (camelCase + px strings)
    jsx = render_jsx(tree, format="react")
    assert 'borderRadius: "16px 16px 0 0"' in jsx


def test_react_format_renders_style_object_on_synthetic_box() -> None:
    """React format emits style={{...}} with camelCase + px strings."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Box",
            "type": "RECTANGLE",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
            "fills": [
                {"type": "SOLID", "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
            ],
            "cornerRadius": 8,
        }
    )
    tree = map_node(scene)
    jsx = render_jsx(tree, format="react")
    assert "<div" in jsx
    assert "export default function" in jsx
    # React style object form
    assert "style={{" in jsx
    # camelCase keys
    assert "backgroundColor:" in jsx
    assert "borderRadius:" in jsx
    # px strings for length values
    assert 'width: "100px"' in jsx
    assert 'height: "50px"' in jsx
    assert 'borderRadius: "8px"' in jsx
    # No HTML-style attributes
    assert 'style="' not in jsx
    assert "background-color" not in jsx


def test_synthetic_frame_with_text_child() -> None:
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Container",
            "type": "FRAME",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 200, "height": 100},
            "layoutMode": "NONE",
            "children": [
                {
                    "id": "1:2",
                    "name": "Label",
                    "type": "TEXT",
                    "characters": "Hello",
                    "absoluteBoundingBox": {"x": 10, "y": 10, "width": 80, "height": 24},
                    "style": {"fontFamily": "Inter", "fontSize": 16, "fontWeight": 500},
                },
            ],
        }
    )
    tree = map_node(scene)
    jsx = render_jsx(tree)

    # Container div should wrap the text
    assert "<div" in jsx
    assert "</div>" in jsx
    # Child span with text
    assert "<span" in jsx
    assert "Hello" in jsx
    # Inspect warning emitted (no auto layout)
    assert any(i["code"] == "no-auto-layout" for i in tree.inspect)


def test_synthetic_invisible_node_skipped_in_children() -> None:
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Parent",
            "type": "FRAME",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 100},
            "children": [
                {
                    "id": "1:2",
                    "name": "Visible",
                    "type": "RECTANGLE",
                    "visible": True,
                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": 50, "height": 50},
                },
                {
                    "id": "1:3",
                    "name": "Hidden",
                    "type": "RECTANGLE",
                    "visible": False,
                    "absoluteBoundingBox": {"x": 50, "y": 0, "width": 50, "height": 50},
                },
            ],
        }
    )
    tree = map_node(scene)
    # Only the visible child should be in children
    assert len(tree.children) == 1
    assert tree.children[0].name == "Visible"


def test_self_closing_when_empty() -> None:
    """Empty div uses explicit open+close (HTML5-valid), not `<div />`."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Empty",
            "type": "RECTANGLE",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 10, "height": 10},
        }
    )
    tree = map_node(scene)
    jsx = render_jsx(tree)
    # Non-void tags close explicitly so HTML5 parsers don't leave them open
    assert jsx.strip().endswith("</div>")


def test_void_tag_self_closes() -> None:
    """img (void element) self-closes with `/>`."""
    from avocado.model.tree_node import TreeNode

    tree = TreeNode(
        id="1:1",
        name="I",
        source_type="RECTANGLE",
        tag_name="img",
        figma_id="1:1",
    )
    tree.is_img = True
    tree.props["src"] = "x.png"
    jsx = render_jsx(tree)
    assert jsx.strip().endswith("/>")


def test_text_escape_special_chars() -> None:
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "T",
            "type": "TEXT",
            "characters": "a < b & c > d",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 50, "height": 20},
        }
    )
    tree = map_node(scene)
    jsx = render_jsx(tree)
    assert "&lt;" in jsx
    assert "&gt;" in jsx
    assert "&amp;" in jsx


# ── HTML mode must not emit ES6 imports ──


def test_html_mode_strips_component_imports() -> None:
    """HTML output is not a JS module — ES6 import statements are illegal.

    When a plugin marks nodes with component_package (name-based recognizer),
    react format collects them into import lines but html format must drop
    them entirely; otherwise browsers render the import as text.
    """
    from avocado.model.tree_node import TreeNode

    root = TreeNode(
        id="1:1",
        name="Page",
        source_type="FRAME",
        tag_name="Button",
        is_component=True,
        component_package="my-component-lib",
        children=[
            TreeNode(
                id="1:2",
                name="Divider",
                source_type="FRAME",
                tag_name="Divider",
                is_component=True,
                component_package="my-component-lib",
            )
        ],
    )

    # HTML mode: no import lines
    html_out = render_jsx(root, format="html")
    assert "import" not in html_out
    assert 'from "' not in html_out

    # React mode: import lines present (sanity check that the tree really has
    # components to import — otherwise the html assertion above is vacuous)
    react_out = render_jsx(root, format="react")
    assert "import" in react_out
    assert "my-component-lib" in react_out


def test_html_mode_preserves_box_sizing_without_imports() -> None:
    """HTML mode with box_sizing emits the <style> reset but still no imports."""
    from avocado.model.tree_node import TreeNode

    root = TreeNode(
        id="1:1",
        name="Page",
        source_type="FRAME",
        tag_name="Button",
        is_component=True,
        component_package="my-component-lib",
    )

    out = render_jsx(root, format="html", box_sizing="content-box")
    # box_sizing style tag is present
    assert "<style>*{box-sizing:content-box}</style>" in out
    # but no import leaked
    assert "import" not in out


# ── no injected semantic reset (issue #28/#30: 0 pollution) ──


def test_no_semantic_reset_injected_in_react_mode() -> None:
    """React output does not inject a semantic <style> reset (issue #30).

    UA-styled semantic tags are only emitted for tailwind (preflight resets
    them); inline/class keep them as div. No <style> reset is ever injected,
    so the generated code stays clean.
    """
    from avocado.model.tree_node import TreeNode

    root = TreeNode(
        id="1:1",
        name="Page",
        source_type="FRAME",
        tag_name="div",
        children=[TreeNode(id="1:2", name="Item", source_type="FRAME", tag_name="li")],
    )
    # li would only be set by tailwind semanticization; render_jsx does not
    # itself know about css_form and must not inject any reset.
    out = render_jsx(root, format="react", box_sizing=None)
    assert "h1,h2,h3" not in out  # no UA-styled reset CSS
    assert "<style>" not in out  # no injected <style> at all


# ── preset props.style merged into computed style (issue #39) ──


def test_preset_props_style_merged_not_duplicated() -> None:
    """A preset `props.style` merges into the computed style — no duplicate
    `style=` attribute (duplicate JSX props are illegal and fail to compile)."""
    from avocado.model.tree_node import TreeNode

    root = TreeNode(
        id="1:1",
        name="Divider",
        source_type="INSTANCE",
        tag_name="Divider",
        is_component=True,
        props={"style": {"margin": "0"}},
        style={"display": "flex", "width": "0", "height": "18px"},
    )
    out = render_jsx(root, format="react", box_sizing=None)
    # single style attribute, preset value merged in
    assert out.count("style=") == 1
    assert "margin: \"0\"" in out
    assert "display: \"flex\"" in out


def test_preset_props_style_wins_on_conflict() -> None:
    """Preset style overrides a conflicting computed-style key (user
    explicitly configured it)."""
    from avocado.model.tree_node import TreeNode

    root = TreeNode(
        id="1:1",
        name="Divider",
        source_type="INSTANCE",
        tag_name="Divider",
        is_component=True,
        props={"style": {"margin": "0"}},
        style={"display": "flex", "margin": "8px"},  # computed has margin too
    )
    out = render_jsx(root, format="react", box_sizing=None)
    assert out.count("style=") == 1
    # preset margin wins; computed display preserved
    assert "margin: \"0\"" in out
    assert "display: \"flex\"" in out


def test_font_family_passthrough_all_forms() -> None:
    """Fonts pass through verbatim from Figma JSON across all output forms.

    Regression guard (font-debrand): the pipeline must never inject or
    substitute specific font names — whatever fontFamily the design uses
    must appear in every output form. "SentinelFont" here is a sentinel: if
    any code path hardcodes a font name, this test fails.
    """
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Container",
            "type": "FRAME",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 200, "height": 100},
            "layoutMode": "NONE",
            "children": [
                {
                    "id": "1:2",
                    "name": "Body",
                    "type": "TEXT",
                    "characters": "Hello",
                    "absoluteBoundingBox": {"x": 10, "y": 10, "width": 80, "height": 24},
                    "style": {"fontFamily": "Inter", "fontSize": 16, "fontWeight": 400},
                },
                {
                    "id": "1:3",
                    "name": "Heading",
                    "type": "TEXT",
                    "characters": "Title",
                    "absoluteBoundingBox": {"x": 10, "y": 40, "width": 120, "height": 28},
                    "style": {"fontFamily": "Roboto Slab", "fontSize": 22, "fontWeight": 500},
                },
            ],
        }
    )
    tree = map_node(scene)

    # react form: style={{...}} object. Single-word family → "Inter, sans-serif";
    # multi-word family → node_mapper quotes it → '"Roboto Slab", sans-serif'.
    react = render_jsx(tree, format="react")
    assert 'fontFamily: "Inter, sans-serif"' in react
    assert "Roboto Slab" in react
    assert "SentinelFont" not in react

    # html form: style="..." attribute. Multi-word family is HTML-escaped.
    html = render_jsx(tree)
    assert "font-family: Inter, sans-serif" in html
    assert "&quot;Roboto Slab&quot;" in html
    assert "SentinelFont" not in html

    # tailwind form: font-[...] arbitrary value (spaces → underscores).
    classes, _ = style_to_tailwind({"font-family": "Inter, sans-serif"})
    assert "font-[Inter,_sans-serif]" in classes
    assert "SentinelFont" not in classes
