"""Tests for Tailwind class generator"""

from __future__ import annotations

from avocado.generator.tailwind import (
    _px_value,
    _spacing_class,
    apply_tailwind,
    style_to_tailwind,
)
from avocado.model.tree_node import TreeNode

# ── helpers ──


def test_px_value_from_int() -> None:
    assert _px_value(8) == 8.0
    assert _px_value(8.5) == 8.5


def test_px_value_from_str() -> None:
    assert _px_value("8px") == 8.0
    assert _px_value("8.5px") == 8.5
    assert _px_value("red") is None


def test_spacing_class_on_grid() -> None:
    assert _spacing_class(8, "p") == "p-2"  # 8px = 2 * 4px
    assert _spacing_class(0, "p") == "p-0"


def test_spacing_class_off_grid_arbitrary() -> None:
    assert _spacing_class(7, "p") == "p-[7px]"
    assert _spacing_class(8.5, "p") == "p-[8.5px]"


# ── style_to_tailwind ──


def test_flex_layout_maps() -> None:
    classes, leftover = style_to_tailwind(
        {
            "display": "flex",
            "flex-direction": "row",
            "justify-content": "center",
            "align-items": "center",
        }
    )
    assert "flex" in classes
    assert "flex-row" in classes
    assert "justify-center" in classes
    assert "items-center" in classes
    assert leftover == {}


def test_gap_on_grid() -> None:
    classes, _ = style_to_tailwind({"gap": "16px"})
    assert "gap-4" in classes


def test_gap_off_grid() -> None:
    classes, _ = style_to_tailwind({"gap": "15px"})
    assert "gap-[15px]" in classes


def test_padding_shorthand_uniform() -> None:
    classes, _ = style_to_tailwind({"padding": "16px 16px 16px 16px"})
    assert "p-4" in classes


def test_padding_shorthand_nonuniform_split() -> None:
    """Non-uniform padding shorthand splits into py-/px- for symmetric pairs."""
    # 8px top/bottom, 16px left/right → py-2 px-4
    classes, leftover = style_to_tailwind({"padding": "8px 16px 8px 16px"})
    assert "py-2" in classes
    assert "px-4" in classes
    assert leftover == {}


def test_padding_shorthand_asymmetric() -> None:
    """Fully asymmetric padding → 4 distinct pt/pr/pb/pl classes."""
    classes, _ = style_to_tailwind({"padding": "8px 16px 12px 20px"})
    assert "pt-2" in classes
    assert "pr-4" in classes
    assert "pb-3" in classes
    assert "pl-5" in classes


def test_padding_shorthand_vertical_symmetric() -> None:
    """Vertical-only symmetric padding: '64px 0 64px 0' → py-16 only."""
    classes, _ = style_to_tailwind({"padding": "64px 0px 64px 0px"})
    assert "py-16" in classes
    # No px-0 (0 is default, filtered)
    assert not any(c.startswith("px-") for c in classes)


def test_named_color_bg() -> None:
    classes, _ = style_to_tailwind({"background-color": "#ffffff"})
    assert "bg-white" in classes


def test_hex_color_maps_to_arbitrary_value() -> None:
    """Non-named hex colors → arbitrary value className."""
    classes, leftover = style_to_tailwind({"background-color": "#faf8f7"})
    assert "bg-[#faf8f7]" in classes
    assert leftover == {}


def test_rgba_color_spaces_become_underscores() -> None:
    """rgba(R, G, B, A) with spaces → single arbitrary value class.

    Hotfix regression test: style_to_tailwind splits multi-class strings
    by space; rgba(0, 0, 0, 0.8) contains spaces so it was split into 3
    broken fragments → tailwind JIT rejected the class → element rendered
    transparent. Spaces inside arbitrary values must become underscores.
    """
    classes, leftover = style_to_tailwind({"background-color": "rgba(0, 0, 0, 0.8)"})
    assert len(classes) == 1, f"rgba class must be single token, got {classes}"
    assert classes[0] == "bg-[rgba(0,_0,_0,_0.8)]"
    assert leftover == {}


def test_rgba_text_and_border_underscores() -> None:
    """text-[rgba] and border-[rgba] also need space→underscore."""
    from avocado.generator.tailwind import _map_one

    assert _map_one("color", "rgba(255, 0, 0, 0.5)") == "text-[rgba(255,_0,_0,_0.5)]"
    assert _map_one("border-color", "rgba(10, 35, 51, 0.15)") == "border-[rgba(10,_35,_51,_0.15)]"


