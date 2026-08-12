"""React style object rendering: TreeNode.style dict → `style={{...}}` string.

Mirrors css.render_inline_style but emits React style object form:
  background-color: red  →  backgroundColor: "red"
  line-height: 24px      →  lineHeight: "24px"   (string, NEVER bare number)
  opacity: 0.5           →  opacity: 0.5          (unitless → bare)

Critical decision: `lineHeight` is always emitted as a string `"Npx"`.
React interprets a bare numeric `lineHeight: 24` as "24× font-size" (CSS
unitless line-height = multiplier), which is wildly different from the 24px
Figma intended. The string form `"24px"` is unambiguous.
"""

from __future__ import annotations

from avocado.generator._style_order import ordered_style
from avocado.generator.css import normalize_css_value
from avocado.model.tree_node import TreeNode

# Vendor prefixes: `-webkit-X` → `WebkitX` (NOT `webkitX` per React convention).
_VENDOR_PREFIXES = {
    "-webkit-": "Webkit",
    "-moz-": "Moz",
    "-ms-": "Ms",
    "-o-": "O",
}


def _to_camel_case(key: str) -> str:
    """kebab-case → camelCase, with React-style vendor prefix handling."""
    for prefix, replacement in _VENDOR_PREFIXES.items():
        if key.startswith(prefix):
            rest = key[len(prefix) :]
            rest_camel = "".join(p.capitalize() for p in rest.split("-") if p)
            return replacement + rest_camel
    parts = key.split("-")
    if len(parts) == 1:
        return key
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


# React's `isUnitlessNumber` set — bare numbers are emitted without a `px`
# suffix when React renders them. For our purposes, properties in this set
# receive bare numeric values; everything else gets `"Npx"` strings.
# Source: React DOM's CSSProperties.js. Subset that Figma pipeline actually
# hits: lineHeight, fontWeight, opacity, flexGrow, flexShrink, zIndex. The
# full set is retained to future-proof against new parser paths.
_UNITLESS_NUMBER_SET = frozenset(
    {
        "animationIterationCount",
        "aspectRatio",
        "borderImageOutset",
        "borderImageSlice",
        "borderImageWidth",
        "boxFlex",
        "boxFlexGroup",
        "boxOrdinalGroup",
        "columnCount",
        "columns",
        "flex",
        "flexGrow",
        "flexPositive",
        "flexShrink",
        "flexNegative",
        "flexOrder",
        "gridArea",
        "gridColumn",
        "gridColumnEnd",
        "gridColumnStart",
        "gridRow",
        "gridRowEnd",
        "gridRowStart",
        "lineClamp",
        "lineHeight",
        "opacity",
        "order",
        "orphans",
        "tabSize",
        "widows",
        "zIndex",
        "zoom",
        "fillOpacity",
        "floodOpacity",
        "stopOpacity",
        "strokeDasharray",
        "strokeDashoffset",
        "strokeMiterlimit",
        "strokeOpacity",
        "strokeWidth",
        "fontWeight",
    }
)


def _format_value(camel_key: str, value) -> str:
    """Format a value for a React style object literal.

    Args:
        camel_key: already camelCased key (e.g. lineHeight, opacity).
        value: original style value (str | int | float).

    Returns the literal source form, e.g. `"24px"`, `0.5`, `24`, `"center"`.
    """
    # Bare numeric value (int/float, not string).
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Special-case lineHeight: bare number in CSS = multiplier (× font-size),
        # NOT pixels. Always emit "Npx" to preserve Figma's intent.
        if camel_key == "lineHeight":
            return f'"{value:g}px"'
        if camel_key in _UNITLESS_NUMBER_SET:
            # Bare number — JS literal. Use :g to drop trailing .0.
            return f"{value:g}"
        # Non-unitless: bare number means px in our pipeline, emit "Npx".
        # Zero is an exception — a zero length never needs a unit (CSS spec).
        if value == 0:
            return '"0"'
        return f'"{value:g}px"'

    # String value.
    s = normalize_css_value(str(value))

    # Pure number string like "24": unitless → bare, else "Npx".
    if s.strip().isdigit():
        n = int(s.strip())
        if camel_key == "lineHeight":
            # Same rule: force "Npx" string for lineHeight.
            return f'"{n}px"'
        if camel_key in _UNITLESS_NUMBER_SET:
            return f"{n}"
        # Zero needs no unit (CSS Values & Units spec) — emit bare "0".
        if n == 0:
            return '"0"'
        return f'"{n}px"'

    # Already has px suffix. For unitless props we still keep the string form
    # ("Npx") because emitting a bare number would change semantics (e.g.
    # lineHeight bare = multiplier). React accepts the string "24px" for any
    # numeric prop without auto-adding px.
    # If the value contains a double quote (e.g. font-family: "Poppins", sans-serif),
    # wrap with single quotes to avoid escaping issues in JSX style object.
    if '"' in s:
        # Escape any embedded single quotes.
        s_escaped = s.replace("'", "\\'")
        return f"'{s_escaped}'"
    return f'"{s}"'


def render_react_style(node: TreeNode) -> str:
    """Build the `style={{...}}` string from node.style.

    Returns empty string if no styles.
    """
    if not node.style:
        return ""
    items = []
    for k, v in ordered_style(node.style).items():
        camel = _to_camel_case(k)
        items.append(f"{camel}: {_format_value(camel, v)}")
    return "style={{" + ", ".join(items) + "}}"
