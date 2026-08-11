"""Tests for inspectDraft rules."""

from __future__ import annotations

from avocado.model.tree_node import TreeNode
from avocado.parser.inspect import (
    _parse_color,
    _wcag_contrast,
    collect_all_warnings,
    rule_component_without_imports,
    rule_deep_nesting,
    rule_inline_style_too_long,
    rule_low_contrast_text,
    rule_many_absolute_children,
    rule_unstyled_image,
    run_all_inspect_rules,
)

# ── color helpers ──


def test_parse_color_hex() -> None:
    assert _parse_color("#000000") == (0.0, 0.0, 0.0)
    assert _parse_color("#ffffff") == (1.0, 1.0, 1.0)
    assert _parse_color("#ff0000") == (1.0, 0.0, 0.0)


def test_parse_color_rgba() -> None:
    assert _parse_color("rgba(0, 0, 0, 1)") == (0.0, 0.0, 0.0)
    assert _parse_color("rgba(255, 0, 0, 0.5)") == (1.0, 0.0, 0.0)


def test_parse_color_invalid() -> None:
    assert _parse_color("red") is None
    assert _parse_color("") is None


def test_wcag_contrast_black_on_white() -> None:
    ratio = _wcag_contrast((0, 0, 0), (1, 1, 1))
    assert ratio == 21  # max contrast


