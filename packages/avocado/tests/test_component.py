"""Tests for component recognition."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from avocado.cli import main as cli_main
from avocado.model.scene_node import SceneNode
from avocado.parser.component import (
    ComponentMapping,
    apply_component,
    load_mapping,
    load_preset,
    recognize,
)
from avocado.parser.node_mapper import map_node

YAML_FIXTURE = Path(__file__).parent / "fixtures" / "test_components.yaml"


def _instance(**overrides) -> dict:
    base = {
        "id": "1:1",
        "name": "Button",
        "type": "INSTANCE",
        "visible": True,
        "componentId": "abc:123",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 80, "height": 32},
    }
    base.update(overrides)
    return base


# ── load_mapping ──


def test_load_mapping_reads_yaml() -> None:
    entries = load_mapping(YAML_FIXTURE)
    assert len(entries) == 3
    names = [e.component for e in entries]
    assert "Button" in names
    assert "Progress" in names
    assert "IconArrow" in names


def test_load_mapping_none_returns_empty() -> None:
    assert load_mapping(None) == []


def test_load_mapping_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_mapping(tmp_path / "nope.yaml") == []


# ── recognize ──


def test_recognize_by_name_case_insensitive() -> None:
    entries = [ComponentMapping(component="X", name="Button")]
    scene = SceneNode.from_dict(_instance(name="BUTTON"))
    m = recognize(scene, entries)
    assert m is not None
    assert m.component == "X"


def test_recognize_by_component_id() -> None:
    entries = [
        ComponentMapping(component="ByName", name="Button"),
        ComponentMapping(component="ById", component_id="abc:123"),
    ]
    scene = SceneNode.from_dict(_instance())
    m = recognize(scene, entries)
    # componentId takes precedence over name
    assert m is not None
    assert m.component == "ById"


def test_recognize_no_match_returns_none() -> None:
    entries = [ComponentMapping(component="X", name="Other")]
    scene = SceneNode.from_dict(_instance())
    assert recognize(scene, entries) is None


def test_recognize_non_instance_returns_none() -> None:
    """Only INSTANCE nodes can be recognized."""
    entries = [ComponentMapping(component="X", name="Box")]
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Box",
            "type": "FRAME",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 10, "height": 10},
        }
    )
    assert recognize(scene, entries) is None


def test_recognize_name_with_whitespace() -> None:
    entries = [ComponentMapping(component="X", name="Progress Indicator")]
    scene = SceneNode.from_dict(_instance(name="Progress Indicator"))
    m = recognize(scene, entries)
    assert m is not None


def test_recognize_skips_name_match_when_blocked_without_dynamic_props() -> None:
    """blockNameMatch:true entries cannot be matched by name unless the
    entry configures dynamic_props (an extractor provides the array data).
    Without dynamic_props they must be matched via componentId.
    """
    entries = [
        ComponentMapping(component="Form", name="Form", block_name_match=True),
    ]
    scene_name = SceneNode.from_dict(_instance(name="Form"))
    assert recognize(scene_name, entries) is None
    # Same scene but with explicit componentId — still matches
    entries_with_id = [
        ComponentMapping(
            component="Form",
            name="Form",
            component_id="abc:1",
            block_name_match=True,
        ),
    ]
    scene_id = SceneNode.from_dict(_instance(name="Form", componentId="abc:1"))
    m = recognize(scene_id, entries_with_id)
    assert m is not None
    assert m.component == "Form"
    # With dynamic_props configured → name match is allowed
    entries_dyn = [
        ComponentMapping(
            component="Form",
            name="Form",
            block_name_match=True,
            dynamic_props={"extractor": "summary_items"},
        ),
    ]
    m_dyn = recognize(scene_name, entries_dyn)
    assert m_dyn is not None
    assert m_dyn.component == "Form"


# ── apply_component ──


def test_apply_component_sets_tag_and_props() -> None:
    entries = [
        ComponentMapping(
            component="Button",
            package="antd",
            name="Button",
            props={"type": "default"},
        ),
    ]
    scene = SceneNode.from_dict(_instance())
    from avocado.model.tree_node import TreeNode

    tree = TreeNode(
        id=scene.id,
        name=scene.name,
        source_type=scene.type,
        tag_name="div",
        figma_id=scene.id,
    )
    result = apply_component(scene, tree, entries)
    assert result is True
    assert tree.tag_name == "Button"
    assert tree.is_component is True
    assert tree.component_package == "antd"
    assert tree.props.get("type") == "default"


def test_apply_component_no_match_returns_false() -> None:
    from avocado.model.tree_node import TreeNode

    scene = SceneNode.from_dict(_instance())
    tree = TreeNode(
        id=scene.id,
        name=scene.name,
        source_type=scene.type,
        tag_name="div",
        figma_id=scene.id,
    )
    result = apply_component(scene, tree, [])
    assert result is False
    assert tree.tag_name == "div"  # unchanged
    assert tree.is_component is False


# ── integration with map_node ──


def test_map_node_recognizes_button_instance() -> None:
    """End-to-end: Button INSTANCE → <Button>."""
    scene = SceneNode.from_dict(_instance())
    mapping = load_mapping(YAML_FIXTURE)
    tree = map_node(scene, component_mapping=mapping)
    assert tree.tag_name == "Button"
    assert tree.is_component is True
    assert tree.component_package == "antd"
    assert tree.props.get("type") == "default"


def test_map_node_unrecognized_instance_warns() -> None:
    """INSTANCE not in mapping → inspect warning + tag stays div."""
    scene = SceneNode.from_dict(_instance(name="MysteryComponent"))
    tree = map_node(scene, component_mapping=[])
    assert tree.tag_name == "div"
    assert tree.is_component is False
    assert any(i["code"] == "instance-not-recognized" for i in tree.inspect)


def test_map_node_recognized_by_component_id_overrides_name() -> None:
    scene = SceneNode.from_dict(_instance(name="Button", componentId="1454:7935"))
    mapping = load_mapping(YAML_FIXTURE)
    tree = map_node(scene, component_mapping=mapping)
    # componentId "1454:7935" → IconArrow (overrides name Button → Button)
    assert tree.tag_name == "IconArrow"


def test_real_confirm_frame_with_mapping() -> None:
    """Real Confirm fixture: with YAML mapping, some INSTANCEs become components."""
    import json

    data = json.loads(
        (Path(__file__).parent / "fixtures" / "02_confirm_frame" / "input.json").read_text()
    )
    doc = data["nodes"]["1732:4245"]["document"]
    scene = SceneNode.from_dict(doc)
    mapping = load_mapping(YAML_FIXTURE)
    tree = map_node(
        scene, client=None, file_key="FIGMA_FILE_KEY_PLACEHOLDER_001", component_mapping=mapping
    )

    # Count recognized components
    components_found = []

    def walk(t):
        if t.is_component:
            components_found.append(t.tag_name)
        for c in t.children:
            walk(c)

    walk(tree)
    # We expect at least 2 Button + 1 Progress Indicator
    assert len(components_found) >= 3
    assert "Button" in components_found
    assert "Progress" in components_found


def test_image_node_not_overridden_by_component() -> None:
    """If an INSTANCE has image fill AND matches component mapping, image wins
    (per code: not tree.is_img check before apply_component)."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Button",
            "type": "INSTANCE",
            "visible": True,
            "componentId": "abc",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 80, "height": 32},
            "fills": [{"type": "IMAGE", "visible": True, "imageRef": "x", "scaleMode": "FILL"}],
        }
    )
    mapping = [ComponentMapping(component="ShouldNotApply", name="Button")]
    tree = map_node(scene, client=None, component_mapping=mapping)
    # image wins
    assert tree.tag_name == "img"
    assert tree.is_img is True
    assert tree.is_component is False


