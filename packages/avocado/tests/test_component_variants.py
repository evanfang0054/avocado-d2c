"""Tests for variantProperties / variants support in component.py."""

from __future__ import annotations

from avocado.model.scene_node import SceneNode
from avocado.model.tree_node import TreeNode
from avocado.parser.component import (
    ComponentMapping,
    apply_component,
    extract_variant_values,
    recognize,
)


def _instance(**props) -> dict:
    base = {
        "id": "1:1",
        "name": "X",
        "type": "INSTANCE",
        "componentId": "abc:123",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 80, "height": 32},
    }
    base.update(props)
    return base


def test_extract_variant_values_filters_non_variant() -> None:
    scene = SceneNode.from_dict(
        _instance(
            componentProperties={
                "Type": {"type": "VARIANT", "value": "Primary"},
                "Checked": {"type": "BOOLEAN", "value": True},
                "Label": {"type": "TEXT", "value": "OK"},
            }
        )
    )
    out = extract_variant_values(scene)
    assert out == {"Type": "Primary"}


def test_extract_variant_values_empty() -> None:
    scene = SceneNode.from_dict(_instance())
    assert extract_variant_values(scene) == {}


# ── variantProperties → props ─────────────────────────────────────────────────


def test_variant_properties_merge_into_props() -> None:
    """Tag State=Success → {theme: success}."""
    entries = [
        ComponentMapping(
            component="Tag",
            name="Tag",
            variant_properties={
                "State": {
                    "Success": {"theme": "success"},
                    "Warning": {"theme": "warning"},
                },
            },
        ),
    ]
    scene = SceneNode.from_dict(
        _instance(
            name="Tag",
            componentProperties={"State": {"type": "VARIANT", "value": "Success"}},
        )
    )
    tree = TreeNode(id=scene.id, name=scene.name, source_type=scene.type)
    assert apply_component(scene, tree, entries)
    assert tree.tag_name == "Tag"
    assert tree.props.get("theme") == "success"


def test_variant_properties_multi_field_button() -> None:
    """Button: Variant + Size + Type all apply together."""
    entries = [
        ComponentMapping(
            component="Button",
            name="Button",
            variant_properties={
                "Variant": {"Primary": {"type": "primary"}, "Ghost": {"type": "ghost"}},
                "Size": {"Large": {"size": "large"}, "Small": {"size": "small"}},
                "Type": {"Block": {"block": True}},
            },
        ),
    ]
    scene = SceneNode.from_dict(
        _instance(
            name="Button",
            componentProperties={
                "Variant": {"type": "VARIANT", "value": "Primary"},
                "Size": {"type": "VARIANT", "value": "Small"},
                "Type": {"type": "VARIANT", "value": "Block"},
            },
        )
    )
    tree = TreeNode(id=scene.id, name=scene.name, source_type=scene.type)
    apply_component(scene, tree, entries)
    assert tree.props == {"type": "primary", "size": "small", "block": True}


def test_variant_properties_missing_field_degrades_gracefully() -> None:
    """If Figma scene has no variant values, variantProperties is a no-op."""
    entries = [
        ComponentMapping(
            component="Tag",
            name="Tag",
            variant_properties={"State": {"Success": {"theme": "success"}}},
        ),
    ]
    scene = SceneNode.from_dict(_instance(name="Tag"))
    tree = TreeNode(id=scene.id, name=scene.name, source_type=scene.type)
    apply_component(scene, tree, entries)
    # Still recognized as Tag, just no extra props
    assert tree.is_component
    assert tree.props == {}


# ── variants → switch component ───────────────────────────────────────────────


def test_variants_switch_component_radio() -> None:
    """Checkbox with Type=Radio Button → Radio component (cloned mapping)."""
    entries = [
        ComponentMapping(
            component="Checkbox",
            name="Checkbox",
            variants={
                "Type": {
                    "Multi Checkbox": {"component": "Checkbox"},
                    "Radio Button": {"component": "Radio"},
                },
            },
        ),
    ]
    scene = SceneNode.from_dict(
        _instance(
            name="Checkbox",
            componentProperties={"Type": {"type": "VARIANT", "value": "Radio Button"}},
        )
    )
    m = recognize(scene, entries)
    assert m is not None
    assert m.component == "Radio"


def test_variants_no_match_keeps_default_component() -> None:
    entries = [
        ComponentMapping(
            component="Checkbox",
            name="Checkbox",
            variants={"Type": {"Radio Button": {"component": "Radio"}}},
        ),
    ]
    scene = SceneNode.from_dict(
        _instance(
            name="Checkbox",
            componentProperties={"Type": {"type": "VARIANT", "value": "Unknown"}},
        )
    )
    m = recognize(scene, entries)
    assert m is not None
    assert m.component == "Checkbox"


def test_variants_does_not_mutate_shared_mapping() -> None:
    """recognize must clone via dataclasses.replace — original mapping intact."""
    entries = [
        ComponentMapping(
            component="Checkbox",
            name="Checkbox",
            variants={"Type": {"Radio Button": {"component": "Radio"}}},
        ),
    ]
    scene = SceneNode.from_dict(
        _instance(
            name="Checkbox",
            componentProperties={"Type": {"type": "VARIANT", "value": "Radio Button"}},
        )
    )
    recognize(scene, entries)
    # Second call — original mapping still has Checkbox as default component
    scene2 = SceneNode.from_dict(
        _instance(
            name="Checkbox",
            componentProperties={"Type": {"type": "VARIANT", "value": "Other"}},
        )
    )
    m2 = recognize(scene2, entries)
    assert m2 is not None
    assert m2.component == "Checkbox"


def test_variants_empty_component_falls_back_to_div() -> None:
    """Tabs 'Circular on Dark' → empty component → apply_component returns False."""
    entries = [
        ComponentMapping(
            component="Tabs",
            name="Tabs",
            variants={"Style": {"Circular on Dark": {"component": ""}}},
        ),
    ]
    scene = SceneNode.from_dict(
        _instance(
            name="Tabs",
            componentProperties={"Style": {"type": "VARIANT", "value": "Circular on Dark"}},
        )
    )
    tree = TreeNode(id=scene.id, name=scene.name, source_type=scene.type)
    assert apply_component(scene, tree, entries) is False
    assert tree.is_component is False
    assert tree.tag_name == "div"
