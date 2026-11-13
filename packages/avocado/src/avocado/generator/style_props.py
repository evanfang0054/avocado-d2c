"""Style → component-prop mapping (preset ``styleMode: props``).

Some component libraries express styling through props instead of CSS: a
typography component takes ``size`` / ``weight`` / ``color``, an image
component takes ``width`` / ``height`` / ``fit``. Without this pass a
recognized component keeps its entire Figma style as a pixel-locked
``style={{...}}`` blob, which is the main reason d2c output reads like a
screenshot dump instead of something a developer would write.

Preset shape (per component entry)::

    - name: Text
      component: Text
      styleMode: props
      styleProps:
        font-size:            # long form: value map
          prop: size
          values: { "12": xs, "14": sm, "16": md }
        color: color          # shorthand: raw value → same-named prop
      dropStyle: [width, height, flex-shrink]

Rules (all chosen to protect fidelity):

- a **value-map miss keeps the CSS property inline** — a design that uses
  17px must not silently become ``size="md"``;
- an existing prop is never overwritten (preset/variant props are author
  intent) and the duplicate CSS property is dropped so it cannot fight the
  prop through inline-style precedence;
- ``dropStyle`` properties are removed unconditionally: they are Figma
  geometry noise on a component that sizes itself (elastic width on Text).
"""

from __future__ import annotations

import re

from avocado.model.tree_node import TreeNode

_PX_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)px\s*$")
_NUM_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*$")


def _var_fallback(value: str) -> str | None:
    """Extract the fallback from ``var(--x, <fallback>)`` (None if absent).

    With ``--css-vars`` a style value can arrive as a var reference; the
    concrete value lives in the fallback and is what the prop mapping needs.
    """
    text = value.strip()
    if not text.startswith("var(") or not text.endswith(")"):
        return None
    inner = text[4:-1]
    if "," not in inner:
        return None
    return inner.rsplit(",", 1)[1].strip()


def _numeric(value) -> float | None:
    """Parse a numeric style value (``14``, ``"14"``, ``"14px"``) → float."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        fallback = _var_fallback(value)
        if fallback is not None:
            return _numeric(fallback)
        m = _PX_RE.match(value) or _NUM_RE.match(value)
        if m:
            return float(m.group(1))
    return None


def _compact_number(value: float):
    """14.0 → 14 (so JSX emits ``height={128}``, not ``height={128.0}``)."""
    rounded = round(value, 4)
    return int(rounded) if float(rounded).is_integer() else rounded


def _lookup(values: dict, raw) -> tuple[bool, object]:
    """Find a mapped prop value. Numeric equality first, then exact string.

    YAML keys may parse as int/float while the style value is ``"14px"``, so
    both are compared numerically. Non-numeric values fall back to a
    case-insensitive string comparison.
    """
    num = _numeric(raw)
    if num is not None:
        for key, mapped in values.items():
            key_num = _numeric(key)
            if key_num is not None and key_num == num:
                return True, mapped
    raw_s = str(raw).strip().lower()
    for key, mapped in values.items():
        if str(key).strip().lower() == raw_s:
            return True, mapped
    return False, None


def _prop_value(raw):
    """Raw style value → prop value: ``"128px"`` → ``128``, ``"100%"`` stays."""
    num = _numeric(raw)
    if num is not None:
        return _compact_number(num)
    return raw


def apply_style_props(node: TreeNode) -> None:
    """Move configured style keys into props; drop Figma geometry noise.

    Mutates ``node`` in place. Callers should only invoke this for nodes whose
    ``style_mode`` is ``"props"`` (see ``apply_style_prop_modes``).
    """
    if not node.style:
        return

    for css_prop in node.style_drop or ():
        node.style.pop(css_prop, None)

    for css_prop, spec in (node.style_props or {}).items():
        if css_prop not in node.style:
            continue
        if not isinstance(spec, dict):
            continue
        prop_name = spec.get("prop")
        if not prop_name:
            continue
        values = spec.get("values") or {}
        raw = node.style[css_prop]
        if values:
            hit, mapped = _lookup(values, raw)
            if not hit:
                continue  # unmapped value: keep the CSS inline (fidelity first)
        else:
            mapped = _prop_value(raw)
        # Preset/variant props are author intent — keep them, but drop the CSS
        # duplicate so inline-style precedence cannot override the prop.
        if prop_name not in node.props:
            node.props[prop_name] = mapped
        del node.style[css_prop]


def apply_style_prop_modes(tree: TreeNode) -> None:
    """Walk the tree and apply ``styleMode: props`` to every recognized component.

    Runs before the ``--css`` branch: moving style into props is orthogonal to
    how the *remaining* CSS is emitted (inline / class / tailwind), so all
    three output forms should get the same component props.
    """
    stack = [tree]
    while stack:
        n = stack.pop()
        if n.is_component and n.tag_name and n.style_mode == "props" and n.style:
            apply_style_props(n)
        stack.extend(n.children)
