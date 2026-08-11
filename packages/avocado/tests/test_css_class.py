"""P2 CSS class extraction tests."""

from __future__ import annotations

from avocado.generator.codegen import render_jsx
from avocado.generator.css_class import apply_css_class, render_css_block
from avocado.model.tree_node import TreeNode


def _node(name="n", source_type="FRAME", **kw) -> TreeNode:
    base = dict(id=name, name=name, source_type=source_type)
    base.update(kw)
    return TreeNode(**base)


def test_chinese_node_name_falls_back_to_source_type():
    # Non-ASCII names should drop to a source-type-derived slug.
    root = _node("中文节点", source_type="FRAME", style={"color": "red"})
    class_map = apply_css_class(root)
    assert "frame" in class_map
    assert root.props.get("className") == "frame"
    assert root.style == {}


def test_collision_gets_numeric_suffix():
    # Two nodes with the same derived name but different styles.
    a = _node("Card", source_type="FRAME", style={"color": "red"})
    b = _node("Card", source_type="FRAME", style={"color": "blue"})
    apply_css_class(a)
    apply_css_class(b)
    # Merging both maps as the CLI would: simulate via a parent tree.
    root = _node("root", source_type="FRAME", style={})
    a2 = _node("Card", source_type="FRAME", style={"color": "red"})
    b2 = _node("Card", source_type="FRAME", style={"color": "blue"})
    root.children = [a2, b2]
    merged = apply_css_class(root)
    # One base name + one suffixed.
    assert "card" in merged
    suffixed = [k for k in merged if k.startswith("card-")]
    assert len(suffixed) == 1


def test_render_css_block_emits_valid_css():
    class_map = {"foo": {"color": "red", "background": "white"}}
    out = render_css_block(class_map)
    assert ".foo {" in out
    assert "color: red;" in out
    assert "background: white;" in out
    assert out.rstrip().endswith("}")


def test_box_sizing_injected_into_html_output():
    root = _node("n", source_type="FRAME", tag_name="div")
    out = render_jsx(root, format="html", box_sizing="border-box")
    assert "<style>*{box-sizing:border-box}</style>" in out


def test_box_sizing_default_is_none_keeps_legacy_output():
    root = _node("n", source_type="FRAME", tag_name="div")
    out = render_jsx(root, format="html")
    assert "<style>" not in out
