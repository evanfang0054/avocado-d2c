"""Tests for image pipeline improvements.

Coverage:
  - FigmaClient.get_image_batch: cache partitioning, batch API, concurrent
    download, offline mode behavior.
  - style_from_scene with image_fills_map: multi-IMAGE fills emit
    background-image layers.
  - collect_image_nodes + prefetch_image_nodes: tree walk correctness and
    stats reporting.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from avocado.model.scene_node import SceneNode
from avocado.parser.image_prefetch import (
    collect_image_nodes,
    prefetch_image_nodes,
)
from avocado.parser.style import style_from_scene

# ── helpers ────────────────────────────────────────────────────────────────


def _make_node(
    nid: str,
    type_: str,
    fills: list[dict] | None = None,
    children: list[SceneNode] | None = None,
) -> SceneNode:
    # Construct via from_dict so Paint/Color get properly parsed — building
    # SceneNode directly with `fills=[Paint(**d)]` skips Color.from_dict.
    raw: dict = {
        "id": nid,
        "name": nid,
        "type": type_,
        "fills": fills or [],
        "children": [
            # Children are already SceneNode — re-serialize via __dict__-ish.
            {"id": c.id, "name": c.name, "type": c.type, "fills": [], "children": []}
            for c in (children or [])
        ],
    }
    # If caller passed pre-built SceneNode children (used for nested tests),
    # use them directly rather than re-parsing the placeholder dicts above.
    node = SceneNode.from_dict(raw)
    if children:
        node.children = children
    return node


def _solid() -> dict:
    return {
        "type": "SOLID",
        "visible": True,
        "color": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 1.0},
    }


def _image(image_ref: str = "abc", visible: bool = True) -> dict:
    # Use Figma's raw camelCase key — SceneNode.from_dict does the
    # snake_case conversion; building dicts in test space mirrors the
    # real input format.
    return {
        "type": "IMAGE",
        "visible": visible,
        "imageRef": image_ref,
        "scaleMode": "FILL",
    }


# ── style_from_scene: multi-IMAGE fills ────────────────────────────────────


def test_style_multi_image_fills_emit_background_image_layers() -> None:
    """Nodes with [IMAGE, SOLID, IMAGE] fills should output CSS background
    layers for the IMAGE paints when given an image_fills_map."""
    node = _make_node(
        "1:1",
        "FRAME",
        fills=[
            _image("ref-A"),
            _solid(),
            _image("ref-B"),
        ],
    )
    fills_map = {
        "ref-A": "/cache/A.png",
        "ref-B": "/cache/B.png",
    }
    style = style_from_scene(node, image_fills_map=fills_map)
    bg = style.get("background", "")
    # Both image URLs should appear as background-image layers
    assert "url('/cache/A.png')" in bg
    assert "url('/cache/B.png')" in bg
    # Comma-separated multi-layer
    assert bg.count(",") >= 2


def test_style_multi_image_fills_without_map_drops_silently() -> None:
    """Backward-compat: when no image_fills_map is provided (caller didn't
    opt in), IMAGE fills are skipped — same as before. Only SOLID
    layers survive."""
    node = _make_node(
        "1:1",
        "FRAME",
        fills=[_image("ref-A"), _solid()],
    )
    style = style_from_scene(node)  # no image_fills_map
    assert "background-color" in style or "background" in style
    assert "url(" not in style.get("background", "")
    assert "url(" not in style.get("background-color", "")


def test_single_image_fill_goes_to_img_not_background() -> None:
    """A single IMAGE fill on a childless FRAME is handled by render_as_image()
    (turns node into <img>). The mapping must NOT leave a redundant
    background layer on the <img> style.

    The exclusion lives in node_mapper: single-IMAGE childless nodes never
    get an image_fills_map, so style_from_scene's IMAGE branch (which serves
    multi-fill / has-children nodes) is not triggered for them.
    """
    from avocado.parser.node_mapper import map_node

    node = _make_node("1:1", "FRAME", fills=[_image("ref-A")])
    tree = map_node(node, client=None)
    assert tree.is_img is True
    assert tree.tag_name == "img"
    assert "background" not in tree.style
    assert "background-color" not in tree.style


# ── collect_image_nodes ────────────────────────────────────────────────────


def test_collect_groups_vector_and_raster() -> None:
    scene = _make_node(
        "0:1",
        "FRAME",
        children=[
            _make_node("1:1", "VECTOR"),  # svg
            _make_node(
                "1:2",
                "RECTANGLE",
                fills=[_image("ref-x")],  # single IMAGE → raster png
            ),
            _make_node(
                "1:3",
                "FRAME",
                fills=[_image("ref-y"), _solid()],  # multi → NOT collected
            ),
            _make_node("1:4", "TEXT", fills=[_solid()]),
        ],
    )
    raster, vector = collect_image_nodes(scene)
    raster_ids = {nid for nid, _ in raster}
    vector_ids = {nid for nid, _ in vector}
    assert vector_ids == {"1:1"}
    assert raster_ids == {"1:2"}  # multi-fill FRAME excluded
    assert "1:3" not in raster_ids
    assert "1:4" not in vector_ids and "1:4" not in raster_ids


def test_collect_respects_include_vectors_flag() -> None:
    scene = _make_node(
        "0:1",
        "FRAME",
        children=[
            _make_node("1:1", "VECTOR"),
            _make_node("1:2", "RECTANGLE", fills=[_image("r")]),
        ],
    )
    raster, vector = collect_image_nodes(scene, include_vectors=False)
    assert vector == []
    assert {n for n, _ in raster} == {"1:2"}


# ── prefetch_image_nodes ───────────────────────────────────────────────────


def test_prefetch_returns_zero_when_no_client_or_file_key() -> None:
    scene = _make_node("0:1", "FRAME")
    assert prefetch_image_nodes(None, "key", scene) == {
        "raster": (0, 0),
        "vector": (0, 0),
    }
    client = MagicMock()
    assert prefetch_image_nodes(client, "", scene) == {
        "raster": (0, 0),
        "vector": (0, 0),
    }


def test_prefetch_calls_get_image_batch_with_correct_format(tmp_path: Path) -> None:
    """Raster nodes → png batch, vector nodes → svg batch."""
    scene = _make_node(
        "0:1",
        "FRAME",
        children=[
            _make_node("1:1", "VECTOR"),
            _make_node("1:2", "RECTANGLE", fills=[_image("r")]),
        ],
    )
    client = MagicMock()
    client._cache_dir = None  # no cache → all network fetches
    client.get_image_batch.return_value = {"1:1": "/x.svg"}
    # Second call returns for raster
    # Patch get_image_batch to record format used
    formats_seen: list[str] = []

    def fake_batch(file_key, ids, *, format, scale, on_progress=None):
        formats_seen.append(format)
        return {nid: f"/cache/{nid}.{format}" for nid in ids}

    client.get_image_batch.side_effect = fake_batch
    stats = prefetch_image_nodes(client, "FILE", scene)
    # Both formats were requested
    assert "svg" in formats_seen
    assert "png" in formats_seen
    # vector was 1 node, all fetched
    assert stats["vector"] == (0, 1)
    assert stats["raster"] == (0, 1)


# ── FigmaClient.get_image_batch ────────────────────────────────────────────
#
# These hit the network so they're marked 'live'. The unit-level behavior
# (cache partitioning, offline no-op) is covered by mocked tests below.


def test_get_image_batch_empty_input_returns_empty() -> None:
    from avocado.api.figma import FigmaClient

    c = FigmaClient(token="x")
    assert c.get_image_batch("file", []) == {}


def test_get_image_batch_offline_returns_only_cache_hits(tmp_path: Path) -> None:
    """Offline mode should NOT make any API call — return only nodes whose
    cache files already exist on disk."""
    from avocado.api.figma import FigmaClient

    cache_dir = tmp_path / "cache"
    c = FigmaClient(token="x", cache_dir=str(cache_dir), offline=True)

    # Pre-populate cache for one node
    key = c._batch_cache_key("FILE", "1:1", "png", 1.0)
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_bytes(b"fake-png")

    results = c.get_image_batch("FILE", ["1:1", "1:2", "1:3"], format="png")
    assert "1:1" in results  # cache hit
    assert "1:2" not in results  # miss, not fetched
    assert "1:3" not in results


def test_get_image_batch_chunks_request_into_50_id_batches(monkeypatch) -> None:
    """When 75 nodes are requested, _get should be called twice."""
    from avocado.api.figma import FigmaClient

    c = FigmaClient(token="x")
    calls: list[str] = []

    def fake_get(path, params=None):
        calls.append(params["ids"])
        return {"images": {nid: f"https://x/{nid}.png" for nid in params["ids"].split(",")}}

    monkeypatch.setattr(c, "_get", fake_get)

    # Disable actual download
    class FakeResp:
        content = b"x"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(c._session, "get", lambda url, timeout: FakeResp())
    monkeypatch.setattr(c, "_cache_put", lambda ck, content: ck)

    node_ids = [f"1:{i}" for i in range(75)]
    results = c.get_image_batch("FILE", node_ids)
    assert len(results) == 75
    assert len(calls) == 2  # 50 + 25
    assert len(calls[0].split(",")) == 50
    assert len(calls[1].split(",")) == 25


# ── _preprocess_cover_image: STRETCH mode ──────────────────────────


def test_preprocess_cover_image_handles_stretch_mode(tmp_path: Path) -> None:
    """STRETCH mode images should be pre-resized to target dimensions.

    Regression: sample_pc "Main Image" 4096x2732 → 568x500 STRETCH was
    skipped by _preprocess_cover_image (only FILL/CROP handled). The
    browser then stretched the original 4096x2732 to 568x500, diverging
    from Figma's Skia resampler by ~3-5% on the hotspot analysis.
    """
    from PIL import Image as PILImage

    from avocado.model.scene_node import SceneNode
    from avocado.model.tree_node import TreeNode
    from avocado.parser.image import _preprocess_cover_image

    # Create a fake source image
    src = tmp_path / "src.png"
    PILImage.new("RGB", (4096, 2732), (123, 200, 50)).save(src)

    scene = SceneNode.from_dict(
        {
            "id": "n",
            "name": "n",
            "type": "RECTANGLE",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 568, "height": 500},
            "fills": [{"type": "IMAGE", "scaleMode": "STRETCH", "imageRef": "r"}],
        }
    )
    tree = TreeNode(
        id="n",
        name="n",
        source_type="RECTANGLE",
        tag_name="img",
        style={"width": "568px", "height": "500px"},
    )

    new_path, ok = _preprocess_cover_image(str(src), scene, tree, "STRETCH")
    assert ok, "STRETCH mode should be preprocessed"
    # Output exists and has target dimensions. Source is 4096x2732 → target
    # 568x500 = ~7.2x downscale (>5 threshold), so scale_factor=1 (no 2x).
    out = PILImage.open(new_path)
    assert out.size == (568, 500), f"expected 568x500 (>5x downscale → 1x), got {out.size}"
