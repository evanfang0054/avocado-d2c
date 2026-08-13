"""Tests for Auto Layout → Flexbox conversion"""

from __future__ import annotations

from avocado.model.scene_node import SceneNode
from avocado.parser.node_mapper import map_node


def _frame(**overrides) -> dict:
    """Synthetic FRAME with optional fields."""
    base = {
        "id": "1:1",
        "name": "F",
        "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 200, "height": 100},
        "children": [],
    }
    base.update(overrides)
    return base


def test_horizontal_layout_produces_row_flex() -> None:
    scene = SceneNode.from_dict(_frame(layoutMode="HORIZONTAL"))
    tree = map_node(scene)
    assert tree.style["display"] == "flex"
    assert tree.style["flex-direction"] == "row"
    assert tree.layout_strategy == "auto_layout"


def test_vertical_layout_produces_column_flex() -> None:
    scene = SceneNode.from_dict(_frame(layoutMode="VERTICAL"))
    tree = map_node(scene)
    assert tree.style["flex-direction"] == "column"


def test_no_layout_falls_to_absolute_when_has_children() -> None:
    # Frames without Auto Layout but with children use absolute
    # positioning (not auto_group) for predictability.
    scene = SceneNode.from_dict(
        {
            **_frame(layoutMode="NONE"),
            "children": [
                {
                    "id": "1:2",
                    "name": "C",
                    "type": "RECTANGLE",
                    "visible": True,
                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": 10, "height": 10},
                },
            ],
        }
    )
    tree = map_node(scene)
    # apply_absolute_layout runs after layout.py and overrides strategy
    assert tree.layout_strategy == "absolute_position"
    assert tree.style.get("display") != "flex"


def test_no_layout_no_children_is_leaf() -> None:
    scene = SceneNode.from_dict(_frame(layoutMode="NONE"))
    tree = map_node(scene)
    assert tree.layout_strategy == "leaf"


def test_primary_axis_alignment_mapping() -> None:
    for figma_val, css_val in [
        ("MIN", "flex-start"),
        ("CENTER", "center"),
        ("MAX", "flex-end"),
        ("SPACE_BETWEEN", "space-between"),
    ]:
        scene = SceneNode.from_dict(_frame(layoutMode="VERTICAL", primaryAxisAlignItems=figma_val))
        tree = map_node(scene)
        assert tree.style["justify-content"] == css_val


def test_counter_axis_alignment_mapping() -> None:
    for figma_val, css_val in [
        ("MIN", "flex-start"),
        ("CENTER", "center"),
        ("MAX", "flex-end"),
    ]:
        scene = SceneNode.from_dict(_frame(layoutMode="VERTICAL", counterAxisAlignItems=figma_val))
        tree = map_node(scene)
        assert tree.style["align-items"] == css_val


def test_item_spacing_becomes_gap() -> None:
    scene = SceneNode.from_dict(_frame(layoutMode="VERTICAL", itemSpacing=16))
    tree = map_node(scene)
    assert tree.style["gap"] == "16px"


def test_item_spacing_skipped_when_space_between() -> None:
    """Regression: SPACE_BETWEEN + itemSpacing must NOT emit CSS `gap`.

    Figma's `itemSpacing` with SPACE_BETWEEN means "minimum gap if there's
    slack", which space-between already distributes. Adding CSS `gap` on
    top double-counts spacing and can push children off-screen.

    Real-world case: iOS status bar row (375px wide, 3 children, gap=134)
    — emitting `gap: 134px` pushed the battery/levels cluster to x=467,
    off the visible 375px viewport, blowing the H5 page's fidelity by ~4%.
    """
    scene = SceneNode.from_dict(
        _frame(
            layoutMode="HORIZONTAL",
            primaryAxisAlignItems="SPACE_BETWEEN",
            itemSpacing=134,
        )
    )
    tree = map_node(scene)
    assert tree.style["justify-content"] == "space-between"
    assert "gap" not in tree.style


def test_horizontal_scroller_emits_overflow_visible() -> None:
    """Investigation: horizontal scroller emits overflow-x:visible.

    We tested overflow:hidden here thinking it would match Figma's PNG
    export (which clips to the node bbox). Reality: Figma's PNG export
    *includes* overflowed siblings (rendered to canvas before clipping),
    so overflow:hidden made fidelity WORSE. The original overflow:visible
    is correct. This test locks the behavior in place.
    """
    scene = SceneNode.from_dict(
        {
            **_frame(layoutMode="HORIZONTAL"),
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 327, "height": 198},
            "children": [
                {
                    "id": "1:2",
                    "name": "Card1",
                    "type": "RECTANGLE",
                    "visible": True,
                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": 307, "height": 198},
                },
                {
                    "id": "1:3",
                    "name": "Card2",
                    "type": "RECTANGLE",
                    "visible": True,
                    "absoluteBoundingBox": {"x": 323, "y": 0, "width": 307, "height": 198},
                },
                {
                    "id": "1:4",
                    "name": "Card3",
                    "type": "RECTANGLE",
                    "visible": True,
                    "absoluteBoundingBox": {"x": 646, "y": 0, "width": 307, "height": 198},
                },
            ],
        }
    )
    tree = map_node(scene)
    assert tree.style.get("overflow-x") == "visible"
    assert tree.style.get("flex-wrap") == "nowrap"


