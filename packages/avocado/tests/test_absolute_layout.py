"""Tests for absolute positioning strategy."""

from __future__ import annotations

from avocado.model.scene_node import SceneNode
from avocado.parser.absolute_layout import (
    children_overlap,
    needs_absolute_strategy,
)
from avocado.parser.node_mapper import map_node


def _box(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def _frame_with_scatter_children():
    """Synthetic FRAME without Auto Layout, with two overlapping children."""
    return {
        "id": "1:1",
        "name": "Scatter",
        "type": "FRAME",
        "layoutMode": "NONE",
        "absoluteBoundingBox": _box(100, 100, 300, 200),
        "children": [
            {
                "id": "1:2",
                "name": "A",
                "type": "RECTANGLE",
                "visible": True,
                "absoluteBoundingBox": _box(110, 110, 100, 50),
            },
            {
                "id": "1:3",
                "name": "B",
                "type": "RECTANGLE",
                "visible": True,
                "absoluteBoundingBox": _box(150, 130, 100, 50),  # overlaps A
            },
        ],
    }


def _frame_with_separated_children():
    """Synthetic FRAME without Auto Layout, with NON-overlapping children."""
    return {
        "id": "1:1",
        "name": "Sep",
        "type": "FRAME",
        "layoutMode": "NONE",
        "absoluteBoundingBox": _box(0, 0, 400, 100),
        "children": [
            {
                "id": "1:2",
                "name": "L",
                "type": "RECTANGLE",
                "visible": True,
                "absoluteBoundingBox": _box(0, 0, 100, 50),
            },
            {
                "id": "1:3",
                "name": "R",
                "type": "RECTANGLE",
                "visible": True,
                "absoluteBoundingBox": _box(300, 0, 100, 50),  # no overlap
            },
        ],
    }


def test_needs_absolute_strategy_no_auto_layout_with_children() -> None:
    scene = SceneNode.from_dict(_frame_with_scatter_children())
    assert needs_absolute_strategy(scene)


def test_needs_absolute_strategy_auto_layout_excluded() -> None:
    scene = SceneNode.from_dict(
        {
            **_frame_with_scatter_children(),
            "layoutMode": "VERTICAL",
        }
    )
    assert not needs_absolute_strategy(scene)


def test_needs_absolute_strategy_single_child_included() -> None:
    """A single child without Auto Layout still triggers absolute (e.g. icon
    placed at corner of a card)."""
    frame = _frame_with_scatter_children()
    frame["children"] = frame["children"][:1]
    scene = SceneNode.from_dict(frame)
    assert needs_absolute_strategy(scene)


def test_children_overlap_detected() -> None:
    scene = SceneNode.from_dict(_frame_with_scatter_children())
    assert children_overlap(scene.children)


def test_children_no_overlap() -> None:
    scene = SceneNode.from_dict(_frame_with_separated_children())
    assert not children_overlap(scene.children)


def test_absolute_layout_applied_to_overlapping() -> None:
    scene = SceneNode.from_dict(_frame_with_scatter_children())
    tree = map_node(scene)
    assert tree.style.get("position") == "relative"
    assert tree.layout_strategy == "absolute_position"
    # Children should be absolutely positioned
    for child in tree.children:
        assert child.style.get("position") == "absolute"
        assert "top" in child.style
        assert "left" in child.style


def test_absolute_coords_relative_to_parent() -> None:
    """top/left are RELATIVE TO PARENT (subtract parent's x/y)."""
    scene = SceneNode.from_dict(_frame_with_scatter_children())
    tree = map_node(scene)
    # Parent at (100, 100); child A at (110, 110) → top:10 left:10
    a = tree.children[0]
    assert a.style["top"] == "10px"
    assert a.style["left"] == "10px"
    # Child B at (150, 130) → top:30 left:50
    b = tree.children[1]
    assert b.style["top"] == "30px"
    assert b.style["left"] == "50px"


def test_absolute_layout_applied_even_when_no_overlap() -> None:
    """Without Auto Layout, even non-overlapping children use absolute
    positioning (D2C default for predictability per design docs)."""
    scene = SceneNode.from_dict(_frame_with_separated_children())
    tree = map_node(scene)
    assert tree.style.get("position") == "relative"
    assert tree.layout_strategy == "absolute_position"


def test_width_height_preserved_on_absolute_children() -> None:
    """Absolute children keep their width/height (box size)."""
    scene = SceneNode.from_dict(_frame_with_scatter_children())
    tree = map_node(scene)
    a = tree.children[0]
    assert a.style.get("width") == "100px"
    assert a.style.get("height") == "50px"


def test_nested_absolute_layout_propagates_correctly() -> None:
    """Multi-level: each child's coords relative to its DIRECT parent."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "Outer",
            "type": "FRAME",
            "layoutMode": "NONE",
            "absoluteBoundingBox": _box(0, 0, 500, 500),
            "children": [
                {
                    "id": "1:2",
                    "name": "Inner",
                    "type": "FRAME",
                    "layoutMode": "NONE",
                    "visible": True,
                    "absoluteBoundingBox": _box(100, 100, 200, 200),
                    "children": [
                        {
                            "id": "1:3",
                            "name": "Deep",
                            "type": "RECTANGLE",
                            "visible": True,
                            "absoluteBoundingBox": _box(150, 150, 50, 50),
                        },
                    ],
                },
            ],
        }
    )
    tree = map_node(scene)
    inner = tree.children[0]
    # Inner is at (100, 100) relative to outer (0, 0)
    assert inner.style["top"] == "100px"
    assert inner.style["left"] == "100px"
    # Deep is at (150, 150) relative to INNER (100, 100) → top:50 left:50
    deep = inner.children[0]
    assert deep.style["top"] == "50px"
    assert deep.style["left"] == "50px"


def test_real_data_no_regression_on_auto_layout() -> None:
    """Real Confirm fixture should NOT trigger absolute positioning at root
    (root uses Auto Layout)."""
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).parent / "fixtures" / "02_confirm_frame" / "input.json").read_text()
    )
    doc = data["nodes"]["1732:4245"]["document"]
    scene = SceneNode.from_dict(doc)
    tree = map_node(scene)
    # Root uses VERTICAL auto layout → flex, NOT absolute
    assert tree.style.get("display") == "flex"
    assert tree.style.get("position") != "relative"
