"""Component recognition for INSTANCE nodes.

(see project design docs) and design docs.

Constraints:
  - Figma REST API does NOT expose `sharedPluginData` (Plugin SDK only),
    so pre-marked components cannot be auto-detected.
  - We support user-provided YAML mapping table as fallback.

Mapping table format (YAML):

 # ~/.avocado/components.yaml
    components:
 # Match by Figma node name (case-insensitive, exact)
      - name: "Button"
        component: "Button"
        package: "antd"
        props:
          type: "default"
 # Match by componentId (more precise; survives renames)
      - componentId: "1454:7935"
        component: "Button"
        package: "antd"

Precedence (when multiple match):
  1. componentId match (most precise)
  2. name match (case-insensitive)
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from avocado.model.scene_node import SceneNode
from avocado.model.tree_node import TreeNode
from avocado.parser.trace import is_enabled, record


@dataclass
class ComponentMapping:
    """One entry in the user's component mapping table."""

    component: str
    package: str = ""
    props: dict = field(default_factory=dict)
    # Match criteria (at least one must be set)
    name: str | None = None
    component_id: str | None = None
    # variantProperties / variants / dynamicProps
    # variant_properties: {figmaField: {figmaValue: {prop: value}}}
    variant_properties: dict = field(default_factory=dict)
    # variants: {figmaField: {figmaValue: {component, package?}}}
    variants: dict = field(default_factory=dict)
    # dynamic_props: {extractor: <name>, path: <optional subnode path>}
    dynamic_props: dict = field(default_factory=dict)
    # leaf components (input/button/switch/etc.) — when recognized,
    # drop the Figma DOM children so they don't double-render with the
    # component's own internal layout. Leaf components carry their own
    # border/input/label DOM; nesting Figma's version on top causes visual
    # duplication (e.g. two borders, misaligned text).
    leaf: bool = False
    # blockNameMatch (YAML: blockNameMatch): skip name-only matching for
    # components that need non-trivial array/object props to render (unless
    # dynamicProps provides them). Prevents white-screening the React tree.
    block_name_match: bool = False
    # leafExtras (YAML: leafExtras): names of subtrees that a leaf component
    # does NOT render itself (helper text, error message, ...). They are kept
    # as siblings of the leaf node instead of being dropped with children.
    leaf_extras: tuple[str, ...] = ()


def load_mapping(path: Path | str | None) -> list[ComponentMapping]:
    """Load YAML mapping file. Returns empty list if path is None/missing.

    Raises ValueError if the file exists and parses to YAML but lacks the
    expected top-level ``components`` key (or that key isn't a list). This
    catches "looks valid but is the wrong shape" cases (e.g. ``not: valid yaml``
    parses successfully to ``{"not": "valid yaml"}`` — silently treating it as
    an empty mapping left users debugging 0% recognition with no clue why).
    Caller (cli.py) wraps ValueError into ``invalid_argument`` envelope.
    """
    if path is None:
        return []
    p = Path(path).expanduser()
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text()) or {}
    # FIX: valid YAML but wrong structure (missing components key or not a list).
    # No longer silently accept an empty mapping; raise ValueError so cli.py reports invalid_argument.
    if not isinstance(data, dict):
        raise ValueError(
            f"top-level YAML is {type(data).__name__}, expected a mapping with a 'components' key"
        )
    if "components" not in data:
        raise ValueError(
            f"YAML missing required top-level key 'components' "
            f"(available keys: {list(data.keys())})"
        )
    entries = data.get("components") or []
    if not isinstance(entries, list):
        raise ValueError(f"'components' must be a list, got {type(entries).__name__}")
    out: list[ComponentMapping] = []
    for e in entries:
        out.append(
            ComponentMapping(
                component=e.get("component", ""),
                package=e.get("package", ""),
                props=dict(e.get("props", {}) or {}),
                name=e.get("name"),
                component_id=e.get("componentId"),
                variant_properties=_normalize_keyed(e.get("variantProperties")),
                variants=_normalize_keyed(e.get("variants")),
                dynamic_props=dict(e.get("dynamicProps", {}) or {}),
                leaf=bool(e.get("leaf", False)),
                block_name_match=bool(e.get("blockNameMatch", False)),
                leaf_extras=tuple(str(x) for x in (e.get("leafExtras") or [])),
            )
        )
    return out