# ── load_preset (--component-lib) ──


def test_load_preset_antd_returns_mappings() -> None:
    """The bundled antd example preset loads and yields mappings."""
    entries = load_preset("antd")
    assert len(entries) > 0
    components = {e.component for e in entries}
    assert "Button" in components
    assert "Tag" in components
    assert "Alert" in components
    # All entries point at the antd package
    assert all(e.package == "antd" for e in entries)


def test_load_preset_antd_has_known_components() -> None:
    """Canonical antd components are present; no fabricated aliases."""
    entries = load_preset("antd")
    by_name = {e.name.lower(): e.component for e in entries if e.name}
    assert by_name.get("button") == "Button"
    assert by_name.get("alert") == "Alert"
    for removed in ("btn", "cta", "carousel", "navheader"):
        assert removed not in by_name, f"{removed} must not be fabricated"


def test_load_preset_antd_button_has_no_unexpected_props() -> None:
    """Button entry has no preset props (variantProperties handles state)."""
    entries = load_preset("antd")
    button_entries = [e for e in entries if e.component == "Button" and e.name == "Button"]
    assert button_entries, "exact-name Button entry must exist"
    assert button_entries[0].props == {}


def test_load_preset_antd_uses_variant_properties() -> None:
    """Button type comes from variantProperties (Figma variant), not from a
    hard-coded preset prop."""
    entries = load_preset("antd")
    button_entries = [e for e in entries if e.name == "Button"]
    assert button_entries
    assert "type" in button_entries[0].variant_properties
    type_map = button_entries[0].variant_properties["type"]
    assert type_map.get("primary") == {"type": "primary"}
    assert type_map.get("default") == {"type": "default"}


