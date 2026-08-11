"""Image node collection + batch fetch.

d2c walks the Figma tree twice:
  1. `collect_image_nodes(scene)` — cheap recursive scan to gather every node
     that `node_mapper.render_as_image()` will eventually need to render.
  2. `FigmaClient.get_image_batch(...)` — single batched API call + concurrent
     download, populating the local cache before the actual mapping walk
     starts. By the time `render_as_image` calls `client.get_image(node)`
     for a single node, it's almost always a cache hit.

This eliminates the previous "serial N-request" pattern that made pages with
50-100+ icons take 3-5 minutes (each request 1-3s plus rate-limit backoff).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from avocado.model.scene_node import SceneNode

if TYPE_CHECKING:
    from avocado.api.figma import FigmaClient

log = logging.getLogger(__name__)

# Node types that node_mapper will turn into <img>. Keep in sync with
# `is_image_node` in parser/image.py.
_IMG_NODE_TYPES = frozenset(
    {
        "VECTOR",
        "LINE",
        "STAR",
        "POLYGON",
        "BOOLEAN_OPERATION",
        "SLICE",
    }
)


def collect_image_nodes(
    scene: SceneNode,
    *,
    include_vectors: bool = True,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Walk the tree and return image nodes that will need rendering.

    Returns two parallel lists:
      - `(node_id, format)` for raster (png) — FRAME/RECTANGLE/INSTANCE/
        COMPONENT with a single IMAGE fill, plus any multi-IMAGE fills
        node whose mixed fills are handled via background-image layers.
      - `(node_id, format)` for vector (svg) — VECTOR/LINE/STAR/POLYGON/
        BOOLEAN_OPERATION.

    `format` is what the caller should pass to `get_image_batch` for that
    node. Vectors default to svg, image-fills to png — matching
    `render_as_image()`'s existing behavior.
    """
    raster: list[tuple[str, str]] = []
    vector: list[tuple[str, str]] = []

    def walk(n: SceneNode) -> None:
        nid = n.id
        if not nid:
            return
        t = n.type
        visible_fills = [p for p in (n.fills or []) if p.visible]

        # VECTOR family → svg
        if include_vectors and t in _IMG_NODE_TYPES:
            vector.append((nid, "svg"))
            # VECTOR has no meaningful children to recurse into.
            return

        # Raster candidates: FRAME/RECTANGLE/INSTANCE/COMPONENT with at
        # least one visible IMAGE fill. `is_image_node` will only fire for
        # single-IMAGE nodes, but multi-IMAGE nodes also need the IMAGE
        # fetched (used as background-image layers). Collecting both here
        # and letting the caller batch-discard the unused ones would be
        # wasteful — instead we mirror is_image_node's exact predicate so
        # we only prefetch what will actually be requested.
        if (
            t in ("FRAME", "RECTANGLE", "INSTANCE", "COMPONENT")
            and len(visible_fills) == 1
            and visible_fills[0].type == "IMAGE"
        ):
            raster.append((nid, "png"))

        for c in n.children or []:
            walk(c)

    walk(scene)
    return raster, vector


def prefetch_image_nodes(
    client: FigmaClient,
    file_key: str,
    scene: SceneNode,
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, tuple[int, int]]:
    """Pre-fetch all raster + vector image nodes for a scene.

    Returns a small stats dict: `{"raster": (hit, miss), "vector": (hit, miss)}`
    where hit/miss are cache-hits vs network-fetched counts, useful for
    logging. Safe to call when offline (returns zeros; batch API is a no-op).
    """
    from avocado.api.figma import FigmaNotFoundError

    stats = {"raster": (0, 0), "vector": (0, 0)}
    if not client or not file_key:
        return stats

    raster, vector = collect_image_nodes(scene)

    def _run(nodes: list[tuple[str, str]], kind: str) -> None:
        if not nodes:
            return
        # Group by format/scale to keep one batch per (format, scale) pair.
        # Currently only one format per group, but kept general for future.
        by_fmt: dict[str, list[str]] = {}
        for nid, fmt in nodes:
            by_fmt.setdefault(fmt, []).append(nid)
        for fmt, ids in by_fmt.items():
            # Count how many are already cache hits (no network needed).
            cache_hits = 0
            if client._cache_dir:
                for nid in ids:
                    ck = client._batch_cache_key(file_key, nid, fmt, 1.0)
                    if ck.exists():
                        cache_hits += 1
            try:
                results = client.get_image_batch(
                    file_key, ids, format=fmt, scale=1.0, on_progress=on_progress
                )
            except FigmaNotFoundError:
                results = {}
            except Exception as e:  # noqa: BLE001
                log.warning("image prefetch %s failed: %s", kind, e)
                results = {}
            # results includes cache hits + freshly fetched.
            fetched_total = len(results)
            network_fetched = max(0, fetched_total - cache_hits)
            stats[kind] = (cache_hits, network_fetched)

    _run(raster, "raster")
    _run(vector, "vector")
    return stats