def _normalize_keyed(raw):
    """Normalize nested {field: {value: {...}}} dict from YAML.

    YAML may parse inner keys with non-string types (e.g. True/False → bool)
    when the field name looks like a boolean. We coerce inner dicts to plain
    dicts and leave string keys untouched.
    """
    if not raw:
        return {}
    out: dict = {}
    for field_name, value_map in raw.items():
        out[str(field_name)] = dict(value_map or {})
    return out


def load_preset(name: str | None) -> list[ComponentMapping]:
    """Load a built-in component-library preset by name (e.g. "antd").

    Uses 4-layer lookup via avocado.paths.resolve_preset:
    CLI > cwd/.avocado/presets/ > ~/.avocado/presets/ > bundled _bundled/presets/

    Returns empty list if name is None. Raises FileNotFoundError if name is
    given but no matching preset exists, so typos fail loudly instead of
    silently producing empty mappings.
    """
    if not name:
        return []
    from avocado.paths import resolve_preset

    p = resolve_preset(name)
    if not p.exists():
        raise FileNotFoundError(
            f"unknown component library preset: {name!r} "
            f"(expected file: {p}). Available presets: "
            f"{_available_presets()}"
        )
    return load_mapping(p)


def _available_presets() -> list[str]:
    """Return list of available preset names (without .yaml extension).

    Scans three layers: bundled _bundled/presets/ + ~/.avocado/presets/ +
    cwd/.avocado/presets/ (de-duped, sorted).
    """
    from importlib.resources import files

    from avocado.paths import _project_avocado_root, _user_avocado_root

    names: set[str] = set()
    # bundled
    bundled_dir = files("avocado._bundled") / "presets"
    bundled_path = Path(str(bundled_dir))
    if bundled_path.is_dir():
        names.update(f.stem for f in bundled_path.glob("*.yaml"))
    # user-level + project-level
    for root in (_user_avocado_root(), _project_avocado_root()):
        presets_dir = root / "presets"
        if presets_dir.is_dir():
            names.update(f.stem for f in presets_dir.glob("*.yaml"))
    return sorted(names)


def extract_variant_values(scene: SceneNode) -> dict[str, str]:
    """Pull {field_name: value} from scene.component_properties[type=VARIANT].

    Values are coerced to string so YAML keys (always strings) can match.
    """
    out: dict[str, str] = {}
    for k, v in (scene.component_properties or {}).items():
        if isinstance(v, dict) and v.get("type") == "VARIANT":
            out[str(k)] = str(v.get("value", ""))
    return out


