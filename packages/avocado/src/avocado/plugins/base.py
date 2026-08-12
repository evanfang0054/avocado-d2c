"""Plugin system for avocado.

(per design docs) / design docs

Plugin contract (Python):

    from avocado.plugins import Plugin, hook

    class MyPlugin(Plugin):
        name = "my-plugin"

        @hook("modify_style")
        def add_unit(self, node, style):
 # Add 'px' suffix to all numeric values missing unit
            ...
            return style

Plugins are discovered as Python modules in:
  - ./plugins/*.py (project-local)
  - ~/.avocado/plugins/*.py (user-global)

Each plugin must define a module-level `plugin` function or class:
  - `def plugin() -> Plugin` returning a Plugin instance, OR
  - `class X(Plugin)` where class name is found via subclass scan

Hooks:
  - modify_json_schema(root) -> root          # post-parse tree rewrite
  - modify_props(node, props) -> props        # per-node JSX props
  - modify_style(node, style) -> style        # per-node CSS
  - modify_css_var(vars) -> vars              # CSS variable table
  - generate_template(root, code) -> code     # final JSX string rewrite
  - inspect_draft(root) -> list[dict]         # extra warnings

KISS: plugins are synchronous, single-subscriber (last registered wins
for any hook). Multi-plugin conflict resolution = "user fixes the
plugins".
"""

from __future__ import annotations

import contextlib
import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from avocado.parser.trace import is_enabled, record

# All supported hook names
HOOK_NAMES = frozenset(
    {
        "modify_json_schema",
        "modify_props",
        "modify_style",
        "modify_css_var",
        "generate_template",
        "inspect_draft",
    }
)


# ─── trace helpers (duck-typed on TreeNode shape to avoid import cycle) ──────

# Hooks that process the whole subtree (nodes_affected = subtree size).
# Per-node hooks (modify_style/modify_props/modify_css_var) count exactly 1.
_TREE_LEVEL_HOOKS = frozenset({"modify_json_schema", "generate_template", "inspect_draft"})


def _find_tree_arg(args: tuple):
    """First arg that looks like a tree node (has children)."""
    for a in args:
        if hasattr(a, "children"):
            return a
    return None


def _count_tree_nodes(node) -> int:
    n = 1
    for c in getattr(node, "children", []) or []:
        n += _count_tree_nodes(c)
    return n


def _collect_node_names(node) -> list[str]:
    out = [getattr(node, "name", "") or ""]
    for c in getattr(node, "children", []) or []:
        out.extend(_collect_node_names(c))
    return out


# ─── Plugin base class ────────────────────────────────────────────────────────


class Plugin:
    """Base class for avocado plugins.

    Subclass and decorate methods with @hook("name").

    Attributes:
        name: Human-readable plugin identifier (shown in envelope ``plugins_applied``).
        presets_used: Preset names this plugin loads internally (e.g. a plugin
            that calls ``load_preset("my-lib")`` in a hook should declare
            ``presets_used = ["my-lib"]``). Reported in envelope
            ``plugins_applied[*].presets_used`` so agents can see the real
            preset in use, not just the CLI ``--component-lib`` flag.
            Defaults to empty (plugin doesn't load any preset).
    """

    name: str = "anonymous"
    presets_used: list[str] = []

    def __repr__(self) -> str:
        return f"<Plugin {self.name!r}>"


# decorator to mark methods as hooks
def hook(name: str) -> Callable:
    """Mark a method as a hook handler.

    Usage:
        class MyPlugin(Plugin):
            @hook("modify_style")
            def my_handler(self, node, style):
                ...
                return style
    """
    if name not in HOOK_NAMES:
        raise ValueError(f"unknown hook name {name!r}; valid: {sorted(HOOK_NAMES)}")

    def decorator(fn: Callable) -> Callable:
        fn._avocado_hook = name  # type: ignore[attr-defined]
        return fn

    return decorator


# ─── HookRegistry ────────────────────────────────────────────────────────────


