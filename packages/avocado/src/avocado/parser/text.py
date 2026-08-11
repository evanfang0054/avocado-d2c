"""TEXT node conversion: SceneNode.text_style + characters → JSX.

(see project design docs)

Features:
  - Single-line: <span>text</span>
  - Multi-line: <span> with white-space: pre-line (preserves \n)
  - styleOverrideTable: per-character style overrides → nested <span>
  - lineHeight all units (PIXELS / PERCENT / AUTO / INSIDE)
  - OpenType features → font-feature-settings
  - Multiple fills (gradient text): background-clip:text + transparent

Output:
  - tag is always <span> for inline, <p> for block-level multi-line.
    Uses <span> universally; keeps that for simplicity but adds
    `white-space: pre-line` to preserve newlines.
"""

from __future__ import annotations

from avocado.model.scene_node import SceneNode
from avocado.model.tree_node import TreeNode


def is_multiline(scene: SceneNode) -> bool:
    """True if characters contain any line break.

    Figma uses three line break forms in `characters`:
      - `\\n`           (LF, common in copy-pasted text)
      - `\\r`           (CR, rare)
      - `\\u2028`       (Unicode LINE SEPARATOR, used by Figma REST API for
                         multi-line text nodes — see
                         https://www.figma.com/developers/api#files-types)
      - `\\u2029`       (Unicode PARAGRAPH SEPARATOR, paragraph breaks)

    All four must trigger multiline handling (white-space: pre-line) so the
    browser renders each line. Without this, multi-line text from Figma
    collapses to a single line and overflows its container.
    """
    if not scene.characters:
        return False
    return any(c in scene.characters for c in ("\n", "\r", "\u2028", "\u2029"))


def has_style_overrides(scene: SceneNode) -> bool:
    """True if characters have per-character style overrides."""
    return (
        bool(scene.character_style_overrides)
        and bool(scene.style_override_table)
        and any(v != 0 for v in scene.character_style_overrides)
    )


def render_text_node(scene: SceneNode, tree: TreeNode) -> None:
    """Populate tree.text_content / children for a TEXT scene node.

    Mutates tree in-place:
      - simple text → tree.text_content
      - multi-style → tree.children with nested spans
    """
    chars = scene.characters or ""
    # Normalize Figma line separators (U+2028 / U+2029) to \\n. CSS
    # white-space: pre-line only honors \\n — U+2028 renders as a zero-width
    # space in browsers, collapsing multi-line Figma text into one line.
    chars = chars.replace("\u2028", "\n").replace("\u2029", "\n")

    if not has_style_overrides(scene):
        # Simple case: one text_content covers everything
        tree.text_content = chars
        if is_multiline(scene):
            # Preserve newlines (HTML collapses \n to space by default)
            tree.style["white-space"] = "pre-line"
        return

    # Rich text: split characters into runs of same style-override-id
    overrides = scene.character_style_overrides
    sot = scene.style_override_table

    runs: list[tuple[str, dict | None]] = []  # (text, styleOverride_dict)
    current_text = ""
    current_id: int | None = None
    # `overrides + [0]*(...)` pads overrides to len(chars) so each char gets
    # an oid (0 means "no override"). strict=False because the pad makes the
    # lengths match by construction.
    for ch, oid in zip(chars, overrides + [0] * (len(chars) - len(overrides)), strict=False):
        if oid != current_id and current_text:
            # flush previous run
            sty = sot.get(str(current_id)) if current_id else None
            runs.append((current_text, sty))
            current_text = ""
        current_text += ch
        current_id = oid
    if current_text:
        sty = sot.get(str(current_id)) if current_id else None
        runs.append((current_text, sty))

    # Build nested spans as children, each with its own style.
    # Clear tree.text_content first — children now carry text.
    tree.text_content = None
    for text, sty in runs:
        if not text:
            continue
        child = TreeNode(
            id=f"{scene.id}#run",
            name=f"{scene.name}#run",
            source_type="TEXT",
            tag_name="span",
            text_content=text,
            figma_id=scene.id,
        )
        if sty:
            child.style.update(_style_override_to_css(sty))
        tree.children.append(child)


def _style_override_to_css(sty: dict) -> dict[str, str | float]:
    """Convert a styleOverride dict (subset of TextStyle fields) to CSS."""
    out: dict[str, str | float] = {}
    if "fontWeight" in sty:
        w = sty["fontWeight"]
        out["font-weight"] = int(w) if float(w).is_integer() else round(float(w), 2)
    if sty.get("fontStyle") == "Italic":
        out["font-style"] = "italic"
    if "fontSize" in sty:
        out["font-size"] = f"{_num(sty['fontSize'])}px"
    if "textDecoration" in sty:
        if sty["textDecoration"] == "UNDERLINE":
            out["text-decoration"] = "underline"
        elif sty["textDecoration"] == "STRIKETHROUGH":
            out["text-decoration"] = "line-through"
    if "color" in sty:
        from avocado.model.scene_node import Color

        c = Color.from_dict(sty["color"])
        if c:
            out["color"] = c.to_rgba_str()
    return out


def _num(v: float, ndigits: int = 2) -> float | int:
    rounded = round(float(v), ndigits)
    if rounded == int(rounded):
        return int(rounded)
    return rounded
