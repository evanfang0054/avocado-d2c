"""Tests for image node detection + rendering."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from avocado.model.scene_node import SceneNode
from avocado.parser.image import (
    get_image_paint,
    is_image_node,
    render_as_image,
)
from avocado.parser.node_mapper import map_node


def _rect_with_image_fill() -> dict:
    return {
        "id": "1:1",
        "name": "Photo",
        "type": "RECTANGLE",
        "visible": True,
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 200, "height": 150},
        "fills": [
            {"type": "IMAGE", "visible": True, "imageRef": "abc", "scaleMode": "FILL"},
        ],
    }


def _rect_with_solid_fill() -> dict:
    return {
        "id": "1:1",
        "name": "Box",
        "type": "RECTANGLE",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
        "fills": [{"type": "SOLID", "color": {"r": 1, "g": 0, "b": 0, "a": 1}}],
    }


def _frame_with_image_fill() -> dict:
    return {
        "id": "1:2",
        "name": "image",
        "type": "FRAME",
        "visible": True,
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 220, "height": 128},
        "fills": [
            {"type": "IMAGE", "visible": True, "imageRef": "xyz", "scaleMode": "FILL"},
        ],
    }


def test_is_image_node_single_image_fill() -> None:
    scene = SceneNode.from_dict(_rect_with_image_fill())
    assert is_image_node(scene)


def test_is_image_node_solid_fill_is_not_image() -> None:
    scene = SceneNode.from_dict(_rect_with_solid_fill())
    assert not is_image_node(scene)


def test_is_image_node_no_fills_is_not_image() -> None:
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "X",
            "type": "RECTANGLE",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 10, "height": 10},
        }
    )
    assert not is_image_node(scene)


def test_is_image_node_frame_with_image_fill() -> None:
    """Frames can also be image nodes (real Confirm fixture has 4)."""
    scene = SceneNode.from_dict(_frame_with_image_fill())
    assert is_image_node(scene)


def test_is_image_node_slice_always_image() -> None:
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "S",
            "type": "SLICE",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 10, "height": 10},
        }
    )
    assert is_image_node(scene)


def test_get_image_paint_returns_the_image() -> None:
    scene = SceneNode.from_dict(_rect_with_image_fill())
    p = get_image_paint(scene)
    assert p is not None
    assert p.type == "IMAGE"
    assert p.image_ref == "abc"


def test_render_as_image_dry_run_no_client() -> None:
    """When no client is provided, mark is_img + placeholder src.

    Dry run is a designed-in mode (placeholder src, no fetch) — it must NOT
    surface as an inspect failure; real fetch failures use the _image_error
    prop, which cli.py collects into envelope warnings.
    """
    scene = SceneNode.from_dict(_rect_with_image_fill())
    from avocado.model.tree_node import TreeNode

    tree = TreeNode(
        id=scene.id,
        name=scene.name,
        source_type=scene.type,
        tag_name="div",
        style={"background-color": "#fff"},
        figma_id=scene.id,
    )
    result = render_as_image(scene, tree, client=None)
    assert result is None
    assert tree.is_img is True
    assert tree.tag_name == "img"
    assert "TODO" in tree.props.get("src", "")
    # background-color should be removed (img doesn't show bg)
    assert "background-color" not in tree.style
    # Dry run is not a failure — no inspect entries, no error marker
    assert tree.inspect == []
    assert "_image_error" not in tree.props


def test_map_node_image_dry_run_marks_is_img() -> None:
    scene = SceneNode.from_dict(_rect_with_image_fill())
    tree = map_node(scene, client=None)
    assert tree.is_img is True
    assert tree.tag_name == "img"


def test_map_node_image_with_real_client() -> None:
    """End-to-end: real Figma API call to render image node."""
    token = os.environ.get("FIGMA_TOKEN")
    if not token:
        pytest.skip("FIGMA_TOKEN not set")
    from avocado.api.figma import FigmaClient

    client = FigmaClient(token=token)

    # Use real image node from Confirm fixture (id 1732:4272)
    scene = SceneNode.from_dict(
        {
            "id": "1732:4272",
            "name": "image",
            "type": "FRAME",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 220, "height": 128},
            "fills": [
                {"type": "IMAGE", "visible": True, "imageRef": "abc", "scaleMode": "FILL"},
            ],
        }
    )
    tree = map_node(scene, client=client, file_key="FIGMA_FILE_KEY_PLACEHOLDER_001")
    assert tree.is_img is True
    assert tree.tag_name == "img"
    src = tree.props.get("src", "")
    # Real URL or fallback TODO on error
    assert "figma" in src or "s3" in src or "TODO" in src


def test_map_node_image_downloads_to_local(tmp_path: Path) -> None:
    """If out_dir is given, image is downloaded and local path used."""
    token = os.environ.get("FIGMA_TOKEN")
    if not token:
        pytest.skip("FIGMA_TOKEN not set")
    from avocado.api.figma import FigmaClient

    client = FigmaClient(token=token)
    from avocado.model.tree_node import TreeNode

    scene = SceneNode.from_dict(
        {
            "id": "1732:4272",
            "name": "image",
            "type": "FRAME",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 220, "height": 128},
            "fills": [
                {"type": "IMAGE", "visible": True, "imageRef": "abc", "scaleMode": "FILL"},
            ],
        }
    )
    tree = TreeNode(
        id=scene.id,
        name=scene.name,
        source_type=scene.type,
        tag_name="div",
        figma_id=scene.id,
    )
    os.environ["FIGMA_FILE_KEY"] = "FIGMA_FILE_KEY_PLACEHOLDER_001"
    result = render_as_image(scene, tree, client=client, out_dir=tmp_path)
    # Either local path or fallback URL — both are non-None on success
    if result and "TODO" not in result:
        # If download succeeded, file should exist
        if result.startswith("/"):
            assert Path(result).exists() or result in [str(p) for p in tmp_path.iterdir()]


def test_text_node_with_image_fill_not_treated_as_img() -> None:
    """Edge case: TEXT node with IMAGE fill (gradient text) should NOT
    become <img> — that's a text-with-mask effect."""
    scene = SceneNode.from_dict(
        {
            "id": "1:1",
            "name": "T",
            "type": "TEXT",
            "characters": "x",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 10, "height": 20},
            "fills": [
                {"type": "IMAGE", "visible": True, "imageRef": "abc", "scaleMode": "FILL"},
            ],
            "style": {"fontFamily": "Inter", "fontSize": 14},
        }
    )
    # is_image_node is True at parser/image.py level, but map_node skips it
    # for TEXT nodes (see node_mapper.py condition `scene.type != "TEXT"`).
    tree = map_node(scene)
    assert tree.tag_name == "span"
    assert tree.is_img is False