def recognize(
    scene: SceneNode,
    mapping: list[ComponentMapping],
    *,
    trace_path: list[str] | None = None,
) -> ComponentMapping | None:
    """Try to recognize an INSTANCE node against the mapping table.

    Precedence: componentId first, then name (case-insensitive).
    Returns None if no match. On match, applies `variants` override (cloned
    via dataclasses.replace so the shared mapping list is not mutated).

    Records a preset_matches trace entry (when --trace-adapter=preset is
    active): matched entries carry matched_by/entry_short/variant_hits,
    unmatched entries carry skipped_by + reason (single recording point —
    node_mapper's instance-not-recognized branch does NOT duplicate this).
    """
    if scene.type != "INSTANCE":
        return None

    trace_on = is_enabled("preset_matches")
    if trace_on:
        from avocado.parser.trace import truncate_path

        _path = truncate_path([*(trace_path or []), scene.name])
    matched: ComponentMapping | None = None
    matched_by: str | None = None
    block_skipped = False

    # 1. componentId match
    if scene.component_id:
        for m in mapping:
            if m.component_id and m.component_id == scene.component_id:
                matched = m
                matched_by = "component_id"
                break

    # 2. name match (case-insensitive)
    if matched is None:
        name_lower = (scene.name or "").lower().strip()
        if name_lower:
            for m in mapping:
                if m.name and m.name.lower().strip() == name_lower:
                    # Skip name-only match for components whose entry sets
                    # blockNameMatch (they need array/object props to render)
                    # UNLESS the entry configures dynamic_props (an extractor
                    # will provide items/groups/...). Without props these
                    # components throw on render and white-screen the tree.
                    if m.block_name_match and not m.dynamic_props:
                        block_skipped = True
                        continue
                    matched = m
                    matched_by = "name"
                    break

    if matched is None:
        if trace_on:
            # 分类优先级：compId 存在时以"未收录"为主因（block 细节并入 reason），
            # 与 spec D2 示例一致；无 compId 时 block 跳过优先于 name 无匹配。
            if scene.component_id:
                skipped_by = "component_id_not_in_preset"
                reason = f"componentId {scene.component_id!r} not in preset"
                if block_skipped:
                    reason += (
                        f"; name {scene.name!r} also matched an entry with "
                        f"blockNameMatch=true and no extractor"
                    )
            elif block_skipped:
                skipped_by = "block_name_match_skip"
                reason = (
                    f"name {scene.name!r} matched an entry with blockNameMatch=true "
                    f"and no extractor; name match skipped (white-screen guard)"
                )
            else:
                skipped_by = "name_no_match"
                reason = f"no preset entry matches name {scene.name!r}"
            try:
                rec: dict = {
                    "node_id": scene.id,
                    "node_name": scene.name,
                    "layer_type": scene.type,
                    "skipped_by": skipped_by,
                    "reason": reason[:200],
                    "path": _path,
                }
                _sug = _suggestion_for(scene, skipped_by)
                if _sug:
                    rec["suggestion"] = _sug
                record("preset_matches", rec)
            except Exception:
                pass  # zero-exception-risk: trace must never break the pipeline
        return None

    # 3. variants override — pick component/package by variant value.
    # Use a CLONE (m is shared across runs).
    variant_hits: list[dict] = []
    variant_values = extract_variant_values(scene)
    if matched.variants and variant_values:
        for field_name, value in variant_values.items():
            table = matched.variants.get(field_name)
            if not table:
                continue
            override = table.get(value)
            if not override:
                # bool-ish variants may arrive as 'True'/'False' strings;
                # also try a case-insensitive lookup just in case.
                override = _lookup_ci(table, value)
            if not override:
                continue
            new_component = override.get("component", matched.component)
            new_package = override.get("package", matched.package)
            # variants override can also flip leaf flag (e.g. Input
            # entry dispatches to LabeledInput which is a leaf component).
            new_leaf = override.get("leaf", matched.leaf)
            # An explicit component='' set by a
            # variants override is a downgrade signal (e.g. Tabs 'Circular on
            # Dark' → empty component to avoid a React crash).
            # Distinguish the "preset-defined component:'' pattern"
            # (Placeholder/Icon Left, should recognize successfully) from
            # "emptied by a variants override" (Tabs downgrade, should abandon
            # recognition).
            # Originally empty (matched.component == '') = preset component:''
            # pattern → keep. Originally non-empty but the override sets it
            # empty = downgrade → return None so apply_component falls back.
            if override.get("component") == "" and matched.component:
                if trace_on:
                    try:
                        record(
                            "preset_matches",
                            {
                                "node_id": scene.id,
                                "node_name": scene.name,
                                "layer_type": scene.type,
                                "skipped_by": "variant_downgrade",
                                "reason": (
                                    f"variants override for {field_name}={value!r} set "
                                    f"component='' (downgrade); recognition abandoned"
                                )[:200],
                                "path": _path,
                            },
                        )
                    except Exception:
                        pass  # zero-exception-risk: trace must never break the pipeline
                return None  # variants downgrade: abandon recognition
            if trace_on:
                variant_hits.append({"field": field_name, "value": value})
            matched = dataclasses.replace(
                matched, component=new_component, package=new_package, leaf=new_leaf
            )
            break  # first matching variant field wins

    if trace_on:
        entry_short: dict = {"component": matched.component}
        if matched.component_id:
            entry_short["componentId"] = matched.component_id
        entry: dict = {
            "node_id": scene.id,
            "node_name": scene.name,
            "layer_type": scene.type,
            "matched_by": matched_by,
            "entry_short": entry_short,
            "path": _path,
        }
        if variant_hits:
            entry["variant_hits"] = variant_hits
        try:
            record("preset_matches", entry)
        except Exception:
            pass  # zero-exception-risk: trace must never break the pipeline

    return matched