def test_padding_concatenated_shorthand() -> None:
    scene = SceneNode.from_dict(
        _frame(
            layoutMode="VERTICAL",
            paddingTop=10,
            paddingRight=20,
            paddingBottom=10,
            paddingLeft=20,
        )
    )
    tree = map_node(scene)
    assert tree.style["padding"] == "10px 20px 10px 20px"


def test_zero_padding_omitted() -> None:
    scene = SceneNode.from_dict(
        _frame(
            layoutMode="VERTICAL",
            paddingTop=0,
            paddingRight=0,
            paddingBottom=0,
            paddingLeft=0,
        )
    )
    tree = map_node(scene)
    assert "padding" not in tree.style


def test_child_layout_grow_becomes_flex_grow() -> None:
    """When parent uses auto layout, child with layoutGrow=1 gets flex-grow."""
    scene = SceneNode.from_dict(
        {
            **_frame(layoutMode="VERTICAL"),
            "children": [
                {
                    "id": "1:2",
                    "name": "Grow",
                    "type": "RECTANGLE",
                    "visible": True,
                    "layoutGrow": 1,
                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
                },
            ],
        }
    )
    tree = map_node(scene)
    child = tree.children[0]
    assert child.style["flex-grow"] == 1


def test_child_sizing_hug_keeps_dimension() -> None:
    """Final: HUG keeps bbox dimension (browser would compute similar
    but explicit is safer for content-sparse children)."""
    scene = SceneNode.from_dict(
        {
            **_frame(layoutMode="HORIZONTAL"),
            "children": [
                {
                    "id": "1:2",
                    "name": "H",
                    "type": "RECTANGLE",
                    "visible": True,
                    "layoutSizingHorizontal": "HUG",
                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
                },
            ],
        }
    )
    tree = map_node(scene)
    child = tree.children[0]
    # HUG keeps bbox width
    assert child.style.get("width") == "100px"


def test_child_sizing_fill_uses_flex_grow() -> None:
    """MAIN-axis FILL → flex-grow:1 + drop dim. CROSS-axis FILL → align-self:stretch only."""
    # VERTICAL parent + vertical FILL child → main-axis FILL → flex-grow
    scene = SceneNode.from_dict(
        {
            **_frame(layoutMode="VERTICAL"),
            "children": [
                {
                    "id": "1:2",
                    "name": "F",
                    "type": "RECTANGLE",
                    "visible": True,
                    "layoutSizingVertical": "FILL",
                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
                },
            ],
        }
    )
    tree = map_node(scene)
    child = tree.children[0]
    assert child.style.get("flex-grow") == 1
    assert child.style.get("flex-basis") == "0"


def test_real_back_nav_produces_centered_row_flex() -> None:
    """Real fixture: Back Nav should produce display:flex row, center align."""
    import json
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "02_confirm_frame" / "input.json"
    data = json.loads(fixture.read_text())
    doc = data["nodes"]["1732:4245"]["document"]
    back_nav = doc["children"][0]  # "Back Nav"
    scene = SceneNode.from_dict(back_nav)
    tree = map_node(scene)
    assert tree.style["display"] == "flex"
    assert tree.style["flex-direction"] == "row"
    assert tree.style["align-items"] == "center"


def test_negative_item_spacing_becomes_child_margin() -> None:
    """Negative itemSpacing (Figma auto-layout overlap) must not be dropped.

    CSS `gap` rejects negative values, so a negative itemSpacing (e.g. -50
    used to overlap a white card over a dark header container) is expressed
    as a negative margin on every child after the first — column →
    margin-top, row → margin-left. Fixes the search-card covered by the dark
    container bug (issue #45).
    """
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "search",
            "type": "FRAME",
            "layoutMode": "VERTICAL",
            "itemSpacing": -50,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 375, "height": 141},
            "children": [
                {
                    "id": "1:2",
                    "name": "dark",
                    "type": "FRAME",
                    "absoluteBoundingBox": {"x": 0, "y": 0, "width": 375, "height": 85},
                },
                {
                    "id": "1:3",
                    "name": "white",
                    "type": "FRAME",
                    "absoluteBoundingBox": {"x": 0, "y": 35, "width": 327, "height": 106},
                },
            ],
        }
    )
    tree = map_node(scene)
    # no positive gap; the overlap is a negative margin on the 2nd+ children
    assert "gap" not in tree.style
    assert tree.children[0].style.get("margin-top") is None
    assert tree.children[1].style.get("margin-top") == "-50px"


def test_negative_item_spacing_row_uses_margin_left() -> None:
    """Horizontal negative itemSpacing → margin-left on 2nd+ children."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "row",
            "type": "FRAME",
            "layoutMode": "HORIZONTAL",
            "itemSpacing": -10,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
            "children": [
                {"id": "1:2", "name": "a", "type": "FRAME",
                 "absoluteBoundingBox": {"x": 0, "y": 0, "width": 40, "height": 50}},
                {"id": "1:3", "name": "b", "type": "FRAME",
                 "absoluteBoundingBox": {"x": 30, "y": 0, "width": 40, "height": 50}},
            ],
        }
    )
    tree = map_node(scene)
    assert tree.style.get("gap") is None
    assert tree.children[1].style.get("margin-left") == "-10px"
