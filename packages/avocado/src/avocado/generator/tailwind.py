"""Tailwind CSS class generator.

(see project design docs) CSS output alternatives.

Converts TreeNode.style dict → Tailwind class names. Covers common cases
for KISS — does NOT aim for 100% coverage (that needs the full Tailwind
config). Unmapped styles stay as inline style (mixed output).

Coverage:
  - display: flex/none/hidden
  - flex-direction: row/column
  - justify-content: flex-start/center/end/between
  - align-items: flex-start/center/end/stretch
  - gap, padding, margin (numeric)
  - width/height (numeric)
  - background-color, color (named colors only; hex falls back to inline)
  - border-radius (rounded-md/lg/full mapping)
  - font-size, font-weight, text-align
"""

from __future__ import annotations

import re

from avocado.model.tree_node import TreeNode

# ── property → tailwind class mapper ──

_DISPLAY = {
    "flex": "flex",
    "block": "block",
    "none": "hidden",
    "inline": "inline",
    "inline-block": "inline-block",
}

_FLEX_DIRECTION = {
    "row": "flex-row",
    "column": "flex-col",
    "row-reverse": "flex-row-reverse",
    "column-reverse": "flex-col-reverse",
}

_JUSTIFY = {
    "flex-start": "justify-start",
    "center": "justify-center",
    "flex-end": "justify-end",
    "space-between": "justify-between",
    "space-around": "justify-around",
}

_ALIGN = {
    "flex-start": "items-start",
    "center": "items-center",
    "flex-end": "items-end",
    "stretch": "items-stretch",
    "baseline": "items-baseline",
}

# Map font-size px → tailwind text-{xs|sm|base|lg|xl|2xl|...}
_FONT_SIZE_PX = {
    12: "text-xs",
    14: "text-sm",
    16: "text-base",
    18: "text-lg",
    20: "text-xl",
    24: "text-2xl",
    30: "text-3xl",
    36: "text-4xl",
    48: "text-5xl",
}

_FONT_WEIGHT = {
    300: "font-light",
    400: "font-normal",
    500: "font-medium",
    600: "font-semibold",
    700: "font-bold",
    800: "font-extrabold",
}

_TEXT_ALIGN = {
    "left": "text-left",
    "center": "text-center",
    "right": "text-right",
    "justify": "text-justify",
}

# border-radius px → rounded-{none|sm|md|lg|xl|2xl|full}
_BORDER_RADIUS_PX = {
    0: "rounded-none",
    2: "rounded-sm",
    4: "rounded",
    6: "rounded-md",
    8: "rounded-lg",
    12: "rounded-xl",
    16: "rounded-2xl",
    24: "rounded-3xl",
    999: "rounded-full",
}

# Named colors → tailwind color classes
_NAMED_COLORS = {
    "#ffffff": "white",
    "#fff": "white",
    "#000000": "black",
    "#000": "black",
    "#ff0000": "red-500",
    "#f00": "red-500",
    "#00ff00": "green-500",
    "#0f0": "green-500",
    "#0000ff": "blue-500",
    "#00f": "blue-500",
}


# Spacing scale: tailwind spacing is 4px/unit (1 → 4px, 2 → 8px, etc.)
# Map arbitrary px → "p-[Npx]" arbitrary value form


def _px_value(v) -> float | None:
    """Extract numeric px from value like '8px' or 8."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.match(r"^(-?\d+(?:\.\d+)?)px$", v.strip())
        if m:
            return float(m.group(1))
    return None


# Tailwind v3 default spacing scale (unit values — NOT all integers, only
# these specific ones are valid class names). Source:
# https://tailwindcss.com/docs/customizing-spacing#default-spacing-scale
# Invalid values (e.g. 13, 15, 17) are silently ignored by Tailwind CDN,
# causing the element to fall back to content-sized height — a subtle layout
# bug. We emit arbitrary value form (h-[52px]) for anything not in this set.
_TW_SPACING_UNITS = frozenset(
    {
        0,
        1,
        1.5,
        2,
        2.5,
        3,
        3.5,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        14,
        16,
        20,
        24,
        28,
        32,
        36,
        40,
        44,
        48,
        52,
        56,
        60,
        64,
        72,
        80,
        96,
    }
)


def _spacing_class(px: float, prefix: str) -> str | None:
    """Convert px to 'p-N' if on Tailwind's spacing scale, else 'p-[Npx]'."""
    if px == 0:
        return f"{prefix}-0"
    unit = px / 4
    # Check against the full Tailwind scale (including half-units like 1.5, 2.5)
    if unit in _TW_SPACING_UNITS:
        # Format: 1.5 → "1.5", 2 → "2"
        ustr = f"{unit:g}" if unit != int(unit) else str(int(unit))
        return f"{prefix}-{ustr}"
    return f"{prefix}-[{px:g}px]"