def _lookup_ci(table: dict, value: str):
    vl = value.lower()
    for k, v in table.items():
        if str(k).lower() == vl:
            return v
    return None


def _suggestion_for(scene: SceneNode, skipped_by: str) -> str | None:
    """Deterministic YAML skeleton for the 2 simple unmatched cases.

    Fills only tool-known fields (name / componentId); component & package
    are left as <fill> for the agent/user to decide. Never guesses semantics
    (e.g. whether a name is an icon) — that would be design-specific and
    non-portable for an open-source tool. Omitted when the skeleton would
    exceed 200 chars. Other skipped_by scenarios return None (their fix is
    not a simple entry add).

    Note: the skeleton uses single-quoted repr for name/componentId — a
    name containing mixed quote styles would not round-trip as valid YAML,
    but that is vanishingly rare for Figma layer names and the skeleton is
    a reference for the adapter author, not a machine-parsed contract.
    """
    if skipped_by not in {"name_no_match", "component_id_not_in_preset"}:
        return None
    lines = [f"- name: {scene.name!r}"]
    if scene.component_id:
        lines.append(f"  componentId: {scene.component_id!r}")
    lines.append("  component: <fill>")
    lines.append("  package: <fill>")
    s = "\n".join(lines)
    return s if len(s) <= 200 else None


def _extractor_sample(extracted: dict) -> dict:
    """Stable summary of an extractor result (never the full payload).

    Takes the first NON-EMPTY list value: its length plus the first item's
    `title` (coerced to str, when present). Empty lists are skipped — an
    empty list carries no usable length signal. Returns {} when there is no
    non-empty list (caller omits the sample key). Deterministic — no set
    iteration order involved.
    """
    for v in extracted.values():
        if isinstance(v, list) and v:
            sample: dict = {"items_len": len(v)}
            first = v[0]
            if isinstance(first, dict) and first.get("title") is not None:
                sample["first_title"] = str(first["title"])
            return sample
    return {}


