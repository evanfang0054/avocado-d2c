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


def test_component_name_is_sanitized() -> None:
    """`--component-name "my page"` must not emit `function my page()`."""
    result = merge_frames([_frame(390), _frame(1440)], page_name="my page", min_shared_nodes=4)
    assert "export default function MyPage()" in result.code
    assert "function my page" not in result.code


def test_component_name_cannot_inject_code() -> None:
    result = merge_frames(
        [_frame(390), _frame(1440)], page_name="X(){ } //", min_shared_nodes=4
    )
    assert "export default function X" in result.code
    assert "//" not in result.code.split("export default function")[1].split("\n")[0]


def test_duplicate_layout_names_are_disambiguated() -> None:
    """Labels that normalize to the same identifier must not collide."""
    a = _frame(390)
    b = _frame(1440)
    a.name = "mobile"
    b.name = "Mobile"
    result = merge_frames([a, b], page_name="Page", min_shared_nodes=4)
    assert result.code.count("function PageMobileLayout(") == 1
    assert result.code.count("function PageMobile2Layout(") == 1


def test_breakpoints_stay_strictly_increasing_for_close_frames() -> None:
    """Sub-pixel frames would collapse two breakpoints onto the same min-width."""
    frames = []
    for width, name in ((1.0, "a"), (1.2, "b"), (1.4, "c")):
        frame = _frame(width, extra=_card(f"only-{name}"))
        frame.name = name
        frames.append(frame)
    result = merge_frames(frames, page_name="Page", min_shared_nodes=4)
    widths = [b["minWidth"] for b in result.breakpoints]
    assert widths == sorted(set(widths)), widths
    assert len(widths) == 3


def test_normalize_root_keeps_fraction_utilities() -> None:
    node = TreeNode(
        id="r",
        name="Screen",
        source_type="FRAME",
        props={"className": "w-1/2 h-1/2 w-[390px] bg-white"},
    )
    normalize_root(node)
    assert "w-1/2" in node.props["className"]
    assert "h-1/2" in node.props["className"]
    assert "w-[390px]" not in node.props["className"]
    assert node.props["className"].count("w-full") == 1


def test_normalize_root_does_not_duplicate_w_full() -> None:
    node = TreeNode(
        id="r", name="Screen", source_type="FRAME", props={"className": "w-full flex"}
    )
    normalize_root(node)
    assert node.props["className"] == "w-full flex"
