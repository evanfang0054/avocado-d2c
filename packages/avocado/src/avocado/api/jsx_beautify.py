"""Pure-Python JSX beautifier built on tree-sitter-javascript.

Prettier-style re-indentation of JSX subtrees via AST slice replacement:
- parse with tree-sitter
- collect top-level JSX nodes (do not descend into collected ones)
- reprint each JSX subtree (style objects expanded, children indented +4)
- splice reprints back into the original source by byte offsets

Non-JSX statements (import/export/function skeleton) are preserved verbatim.
"""

from __future__ import annotations

import functools

import tree_sitter_javascript as _tsjs
from tree_sitter import Language, Parser

_JSX_NODES = {"jsx_element", "jsx_self_closing_element", "jsx_fragment"}
_INDENT = "    "
_LANGUAGE = Language(_tsjs.language())


class JsxBeautifyError(Exception):
    """JSX beautify failure (parse error or invalid input)."""


def beautify(code: str) -> str:
    """Beautify JSX code with prettier-style indentation.

    Raises:
        JsxBeautifyError: on parse error or non-str input.
    """
    if not isinstance(code, str):
        raise JsxBeautifyError(f"expected str input, got {type(code).__name__}")
    return _beautify_cached(code)


@functools.lru_cache(maxsize=256)
def _beautify_cached(code: str) -> str:
    # tree-sitter offsets are BYTE offsets; with multi-byte UTF-8 input
    # (Chinese/£ etc.) the byte count ≠ character count, so slicing str
    # directly by byte offsets would misalign/truncate. Therefore the whole
    # splice is done on bytes and decoded once at the end.
    try:
        code_bytes = code.encode()
    except UnicodeEncodeError as e:
        raise JsxBeautifyError(f"input cannot be encoded as UTF-8: {e}") from e
    parser = Parser(_LANGUAGE)
    tree = parser.parse(code_bytes)
    if tree.root_node.has_error:
        raise JsxBeautifyError("input is not valid JS/JSX")

    replacements: list[tuple[int, int, bytes]] = []
    for node in _top_jsx(tree.root_node):
        out: list[str] = []
        _reprint(node, 0, out)
        text = _indent_following_lines("\n".join(out), _line_leading_spaces(code_bytes, node))
        replacements.append((node.start_byte, node.end_byte, text.encode()))

    if not replacements:
        return code

    result: list[bytes] = []
    pos = 0
    for start, end, text in sorted(replacements):
        result.append(code_bytes[pos:start])
        result.append(text)
        pos = end
    result.append(code_bytes[pos:])
    return b"".join(result).decode()


def is_available() -> bool:
    """tree-sitter is a hard dependency; True once import succeeded."""
    return True


# ─── internals ────────────────────────────────────────────────────────────────


def _line_leading_spaces(code_bytes: bytes, node) -> int:
    """Leading spaces of the line the node starts on (its base indent).

    Takes bytes + a BYTE offset (node.start_byte) to avoid str
    character-index misalignment.
    """
    line_start = code_bytes.rfind(b"\n", 0, node.start_byte) + 1
    n = 0
    while line_start + n < len(code_bytes) and code_bytes[line_start + n] == b" "[0]:
        n += 1
    return n


def _indent_following_lines(text: str, base: int) -> str:
    """Indent all lines after the first by `base` spaces (first stays inline)."""
    if base == 0 or "\n" not in text:
        return text
    lines = text.split("\n")
    pad = " " * base
    return lines[0] + "\n" + "\n".join(pad + line if line else line for line in lines[1:])


def _top_jsx(node):
    """Collect non-nested top-level JSX nodes."""
    if node.type in _JSX_NODES:
        return [node]
    result = []
    for child in node.children:
        result.extend(_top_jsx(child))
    return result