# Tailwind tracking scale: tighter / normal / wider are named, but the
# numeric scale is NOT 4px-based (tracking-1 = 0.25em, not 4px). For our
# px inputs the cleanest mapping is arbitrary value form; common small
# values get a known name.
_TRACKING_NAMED_PX = {
    0: "tracking-normal",
}


def _tracking_class(px: float) -> str:
    """Convert px to a Tailwind tracking class.

    tracking-N is in 0.0Xem increments, not px, so we use arbitrary value
    form for non-zero px values to stay semantically accurate.
    """
    if px in _TRACKING_NAMED_PX:
        return _TRACKING_NAMED_PX[px]
    return f"tracking-[{px:g}px]"


# ── CSS variable arbitrary value mapping ──
# When a style value is a `var(--name, fallback)` reference, emit it as a
# tailwind arbitrary value class (e.g. `bg-[var(--x,#faf8f7)]`). Tailwind
# requires underscores instead of spaces, and the arbitrary value is wrapped
# in square brackets.
_CSS_VAR_PREFIX_MAP: dict[str, str] = {
    "background-color": "bg-",
    "color": "text-",
    "border-color": "border-",
    "border-top-color": "border-t-",
    "border-right-color": "border-r-",
    "border-bottom-color": "border-b-",
    "border-left-color": "border-l-",
    "padding-top": "pt-",
    "padding-right": "pr-",
    "padding-bottom": "pb-",
    "padding-left": "pl-",
    "padding": "p-",
    "margin-top": "mt-",
    "margin-right": "mr-",
    "margin-bottom": "mb-",
    "margin-left": "ml-",
    "margin": "m-",
    "gap": "gap-",
    "width": "w-",
    "height": "h-",
    "border-radius": "rounded-",
    "border-width": "border-",
}

# Properties where the tailwind arbitrary value needs a type hint
# (tailwind can't infer the value type from a var reference).
_CSS_VAR_TYPE_HINT: dict[str, str] = {
    "font-size": "length",
    "font-family": "family-name",
    "font-weight": "number",
    "line-height": "length",
    "letter-spacing": "spacing",
}

# font-* properties use the `text-` / `font-` prefix with type hints
_TW_TEXT_PREFIX: dict[str, str] = {
    "font-size": "text",
    "font-family": "font",
    "font-weight": "font",
    "line-height": "leading",
    "letter-spacing": "tracking",
}


def _css_var_to_arbitrary(prop: str, value: str) -> str | None:
    """Convert a `var(--x, fallback)` value to a tailwind arbitrary class.

    Returns None if the property isn't mapped to a tailwind prefix.
    """
    # Normalize: strip spaces inside the var so tailwind parses it cleanly
    inner = value.replace(" ", "")
    # Determine prefix
    if prop in _CSS_VAR_TYPE_HINT:
        hint = _CSS_VAR_TYPE_HINT[prop]
        return f"{_TW_TEXT_PREFIX[prop]}-[{hint}:{inner}]"
    prefix = _CSS_VAR_PREFIX_MAP.get(prop)
    if not prefix:
        return None
    return f"{prefix}[{inner}]"


