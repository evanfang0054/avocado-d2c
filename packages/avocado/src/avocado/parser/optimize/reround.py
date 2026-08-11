"""Precision rewrite (reround) optimization pass.

Re-rounds numeric portions of CSS values to a target precision. Defaults
to precision2 (e.g. `12.34567px` → `12.35px`); precision=0 strips the
fraction entirely (`12px`).

FIX: besides style, also applies to Tailwind arbitrary values in className
(e.g. `w-[99.67px]` → `w-[100px]` when precision=0). Does not affect props/text_content.
"""

from __future__ import annotations

import re

from avocado.model.tree_node import TreeNode

# Match a leading number (optionally signed, optionally decimal) followed
# by a CSS unit suffix. We anchor on the start so multi-value strings
# like "12.34px 0 8px rgba(0,0,0,0.5)" only round the *first* number —
# matching the behavior of not re-rounding shadow/transform lists.
_NUM_RE = re.compile(r"^(-?\d+(?:\.\d+)?)(px|em|rem|%|deg|s|ms)?")

# FIX: match numbers inside Tailwind arbitrary values ([99.67px] / [12.5rem], etc.)
# Shaped like w-[99.67px] / h-[12.5rem] / top-[3.5px]
_ARBITRARY_RE = re.compile(r"(\[-?\d+(?:\.\d+)?)(px|em|rem|%|deg|s|ms)?(\])")


def reround_value(val: str, precision: int) -> str:
    """Round the leading number in a CSS value string.

    Non-numeric strings are returned unchanged. For precision=0 we cast
    to int so no trailing `.0` appears.
    """
    if not isinstance(val, str):
        return val
    # Fast path: if there's no digit at the start, skip the regex.
    stripped = val.lstrip()
    if not stripped or stripped[0] not in "-0123456789":
        return val
    m = _NUM_RE.match(stripped)
    if not m:
        return val
    num_str, unit = m.group(1), m.group(2) or ""
    try:
        num = float(num_str)
    except ValueError:
        return val
    if precision <= 0:
        rounded: int | float = int(round(num))
    else:
        rounded = round(num, precision)
        if rounded == int(rounded):
            rounded = int(rounded)
    # Preserve any leading whitespace + the trailing portion of the string
    # after the matched number+unit (e.g. " 12.34567px 0 8px" → " 12.35px 0 8px").
    lead = val[: len(val) - len(stripped)]
    rest = stripped[m.end() :]
    return f"{lead}{rounded}{unit}{rest}"


def _reround_arbitrary_value(val: str, precision: int) -> str:
    """Round all Tailwind arbitrary value numbers in a className string.

    FIX: applies to className (e.g. `w-[99.67px] h-[12.5rem]`).
    All arbitrary values will be rewritten.
    """
    if not isinstance(val, str) or "[" not in val:
        return val

    def _replace(m: re.Match) -> str:
        num_str = m.group(1)[1:]  # strip the leading "["
        unit = m.group(2) or ""
        try:
            num = float(num_str)
        except ValueError:
            return m.group(0)
        if precision <= 0:
            rounded: int | float = int(round(num))
        else:
            rounded = round(num, precision)
            if rounded == int(rounded):
                rounded = int(rounded)
        return f"[{rounded}{unit}]"

    return _ARBITRARY_RE.sub(_replace, val)


def reround_styles(root: TreeNode, precision: int) -> None:
    """In-place: re-round all numeric CSS values in the tree."""
    if precision is None:
        return
    stack = [root]
    while stack:
        n = stack.pop()
        for k, v in list(n.style.items()):
            if isinstance(v, str):
                new_v = reround_value(v, precision)
                if new_v != v:
                    n.style[k] = new_v
            elif isinstance(v, float):
                # Bare-float entries (rare; usually boxed into strings).
                if precision <= 0:
                    n.style[k] = int(round(v))
                else:
                    r = round(v, precision)
                    n.style[k] = int(r) if r == int(r) else r
        # FIX: reround also applies to Tailwind arbitrary values in className
        # className lives in n.props["className"] (set by tailwind.py), not n.class_name.
        # Check both places to ensure full coverage.
        cn = None
        if hasattr(n, "class_name") and n.class_name:
            cn = n.class_name
            new_cn = _reround_arbitrary_value(cn, precision)
            if new_cn != cn:
                n.class_name = new_cn
        if hasattr(n, "props") and n.props.get("className"):
            cn2 = n.props["className"]
            new_cn2 = _reround_arbitrary_value(cn2, precision)
            if new_cn2 != cn2:
                n.props["className"] = new_cn2
        stack.extend(n.children)


def reround_class_map(class_map: dict[str, dict], precision: int) -> None:
    """In-place: re-round all values in a CSS-class map.

    `class_map` is `{class_name: {prop: value}}` as produced by
    `apply_css_class`. We round each property value string.
    """
    if precision is None:
        return
    for styles in class_map.values():
        for k, v in list(styles.items()):
            if isinstance(v, str):
                new_v = reround_value(v, precision)
                if new_v != v:
                    styles[k] = new_v
