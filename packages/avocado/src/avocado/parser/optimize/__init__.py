"""Optimization passes — post-parse style/structure cleanup.

Each pass is a small, focused function. The CLI wires them in a fixed
order (see cli.py); they may also be called individually.

Passes:
  - promote_inherited_styles  : lift common inheritable props to parent
  - strip_default_styles      : drop spec-default CSS values
  - unwrap_single_child       : collapse single-child FRAME/GROUP wrappers
  - gap_to_margin             : replace flex gap with per-child margins
  - reround_styles            : re-round numeric CSS to target precision
  - apply_auto_group_variance : orient auto_group nodes via variance
  - apply_semantic_tags       : rewrite tag_name for landmark nodes
                                (header/nav/main/footer/aside/article/section)
"""

from avocado.parser.optimize.auto_group_variance import apply_auto_group_variance
from avocado.parser.optimize.gap_to_margin import gap_to_margin
from avocado.parser.optimize.inherit_promote import promote_inherited_styles
from avocado.parser.optimize.reround import reround_class_map, reround_styles
from avocado.parser.optimize.semantic_tags import apply_semantic_tags
from avocado.parser.optimize.strip_defaults import strip_default_styles
from avocado.parser.optimize.unwrap_single_child import unwrap_single_child

__all__ = [
    "apply_auto_group_variance",
    "apply_semantic_tags",
    "gap_to_margin",
    "promote_inherited_styles",
    "reround_class_map",
    "reround_styles",
    "strip_default_styles",
    "unwrap_single_child",
]
