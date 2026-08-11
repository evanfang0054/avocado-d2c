"""E2E: tree-sitter JSX beautifier integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avocado.api.jsx_beautify import JsxBeautifyError, beautify
from avocado.generator.codegen import render_jsx
from avocado.model.scene_node import SceneNode
from avocado.parser.node_mapper import map_node

FIXTURE = Path(__file__).parent / "fixtures" / "02_confirm_frame" / "input.json"


@pytest.fixture(scope="module")
def raw_jsx() -> str:
    data = json.loads(FIXTURE.read_text())
    doc = data["nodes"]["1732:4245"]["document"]
    scene = SceneNode.from_dict(doc)
    tree = map_node(scene, client=None, file_key="FIGMA_FILE_KEY_PLACEHOLDER_001")
    return render_jsx(tree)


@pytest.fixture(scope="module")
def raw_react_jsx() -> str:
    data = json.loads(FIXTURE.read_text())
    doc = data["nodes"]["1732:4245"]["document"]
    scene = SceneNode.from_dict(doc)
    tree = map_node(scene, client=None, file_key="FIGMA_FILE_KEY_PLACEHOLDER_001")
    return render_jsx(tree, format="react")


def test_beautify_runs_on_real_output(raw_jsx: str) -> None:
    out = beautify(raw_jsx.rstrip() + ";")
    assert "<div" in out
    assert "</div>" in out


def test_beautify_output_preserves_structure(raw_jsx: str) -> None:
    out = beautify(raw_jsx.rstrip() + ";")
    assert raw_jsx.count("<div") == out.count("<div")
    assert raw_jsx.count("<img") == out.count("<img")


def test_beautify_output_preserves_src_urls(raw_jsx: str) -> None:
    import re

    out = beautify(raw_jsx.rstrip() + ";")
    url_re = re.compile(r'src="(https://[^"]+)"')
    in_urls = set(url_re.findall(raw_jsx))
    out_urls = set(url_re.findall(out))
    assert in_urls == out_urls, f"URL mismatch: {in_urls ^ out_urls}"


def test_beautify_preserves_data_figma_id(raw_jsx: str) -> None:
    out = beautify(raw_jsx.rstrip() + ";")
    assert raw_jsx.count("data-figma-id=") == out.count("data-figma-id=")


def test_beautify_runs_on_react_output(raw_react_jsx: str) -> None:
    out = beautify(raw_react_jsx.rstrip())
    assert 'import React from "react"' in out
    assert "export default function Confirm()" in out
    assert "style={{" in out
    assert out.count("<div") == raw_react_jsx.count("<div")


def test_react_snapshot_matches(raw_react_jsx: str) -> None:
    """Golden snapshot for React raw (unbeautified) output."""
    snapshot = (
        Path(__file__).parent / "fixtures" / "02_confirm_frame" / "expected_react_beautified.jsx"
    )
    assert snapshot.exists()
    assert raw_react_jsx == snapshot.read_text()


def test_react_beautified_snapshot_matches(raw_react_jsx: str) -> None:
    """Golden snapshot for React + beautify output (new prettier-style)."""
    beautified = beautify(raw_react_jsx.rstrip()) + "\n"
    snapshot = Path(__file__).parent / "fixtures" / "02_confirm_frame" / "expected_react.jsx"
    assert snapshot.exists(), "regenerate golden via regenerate"
    assert beautified == snapshot.read_text()


def test_invalid_input_degrades() -> None:
    """JsxBeautifyError is raised (cli degrades to raw + warning)."""
    with pytest.raises(JsxBeautifyError):
        beautify("<div>")
