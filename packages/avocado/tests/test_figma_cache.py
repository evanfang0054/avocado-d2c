"""Offline unit tests for FigmaClient cache path resolution.

Covers the rename-induced regression where get_image_fills stored absolute
paths in images.json; after a repo rename those paths dangled. These tests
verify the resolution logic without touching the network.
"""

from __future__ import annotations

import json
from pathlib import Path

from avocado.api.figma import FigmaClient


def _make_client_with_cache(tmp_path: Path, *, offline: bool = False) -> FigmaClient:
    """Build a FigmaClient that only uses the local cache (no network)."""
    return FigmaClient(token="dummy", cache_dir=str(tmp_path), offline=offline)


def _images_json_path(client: FigmaClient, file_key: str) -> Path:
    """Where get_image_fills actually writes images.json for a given file.

    `_cache_key` hashes parts that contain non-alnum chars (like the '.' in
    'images.json'), so the on-disk path is fills/<filekey>/<hash>/images.json.
    """
    return client._cache_key("fills", file_key, "images.json")


def test_get_image_fills_writes_relative_paths(tmp_path: Path) -> None:
    """When writing images.json, entries should be paths relative to cache_dir."""
    client = _make_client_with_cache(tmp_path)
    file_key = "FILE1"
    image_ref = "ref-abc"
    cdn_url = "https://example.com/img.png"
    client._get = lambda path, **kw: {"meta": {"images": {image_ref: cdn_url}}}  # type: ignore[assignment]
    # Stub the image download so no network is hit.
    client._session.get = lambda *a, **kw: type(  # type: ignore[assignment]
        "R", (), {"raise_for_status": lambda self: None, "content": b"\x89PNG"}
    )()

    result = client.get_image_fills(file_key)
    assert image_ref in result
    val = result[image_ref]
    assert not Path(val).is_absolute()
    assert not val.startswith("http")

    disk = json.loads(_images_json_path(client, file_key).read_text())
    assert disk[image_ref] == val
    assert (tmp_path / val).exists()


def test_get_image_fills_reads_legacy_absolute_paths(tmp_path: Path) -> None:
    """Old caches stored absolute paths; resolution re-anchors them."""
    file_key = "FILE2"
    image_ref = "ref-xyz"
    real_img = tmp_path / "fills" / file_key / "images" / image_ref
    real_img.parent.mkdir(parents=True)
    real_img.write_bytes(b"\x89PNG")

    client = _make_client_with_cache(tmp_path, offline=True)
    legacy_abs = Path("/tmp/legacy/cache/fills") / file_key / "images" / image_ref
    disk_path = _images_json_path(client, file_key)
    disk_path.parent.mkdir(parents=True, exist_ok=True)
    disk_path.write_text(json.dumps({image_ref: str(legacy_abs)}))

    result = client.get_image_fills(file_key)
    assert result[image_ref] == str(real_img)


def test_get_image_fills_preserves_url_fallback(tmp_path: Path) -> None:
    """URL entries (failed-download fallbacks) pass through unchanged."""
    file_key = "FILE3"
    image_ref = "ref-url"
    cdn_url = "https://cdn.example.com/x.png"
    client = _make_client_with_cache(tmp_path, offline=True)
    disk_path = _images_json_path(client, file_key)
    disk_path.parent.mkdir(parents=True, exist_ok=True)
    disk_path.write_text(json.dumps({image_ref: cdn_url}))

    result = client.get_image_fills(file_key)
    assert result[image_ref] == cdn_url


def test_get_image_fills_reads_current_relative_paths(tmp_path: Path) -> None:
    """New caches store relative paths; they anchor correctly under cache_dir."""
    file_key = "FILE4"
    image_ref = "ref-rel"
    rel = f"fills/{file_key}/images/{image_ref}"
    real_img = tmp_path / rel
    real_img.parent.mkdir(parents=True, exist_ok=True)
    real_img.write_bytes(b"\x89PNG")

    client = _make_client_with_cache(tmp_path, offline=True)
    disk_path = _images_json_path(client, file_key)
    disk_path.parent.mkdir(parents=True, exist_ok=True)
    disk_path.write_text(json.dumps({image_ref: rel}))

    result = client.get_image_fills(file_key)
    assert result[image_ref] == str(real_img)