@dataclass
class HookRegistry:
    """Tracks registered plugins and their hook handlers."""

    plugins: list[Plugin] = field(default_factory=list)
    # hook_name → list of bound methods (in registration order)
    _handlers: dict[str, list[Callable]] = field(default_factory=dict)

    def register(self, plugin: Plugin) -> None:
        """Register a plugin instance. Auto-detects @hook methods."""
        self.plugins.append(plugin)
        for attr_name in dir(plugin):
            method = getattr(plugin, attr_name)
            hook_name = getattr(method, "_avocado_hook", None)
            if hook_name:
                self._handlers.setdefault(hook_name, []).append(method)

    def has(self, hook_name: str) -> bool:
        return hook_name in self._handlers and bool(self._handlers[hook_name])

    def call(self, hook_name: str, *args):
        """Call all handlers for hook_name. Each handler receives *args and
        must return the (possibly modified) TARGET argument.

        Convention:
          - modify_* hooks take (node, target) and return the new target.
          - generate_template takes (root, code) and returns new code.
          - inspect_draft takes (root) and returns list[dict].

        For modify_* hooks we update args[1] (the target) with each
        handler's return value before passing to the next.
        """
        if hook_name not in self._handlers:
            # No handlers — return the conventional target.
            if hook_name == "inspect_draft":
                return []
            # modify_* / generate_template: target is args[1] (or args[0] for single-arg)
            return args[1] if len(args) >= 2 else (args[0] if args else None)

        current_args = list(args)
        for handler in self._handlers[hook_name]:
            # Guard stdout during plugin execution. avocado's contract is
            # "stdout is always a single JSON envelope"; a plugin calling
            # print() (e.g. for debugging) would otherwise leak text into
            # stdout and break envelope parsing for agents. Redirect to
            # stderr during the handler call so the envelope stays clean.
            with contextlib.redirect_stdout(sys.stderr):
                result = handler(*current_args)
            # Trace hook execution (--trace-adapter=hook): which plugin ran,
            # how many nodes it touched, sample names. Exception-safe — trace
            # must never break the pipeline.
            if is_enabled("plugin_hooks"):
                try:
                    # Whole-tree hooks process the whole subtree; per-node
                    # hooks (modify_style/modify_props/modify_css_var) touch
                    # exactly one target node (their first arg is that node).
                    if hook_name in _TREE_LEVEL_HOOKS:
                        tree_arg = _find_tree_arg(current_args)
                        node_count = _count_tree_nodes(tree_arg) if tree_arg is not None else 1
                        names = _collect_node_names(tree_arg) if tree_arg is not None else []
                    else:
                        node_count = 1
                        names = []
                    owner = getattr(handler, "__self__", None)
                    plugin_name = getattr(owner, "name", "anonymous")
                    record(
                        "plugin_hooks",
                        {
                            "plugin": plugin_name,
                            "hook": hook_name,
                            "nodes_affected": node_count,
                            "sample_names": sorted(n for n in names if n)[:10],
                        },
                    )
                except Exception:
                    pass  # zero-exception-risk: trace must never break the pipeline
            # For modify_* and generate_template: result is the new target
            if hook_name in {
                "modify_props",
                "modify_style",
                "modify_css_var",
                "generate_template",
                "modify_json_schema",
            }:
                if len(current_args) >= 2:
                    current_args[1] = result
                else:
                    current_args[0] = result
            elif hook_name == "inspect_draft":
                # result is a list — we append, but for simplicity replace
                current_args = [result if isinstance(result, list) else []]
        # Return the final target value
        if hook_name in {
            "modify_props",
            "modify_style",
            "modify_css_var",
            "generate_template",
            "modify_json_schema",
        }:
            return current_args[1] if len(current_args) >= 2 else current_args[0]
        if hook_name == "inspect_draft":
            return current_args[0] if current_args else []
        return current_args[-1] if current_args else None


# ─── Discovery / loading ──────────────────────────────────────────────────────


def discover_plugins(*dirs: Path) -> list[Plugin]:
    """Find all .py files in given dirs and load any plugins they define.

    Args:
        dirs: directories to scan (project-local and/or user-global)

    Returns:
        list of instantiated Plugin subclasses
    """
    plugins: list[Plugin] = []
    for d in dirs:
        if not d.exists() or not d.is_dir():
            continue
        for py_file in sorted(d.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                loaded = _load_plugin_file(py_file)
                if loaded:
                    plugins.extend(loaded)
            except Exception as e:
                # Log to stderr but don't fail the whole pipeline
                import sys

                print(
                    f"warning: failed to load plugin {py_file}: {e}",
                    file=sys.stderr,
                )
    return plugins


def _load_plugin_file(path: Path) -> list[Plugin]:
    """Import a .py file as a module and extract Plugin instances."""
    mod_name = f"_avocado_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        return []
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)

    out: list[Plugin] = []

    # 1. module-level `plugin` function takes precedence (explicit)
    if hasattr(module, "plugin") and callable(module.plugin):
        try:
            result = module.plugin()
            if isinstance(result, Plugin):
                out.append(result)
                return out  # don't double-load via class scan
        except Exception:
            pass

    # 2. any Plugin subclass defined in module (fallback)
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, Plugin) and attr is not Plugin:
            try:
                out.append(attr())
            except Exception:
                pass

    return out


# ─── Helpers ──────────────────────────────────────────────────────────────────


def build_registry(*dirs: Path) -> HookRegistry:
    """Convenience: discover plugins in dirs, return populated registry."""
    reg = HookRegistry()
    for p in discover_plugins(*dirs):
        reg.register(p)
    return reg


def default_plugin_dirs() -> list[Path]:
    """Default plugin search paths."""
    paths = [
        Path.cwd() / "plugins",  # project-local
        Path.home() / ".avocado" / "plugins",  # user-global
    ]
    return paths
