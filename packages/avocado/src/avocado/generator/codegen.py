"""JSX codegen: TreeNode tree → JSX string.

Uses pure-Python codegen (per design docs in design docs). Will add
optional JSX beautify via api.jsx_beautify (tree-sitter).

Output format:
  - Void tags (img/input/br/etc.) self-close with `/>` (or just `>`).
  - Non-void tags with no children use explicit open+close: `<div ...></div>`.
    This is critical: HTML5 parsers ignore `<div ... />` (the `/` is treated
    as a stray char) and the div stays open, mangling the DOM tree. JSX
    allows self-close on any tag, but we output HTML/JSX-as-HTML for browser
    preview, so we must use HTML5-valid syntax.
  - Style: HTML mode emits `style="..."`; React mode emits `style={{...}}`.
  - Children indented 2 spaces
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from avocado.generator.css import render_inline_style
from avocado.generator.react_style import render_react_style
from avocado.model.tree_node import TreeNode

# HTML void elements — content forbidden, no end tag.
# https://html.spec.whatwg.org/multipage/syntax.html#void-elements
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

# Type alias for the style-renderer strategy.
StyleRenderer = Callable[[TreeNode], str]


def render_jsx(
    root: TreeNode,
    indent: int = 2,
    *,
    format: Literal["html", "react", "vue"] = "html",
    css: Literal["inline", "tailwind", "class"] = "inline",
    component_name: str | None = None,
    box_sizing: str | None = None,
    emit_figma_id: bool = False,
) -> str:
    """Render a TreeNode tree as a JSX string.

    Args:
        root: root TreeNode
        indent: spaces per level (default 2)
        format: 'html' (default, HTML fragment with style="...") or 'react'
            (full ES module with `export default function` wrapper + style={{}}).
            'vue' is reserved for future use and raises NotImplementedError.
        css: CSS form — purely informational at this layer (Tailwind className
            is applied upstream in cli.py via apply_tailwind). Kept as a
            parameter so callers can pin the form for future codegen variants.
        component_name: React mode only. Component name for the
            `export default function Xxx()` wrapper. When None, derived from
            the root node's name.
        box_sizing: emit a leading `<style>*{box-sizing:<value>}</style>` so
            the output is self-contained for browser preview. Default
            'content-box' preserves original behavior.
        emit_figma_id: FIX:. When True (default), emit data-figma-id
            attribute for traceability. Set False for clean delivery output.

    The default `format='html'` preserves original behavior: all existing
    tests calling `render_jsx(tree)` without explicit format continue to work.
    """
    if format == "vue":
        raise NotImplementedError("vue format not implemented yet")

    # Choose style renderer per format.
    if format == "react":
        style_renderer: StyleRenderer = render_react_style
    else:
        style_renderer = render_inline_style

    imports = _collect_imports(root)
    lines = _render_node(
        root,
        level=0,
        indent=indent,
        style_renderer=style_renderer,
        react=(format == "react"),
        emit_figma_id=emit_figma_id,
    )
    body = "\n".join(lines) + "\n"

    # Box-sizing reset: a single <style> tag prepended to the output so the
    # browser-preview path renders with the intended box model.
    # React/JSX mode requires the CSS body wrapped in a string expression
    # `{"..."}` — otherwise `{box-sizing:...}` is parsed as a JSX expression
    # container and the JSX parser chokes on the bare `:` inside.
    if box_sizing:
        css_text = f"*{{box-sizing:{box_sizing}}}"
        if format == "react":
            box_sizing_tag = f'<style>{{"{css_text}"}}</style>'
        else:
            box_sizing_tag = f"<style>{css_text}</style>"
    else:
        box_sizing_tag = ""

    if format == "react":
        name = component_name or _to_component_name(root.name)
        return _wrap_react_component(
            body,
            component_name=name,
            imports=imports,
            box_sizing_tag=box_sizing_tag,
        )

    # html path (default): preserve original behavior
    prefix = ""
    if box_sizing_tag:
        prefix = box_sizing_tag + "\n"
    if imports:
        return prefix + imports + "\n" + body
    return prefix + body


def _collect_imports(root: TreeNode) -> str:
    """Walk tree, collect (component, package) pairs, emit import lines.

    One import line per package, grouping all components from that package.
    Components without a package are skipped (no import to emit).
    """
    by_pkg: dict[str, set[str]] = {}
    stack = [root]
    while stack:
        n = stack.pop()
        if n.is_component and n.component_package and n.tag_name:
            by_pkg.setdefault(n.component_package, set()).add(n.tag_name)
        stack.extend(n.children)
    if not by_pkg:
        return ""
    out = []
    for pkg in sorted(by_pkg):
        comps = sorted(by_pkg[pkg])
        out.append(f'import {{ {", ".join(comps)} }} from "{pkg}";')
    return "\n".join(out)


def _wrap_react_component(
    body: str,
    *,
    component_name: str,
    imports: str,
    box_sizing_tag: str = "",
) -> str:
    """Wrap JSX body as a default-export React function component.

    Layout:
      import React from "react";
      <business component imports if any>

      export default function Xxx() {
        return (
          [<box-sizing style>,]<body>
        );
      }
    """
    header_lines = ['import React from "react";']
    if imports:
        header_lines.append(imports)
    header = "\n".join(header_lines)
    # Indent body by 6 spaces (function body return paren depth):
    # export default function Xxx {
    # return (
    # <div ...> ← body indented +6 from col 0 (function body +2, return paren +4)
    # ...
    # </div>
    # );
    # }
    indented_body = "\n".join(
        "      " + line if line else line for line in body.rstrip("\n").split("\n")
    )
    inner = ""
    if box_sizing_tag:
        indented_bs = "      " + box_sizing_tag
        # box-sizing <style> + body root = 2+ adjacent JSX elements. React
        # requires a single root, so wrap in a Fragment. (body itself is a
        # single root — the TreeNode tree maps to one top-level div.)
        inner = f"      <>\n{indented_bs}\n{indented_body}\n      </>"
    else:
        inner = indented_body
    return (
        f"{header}\n\n"
        f"export default function {component_name}() {{\n"
        f"  return (\n"
        f"{inner}\n"
        f"  );\n"
        f"}}\n"
    )


# Separator chars that may appear in Figma node names.
_NAME_SPLIT_RE = re.compile(r"[\s\-_:/]+")


def _to_component_name(name: str) -> str:
    """Convert a Figma node name to a valid PascalCase React component name.

    Rules:
      1. Split on whitespace / hyphen / underscore / colon / slash.
      2. PascalCase each segment and concatenate.
      3. Strip any remaining non [A-Za-z0-9_] characters.
      4. If the result starts with a digit, prefix with `F` (JS identifier rule).
      5. Truncate to 60 chars.
      6. Empty/invalid → fallback `FigmaNode`.
    """
    if not name:
        return "FigmaNode"
    # Capitalize first char of each segment, preserve the rest as-is.
    # (Using str.capitalize would lowercase the rest, breaking camelCase
    # names like "MyComponent" → "Mycomponent".)
    parts = []
    for p in _NAME_SPLIT_RE.split(name):
        if p:
            parts.append(p[0].upper() + p[1:])
    raw = "".join(parts)
    # Drop any chars that aren't valid in a JS identifier
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", raw)
    if not cleaned:
        return "FigmaNode"
    if cleaned[0].isdigit():
        cleaned = "F" + cleaned
    if len(cleaned) > 60:
        cleaned = cleaned[:60]
    return cleaned


def _render_node(
    node: TreeNode,
    level: int,
    indent: int,
    *,
    style_renderer: StyleRenderer = render_inline_style,
    react: bool = False,
    emit_figma_id: bool = False,
) -> list[str]:
    pad = " " * (level * indent)
    next_pad = " " * ((level + 1) * indent)

    tag = (
        node.tag_name or "div"
    )  # empty tag_name falls back to div (avoids invalid JSX like `< className>`)

    # Build attrs
    attrs: list[str] = []
    # FIX: in HTML mode className → class (browsers only understand class; the Tailwind CDN relies entirely on this)
    # React mode keeps className (React component convention)
    props_copy = dict(node.props)
    if not react and "className" in props_copy:
        props_copy["class"] = props_copy.pop("className")
    # FIX: img tags must have an alt attribute (WCAG a11y standard).
    # FIX: content images use the figma layer name as alt (not always "").
    # Decorative images (icon / VECTOR / small images) use "" (WCAG 1.1.1 allows empty alt for decorative images).
    # Content images (name contains cover/photo/avatar/image/pic/banner/card, etc.) use the name.
    if tag == "img" and "alt" not in props_copy:
        node_name = (getattr(node, "name", "") or "").strip()
        nm_lower = node_name.lower()
        # Decorative-image keywords (icon / arrow / divider / spacer / shape / vector / bg /
        # path / cap / line — FIX: added path/cap/line icon sub-shapes)
        _decorative_kw = (
            "icon",
            "arrow",
            "divider",
            "spacer",
            "shape",
            "vector",
            "bg",
            "background",
            "shadow",
            "overlay",
            "mask",
            "border",
            "path",
            "cap",
            "line",
        )
        # Content-image keywords (cover/photo/avatar/image/pic/banner/card/hero/logo/product)
        _content_kw = (
            "cover",
            "photo",
            "avatar",
            "image",
            "pic",
            "picture",
            "banner",
            "card",
            "hero",
            "logo",
            "product",
            "illustration",
            "thumbnail",
            "preview",
            "portrait",
        )
        # FIX: when the node name as a whole (strip+lower) is exactly a
        # generic content word, degrade. If the Figma layer name is literally
        # "image", alt="image" is meaningless; use "image" as a placeholder
        # description (not the raw value) — same for pic/picture.
        _generic_content_words = {"image", "pic", "picture", "photo"}
        _name_lower_stripped = nm_lower.strip()
        if _name_lower_stripped in _generic_content_words:
            # Generic word as the whole name: use the description word as alt (don't echo the raw value)
            props_copy["alt"] = _name_lower_stripped
        elif any(kw in nm_lower for kw in _content_kw):
            # Content image: use the (cleaned) layer name as alt
            _alt = re.sub(r"\s+", " ", node_name)[:200] if node_name else "image"
            props_copy["alt"] = _alt
        elif any(kw in nm_lower for kw in _decorative_kw) or not node_name:
            # Decorative image / no name: empty alt (allowed by WCAG)
            props_copy["alt"] = ""
        else:
            # Has a name but can't clearly classify content/decorative: use the name as alt (better to describe more than to miss)
            props_copy["alt"] = re.sub(r"\s+", " ", node_name)[:200]
    # Props (component-specific) first
    for k, v in _sorted_props(props_copy).items():
        if isinstance(v, bool) and v:
            # Bare boolean attribute: `block` (not `block=` — invalid JSX).
            attrs.append(f"{k}")
        else:
            attrs.append(f"{k}={_format_attr_value(v)}")
    # Style — rendered via the chosen strategy (HTML style attr vs React object)
    style_str = style_renderer(node)
    if style_str:
        attrs.append(style_str)
    # data-figma-id for traceability (: can be disabled via emit_figma_id=False)
    if emit_figma_id and node.figma_id:
        attrs.append(f'data-figma-id="{node.figma_id}"')

    open_tag = f"{pad}<{tag}"
    if attrs:
        open_tag += " " + " ".join(attrs)

    # Self-closing if no children and no text
    if not node.children and not node.text_content:
        if tag in _VOID_TAGS:
            # img/input/etc — true self-close
            return [f"{open_tag} />"]
        # Non-void tag with no content: explicit open+close
        # (HTML5 ignores <div /> as a self-close; JSX would allow it but
        # our output is parsed as HTML by browsers during preview).
        return [f"{open_tag}></{tag}>"]

    # Text-only leaf node
    if not node.children and node.text_content:
        text = _escape_text(node.text_content, react=react)
        return [f"{open_tag}>{text}</{tag}>"]

    # Has children
    out = [f"{open_tag}>"]
    if node.text_content:
        text = _escape_text(node.text_content, react=react).strip()
        if text:
            out.append(f"{next_pad}{text}")
    for child in node.children:
        out.extend(
            _render_node(
                child,
                level + 1,
                indent,
                style_renderer=style_renderer,
                react=react,
                emit_figma_id=emit_figma_id,
            )
        )
    out.append(f"{pad}</{tag}>")
    return out


def _sorted_props(props: dict) -> dict:
    # className/class first, then alphabetical
    # : in HTML mode className is already converted to class; both need priority sorting
    first_key = None
    if "className" in props:
        first_key = "className"
    elif "class" in props:
        first_key = "class"
    if first_key:
        rest = {k: v for k, v in props.items() if k != first_key}
        sorted_rest = dict(sorted(rest.items()))
        return {first_key: props[first_key], **sorted_rest}
    return dict(sorted(props.items()))


def _format_attr_value(v) -> str:
    """Format an attribute value for JSX."""
    if isinstance(v, bool):
        return "" if v else "{false}"  # D2C-style: omit value for true
    if isinstance(v, (int, float)):
        return f"{{{v}}}"
    if isinstance(v, str):
        # Simple string literal
        if '"' in v:
            return f"{{'{v}'}}"
        return f'"{v}"'
    # dict/list → JSON-like
    return "{" + str(v) + "}"


def _escape_text(s: str, *, react: bool = False) -> str:
    """Escape text content for JSX/HTML.

    HTML mode uses entities (&lt; &gt; &amp;) — browsers render them.
    React mode must use JSX string expressions for `<`/`>` because a JSX
    beautify/parser round-trip would read entities back as raw `<`/`>`
    (invalid JSX text; `<App name>` would be parsed as a JSX element).
    `{"<"}` survives the beautify round-trip verbatim.
    `&amp;` is fine in both — the beautifier restores it to `&` which is
    valid JSX text.
    """
    if not react:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # React: `<`/`>` → JSX string expressions; `&` left as-is (beautify-safe, and
    # `&` is legal in JSX text).
    out: list[str] = []
    for ch in s:
        if ch == "<":
            out.append('{"<"}')
        elif ch == ">":
            out.append('{">"}')
        elif ch == "&":
            out.append("&amp;")  # beautify round-trip restores it to & (valid JSX text)
        else:
            out.append(ch)
    return "".join(out)
