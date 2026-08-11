"""End-to-end test: image nodes, VECTOR → svg export, absolute positioning."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from avocado.api.figma import FigmaClient
from avocado.generator.codegen import render_jsx
from avocado.model.scene_node import SceneNode
from avocado.model.tree_node import TreeNode
from avocado.parser.node_mapper import map_node

FIXTURE = Path(__file__).parent / "fixtures" / "02_confirm_frame" / "input.json"


@pytest.fixture(scope="module")
def confirm_tree() -> TreeNode:
    if not FIXTURE.exists():
        pytest.skip("missing fixture")
    data = json.loads(FIXTURE.read_text())
    doc = data["nodes"]["1732:4245"]["document"]
    scene = SceneNode.from_dict(doc)
    # client=None: image nodes get placeholder src, no API calls
    return map_node(scene, client=None, file_key="FIGMA_FILE_KEY_PLACEHOLDER_001")


def test_visible_tree_size_is_123(confirm_tree) -> None:
    """Only visible nodes appear (most are inside invisible variants)."""
    total = [0]

    def walk(t):
        total[0] += 1
        for c in t.children:
            walk(c)

    walk(confirm_tree)
    # Exact 123 — most source-tree nodes (910) are hidden inside INSTANCE
    # variants. Confirming this number proves _should_include + visibility
    # filter works correctly.
    assert total[0] == 123


def test_image_frame_rendered_as_img(confirm_tree) -> None:
    """4 image-fill FRAME nodes should become <img>."""
    img_count = [0]

    def walk(t):
        if t.is_img:
            img_count[0] += 1
        for c in t.children:
            walk(c)

    walk(confirm_tree)
    # 4 image FRAMEs + 1 visible VECTOR = 5 total
    assert img_count[0] == 5


def test_vector_nodes_become_img(confirm_tree) -> None:
    """VECTOR nodes → <img src=...svg...>."""
    vectors = []

    def walk(t):
        if t.source_type == "VECTOR":
            vectors.append(t)
        for c in t.children:
            walk(c)

    walk(confirm_tree)
    # All visible VECTORs should be tagged img
    assert len(vectors) == 1  # only 1 visible VECTOR in this fixture
    assert vectors[0].tag_name == "img"
    assert vectors[0].is_img is True


def test_boolean_operation_keeps_children(confirm_tree) -> None:
    """BOOLEAN_OPERATION has children → stays as <div> wrapper."""
    bo_with_children = []

    def walk(t):
        if t.source_type == "BOOLEAN_OPERATION" and t.children:
            bo_with_children.append(t)
        for c in t.children:
            walk(c)

    walk(confirm_tree)
    # All such BOOLEAN_OPERATION should be div, not img
    for bo in bo_with_children:
        assert bo.tag_name == "div"
        assert bo.is_img is False


def test_no_nested_img_tag(confirm_tree) -> None:
    """Regression: <img> should never have children (no nested </img>)."""
    jsx = render_jsx(confirm_tree)
    assert "</img>" not in jsx


def test_image_nodes_have_src_prop(confirm_tree) -> None:
    """Every <img> should have a src prop (URL or TODO placeholder)."""

    def walk(t):
        if t.is_img:
            assert "src" in t.props, f"img without src: {t.name}"
            assert t.props["src"], f"empty src on {t.name}"
        for c in t.children:
            walk(c)

    walk(confirm_tree)


def test_absolute_positioning_applied_where_no_auto_layout(confirm_tree) -> None:
    """Frames without Auto Layout should use position:relative + absolute children."""
    abs_count = [0]
    flex_count = [0]

    def walk(t):
        if t.layout_strategy == "absolute_position":
            abs_count[0] += 1
        elif t.layout_strategy == "auto_layout":
            flex_count[0] += 1
        for c in t.children:
            walk(c)

    walk(confirm_tree)
    # Both should be present in this fixture
    assert abs_count[0] > 0
    assert flex_count[0] > 0


def test_end_to_end_with_real_image_fetch() -> None:
    """Optional: real Figma image API call for one image node."""
    token = os.environ.get("FIGMA_TOKEN")
    if not token:
        pytest.skip("FIGMA_TOKEN not set")
    data = json.loads(FIXTURE.read_text())
    doc = data["nodes"]["1732:4245"]["document"]
    scene = SceneNode.from_dict(doc)
    client = FigmaClient(token=token)
    tree = map_node(scene, client=client, file_key="FIGMA_FILE_KEY_PLACEHOLDER_001")

    # Find an is_img node and check src looks like a URL
    found_url = False

    def walk(t):
        nonlocal found_url
        if t.is_img and "src" in t.props:
            src = t.props["src"]
            if "http" in src or "s3" in src:
                found_url = True
        for c in t.children:
            walk(c)

    walk(tree)
    assert found_url, "expected at least one real image URL in output"