def test_load_preset_none_returns_empty() -> None:
    assert load_preset(None) == []
    assert load_preset("") == []


def test_load_preset_unknown_raises() -> None:
    """Unknown preset name must raise FileNotFoundError (no silent empty)."""
    with pytest.raises(FileNotFoundError):
        load_preset("does-not-exist")


# ── CLI --component-lib ──


def test_cli_component_lib_and_components_mutually_exclusive(tmp_path: Path) -> None:
    """Passing both flags exits with code 2."""
    components_file = tmp_path / "components.yaml"
    components_file.write_text("components: []\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli_main,
        [
            "https://www.figma.com/design/KEY/T?node-id=1:2",
            "--components",
            str(components_file),
            "--component-lib",
            "antd",
        ],
    )
    assert result.exit_code == 2
    combined = (result.output or "") + (result.stderr or "")
    assert "mutually exclusive" in combined.lower()


def test_cli_unknown_component_lib_exits_2(monkeypatch) -> None:
    """Unknown --component-lib name exits with code 2 before hitting the API."""
    # Avoid needing a real FIGMA_TOKEN — the preset check runs before token check
    # only if the token is already set; to be safe, give a dummy token.
    monkeypatch.setenv("FIGMA_TOKEN", "dummy")
    runner = CliRunner()
    result = runner.invoke(
        cli_main,
        ["https://www.figma.com/design/KEY/T?node-id=1:2", "--component-lib", "nope-never"],
    )
    assert result.exit_code == 2
    combined = (result.output or "") + (result.stderr or "")
    assert "unknown component library preset" in combined.lower()


# ── blockNameMatch / leafExtras (neutral preset fields) ──


def test_load_mapping_parses_block_name_match(tmp_path: Path) -> None:
    """blockNameMatch:true is parsed onto ComponentMapping.block_name_match."""
    p = tmp_path / "preset.yaml"
    p.write_text(
        "components:\n"
        "  - name: Steps\n"
        "    component: Steps\n"
        "    package: '@org/lib'\n"
        "    blockNameMatch: true\n"
    )
    mappings = load_mapping(p)
    assert mappings[0].block_name_match is True


def test_load_mapping_parses_leaf_extras(tmp_path: Path) -> None:
    """leafExtras list is parsed onto ComponentMapping.leaf_extras."""
    p = tmp_path / "preset.yaml"
    p.write_text(
        "components:\n"
        "  - name: Input\n"
        "    component: Input\n"
        "    package: '@org/lib'\n"
        "    leaf: true\n"
        "    leafExtras: ['helper text', 'error message']\n"
    )
    mappings = load_mapping(p)
    assert mappings[0].leaf is True
    assert mappings[0].leaf_extras == ("helper text", "error message")