def _split_top_level(s: str) -> list[str]:
    """Split on top-level commas (depth-aware, string-aware)."""
    parts: list[str] = []
    depth = 0
    current = ""
    in_str: str | None = None
    for ch in s:
        if in_str is not None:
            current += ch
            if ch == in_str:
                in_str = None
            continue
        if ch in "\"'":
            in_str = ch
            current += ch
            continue
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def _fmt_attr_value(node, indent: int) -> str:
    """Format a jsx_attribute value: object literal → multi-line, else verbatim."""
    if node.type == "jsx_expression":
        inner = node.text.decode()[1:-1].strip()
        if inner.startswith("{") and inner.endswith("}"):
            pairs = _split_top_level(inner[1:-1])
            pad_in = _INDENT * (indent + 1)
            pad_close = _INDENT * indent
            body = "\n".join(f"{pad_in}{p}," for p in pairs if p)
            return "{{\n" + body + "\n" + pad_close + "}}"
        return "{" + inner + "}"
    return node.text.decode()


def _fmt_attr(attr_node, indent: int) -> str:
    """Format a jsx_attribute: `name=value`, or bare boolean attr (`<input disabled>`)."""
    name = attr_node.children[0].text.decode()
    if len(attr_node.children) < 3:  # boolean attribute: no `=` + value
        return name
    return f"{name}={_fmt_attr_value(attr_node.children[2], indent)}"


def _fmt_open(node, indent: int) -> str:
    """Format jsx_opening_element: `<div style={{...}}>` (attrs expanded).

    A Fragment shorthand opening tag `< >` (tree-sitter models `<>...</>` as
    a jsx_element whose opening element is just `<` + `>`) must be reprinted
    as `<>` — treating the bare `>` as a tag name would emit the invalid
    `<>>`. Regression found in #30 (React mode white-screen).
    """
    if len(node.children) == 2 and node.children[0].text == b"<" and node.children[1].text == b">":
        return "<>"
    tag = node.children[1].text.decode()  # children[0] is '<', [1] is the tag name
    attrs = [c for c in node.children if c.type == "jsx_attribute"]
    if not attrs:
        return f"<{tag}>"
    parts = [_fmt_attr(a, indent) for a in attrs]
    return f"<{tag} " + " ".join(parts) + ">"


def _reprint(node, indent: int, out: list[str]) -> None:
    pad = _INDENT * indent
    if node.type == "jsx_element":
        open_node, close_node = node.children[0], node.children[-1]
        kids = node.children[1:-1]
        # Empty element (or whitespace-only text): keep single line `<div></div>`
        if not kids or all(k.type == "jsx_text" and not k.text.decode().strip() for k in kids):
            out.append(pad + _fmt_open(open_node, indent) + close_node.text.decode())
            return
        # Single text child: keep single line `<span>text</span>` (prettier-style)
        non_blank = [k for k in kids if not (k.type == "jsx_text" and not k.text.decode().strip())]
        if len(non_blank) == 1 and non_blank[0].type == "jsx_text":
            text = non_blank[0].text.decode().strip()
            out.append(pad + _fmt_open(open_node, indent) + text + close_node.text.decode())
            return
        out.append(pad + _fmt_open(open_node, indent))
        for kid in kids:
            _reprint(kid, indent + 1, out)
        out.append(pad + close_node.text.decode())
    elif node.type == "jsx_self_closing_element":
        tag = node.children[1].text.decode()
        attrs = [c for c in node.children if c.type == "jsx_attribute"]
        if not attrs:
            out.append(pad + f"<{tag}/>")
        else:
            parts = [_fmt_attr(a, indent) for a in attrs]
            out.append(pad + f"<{tag} " + " ".join(parts) + "/>")
    elif node.type == "jsx_fragment":
        kids = [
            c
            for c in node.children
            if c.type not in ("jsx_opening_fragment", "jsx_closing_fragment")
        ]
        out.append(pad + "<>")
        for kid in kids:
            _reprint(kid, indent + 1, out)
        out.append(pad + "</>")
    elif node.type == "jsx_text":
        text = node.text.decode().strip()
        if text:
            out.append(pad + text)
    elif node.type == "jsx_expression":
        out.append(pad + node.text.decode())
    else:
        out.append(pad + node.text.decode())