def test_wcag_contrast_same_color_is_one() -> None:
    ratio = _wcag_contrast((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
    assert abs(ratio - 1.0) < 0.01


# ── rule: deep_nesting ──


def _chain(depth: int) -> TreeNode:
    """Build a TreeNode chain of given depth."""
    root = TreeNode(id="0", name="root", source_type="FRAME")
    cur = root
    for i in range(depth):
        child = TreeNode(id=str(i), name=f"d{i}", source_type="FRAME")
        cur.children.append(child)
        cur = child
    return root


def test_deep_nesting_warns_at_8() -> None:
    root = _chain(9)  # depth 0..9
    rule_deep_nesting(root)
    # At least one node at depth >= 8 should have inspect entry
    found = []
    stack = [(root, 0)]
    while stack:
        n, d = stack.pop()
        if d >= 8 and n.inspect:
            found.append(n)
        for c in n.children:
            stack.append((c, d + 1))
    assert len(found) > 0


def test_deep_nesting_no_warning_when_shallow() -> None:
    root = _chain(3)
    rule_deep_nesting(root)
    # No node should have deep-nesting warning
    stack = [root]
    while stack:
        n = stack.pop()
        assert all(i["code"] != "deep-nesting" for i in n.inspect)
        stack.extend(n.children)


# ── rule: many_absolute_children ──


def test_many_absolute_children_warns() -> None:
    root = TreeNode(id="0", name="root", source_type="FRAME", layout_strategy="absolute_position")
    for i in range(6):
        root.children.append(TreeNode(id=str(i), name=f"c{i}", source_type="RECTANGLE"))
    rule_many_absolute_children(root)
    assert any(i["code"] == "many-absolute-children" for i in root.inspect)


def test_many_absolute_children_no_warn_when_few() -> None:
    root = TreeNode(id="0", name="root", source_type="FRAME", layout_strategy="absolute_position")
    for i in range(3):
        root.children.append(TreeNode(id=str(i), name=f"c{i}", source_type="RECTANGLE"))
    rule_many_absolute_children(root)
    assert not any(i["code"] == "many-absolute-children" for i in root.inspect)


# ── rule: low_contrast_text ──


def test_low_contrast_warns() -> None:
    """Light gray text on white = low contrast."""
    root = TreeNode(id="0", name="root", source_type="FRAME", style={"background-color": "#ffffff"})
    text = TreeNode(
        id="1",
        name="t",
        source_type="TEXT",
        tag_name="span",
        text_content="x",
        style={"color": "#cccccc"},
    )
    root.children.append(text)
    rule_low_contrast_text(root)
    assert any(i["code"] == "low-contrast" for i in text.inspect)


def test_high_contrast_no_warning() -> None:
    root = TreeNode(id="0", name="root", source_type="FRAME", style={"background-color": "#ffffff"})
    text = TreeNode(
        id="1",
        name="t",
        source_type="TEXT",
        tag_name="span",
        text_content="x",
        style={"color": "#000000"},
    )
    root.children.append(text)
    rule_low_contrast_text(root)
    assert not any(i["code"] == "low-contrast" for i in text.inspect)


def test_contrast_inherits_parent_bg() -> None:
    """If span has no own bg, uses parent's bg."""
    root = TreeNode(id="0", name="root", source_type="FRAME", style={"background-color": "#ffffff"})
    inner = TreeNode(id="1", name="inner", source_type="FRAME")
    text = TreeNode(
        id="2",
        name="t",
        source_type="TEXT",
        tag_name="span",
        text_content="x",
        style={"color": "#dddddd"},
    )
    inner.children.append(text)
    root.children.append(inner)
    rule_low_contrast_text(root)
    assert any(i["code"] == "low-contrast" for i in text.inspect)


# ── rule: unstyled_image ──


def test_unstyled_image_warns_when_no_size() -> None:
    img = TreeNode(id="0", name="img", source_type="VECTOR", tag_name="img", is_img=True)
    rule_unstyled_image(img)
    assert any(i["code"] == "img-no-size" for i in img.inspect)


def test_unstyled_image_no_warn_with_size() -> None:
    img = TreeNode(
        id="0",
        name="img",
        source_type="VECTOR",
        tag_name="img",
        is_img=True,
        style={"width": "100px", "height": "50px"},
    )
    rule_unstyled_image(img)
    assert not any(i["code"] == "img-no-size" for i in img.inspect)


# ── rule: inline_style_too_long ──


def test_inline_style_too_long_warns() -> None:
    n = TreeNode(id="0", name="n", source_type="FRAME", style={f"prop{i}": "v" for i in range(10)})
    rule_inline_style_too_long(n)
    assert any(i["code"] == "long-inline-style" for i in n.inspect)


def test_inline_style_short_no_warning() -> None:
    n = TreeNode(id="0", name="n", source_type="FRAME", style={"a": "1", "b": "2"})
    rule_inline_style_too_long(n)
    assert not any(i["code"] == "long-inline-style" for i in n.inspect)


# ── rule: component_without_imports ──


def test_component_without_package_warns() -> None:
    n = TreeNode(
        id="0",
        name="x",
        source_type="INSTANCE",
        tag_name="MyComp",
        is_component=True,
        component_package=None,
    )
    rule_component_without_imports(n)
    assert any(i["code"] == "component-no-package" for i in n.inspect)


def test_component_with_package_no_warning() -> None:
    n = TreeNode(
        id="0",
        name="x",
        source_type="INSTANCE",
        tag_name="MyComp",
        is_component=True,
        component_package="@scope/pkg",
    )
    rule_component_without_imports(n)
    assert not any(i["code"] == "component-no-package" for i in n.inspect)


# ── registry / collect_all_warnings ──


def test_run_all_inspect_rules_returns_count() -> None:
    root = _chain(10)
    count = run_all_inspect_rules(root)
    assert count > 0


def test_collect_all_warnings_flattens() -> None:
    root = TreeNode(id="0", name="root", source_type="FRAME")
    root.add_inspect(severity="info", code="x", message="a")
    child = TreeNode(id="1", name="c", source_type="FRAME")
    child.add_inspect(severity="warning", code="y", message="b")
    root.children.append(child)
    all_w = collect_all_warnings(root)
    assert len(all_w) == 2
    codes = {w["code"] for w in all_w}
    assert codes == {"x", "y"}


def test_collect_all_warnings_includes_node_info() -> None:
    root = TreeNode(id="0", name="root", source_type="FRAME", figma_id="abc")
    root.add_inspect(severity="info", code="x", message="a")
    all_w = collect_all_warnings(root)
    assert all_w[0]["figma_id"] == "abc"
    assert all_w[0]["node_name"] == "root"


def test_real_confirm_fixture_emits_warnings() -> None:
    """Real fixture should produce many warnings after inspect rules run."""
    import json
    from pathlib import Path

    from avocado.model.scene_node import SceneNode
    from avocado.parser.node_mapper import map_node

    data = json.loads(
        (Path(__file__).parent / "fixtures" / "02_confirm_frame" / "input.json").read_text()
    )
    doc = data["nodes"]["1732:4245"]["document"]
    scene = SceneNode.from_dict(doc)
    tree = map_node(scene, client=None, file_key="FIGMA_FILE_KEY_PLACEHOLDER_001")
    run_all_inspect_rules(tree)
    all_w = collect_all_warnings(tree)
    # Many warnings expected (deep-nesting, instance-not-recognized, etc)
    assert len(all_w) > 20
    # At least 3 different codes
    codes = {w["code"] for w in all_w}
    assert len(codes) >= 3
