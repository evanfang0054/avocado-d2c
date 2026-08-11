"""Tests for var_map loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

from avocado.parser.var_map import load_var_map


def test_load_var_map_returns_empty_when_none() -> None:
    assert load_var_map(None) == {}


def test_load_var_map_returns_empty_when_missing(tmp_path: Path) -> None:
    assert load_var_map(tmp_path / "nonexistent.yaml") == {}


def test_load_var_map_parses_yaml(tmp_path: Path) -> None:
    f = tmp_path / "m.yaml"
    f.write_text(
        textwrap.dedent("""
        "VariableID:abc/1:1": color-bg-primary
        "VariableID:abc/1:2": spacing-md
    """).strip()
    )
    out = load_var_map(f)
    assert out == {
        "VariableID:abc/1:1": "color-bg-primary",
        "VariableID:abc/1:2": "spacing-md",
    }


def test_load_var_map_skips_invalid_key(tmp_path: Path) -> None:
    """Non-VariableID keys are silently skipped."""
    f = tmp_path / "m.yaml"
    f.write_text(
        textwrap.dedent("""
        "NotAVarID:1": foo
        "VariableID:abc/1:2": valid-name
        "random-string": bar
    """).strip()
    )
    out = load_var_map(f)
    assert out == {"VariableID:abc/1:2": "valid-name"}


def test_load_var_map_skips_invalid_value(tmp_path: Path) -> None:
    """Invalid CSS identifier values are skipped."""
    f = tmp_path / "m.yaml"
    f.write_text(
        textwrap.dedent("""
        "VariableID:abc/1:1": "has space"
        "VariableID:abc/1:2": "123numeric"
        "VariableID:abc/1:3": valid-name
    """).strip()
    )
    out = load_var_map(f)
    assert out == {"VariableID:abc/1:3": "valid-name"}