def style_to_tailwind(style: dict) -> tuple[list[str], dict]:
    """Convert a style dict to (class_names, leftover_style).

    Leftover style contains properties we couldn't map — kept as inline
    style for correctness.
    """
    classes: list[str] = []
    leftover: dict = {}

    for k, v in style.items():
        cls = _map_one(k, v)
        if cls:
            # _map_one may return space-joined multi-class (e.g. non-uniform
            # padding → "pt-4 pr-4 pb-4 pl-4"). Split and add each separately
            # so dedup works per-class.
            if " " in cls:
                classes.extend(cls.split())
            else:
                classes.append(cls)
        else:
            leftover[k] = v

    # Dedup classes preserving order
    seen = set()
    out_classes = []
    for c in classes:
        if c not in seen:
            out_classes.append(c)
            seen.add(c)

    return out_classes, leftover


def _map_one(prop: str, value) -> str | None:
    """Try to map one (prop, value) → tailwind class. None if no match."""
    # ── CSS variable values → tailwind arbitrary value syntax ──
    if isinstance(value, str) and "var(--" in value:
        cls = _css_var_to_arbitrary(prop, value)
        if cls:
            return cls
    # otherwise fall through and likely land in leftover

    if prop == "display" and value in _DISPLAY:
        return _DISPLAY[value]
    if prop == "flex-direction" and value in _FLEX_DIRECTION:
        return _FLEX_DIRECTION[value]
    if prop == "justify-content" and value in _JUSTIFY:
        return _JUSTIFY[value]
    if prop == "align-items" and value in _ALIGN:
        return _ALIGN[value]
    if prop == "flex-wrap" and value == "wrap":
        return "flex-wrap"

    if prop == "gap":
        px = _px_value(value)
        if px is not None:
            return _spacing_class(px, "gap")

    if prop in ("padding-top", "padding-right", "padding-bottom", "padding-left"):
        prefix_map = {
            "padding-top": "pt",
            "padding-right": "pr",
            "padding-bottom": "pb",
            "padding-left": "pl",
        }
        px = _px_value(value)
        if px is not None:
            return _spacing_class(px, prefix_map[prop])

    if prop == "padding" and isinstance(value, str):
        # 4-value shorthand. Split into 4 longhand pt/pr/pb/pl classes so
        # non-uniform values also get mapped to className instead of leftover
        # inline style
        parts = value.split()
        if len(parts) == 4 and all(p == parts[0] for p in parts):
            px = _px_value(parts[0])
            if px is not None:
                return _spacing_class(px, "p")
        elif len(parts) == 4:
            # Non-uniform 4-value. Emit py-/px- for symmetric pairs, else
            # individual pt/pr/pb/pl. Example: "64px 0 64px 0" → "py-16"
            # (only 1 class, since px-0 == default → filtered by strip).
            # Order in CSS: top right bottom left.
            top, right, bottom, left = parts
            out = []
            if top == bottom:
                px = _px_value(top)
                if px is not None:
                    if px != 0:
                        out.append(_spacing_class(px, "py"))
                else:
                    return None
            else:
                for pfx, raw in (("pt", top), ("pb", bottom)):
                    px = _px_value(raw)
                    if px is not None:
                        if px != 0:
                            out.append(_spacing_class(px, pfx))
                    else:
                        return None
            if right == left:
                px = _px_value(right)
                if px is not None:
                    if px != 0:
                        out.append(_spacing_class(px, "px"))
                else:
                    return None
            else:
                for pfx, raw in (("pr", right), ("pl", left)):
                    px = _px_value(raw)
                    if px is not None:
                        if px != 0:
                            out.append(_spacing_class(px, pfx))
                    else:
                        return None
            return " ".join(out) if out else None
        elif len(parts) == 2:
            # 2-value: "V V" → vertical/horizontal symmetric
            # pt/pb share one value, pr/pl share another
            out = []
            px_v = _px_value(parts[0])
            px_h = _px_value(parts[1])
            if px_v is not None and px_h is not None:
                out.append(_spacing_class(px_v, "py"))
                out.append(_spacing_class(px_h, "px"))
                return " ".join(out)
        elif len(parts) == 1:
            px = _px_value(parts[0])
            if px is not None:
                return _spacing_class(px, "p")

    if prop == "width":
        px = _px_value(value)
        if px is not None:
            return _spacing_class(px, "w")
    if prop == "height":
        px = _px_value(value)
        if px is not None:
            return _spacing_class(px, "h")

    if prop == "background-color":
        s = str(value).lower()
        if s in _NAMED_COLORS:
            return f"bg-{_NAMED_COLORS[s]}"
        # Readability: hex/rgb colors → arbitrary value class.
        # Emit all colors as bg-[#xxx] so the output isn't half-className /
        # half-inline-style.
        if s.startswith("#") or s.startswith("rgb"):
            # Hotfix: rgba(R, G, B, A) contains spaces, and tailwind
            # arbitrary values [..] don't allow spaces inside (style_to_tailwind
            # splits on spaces → broken class names).
            # Convert spaces to underscores (consistent with font-/shadow-).
            return f"bg-[{s.replace(' ', '_')}]"
    if prop == "color":
        s = str(value).lower()
        if s in _NAMED_COLORS:
            return f"text-{_NAMED_COLORS[s]}"
        if s.startswith("#") or s.startswith("rgb"):
            return f"text-[{s.replace(' ', '_')}]"

    if prop == "border-radius":
        px = _px_value(value)
        if px is not None:
            if px in _BORDER_RADIUS_PX:
                return _BORDER_RADIUS_PX[px]
            return f"rounded-[{px:g}px]"
        # Non-uniform 4-value (Figma rectangleCornerRadii): "TL TR BR BL" →
        # arbitrary value. Tailwind maps underscores to spaces in arbitrary
        # values, so rounded-[16px_16px_0_0] → border-radius: 16px 16px 0 0.
        if isinstance(value, str) and len(value.split()) == 4:
            return f"rounded-[{value.replace(' ', '_')}]"

    # border-color arbitrary value (parallel to bg-/text- above)
    if prop == "border-color":
        s = str(value).lower()
        if s in _NAMED_COLORS:
            return f"border-{_NAMED_COLORS[s]}"
        if s.startswith("#") or s.startswith("rgb"):
            return f"border-[{s.replace(' ', '_')}]"

    # border-width arbitrary value (border / border-2 / border-Npx)
    if prop in (
        "border-width",
        "border-top-width",
        "border-right-width",
        "border-bottom-width",
        "border-left-width",
    ):
        px = _px_value(value)
        if px is not None:
            prefix_map = {
                "border-width": "border",
                "border-top-width": "border-t",
                "border-right-width": "border-r",
                "border-bottom-width": "border-b",
                "border-left-width": "border-l",
            }
            pfx = prefix_map[prop]
            if px == 0:
                return None  # let strip_defaults handle border:0
            if px == 1:
                return pfx  # "border" = 1px in Tailwind defaults
            if px == 2:
                return f"{pfx}-2"
            return f"{pfx}-[{px:g}px]"

    if prop == "font-size":
        px = _px_value(value)
        if px is not None and px in _FONT_SIZE_PX:
            return _FONT_SIZE_PX[px]

    if prop == "font-weight":
        try:
            w = int(value) if isinstance(value, (int, float, str)) else None
            if w in _FONT_WEIGHT:
                return _FONT_WEIGHT[w]
        except (ValueError, TypeError):
            pass

    if prop == "text-align" and value in _TEXT_ALIGN:
        return _TEXT_ALIGN[value]

    # Readability: font-family arbitrary value (font-[...])
    # Emit font-family as className to keep styles out of inline.
    # Value may be: a bare family name, "Family, sans-serif", or a quoted
    # multi-word family like '"Multi Word", sans-serif'
    # Tailwind font-[...] expects a CSS family value; we pass it through as-is
    # but normalize quote chars so the class name stays a single token.
    if prop == "font-family" and isinstance(value, str) and value.strip():
        # Replace double quotes with single quotes (Tailwind arbitrary value
        # uses square brackets; single quotes are valid CSS string escapes).
        v = value.strip().replace('"', "'")
        # Replace spaces with underscores (Tailwind arbitrary value rule).
        # But don't touch commas or quotes — those are CSS-level.
        # Note: Tailwind treats `_` as space, so "Family, sans-serif" →
        # "Family,_sans-serif" — but actually we want literal space. Use
        # underscores as Tailwind docs specify.
        # See https://tailwindcss.com/docs/adding-custom-styles#resolving-ambiguities
        v_tw = v.replace(" ", "_")
        return f"font-[{v_tw}]"

    # Readability: overflow maps to standard Tailwind classes
    if prop in ("overflow", "overflow-x", "overflow-y"):
        _OVERFLOW_MAP = {
            "hidden": "overflow-hidden",
            "auto": "overflow-auto",
            "visible": "overflow-visible",
            "scroll": "overflow-scroll",
        }
        if value in _OVERFLOW_MAP:
            base = _OVERFLOW_MAP[value]
            if prop == "overflow":
                return base
            elif prop == "overflow-x":
                return base.replace("overflow-", "overflow-x-")
            elif prop == "overflow-y":
                return base.replace("overflow-", "overflow-y-")

    # Readability: flex-shrink:0 → shrink-0 (Tailwind utility)
    if prop == "flex-shrink":
        if value == 0 or str(value) == "0":
            return "shrink-0"
        if value == 1 or str(value) == "1":
            return "shrink"

    # Readability: flex-grow → grow-N
    if prop == "flex-grow":
        if value == 1 or str(value) == "1":
            return "grow"
        if value == 0 or str(value) == "0":
            return "grow-0"

    # Readability: box-shadow arbitrary value
    if prop == "box-shadow" and isinstance(value, str):
        v = value.strip()
        if v and v != "none":
            # Tailwind arbitrary value uses underscores for spaces
            v_tw = v.replace(" ", "_")
            return f"shadow-[{v_tw}]"

    # ── text layout props (kept as inline-style-friendly via arbitrary
    # value syntax). These were previously left in leftover inline style,
    # which is fine — but we map the common ones here for cleaner output. ──
    if prop == "line-height":
        # "Npx" → leading-N (on 4px grid) or leading-[Npx].
        # NEVER emit leading-Npx — Tailwind reads `24px` as a token name, not a
        # value, and the class silently does nothing.
        # Percent/bare-number → arbitrary `leading-[...]`.
        px = _px_value(value)
        if px is not None:
            return _spacing_class(px, "leading")
        return f"leading-[{value}]"
    if prop == "letter-spacing":
        # tracking uses a different spacing scale than p/gap, so we can't
        # reuse _spacing_class. Map on-grid values manually; arbitrary for
        # the rest. Avoid emitting tracking-Npx (same trap as leading-Npx).
        px = _px_value(value)
        if px is not None:
            return _tracking_class(px)
        return f"tracking-[{value}]"
    if prop == "white-space":
        if value == "pre-line":
            return "whitespace-pre-line"
        if value == "nowrap":
            return "whitespace-nowrap"

    if prop == "position":
        if value == "relative":
            return "relative"
        if value == "absolute":
            return "absolute"

    return None