def test_border_radius_named() -> None:
    classes, _ = style_to_tailwind({"border-radius": "8px"})
    assert "rounded-lg" in classes


def test_border_radius_full() -> None:
    classes, _ = style_to_tailwind({"border-radius": "999px"})
    assert "rounded-full" in classes


def test_font_size_base() -> None:
    classes, _ = style_to_tailwind({"font-size": "16px"})
    assert "text-base" in classes


def test_font_weight_medium() -> None:
    classes, _ = style_to_tailwind({"font-weight": 500})
    assert "font-medium" in classes


def test_text_align() -> None:
    classes, _ = style_to_tailwind({"text-align": "center"})
    assert "text-center" in classes


def test_position_relative() -> None:
    classes, _ = style_to_tailwind({"position": "relative"})
    assert "relative" in classes


def test_font_family_maps_to_arbitrary_value() -> None:
    """font-family → font-[Name] arbitrary value."""
    classes, leftover = style_to_tailwind(
        {
            "font-family": "Inter",
        }
    )
    assert "font-[Inter]" in classes
    assert leftover == {}


def test_font_family_with_fallback_maps() -> None:
    """font-family 'Inter, sans-serif' → font-[Inter,_sans-serif]."""
    classes, _ = style_to_tailwind({"font-family": "Inter, sans-serif"})
    # Tailwind arbitrary value uses _ for space
    assert "font-[Inter,_sans-serif]" in classes


def test_dedup_classes() -> None:
    classes, _ = style_to_tailwind(
        {
            "display": "flex",
            "background-color": "#ffffff",  # bg-white
        }
    )
    assert classes.count("flex") == 1


# ── apply_tailwind on tree ──


def test_apply_tailwind_sets_className() -> None:
    node = TreeNode(
        id="0",
        name="n",
        source_type="FRAME",
        style={"display": "flex", "background-color": "#ffffff"},
    )
    apply_tailwind(node)
    assert "className" in node.props
    assert "flex" in node.props["className"]
    assert "bg-white" in node.props["className"]
    # style should be empty (all mapped)
    assert node.style == {}


def test_apply_tailwind_maps_all_to_className() -> None:
    """Hex color also maps to arbitrary value className."""
    node = TreeNode(
        id="0",
        name="n",
        source_type="FRAME",
        style={"display": "flex", "background-color": "#faf8f7"},
    )
    apply_tailwind(node)
    assert "flex" in node.props["className"]
    assert "bg-[#faf8f7]" in node.props["className"]
    # style should be empty (all mapped)
    assert node.style == {}


def test_apply_tailwind_walks_children() -> None:
    parent = TreeNode(id="0", name="p", source_type="FRAME", style={"display": "flex"})
    child = TreeNode(
        id="1", name="c", source_type="RECTANGLE", style={"background-color": "#000000"}
    )
    parent.children.append(child)
    apply_tailwind(parent)
    assert "flex" in parent.props.get("className", "")
    assert "bg-black" in child.props.get("className", "")


def test_apply_tailwind_skips_component_nodes() -> None:
    """Recognized components keep inline style — appending tailwind className
    would stack with the library's internal padding/sizing (issue #35)."""
    node = TreeNode(
        id="0",
        name="btn",
        source_type="INSTANCE",
        tag_name="Button",
        is_component=True,
        props={"className": "btn-primary"},
        style={"display": "flex", "background-color": "#ffffff"},
    )
    apply_tailwind(node)
    # component className untouched (no tailwind classes appended)
    assert node.props["className"] == "btn-primary"
    # style kept inline (not converted to className)
    assert node.style == {"display": "flex", "background-color": "#ffffff"}


def test_apply_tailwind_still_converts_component_children() -> None:
    """Plain child nodes of a component are still converted to className."""
    child = TreeNode(id="1", name="text", source_type="TEXT", tag_name="span",
                     style={"background-color": "#000000"})
    node = TreeNode(id="0", name="btn", source_type="INSTANCE", tag_name="Button",
                    is_component=True, props={"className": "btn-primary"},
                    style={"display": "flex"}, children=[child])
    apply_tailwind(node)
    # component itself keeps inline style
    assert node.style == {"display": "flex"}
    # plain child converted
    assert "bg-black" in child.props.get("className", "")


# ── Readability: extended mappings ──


def test_overflow_maps() -> None:
    classes, _ = style_to_tailwind({"overflow": "hidden"})
    assert "overflow-hidden" in classes