def apply_component(
    scene: SceneNode,
    tree: TreeNode,
    mapping: list[ComponentMapping],
    *,
    trace_path: list[str] | None = None,
) -> bool:
    """If scene is a recognized INSTANCE, mutate tree to use the component.

    Returns True if recognized, False otherwise. Applies variantProperties
    (Figma variant value → component prop) and dynamicProps (Figma children →
    items/groups/... via extractor) in addition to base props.
    """
    m = recognize(scene, mapping, trace_path=trace_path)
    if m is None:
        return False

    # The component:'' pattern (Placeholder/Icon Left,
    # etc.) marks is_component=True (correct recognition-rate stats) but does
    # not change tag_name/DOM (keep the Figma SVG/children).
    # Don't set component_package (avoids a codegen import — component:'' has
    # no corresponding business component).
    if not m.component:
        tree.is_component = True  # mark recognition success (stats layer), do not change DOM
        # Don't set tree.component_package (component:'' is not imported)
        return True  # return True so recognition-rate stats stay correct

    tree.tag_name = m.component
    tree.is_component = True
    tree.component_package = m.package
    # Merge in any preset props
    tree.props.update(m.props)

    # variantProperties → props
    variant_prop_hits: list[dict] = []
    variant_prop_misses: list[dict] = []
    variant_values = extract_variant_values(scene)
    if m.variant_properties and variant_values:
        for field_name, value in variant_values.items():
            table = m.variant_properties.get(field_name)
            # 未命中 = 表里没配该 field 或该值（prop 静默不生效——正是要暴露的还原度问题）
            entry = (table.get(value) or _lookup_ci(table, value)) if table else None
            if entry:
                tree.props.update(entry)
                variant_prop_hits.append(
                    {"field": field_name, "value": value, "applied": sorted(entry.keys(), key=str)}
                )
            else:
                variant_prop_misses.append({"field": field_name, "value": value})

    # dynamicProps extractor (Phase 3)
    if m.dynamic_props and m.dynamic_props.get("extractor"):
        from avocado.parser.component_extractors import run_extractor

        _err_out: list[str] = []
        extracted = run_extractor(
            m.dynamic_props["extractor"],
            scene,
            m.dynamic_props.get("path"),
            error_out=_err_out,
        )
        # Trace the extractor outcome so adapter authors can see what was
        # actually extracted (keys + stable sample), not just empty/non-empty.
        if is_enabled("extractor_outputs"):
            try:
                entry: dict = {
                    "component": m.component,
                    "extractor": m.dynamic_props["extractor"],
                    "path": m.dynamic_props.get("path"),
                    "success": bool(extracted),
                    "keys": sorted(extracted.keys(), key=str) if extracted else [],
                }
                if extracted:
                    sample = _extractor_sample(extracted)
                    if sample:
                        entry["sample"] = sample
                else:
                    # 失败分类：机器枚举 + 独立 detail（agent 靠 error 分支）
                    if _err_out and _err_out[0] == "not_registered":
                        entry["error"] = "not_registered"
                    elif _err_out:
                        entry["error"] = "exception"
                        _detail = _err_out[0].removeprefix("exception: ").strip()
                        if _detail:
                            entry["error_detail"] = _detail[:200]
                    else:
                        entry["error"] = "empty_result"
                record("extractor_outputs", entry)
            except Exception:
                pass  # zero-exception-risk: trace must never break the pipeline
        if extracted:
            tree.props.update(extracted)
        else:
            tree.add_inspect(
                severity="info",
                code="extractor-empty",
                message=(
                    f"dynamicProps extractor {m.dynamic_props['extractor']!r} "
                    f"returned no data for component {m.component!r}."
                ),
            )

    # leaf components carry their own internal DOM (input/border/
    # label). Drop the Figma DOM children to avoid double-rendering.
    # Without this, e.g. a labeled input gets Figma's div+span+border
    # nested inside, which paints duplicate borders and misaligns text.
    #
    # Some Figma designs include elements that the leaf component
    # does NOT render itself (e.g. helper text below an input, error
    # messages, etc.). These would be lost by a naive `children = []`.
    # Instead, scan children for subtrees whose name matches an entry in
    # m.leaf_extras — those are kept as siblings of this node (moved from
    # children list to a new "extra" list returned via
    # tree.props['_leaf_extras']). The caller (node_mapper) inserts them
    # as siblings.
    leaf_dropped_info: dict | None = None
    if m.leaf:
        # Walk the children subtree depth-first; collect any node whose own
        # name matches an extra keyword (helper text / error message / etc.).
        # These are elements the component does NOT render itself, so they
        # would be lost by `children = []`. We extract just those nodes
        # (not their parents — pulling the parent would also drag the
        # input field / label / etc. and re-double-render).
        _pre_children_count = len(tree.children or [])
        extras: list[TreeNode] = []
        stack: list[TreeNode] = list(tree.children or [])
        while stack:
            n = stack.pop()
            nm = (n.name or "").lower()
            if any(kw in nm for kw in m.leaf_extras):
                extras.append(n)
                # Don't descend — the whole node is preserved as-is.
                continue
            stack.extend(n.children or [])
        tree.children = []
        tree.text_content = None
        if extras:
            tree.props["_leaf_extras"] = extras
        leaf_dropped_info = {
            "children_count": _pre_children_count,
            "kept_extras": sorted((getattr(e, "name", "") or "") for e in extras),
        }

    # ── trace: applied_details (variant/leaf 应用侧，内部 event:"applied" 标记) ──
    if is_enabled("preset_matches"):
        if variant_prop_hits or variant_prop_misses or (
            leaf_dropped_info is not None and leaf_dropped_info["children_count"] > 0
        ):
            try:
                applied_rec: dict = {
                    "event": "applied",
                    "node_id": scene.id,
                    "node_name": scene.name,
                }
                if m.component:
                    applied_rec["component"] = m.component
                if trace_path:
                    from avocado.parser.trace import truncate_path

                    applied_rec["path"] = truncate_path([*(trace_path or []), scene.name])
                if variant_prop_hits:
                    applied_rec["variant_prop_hits"] = variant_prop_hits
                if variant_prop_misses:
                    applied_rec["variant_prop_misses"] = variant_prop_misses
                if leaf_dropped_info is not None and leaf_dropped_info["children_count"] > 0:
                    applied_rec["leaf_dropped"] = leaf_dropped_info
                record("preset_matches", applied_rec)
            except Exception:
                pass  # zero-exception-risk: trace must never break the pipeline

    return True
