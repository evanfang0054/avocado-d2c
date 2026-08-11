"""Tests for avocado.api.jsx_beautify (pure-Python tree-sitter JSX beautifier)."""

from __future__ import annotations

import subprocess

import pytest

from avocado.api.jsx_beautify import JsxBeautifyError, beautify, is_available


def test_is_available_returns_bool() -> None:
    assert isinstance(is_available(), bool)


def test_beautify_preserves_jsx() -> None:
    out = beautify('<div className="x">hi</div>;')
    assert "<div" in out
    assert "React.createElement" not in out


def test_beautify_indents_nested_jsx() -> None:
    out = beautify("<div><span><strong>x</strong></span></div>;")
    assert "\n" in out


def test_beautify_handles_self_closing() -> None:
    out = beautify('<div><img src="x" /></div>;')
    assert "<img" in out
    assert "/>" in out


def test_beautify_boolean_attributes() -> None:
    # JSX boolean attrs (<Stepper block />, <input disabled>) have no `=value`;
    # they used to crash beautify with `list index out of range`.
    out = beautify("<div><input disabled checked /><Stepper block>x</Stepper></div>;")
    assert "<input disabled checked/>" in out
    assert "<Stepper block>" in out


def test_beautify_style_object_expands_multiline() -> None:
    out = beautify('<div style={{color: "red", fontSize: "14px"}}>x</div>;')
    assert "style={{\n" in out
    assert 'color: "red",' in out
    assert 'fontSize: "14px",' in out


def test_beautify_preserves_quoted_px() -> None:
    out = beautify('<div style={{lineHeight: "24px", opacity: 0.5}}><span>hi</span></div>;')
    assert 'lineHeight: "24px"' in out
    assert "opacity: 0.5" in out
    assert "lineHeight: 24" not in out.replace('"24px"', "")


def test_beautify_trims_text() -> None:
    out = beautify("<div><span>Back </span></div>;")
    assert "Back " not in out  # trailing space trimmed


def test_beautify_drops_whitespace_only_text() -> None:
    out = beautify("<div>\n  <span>x</span>\n</div>;")
    assert out == "<div>\n    <span>x</span>\n</div>;"


def test_beautify_preserves_non_jsx_statements() -> None:
    code = (
        'import React from "react";\nexport default function C() {\n    return (<div>x</div>);\n}'
    )
    out = beautify(code)
    assert 'import React from "react";' in out
    assert "export default function C() {" in out


def test_beautify_multibyte_utf8_keeps_tail() -> None:
    """Regression: tree-sitter byte offsets must not be used as str indices.

    Input containing non-ASCII (Chinese/£ etc.) makes byte offset ≠ char count;
    splicing with byte offsets into a str dropped the trailing `);` and `}` of a
    React component, producing invalid JS that fails Vite build.
    """
    code = (
        'import React from "react";\n'
        "export default function Pay() {\n"
        "  return (\n"
        '      <div style={{color: "#ff0000"}}>\n'
        "          <span>¥100.00 总价</span>\n"
        "      </div>\n"
        "  );\n"
        "}\n"
    )
    out = beautify(code)
    assert out.rstrip().endswith(");\n}")
    assert "总价" in out
    # Exact snapshot: full output must be byte-stable (no tail truncation)
    assert out == (
        'import React from "react";\n'
        "export default function Pay() {\n"
        "  return (\n"
        "      <div style={{\n"
        '          color: "#ff0000",\n'
        "      }}>\n"
        "          <span>¥100.00 总价</span>\n"
        "      </div>\n"
        "  );\n"
        "}\n"
    )


def test_beautify_multibyte_mid_slice() -> None:
    """Two sibling JSX roots, first contains non-ASCII: mid-slice stays aligned.

    Covers the mid-slice path (second node's start_byte sits after multibyte
    content), distinct from the tail-slice regression above.
    """
    code = "<div>¥100 总价</div>;\n<div>second</div>;"
    out = beautify(code)
    assert out.endswith("</div>;")
    assert "总价" in out
    assert "second" in out


def test_beautify_rejects_non_str() -> None:
    with pytest.raises(JsxBeautifyError):
        beautify(None)  # type: ignore[arg-type]
    with pytest.raises(JsxBeautifyError):
        beautify(b"<div/>")  # type: ignore[arg-type]


def test_beautify_rejects_unencodable_surrogate() -> None:
    with pytest.raises(JsxBeautifyError):
        beautify("<div>\ud800</div>")


def test_beautify_caches() -> None:
    code = "<div>x</div>;"
    assert beautify(code) == beautify(code)


def test_beautify_invalid_jsx_raises() -> None:
    with pytest.raises(JsxBeautifyError):
        beautify("<div>")


def test_beautify_empty_input() -> None:
    assert beautify("").strip() == ""


def test_beautify_no_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("must not spawn subprocess")

    monkeypatch.setattr(subprocess, "run", boom)
    beautify("<div>x</div>;")
