"""Execution stages for plugin hooks.

``plugins/base.py`` documents six hooks, but until now only two had a call
site (``modify_json_schema`` and ``modify_style``). The other four were
registered and trace-counted but never invoked, so a plugin implementing
them silently did nothing. Each stage below is a thin, testable wrapper:

- ``apply_node_hooks``     — per-node ``modify_style`` then ``modify_props``
- ``apply_css_var_hook``   — ``modify_css_var`` over the collected table
- ``apply_template_hook``  — ``generate_template`` over the final JSX string
- ``collect_draft_warnings`` — ``inspect_draft`` → inspect warnings

Keeping them here (rather than inline in cli.py) makes the wiring unit
testable; ``tests/test_plugins.py::test_every_hook_has_a_call_site`` guards
against a hook silently going dead again.
"""

from __future__ import annotations

from avocado.model.tree_node import TreeNode
from avocado.plugins.base import HookRegistry


def apply_node_hooks(registry: HookRegistry, tree: TreeNode) -> None:
    """Run per-node hooks over the whole tree: ``modify_style`` → ``modify_props``.

    One traversal serves both hooks. Style runs first so ``modify_props`` can
    read the final CSS (e.g. derive a prop from a resolved style value).
    A handler returning a non-dict is ignored rather than corrupting the node.
    """
    has_style = registry.has("modify_style")
    has_props = registry.has("modify_props")
    if not (has_style or has_props):
        return
    stack = [tree]
    while stack:
        n = stack.pop()
        if has_style:
            new_style = registry.call("modify_style", n, dict(n.style))
            if isinstance(new_style, dict):
                n.style = new_style
        if has_props:
            new_props = registry.call("modify_props", n, dict(n.props))
            if isinstance(new_props, dict):
                n.props = new_props
        stack.extend(n.children)


def apply_css_var_hook(registry: HookRegistry, variables: dict) -> dict:
    """Let ``modify_css_var`` rewrite the collected variable table."""
    if not registry.has("modify_css_var"):
        return variables
    new_vars = registry.call("modify_css_var", dict(variables))
    return new_vars if isinstance(new_vars, dict) else variables


def apply_template_hook(registry: HookRegistry, tree: TreeNode, code: str) -> str:
    """Let ``generate_template`` rewrite the final JSX/HTML string."""
    if not registry.has("generate_template"):
        return code
    new_code = registry.call("generate_template", tree, code)
    return new_code if isinstance(new_code, str) else code


def collect_draft_warnings(registry: HookRegistry, tree: TreeNode) -> None:
    """Merge ``inspect_draft`` results into the root node's inspect list.

    Entries follow the inspect-rule shape (``severity`` / ``code`` /
    ``message`` / optional ``suggestion``). Malformed entries are skipped —
    a plugin must never be able to break the envelope.
    """
    if not registry.has("inspect_draft"):
        return
    entries = registry.call("inspect_draft", tree)
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        message = entry.get("message")
        if not message:
            continue
        tree.add_inspect(
            severity=str(entry.get("severity", "info")),
            code=str(entry.get("code", "plugin-inspect")),
            message=str(message),
            suggestion=entry.get("suggestion"),
        )
