"""Tests for multi-frame responsive merge (--responsive)."""

from __future__ import annotations

import pytest

from avocado.commands.responsive import parse_frame_specs
from avocado.generator.responsive import Frame, merge_frames, normalize_root
from avocado.model.tree_node import TreeNode


def _card(title: str) -> TreeNode:
    """A small repeated block: root + 3 children (size 4)."""
    return TreeNode(
        id="card",
        name="Card",
        source_type="FRAME",
        tag_name="div",
        props={"className": "bg-white rounded-lg"},
        children=[
            TreeNode(id="t", name="Title", source_type="TEXT", tag_name="div", text_content=title),
            TreeNode(id="b", name="Body", source_type="TEXT", tag_name="div", text_content="body"),
            TreeNode(id="i", name="Icon", source_type="VECTOR", tag_name="img", is_img=True),
        ],
    )


def _frame(width: float, *, extra: TreeNode | None = None) -> Frame:
    children = [_card("Same")]
    if extra is not None:
        children.append(extra)
    root = TreeNode(
        id="root",
        name="Screen",
        source_type="FRAME",
        tag_name="div",
        props={"className": f"w-[{int(width)}px] h-[900px] flex flex-col"},
        children=children,
    )
    return Frame(name="mobile" if width < 600 else "desktop", tree=root, width=width)


# ── spec parsing ──


def test_parse_frame_specs_normalises_dash_ids() -> None:
    assert parse_frame_specs(("mobile=1-2", "desktop=3-4")) == [
        ("mobile", "1:2"),
        ("desktop", "3:4"),
    ]


def test_parse_frame_specs_rejects_missing_equals() -> None:
    with pytest.raises(ValueError, match="NAME=NODE_ID"):
        parse_frame_specs(("mobile",))


def test_parse_frame_specs_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        parse_frame_specs(("mobile=1:2", "mobile=3:4"))


def test_parse_frame_specs_needs_two_frames() -> None:
    with pytest.raises(ValueError, match="at least two"):
        parse_frame_specs(("mobile=1:2",))


# ── root normalisation ──


def test_normalize_root_drops_pinned_size() -> None:
    node = TreeNode(
        id="r",
        name="Screen",
        source_type="FRAME",
        props={"className": "w-[390px] h-[2102.55px] min-w-[320px] bg-white"},
        style={"width": "390px", "height": "2102px", "background-color": "#fff"},
    )
    normalize_root(node)
    assert node.props["className"] == "bg-white w-full"
    assert node.style == {"background-color": "#fff"}


def test_normalize_root_keeps_non_size_utilities() -> None:
    node = TreeNode(
        id="r",
        name="Screen",
        source_type="FRAME",
        props={"className": "flex flex-col overflow-hidden"},
    )
    normalize_root(node)
    assert node.props["className"] == "flex flex-col overflow-hidden w-full"


# ── merge ──


def test_merge_emits_one_module_with_breakpoints() -> None:
    result = merge_frames(
        [_frame(390), _frame(1440, extra=_card("Only desktop"))],
        page_name="Page",
        min_shared_nodes=4,
    )
    code = result.code
    assert 'import React from "react";' in code
    assert "export function useResponsiveBreakpoint()" in code
    assert "export default function Page()" in code
    assert "function PageMobileLayout()" in code
    assert "function PageDesktopLayout()" in code
    assert result.breakpoints == [
        {"name": "mobile", "minWidth": 0},
        {"name": "desktop", "minWidth": 915},
    ]
    # One switch statement per non-default breakpoint
    assert 'if (breakpoint === "desktop") return <PageDesktopLayout />;' in code


def test_merge_extracts_shared_subtree() -> None:
    result = merge_frames([_frame(390), _frame(1440)], page_name="Page", min_shared_nodes=4)
    assert result.shared_components == ["SharedCard"]
    assert "function SharedCard()" in result.code
    # Both layouts reference the shared component instead of re-inlining it
    assert result.code.count("<SharedCard />") == 2
    # The repeated text lives inside the shared component exactly once
    assert result.code.count(">Same<") == 1


def test_merge_does_not_share_root() -> None:
    result = merge_frames([_frame(390), _frame(1440)], page_name="Page", min_shared_nodes=1)
    assert "SharedScreen" not in result.shared_components


def test_merge_rejects_single_frame() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        merge_frames([_frame(390)])


def test_merge_rejects_equal_widths() -> None:
    with pytest.raises(ValueError, match="distinct widths"):
        merge_frames([_frame(390), _frame(390)])


def test_merge_reports_stats() -> None:
    result = merge_frames([_frame(390), _frame(1440)], page_name="Page", min_shared_nodes=4)
    assert result.stats["frames"] == 2
    assert result.stats["generated_lines"] == result.code.count("\n")
    assert result.stats["nodes_replaced_by_shared"] > 0
