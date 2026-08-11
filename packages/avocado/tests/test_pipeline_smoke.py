"""End-to-end test: load real Confirm frame, render, compare structure.

This is a smoke test ensuring the full pipeline runs without errors
on real Figma data, and produces output that includes the features
(Auto Layout → flex, text styling with color/line-height).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avocado.generator.codegen import render_jsx
from avocado.model.scene_node import SceneNode
from avocado.parser.node_mapper import map_node

FIXTURE = Path(__file__).parent / "fixtures" / "02_confirm_frame" / "input.json"


@pytest.fixture(scope="module")
def confirm_output() -> str:
    """Render the real Confirm frame end-to-end."""
    if not FIXTURE.exists():
        pytest.skip("missing fixture")
    data = json.loads(FIXTURE.read_text())
    doc = data["nodes"]["1732:4245"]["document"]
    scene = SceneNode.from_dict(doc)
    tree = map_node(scene)
    return render_jsx(tree)


@pytest.fixture(scope="module")
def confirm_output_react() -> str:
    """Render the Confirm frame in React format"""
    if not FIXTURE.exists():
        pytest.skip("missing fixture")
    data = json.loads(FIXTURE.read_text())
    doc = data["nodes"]["1732:4245"]["document"]
    scene = SceneNode.from_dict(doc)
    tree = map_node(scene)
    return render_jsx(tree, format="react")


def test_pipeline_runs_on_real_data(confirm_output: str) -> None:
    assert len(confirm_output) > 1000
    assert "<div" in confirm_output


def test_root_has_flex_layout(confirm_output: str) -> None:
    """Root Frame should now have display:flex instead of plain div."""
    first_line = confirm_output.split("\n", 1)[0]
    assert "display: flex" in first_line
    assert "flex-direction: column" in first_line


def test_text_nodes_have_color(confirm_output: str) -> None:
    """TEXT spans should include color property (not just background-color)."""
    span_lines = [line for line in confirm_output.split("\n") if "<span" in line]
    assert len(span_lines) > 5
    color_lines = [line for line in span_lines if "color:" in line]
    assert len(color_lines) >= 3


def test_text_nodes_have_line_height(confirm_output: str) -> None:
    """TEXT nodes should include line-height from Figma style.lineHeightPx."""
    span_lines = [line for line in confirm_output.split("\n") if "<span" in line]
    line_height_lines = [line for line in span_lines if "line-height" in line]
    assert len(line_height_lines) >= 1


def test_auto_layout_frames_have_gap(confirm_output: str) -> None:
    """Auto Layout frames with itemSpacing should produce gap."""
    # Confirm root has gap: 48px
    assert "gap: 48px" in confirm_output
    # And various inner gaps
    assert "gap: 24px" in confirm_output or "gap: 8px" in confirm_output


def test_padding_from_auto_layout(confirm_output: str) -> None:
    """Frame padding should become CSS padding shorthand."""
    assert "padding: 64px" in confirm_output  # root 64px padding


def test_flex_grow_for_fill_children(confirm_output: str) -> None:
    """Children with layoutSizingHorizontal=FILL should have flex-grow:1.
    Fix: FILL now uses bbox width as fallback (no longer '100%')."""
    assert "flex-grow: 1" in confirm_output


def test_inspect_warnings_emitted() -> None:
    """Walk tree; the inspect warnings system should be populated for
    at least one frame type. The Confirm fixture is mostly well-formed
    Auto Layout, so warnings may be 0 — that's fine. We just verify
    the inspect field exists and is a list on every node."""
    data = json.loads(FIXTURE.read_text())
    doc = data["nodes"]["1732:4245"]["document"]
    scene = SceneNode.from_dict(doc)
    tree = map_node(scene)
    # Every node should have inspect: list[dict]
    stack = [tree]
    total_nodes = 0
    while stack:
        n = stack.pop()
        assert isinstance(n.inspect, list)
        total_nodes += 1
        stack.extend(n.children)
    assert total_nodes > 10  # sanity check on tree size


def test_no_double_color_on_text(confirm_output: str) -> None:
    """Regression: TEXT spans should not have both background-color and color
    set to the same value (was a bug in early versions)."""
    span_lines = [line for line in confirm_output.split("\n") if "<span" in line]
    for line in span_lines:
        # If both are present with same value, it's the bug
        if "background-color:" in line and "color:" in line:
            # extract both
            import re

            bg = re.search(r"background-color: (\S+)", line)
            col = re.search(r"(?<!background-)color: (\S+)", line)
            if bg and col:
                # same color is suspicious for text nodes
                assert bg.group(1) != col.group(1), f"text span has same bg+color: {line}"


# ── React format ──


def test_react_format_renders_style_object(confirm_output_react: str) -> None:
    """React output should have style={{...}} objects and a function wrapper."""
    assert 'import React from "react"' in confirm_output_react
    assert "export default function" in confirm_output_react
    assert "style={{" in confirm_output_react
    # No HTML-style style attributes
    assert 'style="' not in confirm_output_react


def test_react_format_line_height_is_quoted_string(confirm_output_react: str) -> None:
    """The key fix: lineHeight must be "Npx" string, never a bare number."""
    span_lines = [line for line in confirm_output_react.split("\n") if "<span" in line]
    line_height_lines = [line for line in span_lines if "lineHeight:" in line]
    assert len(line_height_lines) >= 1
    for line in line_height_lines:
        # Must be quoted form
        assert (
            'lineHeight: "24px"' in line
            or 'lineHeight: "22px"' in line
            or 'lineHeight: "34px"' in line
        ), f"unexpected lineHeight form in: {line}"
