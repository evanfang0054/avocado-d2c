"""Tests for style → component-prop mapping (preset ``styleMode: props``)."""

from __future__ import annotations

import pytest

from avocado.generator.style_props import apply_style_props
from avocado.model.tree_node import TreeNode
from avocado.parser.component import _normalize_style_props, load_mapping


def _node(**kwargs) -> TreeNode:
    defaults = {
        "id": "0",
        "name": "n",
        "source_type": "INSTANCE",
        "tag_name": "Text",
        "is_component": True,
    }
    defaults.update(kwargs)
    return TreeNode(**defaults)


# ── value-map form ──


def test_value_map_moves_style_into_prop() -> None:
    node = _node(
        style={"font-size": "14px", "line-height": "20px"},
        style_mode="props",
        style_props={"font-size": {"prop": "size", "values": {"12": "xs", "14": "sm"}}},
    )
    apply_style_props(node)
    assert node.props["size"] == "sm"
    assert "font-size" not in node.style
    # unmapped keys are untouched
    assert node.style["line-height"] == "20px"


def test_value_map_accepts_numeric_yaml_keys() -> None:
    """YAML may parse ``14: sm`` with an int key while style is ``"14px"``."""
    node = _node(
        style={"font-size": 14},
        style_mode="props",
        style_props={"font-size": {"prop": "size", "values": {14: "sm"}}},
    )
    apply_style_props(node)
    assert node.props["size"] == "sm"


def test_value_map_miss_keeps_css_inline() -> None:
    """17px has no token: never silently round it to a mapped size."""
    node = _node(
        style={"font-size": "17px"},
        style_mode="props",
        style_props={"font-size": {"prop": "size", "values": {"12": "xs", "14": "sm"}}},
    )
    apply_style_props(node)
    assert "size" not in node.props
    assert node.style["font-size"] == "17px"


# ── shorthand form (raw value → prop) ──


def test_shorthand_px_value_becomes_number() -> None:
    node = _node(
        tag_name="Image",
        style={"height": "128px", "width": "400px"},
        style_mode="props",
        style_props={
            "height": {"prop": "height", "values": {}},
            "width": {"prop": "width", "values": {}},
        },
    )
    apply_style_props(node)
    assert node.props["height"] == 128
    assert node.props["width"] == 400
    assert node.style == {}


def test_shorthand_keeps_non_numeric_value() -> None:
    node = _node(
        tag_name="Image",
        style={"width": "100%"},
        style_mode="props",
        style_props={"width": {"prop": "width", "values": {}}},
    )
    apply_style_props(node)
    assert node.props["width"] == "100%"


# ── dropStyle ──


def test_drop_style_removes_geometry_noise() -> None:
    node = _node(
        style={"width": "70px", "height": "22px", "flex-shrink": "0", "font-size": "14px"},
        style_mode="props",
        style_props={"font-size": {"prop": "size", "values": {"14": "sm"}}},
        style_drop=("width", "height", "flex-shrink"),
    )
    apply_style_props(node)
    assert node.style == {}
    assert node.props == {"size": "sm"}


# ── precedence ──


def test_existing_prop_wins_and_css_duplicate_is_dropped() -> None:
    """A preset/variant prop is author intent; inline CSS must not fight it."""
    node = _node(
        props={"size": "large"},
        style={"font-size": "14px"},
        style_mode="props",
        style_props={"font-size": {"prop": "size", "values": {"14": "sm"}}},
    )
    apply_style_props(node)
    assert node.props["size"] == "large"
    assert node.style == {}


def test_empty_style_is_noop() -> None:
    node = _node(style_mode="props", style_props={"width": {"prop": "width", "values": {}}})
    apply_style_props(node)
    assert node.props == {}


# ── preset loading ──


def test_load_mapping_parses_style_fields(tmp_path) -> None:
    preset = tmp_path / "preset.yaml"
    preset.write_text(
        """
components:
  - name: Text
    component: Text
    package: '@scope/ui'
    styleMode: props
    styleProps:
      font-size:
        prop: size
        values:
          14: sm
      color: color
    dropStyle: [width, height]
"""
    )
    [entry] = load_mapping(preset)
    assert entry.style_mode == "props"
    assert entry.style_props["font-size"] == {"prop": "size", "values": {14: "sm"}}
    assert entry.style_props["color"] == {"prop": "color", "values": {}}
    assert entry.style_drop == ("width", "height")


def test_load_mapping_defaults_to_inline(tmp_path) -> None:
    preset = tmp_path / "preset.yaml"
    preset.write_text("components:\n  - name: Button\n    component: Button\n")
    [entry] = load_mapping(preset)
    assert entry.style_mode == "inline"
    assert entry.style_props == {}
    assert entry.style_drop == ()


def test_load_mapping_rejects_unknown_style_mode(tmp_path) -> None:
    preset = tmp_path / "preset.yaml"
    preset.write_text(
        "components:\n  - name: Button\n    component: Button\n    styleMode: magic\n"
    )
    with pytest.raises(ValueError, match="invalid styleMode"):
        load_mapping(preset)


def test_normalize_style_props_derives_camel_case_prop() -> None:
    assert _normalize_style_props({"font-size": {}}) == {
        "font-size": {"prop": "fontSize", "values": {}}
    }


def test_normalize_style_props_rejects_non_mapping() -> None:
    with pytest.raises(ValueError, match="styleProps must be a mapping"):
        _normalize_style_props(["nope"])


def test_normalize_style_props_rejects_bad_entry() -> None:
    with pytest.raises(ValueError, match="must be a prop name or a mapping"):
        _normalize_style_props({"width": 42})


# ── tree-level stage ──


def test_apply_style_prop_modes_walks_components_only() -> None:
    from avocado.generator.style_props import apply_style_prop_modes

    text = _node(
        id="1",
        style={"font-size": "14px"},
        style_mode="props",
        style_props={"font-size": {"prop": "size", "values": {"14": "sm"}}},
    )
    plain = TreeNode(
        id="2",
        name="d",
        source_type="FRAME",
        style={"font-size": "14px"},
        style_mode="props",  # ignored: not a component
    )
    root = TreeNode(id="0", name="r", source_type="FRAME", children=[text, plain])
    apply_style_prop_modes(root)
    assert text.props["size"] == "sm"
    assert text.style == {}
    assert plain.props == {}
    assert plain.style == {"font-size": "14px"}


def test_apply_style_mode_helper_copies_fields() -> None:
    """Name-recognizer plugins call this after map_node; keep it in sync."""
    from avocado.parser.component import ComponentMapping, apply_style_mode

    node = _node(style_mode="inline")
    mapping = ComponentMapping(
        component="Text",
        style_mode="props",
        style_props={"font-size": {"prop": "size", "values": {"14": "sm"}}},
        style_drop=("width",),
    )
    apply_style_mode(node, mapping)
    assert node.style_mode == "props"
    assert node.style_props == {"font-size": {"prop": "size", "values": {"14": "sm"}}}
    assert node.style_drop == ("width",)
