"""Tests for plugin system."""

from __future__ import annotations

from pathlib import Path

import pytest

from avocado.model.tree_node import TreeNode
from avocado.plugins.base import (
    HOOK_NAMES,
    HookRegistry,
    Plugin,
    build_registry,
    default_plugin_dirs,
    discover_plugins,
    hook,
)

PLUGINS_DIR = Path(__file__).parent / "fixtures" / "plugins"


# ── Plugin / hook decorator ──


def test_hook_decorator_marks_method() -> None:
    class P(Plugin):
        name = "p"

        @hook("modify_style")
        def m(self, node, style):
            return style

    p = P()
    assert hasattr(p.m, "_avocado_hook")
    assert p.m._avocado_hook == "modify_style"


def test_hook_decorator_rejects_unknown_name() -> None:
    with pytest.raises(ValueError):
        hook("bogus")


def test_hook_names_includes_known() -> None:
    assert "modify_style" in HOOK_NAMES
    assert "modify_props" in HOOK_NAMES
    assert "generate_template" in HOOK_NAMES


# ── HookRegistry ──


def test_registry_register_detects_hooks() -> None:
    class P(Plugin):
        name = "p"

        @hook("modify_style")
        def upper(self, node, style):
            return {k: str(v).upper() for k, v in style.items()}

    reg = HookRegistry()
    reg.register(P())
    assert reg.has("modify_style")
    assert not reg.has("modify_props")


def test_registry_call_chains_handlers() -> None:
    class P1(Plugin):
        name = "p1"

        @hook("modify_style")
        def add_x(self, node, style):
            return {**style, "x": "1"}

    class P2(Plugin):
        name = "p2"

        @hook("modify_style")
        def add_y(self, node, style):
            return {**style, "y": "2"}

    reg = HookRegistry()
    reg.register(P1())
    reg.register(P2())
    node = TreeNode(id="0", name="n", source_type="FRAME")
    result = reg.call("modify_style", node, {"a": "v"})
    assert result == {"a": "v", "x": "1", "y": "2"}


def test_registry_call_no_handlers_returns_input() -> None:
    reg = HookRegistry()
    node = TreeNode(id="0", name="n", source_type="FRAME")
    result = reg.call("modify_style", node, {"a": "b"})
    assert result == {"a": "b"}


# ── Discovery ──


def test_discover_plugins_loads_py_files() -> None:
    plugins = discover_plugins(PLUGINS_DIR)
    # px_unit.py + func_form.py
    assert len(plugins) >= 2
    names = [p.name for p in plugins]
    assert "px-unit-fixer" in names
    assert "tag-prefixer" in names


def test_discover_skips_underscore_files(tmp_path: Path) -> None:
    (tmp_path / "_hidden.py").write_text("# not a plugin")
    plugins = discover_plugins(tmp_path)
    assert plugins == []


def test_discover_handles_missing_dir() -> None:
    plugins = discover_plugins(Path("/nonexistent"))
    assert plugins == []


def test_discover_resilient_to_bad_plugin(tmp_path: Path) -> None:
    """A bad plugin file should not crash the whole discovery."""
    (tmp_path / "bad.py").write_text("raise RuntimeError('boom')")
    # Should not raise
    plugins = discover_plugins(tmp_path)
    assert plugins == []


def test_func_form_plugin_loads() -> None:
    """A module with def plugin(): return Plugin() works."""
    plugins = discover_plugins(PLUGINS_DIR)
    func_plugins = [p for p in plugins if p.name == "tag-prefixer"]
    assert len(func_plugins) == 1


def test_class_form_plugin_loads() -> None:
    """A module with class X(Plugin) works."""
    plugins = discover_plugins(PLUGINS_DIR)
    class_plugins = [p for p in plugins if p.name == "px-unit-fixer"]
    assert len(class_plugins) == 1


# ── build_registry ──


def test_build_registry_combines_dirs() -> None:
    reg = build_registry(PLUGINS_DIR)
    assert len(reg.plugins) >= 2
    assert reg.has("modify_style")  # px_unit has it


def test_px_unit_plugin_actually_fixes_units() -> None:
    """Real plugin: bare int 100 → '100px' for width."""
    reg = build_registry(PLUGINS_DIR)
    node = TreeNode(id="0", name="n", source_type="RECTANGLE", style={"width": 100, "color": "red"})
    result = reg.call("modify_style", node, dict(node.style))
    # width should now have px suffix
    assert result["width"] == "100px"
    # color should be unchanged (not in dimensional props)
    assert result["color"] == "red"


def test_default_plugin_dirs_returns_two() -> None:
    paths = default_plugin_dirs()
    assert len(paths) == 2
    # cwd/plugins + ~/.avocado/plugins
    assert any(p.name == "plugins" for p in paths)
