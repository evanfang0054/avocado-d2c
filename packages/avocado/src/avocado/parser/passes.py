"""Shared tree-rewrite stage list.

The parse pipeline is order-sensitive (see ``CLAUDE.md`` "optimize pass 顺序").
It used to live inline in ``cli.main``; multi-frame (``--responsive``) builds
several trees per run and must apply *exactly* the same passes, so the order
now has a single definition here.

Order matters:
  1. auto_group_variance — orient ambiguous containers first so subsequent
     structural passes see a stable flex direction.
  2. inherit_promote — lift common inherited props before strip_defaults
     touches them.
  3. strip_defaults — drop defaults now that inherit-promote has consolidated
     values.
  4. modify_json_schema (plugin) — run BEFORE unwrap_single_child. unwrap
     merges single-child wrappers into their child; if the wrapper's layer
     name matches a preset component (e.g. "Body" → <Text>), unwrapping it
     would delete a component the plugin would have recognized. Marking
     components first lets unwrap's is_component guard keep them.
  5. unwrap_single_child — collapse wrappers after style is settled.
  6. gap_to_margin — last; depends on final flex-direction.
  7. semantic_tags — only rewrites tag_name, never style/layout, so it runs
     after everything else. Zero visual impact, improves SEO/a11y.
  8. per-node plugin hooks (modify_style → modify_props).
"""

from __future__ import annotations

from avocado.model.tree_node import TreeNode
from avocado.parser.optimize import (
    apply_auto_group_variance,
    apply_semantic_tags,
    gap_to_margin,
    promote_inherited_styles,
    strip_default_styles,
    unwrap_single_child,
)
from avocado.plugins.base import HookRegistry
from avocado.plugins.stages import apply_node_hooks


def apply_parse_passes(
    tree: TreeNode,
    *,
    registry: HookRegistry,
    css_form: str = "tailwind",
    auto_group_variance: bool = False,
    inherit_promote: bool = True,
    strip_defaults: bool = True,
    unwrap_single: bool = True,
    gap_to_margin_enabled: bool = False,
) -> TreeNode:
    """Run the shared pre-output passes. Returns the (possibly new) root."""
    if auto_group_variance:
        apply_auto_group_variance(tree)
    if inherit_promote:
        promote_inherited_styles(tree)
    if strip_defaults:
        strip_default_styles(tree)
    if registry.has("modify_json_schema"):
        tree = registry.call("modify_json_schema", None, tree)
    if unwrap_single:
        tree = unwrap_single_child(tree)
    if gap_to_margin_enabled:
        gap_to_margin(tree)
    apply_semantic_tags(tree, css_form=css_form)
    apply_node_hooks(registry, tree)
    return tree
