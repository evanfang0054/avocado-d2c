"""Coverage check: bundled preset (antd.yaml example) is well-formed.

Users maintain their own component-library presets under ~/.avocado/presets/
or cwd/.avocado/presets/ — coverage against a specific library's component
list is the user's responsibility. This file validates the bundled example's
self-consistency: every declared component resolves to a non-empty package
and the example covers a reasonable set of components.
"""

from __future__ import annotations

from avocado.parser.component import load_preset


def test_preset_loads_non_empty() -> None:
    entries = load_preset("antd")
    assert entries


def test_preset_has_minimum_entry_count() -> None:
    entries = load_preset("antd")
    # antd.yaml example ships ~20 components
    assert len(entries) >= 10


def test_every_entry_resolves_to_package() -> None:
    """Each non-variants entry declares a non-empty component and package."""
    entries = load_preset("antd")
    for m in entries:
        if m.variants:
            continue  # variants may swap component/package at runtime
        assert m.component, f"entry {m.name!r} has empty component"
        assert m.package, f"entry {m.name!r} has empty package"
