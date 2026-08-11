"""Schema validation for bundled presets (antd.yaml example).

The bundled preset is a neutral example; users may add their own presets
under ~/.avocado/presets/ or cwd/.avocado/presets/. These tests validate
the bundled example and the generic entry shapes any preset must follow.
"""

from __future__ import annotations

import yaml

from avocado.parser.component import ComponentMapping, load_preset
from avocado.parser.component_extractors import available_extractors
from avocado.paths import resolve_preset

# The bundled antd example ships with the package, so it always resolves.
PRESET_PATH = resolve_preset("antd")
assert PRESET_PATH.exists(), f"bundled preset missing: {PRESET_PATH}"


def _raw_entries() -> list[dict]:
    data = yaml.safe_load(PRESET_PATH.read_text()) or {}
    return data.get("components", []) or []


def test_yaml_is_well_formed_and_has_components_key() -> None:
    data = yaml.safe_load(PRESET_PATH.read_text()) or {}
    assert "components" in data
    assert isinstance(data["components"], list)
    assert len(data["components"]) >= 10


def test_every_entry_has_component_or_variants() -> None:
    """Each entry must resolve to a component (directly or via variants).

    An entry may set `component: ''` to explicitly disable replacement
    (the original Figma DOM is preserved). Such entries still need
    variantProperties or dynamicProps to justify their presence.
    """
    for i, e in enumerate(_raw_entries()):
        has_component = bool(e.get("component"))
        has_variants = bool(e.get("variants"))
        has_vp = bool(e.get("variantProperties"))
        has_dp = bool(e.get("dynamicProps"))
        assert has_component or has_variants or has_vp or has_dp, (
            f"entry #{i} ({e.get('name')}) needs `component`, `variants`, "
            f"`variantProperties`, or `dynamicProps`"
        )


def test_every_entry_has_package_or_variants() -> None:
    for i, e in enumerate(_raw_entries()):
        if e.get("variants"):
            continue  # variants may swap component/package at runtime
        assert e.get("package"), f"entry #{i} ({e.get('name')}) missing package"


def test_variant_properties_shape() -> None:
    """variantProperties must be {field: {value: {props}}}."""
    for e in _raw_entries():
        vp = e.get("variantProperties")
        if not vp:
            continue
        assert isinstance(vp, dict)
        for field_name, value_map in vp.items():
            assert isinstance(field_name, str)
            assert isinstance(value_map, dict), f"variantProperties[{field_name}] must be a dict"
            for value, props in value_map.items():
                assert isinstance(value, str)
                assert isinstance(props, dict), (
                    f"variantProperties[{field_name}][{value}] must be a dict"
                )


def test_variants_shape() -> None:
    """variants must be {field: {value: {component, package?}}}."""
    for e in _raw_entries():
        vs = e.get("variants")
        if not vs:
            continue
        assert isinstance(vs, dict)
        for field_name, value_map in vs.items():
            assert isinstance(value_map, dict)
            for value, override in value_map.items():
                assert isinstance(override, dict)
                assert "component" in override, (
                    f"variants[{field_name}][{value}] must have `component`"
                )


def test_dynamic_props_extractor_must_be_registered() -> None:
    """If an entry declares dynamicProps.extractor, the name must be
    registered (via register_extractor) before the preset is used."""
    registered = set(available_extractors())
    for e in _raw_entries():
        dp = e.get("dynamicProps")
        if not dp:
            continue
        assert isinstance(dp, dict)
        assert "extractor" in dp, f"entry {e.get('name')}: dynamicProps needs `extractor`"
        ext = dp["extractor"]
        assert isinstance(ext, str)
        assert ext in registered, (
            f"entry {e.get('name')}: extractor {ext!r} not registered. "
            f"Available: {sorted(registered)}"
        )


def test_no_duplicate_names() -> None:
    """Same `name + componentId` pair may only appear once.

    Same name with DIFFERENT componentId is allowed — a component may be
    backed by multiple Figma componentSets from different files. The
    duplicate check catches typos / accidental re-declaration.
    """
    seen: dict[tuple, int] = {}
    for e in _raw_entries():
        n = e.get("name")
        if not n:
            continue
        cid = e.get("componentId") or ""
        key = (n, cid)
        seen[key] = seen.get(key, 0) + 1
    dups = {k: v for k, v in seen.items() if v > 1}
    assert not dups, f"duplicate (name, componentId) entries: {dups}"


def test_loaded_entries_have_consistent_types() -> None:
    """load_preset returns ComponentMapping objects with fields populated."""
    entries = load_preset("antd")
    assert entries
    for m in entries:
        assert isinstance(m, ComponentMapping)
        assert isinstance(m.variant_properties, dict)
        assert isinstance(m.variants, dict)
        assert isinstance(m.dynamic_props, dict)
        assert isinstance(m.block_name_match, bool)
        assert isinstance(m.leaf_extras, tuple)


def test_leaf_and_leaf_extras_fields_parse() -> None:
    """leaf:true entries with leafExtras parse onto the mapping."""
    entries = load_preset("antd")
    leaf_entries = [m for m in entries if m.leaf]
    # antd.yaml example marks several leaf components (Input, Checkbox, ...)
    assert leaf_entries, "antd.yaml should declare at least one leaf component"
