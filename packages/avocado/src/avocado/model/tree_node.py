"""TreeNode — D2C internal intermediate representation.

This is the post-parse, pre-generate form: a simplified, code-shaped tree
that maps cleanly to JSX elements. SceneNode → TreeNode conversion happens
in parser/node_mapper.py.

(per design docs) this defines the contract surface for D2C plugins.
Plugins written against this TreeNode target the post-parse tree directly.

Differences from SceneNode:
  - `style` is a flat CSS-like dict, not Figma-native fields
  - `children` is list[TreeNode], not list[SceneNode]
  - `tag_name` is the target JSX tag (div / img / Button / span / ...)
  - `props` is the JSX props dict
  - `text_content` is the literal string (TEXT nodes only)
  - `is_img` / `is_component` are pre-computed flags
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# CSS value type — most are str, but some (numbers for legacy props) allowed.
CSSValue = str | float | int
StyleDict = dict[str, CSSValue]
PropsDict = dict[str, Any]


# Layout strategy tag, set by parser/layout.py during parse.
LayoutStrategy = Literal["auto_layout", "absolute_position", "auto_group", "leaf"]


@dataclass
class TreeNode:
    """D2C intermediate node. Plugin hooks operate on this."""

    # ── identity ──
    id: str
    name: str
    # Figma source type, kept for traceability. Generator rarely uses it.
    source_type: str  # FRAME / TEXT / RECTANGLE / ...

    # ── JSX target ──
    tag_name: str = "div"  # div / span / img / Button / section / ...
    props: PropsDict = field(default_factory=dict)
    children: list[TreeNode] = field(default_factory=list)

    # ── styling ──
    style: StyleDict = field(default_factory=dict)
    # CSS class name (set by generator/css.py when extracting to .css file)
    class_name: str | None = None

    # ── content ──
    text_content: str | None = None  # TEXT nodes

    # ── flags ──
    is_img: bool = False
    is_component: bool = False  # INSTANCE recognized as business component
    component_package: str | None = None  # import package when is_component
    layout_strategy: LayoutStrategy = "leaf"

    # ── Figma source link (for inspect/debug) ──
    figma_id: str | None = None

    # ── plugin extension slot ──
    # Plugins may set this to override JSX output (Vue/Emotion plugins use this)
    to_template: Any | None = None

    # ── inspect warnings collected during parse ──
    inspect: list[dict[str, Any]] = field(default_factory=list)

    def add_inspect(
        self,
        severity: str,
        code: str,
        message: str,
        suggestion: str | None = None,
    ) -> None:
        """Add an inspect-draft entry. severity ∈ {error, warning, info}."""
        entry: dict[str, Any] = {
            "severity": severity,
            "code": code,
            "message": message,
        }
        if suggestion:
            entry["suggestion"] = suggestion
        self.inspect.append(entry)
