"""Tests for CSS variable extraction."""

from __future__ import annotations

import json
from pathlib import Path

from avocado.model.scene_node import SceneNode
from avocado.parser.css_variable import (
    CssVariableCollection,
    _format_value,
    _short_id,
    collect_variables,
)
from avocado.parser.node_mapper import map_node

FIXTURE = Path(__file__).parent / "fixtures" / "02_confirm_frame" / "input.json"


# ── helpers ──


def test_short_id_extracts_last_segment() -> None:
    full = "VariableID:9810cffc.../15156:453"
    short = _short_id(full)
    assert short == "fig-var-15156-453"


def test_format_value_adds_px() -> None:
    assert _format_value(8) == "8px"
    assert _format_value(8.5) == "8.5px"
    assert _format_value("red") == "red"


def test_format_value_rounds_and_strips_zero() -> None:
    assert _format_value(8.0) == "8px"
    assert _format_value(8.10) == "8.1px"


# ── CssVariableCollection ──


def test_collection_add_returns_var_ref() -> None:
    c = CssVariableCollection()
    ref = c.add("VariableID:abc/1:2", 16)
    assert ref == "var(--fig-var-1-2)"


def test_collection_dedupes_same_var_id() -> None:
    c = CssVariableCollection()
    c.add("VariableID:abc/1:2", 16)
    c.add("VariableID:abc/1:2", 16)  # same id
    assert len(c.variables) == 1


def test_collection_render_root_block() -> None:
    c = CssVariableCollection()
    c.add("VariableID:abc/1:2", 16)
    c.add("VariableID:def/3:4", "red")
    block = c.render_root_block()
    assert ":root {" in block
    assert "--fig-var-1-2: 16px" in block
    assert "--fig-var-3-4: red" in block
    assert "}" in block


def test_collection_render_empty() -> None:
    c = CssVariableCollection()
    assert c.render_root_block() == ""


# ── collect_variables ──


def test_collect_from_synthetic_bound_node() -> None:
    """A node with cornerRadius bound to a variable → border-radius replaced."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Box",
            "type": "RECTANGLE",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
            "cornerRadius": 8,
            "boundVariables": {
                "cornerRadius": {
                    "id": "VariableID:abc/1:2",
                    "type": "VARIABLE_ALIAS",
                }
            },
        }
    )
    tree = map_node(scene)
    collection = collect_variables(scene, tree)

    assert "fig-var-1-2" in collection.variables
    assert collection.variables["fig-var-1-2"] == "8px"
    # tree.style["border-radius"] should now be the var reference (with fallback)
    assert tree.style.get("border-radius") == "var(--fig-var-1-2, 8px)"


def test_collect_does_not_replace_when_value_mismatches() -> None:
    """If the bound var value doesn't match the style value, leave style alone."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Box",
            "type": "RECTANGLE",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
            "cornerRadius": 8,
            "boundVariables": {
                "cornerRadius": {
                    "id": "VariableID:abc/1:2",
                    "type": "VARIABLE_ALIAS",
                }
            },
        }
    )
    tree = map_node(scene)
    # Manually mess with style to force mismatch
    tree.style["border-radius"] = "99px"
    collection = collect_variables(scene, tree)
    # var is still collected
    assert "fig-var-1-2" in collection.variables
    # but style not replaced (value mismatch)
    assert tree.style["border-radius"] == "99px"


def test_collect_skips_unsupported_props() -> None:
    """boundVariables with props we don't support (e.g. fills) → no var."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "X",
            "type": "RECTANGLE",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 10, "height": 10},
            "boundVariables": {
                "fills": {"id": "VariableID:abc/1:2", "type": "VARIABLE_ALIAS"},
            },
        }
    )
    tree = map_node(scene)
    collection = collect_variables(scene, tree)
    # 'fills' not in _SUPPORTED_PROPS → not collected
    assert collection.variables == {}


def test_collect_from_real_confirm_fixture() -> None:
    """Real Confirm fixture has many boundVariables; we should collect some."""
    data = json.loads(FIXTURE.read_text())
    doc = data["nodes"]["1732:4245"]["document"]
    scene = SceneNode.from_dict(doc)
    tree = map_node(scene, client=None, file_key="FIGMA_FILE_KEY_PLACEHOLDER_001")
    collection = collect_variables(scene, tree)
    # Real fixture has 13 unique var ids; supported props subset will collect some
    assert len(collection.variables) > 0
    # Root block should be non-empty
    block = collection.render_root_block()
    assert ":root" in block


def test_collect_walks_nested_tree() -> None:
    """boundVariables on a deeply nested child should still be collected."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Root",
            "type": "FRAME",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 200, "height": 100},
            "children": [
                {
                    "id": "1:2",
                    "name": "Child",
                    "type": "RECTANGLE",
                    "visible": True,
                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": 50, "height": 50},
                    "cornerRadius": 4,
                    "boundVariables": {
                        "cornerRadius": {
                            "id": "VariableID:xyz/9:9",
                            "type": "VARIABLE_ALIAS",
                        },
                    },
                },
            ],
        }
    )
    tree = map_node(scene)
    collection = collect_variables(scene, tree)
    assert "fig-var-9-9" in collection.variables
    assert collection.variables["fig-var-9-9"] == "4px"
    # Child tree node should have var reference (with fallback by default)
    child = tree.children[0]
    assert child.style.get("border-radius") == "var(--fig-var-9-9, 4px)"