def test_overflow_x_y_maps() -> None:
    classes, _ = style_to_tailwind({"overflow-x": "hidden", "overflow-y": "auto"})
    assert "overflow-x-hidden" in classes
    assert "overflow-y-auto" in classes


def test_flex_shrink_maps_to_shrink_0() -> None:
    classes, leftover = style_to_tailwind({"flex-shrink": 0})
    assert "shrink-0" in classes
    assert leftover == {}


def test_flex_grow_maps_to_grow() -> None:
    classes, _ = style_to_tailwind({"flex-grow": 1})
    assert "grow" in classes


def test_border_color_hex_maps() -> None:
    classes, _ = style_to_tailwind({"border-color": "#cdcbcb"})
    assert "border-[#cdcbcb]" in classes


def test_border_width_1px() -> None:
    classes, _ = style_to_tailwind({"border-width": "1px"})
    assert "border" in classes


def test_border_width_2px() -> None:
    classes, _ = style_to_tailwind({"border-width": "2px"})
    assert "border-2" in classes


def test_box_shadow_arbitrary() -> None:
    classes, _ = style_to_tailwind({"box-shadow": "0 4px 6px rgba(0,0,0,0.1)"})
    assert classes == ["shadow-[0_4px_6px_rgba(0,0,0,0.1)]"]


# ── CSS variable arbitrary value syntax ──


def test_tailwind_emits_arbitrary_value_for_css_var_color() -> None:
    """background-color: var(--x, #faf8f7) → bg-[var(--x,#faf8f7)]"""
    classes, leftover = style_to_tailwind(
        {
            "background-color": "var(--color-bg-primary, #faf8f7)",
        }
    )
    assert "bg-[var(--color-bg-primary,#faf8f7)]" in classes
    assert "background-color" not in leftover


def test_tailwind_emits_arbitrary_value_for_css_var_spacing() -> None:
    """padding-top: var(--x, 16px) → pt-[var(--x,16px)]"""
    classes, leftover = style_to_tailwind(
        {
            "padding-top": "var(--spacing-md, 16px)",
        }
    )
    assert "pt-[var(--spacing-md,16px)]" in classes
    assert "padding-top" not in leftover


# ── line-height / letter-spacing fix ──


def test_line_height_on_grid() -> None:
    """24px line-height → leading-6 (24px is on the 4px spacing grid)."""
    classes, leftover = style_to_tailwind({"line-height": "24px"})
    assert "leading-6" in classes
    assert "line-height" not in leftover


def test_line_height_off_grid() -> None:
    """22px line-height → leading-[22px] (off the 4px grid)."""
    classes, leftover = style_to_tailwind({"line-height": "22px"})
    assert "leading-[22px]" in classes
    assert "line-height" not in leftover


def test_line_height_zero() -> None:
    """0px line-height → leading-0 (on grid)."""
    classes, _ = style_to_tailwind({"line-height": "0px"})
    assert "leading-0" in classes


def test_line_height_percentage_arbitrary() -> None:
    """Percentage values fall through to arbitrary syntax."""
    classes, _ = style_to_tailwind({"line-height": "150%"})
    assert "leading-[150%]" in classes


def test_line_height_never_emits_bare_px_token() -> None:
    """Regression guard: leading-24px is an INVALID Tailwind class
    (Tailwind reads `24px` as a token name, not a value, and the class
    silently does nothing). The fix moved away from that form."""
    classes, _ = style_to_tailwind({"line-height": "24px"})
    assert "leading-24px" not in classes


def test_letter_spacing_zero() -> None:
    """0px letter-spacing → tracking-normal (named)."""
    classes, _ = style_to_tailwind({"letter-spacing": "0px"})
    assert "tracking-normal" in classes


def test_letter_spacing_nonzero_arbitrary() -> None:
    """Non-zero letter-spacing → tracking-[Npx] (no bare px token)."""
    classes, _ = style_to_tailwind({"letter-spacing": "1px"})
    assert "tracking-[1px]" in classes
    assert "tracking-1px" not in classes


def test_border_radius_non_uniform_4_value() -> None:
    """4-value border-radius (Figma rectangleCornerRadii) → arbitrary value.

    Tailwind maps underscores to spaces in arbitrary values, so
    rounded-[16px_16px_0_0] → border-radius: 16px 16px 0 0.
    """
    classes, leftover = style_to_tailwind({"border-radius": "16px 16px 0 0"})
    assert "rounded-[16px_16px_0_0]" in classes
    assert leftover == {}
