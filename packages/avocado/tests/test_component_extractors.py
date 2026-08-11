"""Tests for the neutral extractor registry."""

from __future__ import annotations

import pytest

from avocado.model.scene_node import SceneNode
from avocado.parser.component_extractors import (
    _EXTRACTORS,
    available_extractors,
    register_extractor,
    run_extractor,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    """Isolate the module-level registry between tests."""
    _EXTRACTORS.clear()
    yield
    _EXTRACTORS.clear()


def _scene() -> SceneNode:
    base = {
        "id": "1:1",
        "name": "root",
        "type": "INSTANCE",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 100},
    }
    return SceneNode.from_dict(base)


def test_registry_starts_empty() -> None:
    assert available_extractors() == []


def test_register_then_run() -> None:
    """Register then dispatch round-trip returns the extractor output."""

    def _my_extractor(scene: SceneNode, path: str | None) -> dict:
        return {"items": ["a", "b"]}

    register_extractor("my_extractor", _my_extractor)
    assert "my_extractor" in available_extractors()
    assert run_extractor("my_extractor", _scene(), None) == {"items": ["a", "b"]}


def test_register_overwrites_duplicate(capsys) -> None:
    register_extractor("dup", lambda s, p: {"v": 1})
    register_extractor("dup", lambda s, p: {"v": 2})
    assert run_extractor("dup", _scene(), None) == {"v": 2}
    # Overwriting an existing registration emits a discoverable warning
    assert "re-registered" in capsys.readouterr().err


def test_unknown_extractor_returns_empty() -> None:
    assert run_extractor("nonexistent", _scene(), None) == {}


def test_extractor_exception_returns_empty() -> None:
    def _boom(scene, path):
        raise RuntimeError("boom")

    register_extractor("boom_ext", _boom)
    assert run_extractor("boom_ext", _scene(), None) == {}