# ── new features (paint embedded, font, fallback, var_map) ──


def test_paint_embedded_bound_variables_collected() -> None:
    """fills[0].boundVariables.color → background-color replaced."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Box",
            "type": "RECTANGLE",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
            "fills": [
                {
                    "type": "SOLID",
                    "visible": True,
                    "opacity": 1.0,
                    "color": {"r": 0.98, "g": 0.95, "b": 0.94, "a": 1.0},
                    "boundVariables": {
                        "color": {
                            "id": "VariableID:abc/5:5",
                            "type": "VARIABLE_ALIAS",
                        }
                    },
                }
            ],
        }
    )
    tree = map_node(scene)
    collect_variables(scene, tree)
    # background-color should now be var reference with fallback
    bg = tree.style.get("background-color", "")
    assert "var(--" in bg
    assert bg.startswith("var(--fig-var-5-5")
    # fallback includes the hex color (0.98, 0.95, 0.94 → #faf2f0)
    assert "#faf2f0" in bg or "rgba(" in bg


def test_paint_embedded_with_opacity() -> None:
    """paint.opacity < 1 → fallback is rgba() form."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Box",
            "type": "RECTANGLE",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
            "fills": [
                {
                    "type": "SOLID",
                    "visible": True,
                    "opacity": 0.5,
                    "color": {"r": 1.0, "g": 0.0, "b": 0.0, "a": 1.0},
                    "boundVariables": {
                        "color": {
                            "id": "VariableID:abc/7:7",
                            "type": "VARIABLE_ALIAS",
                        }
                    },
                }
            ],
        }
    )
    tree = map_node(scene)
    collect_variables(scene, tree)
    bg = tree.style.get("background-color", "")
    assert "rgba(255, 0, 0, 0.5)" in bg


def test_font_size_binding_extracted() -> None:
    """TEXT node fontSize binding → font-size replaced."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Label",
            "type": "TEXT",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 50, "height": 20},
            "characters": "Hello",
            "style": {"fontFamily": "Arial", "fontSize": 14, "fontWeight": 400},
            "boundVariables": {
                "fontSize": {
                    "id": "VariableID:abc/8:8",
                    "type": "VARIABLE_ALIAS",
                }
            },
        }
    )
    tree = map_node(scene)
    collect_variables(scene, tree)
    fs = tree.style.get("font-size", "")
    assert "var(--fig-var-8-8" in fs
    assert "14px" in fs


def test_rectangle_corner_radii_four_equal() -> None:
    """4-corner equal radius → single border-radius (handled by cornerRadius)."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Box",
            "type": "RECTANGLE",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
            "cornerRadius": 8,
            "boundVariables": {
                "cornerRadius": {
                    "id": "VariableID:abc/9:9",
                    "type": "VARIABLE_ALIAS",
                }
            },
        }
    )
    tree = map_node(scene)
    collect_variables(scene, tree)
    assert tree.style.get("border-radius", "").startswith("var(--fig-var-9-9")


def test_fallback_value_in_var_ref() -> None:
    """with_fallback=True outputs var(--x, fallback)."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Box",
            "type": "RECTANGLE",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
            "cornerRadius": 8,
            "boundVariables": {
                "cornerRadius": {
                    "id": "VariableID:abc/10:10",
                    "type": "VARIABLE_ALIAS",
                }
            },
        }
    )
    tree = map_node(scene)
    collect_variables(scene, tree, with_fallback=True)
    br = tree.style.get("border-radius", "")
    assert br == "var(--fig-var-10-10, 8px)"


def test_collect_variables_uses_var_map() -> None:
    """var_map provides semantic names → var(--color-bg-primary, #...)."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Box",
            "type": "RECTANGLE",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
            "cornerRadius": 8,
            "boundVariables": {
                "cornerRadius": {
                    "id": "VariableID:abc/11:11",
                    "type": "VARIABLE_ALIAS",
                }
            },
        }
    )
    tree = map_node(scene)
    var_map = {"VariableID:abc/11:11": "radius-md"}
    collect_variables(scene, tree, var_map=var_map, with_fallback=True)
    br = tree.style.get("border-radius", "")
    assert br == "var(--radius-md, 8px)"
