"""Neutral dynamicProps extractor registry.

Presets reference extractors via ``dynamicProps: {extractor: <name>}``.
The core package ships NO built-in extractors — component-library-specific
extractors are registered by user plugins (e.g. from ~/.avocado/plugins/)
via ``register_extractor``. Unknown names degrade to ``{}`` (plain div).
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from avocado.model.scene_node import SceneNode

_EXTRACTORS: dict[str, Callable[[SceneNode, str | None], dict]] = {}


def register_extractor(name: str, fn: Callable[[SceneNode, str | None], dict]) -> None:
    """Register a named extractor. Overwrites any existing registration.

    Emits a warning to stderr when overwriting an existing registration so
    plugin conflicts are discoverable instead of silently clobbering.
    """
    if name in _EXTRACTORS:
        sys.stderr.write(f"warning: extractor {name!r} re-registered (overwriting previous)\n")
    _EXTRACTORS[name] = fn


def run_extractor(
    name: str,
    scene: SceneNode,
    path: str | None,
    *,
    error_out: list[str] | None = None,
) -> dict:
    """Dispatch to a named extractor. Silent-fails on unknown name / error.

    Returns {} on any failure so a missing prop degrades to the component's
    default rather than crashing codegen. When error_out is provided, a
    machine-readable reason is appended: "not_registered", or
    "exception: <message>" (message never reaches the main flow).
    """
    fn = _EXTRACTORS.get(name)
    if fn is None:
        if error_out is not None:
            error_out.append("not_registered")
        return {}
    try:
        return fn(scene, path) or {}
    except Exception as e:  # noqa: BLE001 — silent-fail contract
        if error_out is not None:
            error_out.append(f"exception: {e}")
        return {}


def available_extractors() -> list[str]:
    """Sorted list of registered extractor names (for schema tests)."""
    return sorted(_EXTRACTORS.keys())
