"""CSS variable extraction from boundVariables.

Extension:
  - Extends `_SUPPORTED_PROPS` to cover font/padding/corner/stroke bindings.
  - Adds paint-embedded boundVariables scanning (fills/strokes).
  - `collect_variables` now accepts `var_map` (VariableID → semantic name)
    and `with_fallback` (default True) — emits `var(--name, fallback)` so
    downstream projects without the variable defined still render the
    design-accurate value.

We do NOT emit a `:root` block (KISS). `:root` definitions are the downstream
project's responsibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from avocado.model.scene_node import SceneNode
from avocado.model.tree_node import TreeNode
from avocado.parser.style import paint_color_to_css

# Properties we extract from boundVariables → CSS mapping
# Figma property name → (css property name, value extractor)
# Extractors take a SceneNode and return its current value (or None)
_SUPPORTED_PROPS: dict[str, tuple[str, callable]] = {
    "cornerRadius": ("border-radius", lambda s: s.corner_radius),
    "itemSpacing": ("gap", lambda s: s.item_spacing),
    "paddingTop": ("padding-top", lambda s: s.padding_top),
    "paddingRight": ("padding-right", lambda s: s.padding_right),
    "paddingBottom": ("padding-bottom", lambda s: s.padding_bottom),
    "paddingLeft": ("padding-left", lambda s: s.padding_left),
    "strokeWeight": ("border-width", lambda s: s.stroke_weight),
    # ── additional supported props ──
    "fontSize": ("font-size", lambda s: s.text_style.font_size if s.text_style else None),
    "fontFamily": ("font-family", lambda s: s.text_style.font_family if s.text_style else None),
    "fontWeight": ("font-weight", lambda s: s.text_style.font_weight if s.text_style else None),
    # width/height not commonly var-bound; skip for KISS
}


@dataclass
class CssVariableCollection:
    """All CSS variables collected from a tree."""

    # var_id (short) → value
    variables: dict[str, str] = field(default_factory=dict)

    # var_id (short) → original full VariableID
    full_ids: dict[str, str] = field(default_factory=dict)

    # Var-map hit tracking: how many bindings matched a var_map entry vs
    # fell back to fig-var-<short>. When var_map is empty, matched=0 and
    # total = number of bindings collected. Lets the caller (cli.py envelope)
    # warn when --var-map loaded 0 mappings so users don't silently get
    # unreadable fig-var-XXX names.
    var_map_matched: int = 0
    var_map_total: int = 0

    def add(self, full_id: str, value: str | float | None) -> str:
        """Add a variable. Returns the short name to use in CSS.

        If value is None, still registers the variable but skips value.
        Returns "--fig-var-<short>" form for CSS reference.
        """
        short = _short_id(full_id)
        self.full_ids[short] = full_id
        if value is not None and short not in self.variables:
            self.variables[short] = _format_value(value)
        return f"var(--{short})"

    def render_root_block(self) -> str:
        """Render `:root { --var-name: value; ... }` block.

        Deprecated (we no longer emit :root) but retained for
        backward compatibility with existing tests.
        """
        if not self.variables:
            return ""
        lines = [":root {"]
        for short, value in sorted(self.variables.items()):
            lines.append(f"  --{short}: {value};")
        lines.append("}")
        return "\n".join(lines) + "\n"


def _short_id(full_id: str) -> str:
    """Convert VariableID:abc123/123:45 → fig-var-123-45 (last segment)."""
    # full_id like "VariableID:9810cffc.../15156:453"
    # → use last "/15156:453" segment, replace : with -
    m = re.search(r"/([^/:]+:[^/:]+)$", full_id)
    if m:
        return f"fig-var-{m.group(1).replace(':', '-')}"
    # fallback: hash
    return f"fig-var-{abs(hash(full_id)) % 100000}"


def _format_value(v: str | float) -> str:
    """Format a value for CSS. Add px suffix to bare numbers when meaningful."""
    if isinstance(v, (int, float)):
        rounded = round(float(v), 2)
        if rounded == int(rounded):
            rounded = int(rounded)
        return f"{rounded}px"
    return str(v)


def collect_variables(
    scene: SceneNode,
    tree: TreeNode,
    var_map: dict[str, str] | None = None,
    with_fallback: bool = True,
) -> CssVariableCollection:
    """Walk scene tree parallel to TreeNode tree, collect boundVariables.

    Returns the collection. Side effect: replaces tree.style values with
    `var(--name, fallback)` references where the scene node had a binding.

    Args:
        scene: root SceneNode
        tree: root TreeNode (will be mutated)
        var_map: VariableID → semantic CSS name (without `--`). If a binding's
            id is in var_map, the emitted var() uses the semantic name;
            otherwise falls back to `fig-var-<short>`.
        with_fallback: when True (default), emit `var(--x, fallback)` with
            the node's current value as fallback. When False, emit just
            `var(--x)`.
    """
    collection = CssVariableCollection()
    _collect_recursive(scene, tree, collection, var_map or {}, with_fallback)
    return collection


def _var_ref(
    full_id: str,
    fallback: str | float | None,
    var_map: dict[str, str],
    with_fallback: bool,
    collection: CssVariableCollection,
) -> str:
    """Build a `var(--name, fallback)` string and register the variable."""
    matched = full_id in var_map
    collection.var_map_total += 1
    if matched:
        collection.var_map_matched += 1
    name = var_map[full_id] if matched else _short_id(full_id)
    # Always register short → full for collection completeness
    short = _short_id(full_id)
    collection.full_ids[short] = full_id
    if fallback is not None and short not in collection.variables:
        collection.variables[short] = _format_value(fallback)
    if with_fallback and fallback is not None:
        return f"var(--{name}, {_format_value(fallback)})"
    return f"var(--{name})"


def _collect_recursive(
    scene: SceneNode,
    tree: TreeNode,
    collection: CssVariableCollection,
    var_map: dict[str, str],
    with_fallback: bool,
) -> None:
    """Process one node, then recurse into matching children."""
    bv = scene.raw.get("boundVariables") if scene.raw else None
    if bv:
        for figma_prop, var_ref in bv.items():
            if figma_prop not in _SUPPORTED_PROPS:
                continue
            if not isinstance(var_ref, dict):
                continue
            full_id = var_ref.get("id")
            if not full_id:
                continue
            css_prop, extractor = _SUPPORTED_PROPS[figma_prop]
            value = extractor(scene)
            # Replace in tree.style IF the corresponding CSS prop is set
            if css_prop in tree.style and value is not None:
                expected = _format_value(value)
                if str(tree.style[css_prop]) == expected:
                    tree.style[css_prop] = _var_ref(
                        full_id,
                        value,
                        var_map,
                        with_fallback,
                        collection,
                    )
                else:
                    # Value mismatch — still register the var
                    _var_ref(full_id, value, var_map, False, collection)
            else:
                _var_ref(full_id, value, var_map, False, collection)

    # ── paint-embedded boundVariables (fills/strokes color) ──
    _collect_paint_bindings(scene, tree, collection, var_map, with_fallback)

    # Recurse into children — match by figma_id
    scene_children_by_id = {c.id: c for c in scene.children}
    for child_tree in tree.children:
        scene_child = scene_children_by_id.get(child_tree.figma_id or "")
        if scene_child:
            _collect_recursive(
                scene_child,
                child_tree,
                collection,
                var_map,
                with_fallback,
            )


def _collect_paint_bindings(
    scene: SceneNode,
    tree: TreeNode,
    collection: CssVariableCollection,
    var_map: dict[str, str],
    with_fallback: bool,
) -> None:
    """Scan fills/strokes paints for embedded boundVariables.color.

    Replaces `background-color` for SOLID fills whose color is var-bound.
    Strokes are registered in the collection but NOT replaced in style
    (border is a composite `Npx solid color` value — KISS, don't touch).
    """
    # Fills: replace background-color
    solid_fills = [p for p in scene.fills if p.visible and p.type == "SOLID" and p.bound_variables]
    for paint in solid_fills:
        color_binding = paint.bound_variables.get("color") if paint.bound_variables else None
        if not isinstance(color_binding, dict):
            continue
        full_id = color_binding.get("id")
        if not full_id:
            continue
        fallback = paint_color_to_css(paint)
        if "background-color" in tree.style and fallback is not None:
            if str(tree.style["background-color"]) == fallback:
                tree.style["background-color"] = _var_ref(
                    full_id,
                    fallback,
                    var_map,
                    with_fallback,
                    collection,
                )
            else:
                _var_ref(full_id, fallback, var_map, False, collection)
        else:
            _var_ref(full_id, fallback, var_map, False, collection)

    # Strokes: register only (border is composite, don't replace)
    solid_strokes = [
        p for p in scene.strokes if p.visible and p.type == "SOLID" and p.bound_variables
    ]
    for paint in solid_strokes:
        color_binding = paint.bound_variables.get("color") if paint.bound_variables else None
        if not isinstance(color_binding, dict):
            continue
        full_id = color_binding.get("id")
        if not full_id:
            continue
        fallback = paint_color_to_css(paint)
        _var_ref(full_id, fallback, var_map, False, collection)
