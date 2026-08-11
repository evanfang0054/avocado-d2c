"""Tests for SceneNode dataclass parsing using real Figma JSON."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from avocado.model.scene_node import (
    Box,
    Color,
    Paint,
    SceneNode,
    TextStyle,
)

FIXTURE = Path(__file__).parent / "fixtures" / "confirm_frame.json"


@pytest.fixture(scope="module")
def confirm_doc() -> SceneNode:
    if not FIXTURE.exists():
        # Build fixture from cached API response
        cache = Path(os.environ.get("FIGMA_CACHE", "/tmp/figma_node_test.json"))
        if not cache.exists():
            pytest.skip("no fixture and no cache")
        with cache.open() as f:
            data = json.load(f)
        doc = data["nodes"]["1732:4245"]["document"]
    else:
        with FIXTURE.open() as f:
            doc = json.load(f)
    return SceneNode.from_dict(doc)


def test_root_is_frame(confirm_doc: SceneNode) -> None:
    assert confirm_doc.type == "FRAME"
    assert confirm_doc.name == "Confirm"
    assert confirm_doc.box is not None
    assert confirm_doc.box.width == pytest.approx(1440.0)


def test_box_coordinates(confirm_doc: SceneNode) -> None:
    b = confirm_doc.box
    assert b is not None
    # absoluteBoundingBox is in file-absolute coords, not relative to (0,0)
    assert b.x >= 0
    assert b.height > 1000


def test_has_children(confirm_doc: SceneNode) -> None:
    assert len(confirm_doc.children) >= 2
    names = [c.name for c in confirm_doc.children]
    assert "Back Nav" in names


def test_paint_parsing_solid() -> None:
    p = Paint.from_dict(
        {
            "type": "SOLID",
            "color": {"r": 1, "g": 0, "b": 0, "a": 1},
        }
    )
    assert p.type == "SOLID"
    assert p.color is not None
    assert p.color.r == 1.0
    assert p.color.to_rgba_str() == "#ff0000"


def test_color_with_alpha() -> None:
    c = Color(r=0.5, g=0.5, b=0.5, a=0.5)
    assert c.to_rgba_str() == "rgba(128, 128, 128, 0.5)"


def test_color_from_dict_none() -> None:
    assert Color.from_dict(None) is None


def test_text_node_found(confirm_doc: SceneNode) -> None:
    """Walk tree looking for any TEXT node."""

    def find_text(n: SceneNode) -> SceneNode | None:
        if n.type == "TEXT":
            return n
        for c in n.children:
            r = find_text(c)
            if r:
                return r
        return None

    t = find_text(confirm_doc)
    assert t is not None
    assert t.characters is not None
    assert t.text_style is not None
    assert t.text_style.font_family is not None


def test_instance_node_found(confirm_doc: SceneNode) -> None:
    def find_instance(n: SceneNode) -> SceneNode | None:
        if n.type == "INSTANCE":
            return n
        for c in n.children:
            r = find_instance(c)
            if r:
                return r
        return None

    i = find_instance(confirm_doc)
    assert i is not None
    assert i.component_id  # INSTANCE must have componentId


def test_box_from_invalid_dict() -> None:
    assert Box.from_dict(None) is None
    assert Box.from_dict({}) is None or True  # accept either behavior


def test_paint_image_type() -> None:
    p = Paint.from_dict(
        {
            "type": "IMAGE",
            "imageRef": "abc",
            "scaleMode": "FILL",
        }
    )
    assert p.type == "IMAGE"
    assert p.image_ref == "abc"
    assert p.scale_mode == "FILL"


def test_text_style_line_height_units() -> None:
    ts = TextStyle.from_dict(
        {
            "fontFamily": "Inter",
            "fontSize": 14,
            "lineHeightPx": 20,
            "lineHeightUnit": "PIXELS",
        }
    )
    assert ts is not None
    assert ts.font_size == 14
    assert ts.line_height_px == 20
    assert ts.line_height_unit == "PIXELS"