def apply_tailwind(tree: TreeNode) -> None:
    """Walk tree, convert each node's style to className + leftover style.

    Mutates tree in-place: sets tree.props['className'] and trims tree.style.

    Recognized component nodes (``is_component`` with a component tag) are
    skipped: their style stays as an inline ``style={{...}}`` prop. React
    merges a ``style`` prop onto the component's root element, reliably
    overriding the library's own defaults, whereas a tailwind ``className``
    is *appended* and stacks with the component's internal token-driven
    padding/sizing — double padding, off-size buttons, misaligned regions
    below (issue #35). Children of a component are still converted (they are
    plain nodes).

    Pseudo components (``is_component`` but an empty ``tag_name`` — a preset
    with ``component: ''`` that keeps the Figma DOM) render as plain div/img
    with no library default styles, so converting them to className is safe
    and keeps className usage consistent (issue #41).
    """
    stack = [tree]
    while stack:
        n = stack.pop()
        # Skip *real* components (is_component with a tag). Pseudo components
        # (empty tag_name → plain div/img) convert normally.
        if not (n.is_component and n.tag_name) and n.style:
            classes, leftover = style_to_tailwind(n.style)
            if classes:
                # If node has existing className (e.g. from earlier passes),
                # prepend the tailwind classes
                existing = n.props.get("className", "")
                new_class = " ".join(classes)
                if existing:
                    n.props["className"] = f"{existing} {new_class}".strip()
                else:
                    n.props["className"] = new_class
                n.style = leftover
        stack.extend(n.children)
