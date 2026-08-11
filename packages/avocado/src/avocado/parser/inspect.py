"""inspectDraft rules.

(see project design docs)

Each rule walks the TreeNode tree post-parse and emits warnings:
  - severity: error | warning | info
  - code: short identifier
  - message: human-readable
  - suggestion: optional fix hint
  - figma_id: optional source node id

Rules are PURE checks on TreeNode — no Figma API calls. They run AFTER
parser completes so they see the final structure including layout_strategy.
"""

from __future__ import annotations

from collections.abc import Callable

from avocado.model.tree_node import TreeNode

# WCAG contrast thresholds (per design docs)
WCAG_AA_NORMAL = 4.5
WCAG_AA_LARGE = 3.0
WCAG_AAA_NORMAL = 7.0

# Thresholds
NESTING_DEPTH_WARN = 8  # depth > 8 = warning
NESTING_DEPTH_ERROR = 15
ABSOLUTE_CHILD_LIMIT = 5  # absolute children > 5 = info


# ── individual rules ──────────────────────────────────────────────────────────


def rule_deep_nesting(root: TreeNode) -> list[dict]:
    """Flag excessive nesting depth (D2C output gets unwieldy)."""
    out: list[dict] = []
    stack: list[tuple[TreeNode, int]] = [(root, 0)]
    while stack:
        n, d = stack.pop()
        if d >= NESTING_DEPTH_ERROR:
            n.add_inspect(
                severity="error",
                code="deep-nesting",
                message=f"Node {n.name!r} is at depth {d}; output may be hard to maintain.",
            )
        elif d >= NESTING_DEPTH_WARN:
            n.add_inspect(
                severity="warning",
                code="deep-nesting",
                message=f"Node {n.name!r} is at depth {d}.",
            )
        for c in n.children:
            stack.append((c, d + 1))
    return out


def rule_many_absolute_children(root: TreeNode) -> list[dict]:
    """A wrapper using absolute positioning with > 5 children is fragile."""
    stack = [root]
    while stack:
        n = stack.pop()
        if n.layout_strategy == "absolute_position" and len(n.children) > ABSOLUTE_CHILD_LIMIT:
            n.add_inspect(
                severity="info",
                code="many-absolute-children",
                message=f"Node {n.name!r} has {len(n.children)} absolutely-positioned "
                f"children (> {ABSOLUTE_CHILD_LIMIT}); consider Auto Layout.",
                suggestion="Use Figma Auto Layout for cleaner output.",
            )
        for c in n.children:
            stack.append(c)
    return []


def rule_low_contrast_text(root: TreeNode) -> list[dict]:
    """Text on background with WCAG contrast below AA = warning.

    Looks at TreeNode.style['color'] (text) and nearest ancestor's
    'background-color' as background proxy.
    """

    def _contrast(fg: str, bg: str) -> float | None:
        fg_c = _parse_color(fg)
        bg_c = _parse_color(bg)
        if not fg_c or not bg_c:
            return None
        return _wcag_contrast(fg_c, bg_c)

    stack: list[tuple[TreeNode, str | None]] = [(root, None)]
    while stack:
        n, parent_bg = stack.pop()
        this_bg = n.style.get("background-color") or parent_bg
        if n.text_content and n.tag_name == "span":
            color = n.style.get("color")
            if color and this_bg:
                ratio = _contrast(color, this_bg)
                if ratio is not None and ratio < WCAG_AA_NORMAL:
                    n.add_inspect(
                        severity="warning",
                        code="low-contrast",
                        message=f"Text color {color!r} on {this_bg!r} has "
                        f"contrast {ratio:.2f}:1 (WCAG AA requires "
                        f"{WCAG_AA_NORMAL}:1).",
                        suggestion="Darken text or lighten background.",
                    )
        for c in n.children:
            stack.append((c, this_bg))
    return []


def rule_unstyled_image(root: TreeNode) -> list[dict]:
    """<img> with no width/height is a layout-shift risk."""
    stack = [root]
    while stack:
        n = stack.pop()
        if n.is_img:
            if "width" not in n.style or "height" not in n.style:
                n.add_inspect(
                    severity="info",
                    code="img-no-size",
                    message=f"<img> {n.name!r} missing width/height; may cause layout shift.",
                )
        for c in n.children:
            stack.append(c)
    return []


def rule_inline_style_too_long(root: TreeNode) -> list[dict]:
    """Style with > 8 properties should probably extract to className."""
    STYLE_THRESHOLD = 8
    stack = [root]
    while stack:
        n = stack.pop()
        # Exclude props that codegen always emits (data-* attrs are in props)
        style_count = len(n.style)
        if style_count > STYLE_THRESHOLD:
            n.add_inspect(
                severity="info",
                code="long-inline-style",
                message=f"Node {n.name!r} has {style_count} inline style properties; "
                "consider extracting to CSS class.",
            )
        for c in n.children:
            stack.append(c)
    return []


def rule_component_without_imports(root: TreeNode) -> list[dict]:
    """Recognized components should have a package — if not, user must add import."""
    stack = [root]
    while stack:
        n = stack.pop()
        if n.is_component and not n.component_package:
            n.add_inspect(
                severity="warning",
                code="component-no-package",
                message=f"Component {n.tag_name!r} recognized but no package set; "
                "add import manually.",
            )
        for c in n.children:
            stack.append(c)
    return []


def rule_image_fetch_failed(root: TreeNode) -> list[dict]:
    """FIX: <img> with empty src = image fetch failed in pipeline.

    image.py sets src="" + _image_error prop when fetch fails.
    cli.py collects _image_error into envelope warnings, but inspect
    rule gives per-node visibility (agent can locate which figma node failed).
    """
    stack = [root]
    while stack:
        n = stack.pop()
        # Check the _image_error prop (cli.py cleans it up before render_jsx,
        # but inspect runs before render_jsx, so it can still detect it)
        if hasattr(n, "props") and n.props.get("_image_error"):
            # FIX: don't truncate the error at 80 chars — the Figma render
            # failure detail (which node id, what the API returned) is what
            # lets the agent judge the root cause.
            n.add_inspect(
                severity="warning",
                code="image-fetch-failed",
                message=f"<img> {n.name!r} fetch failed: {n.props['_image_error']}",
                suggestion=(
                    "check the figma imageRef or run once online to repopulate the cache (--cache-dir). "
                    "If the node id is a nested-instance combo id (I<file>:<id>;<id>;...), the Figma "
                    "render API cannot export it — avocado falls back to the nearest renderable "
                    "ancestor or inline SVG when vector geometry is available"
                ),
            )
        # Also detect the src="" case (_image_error already cleaned up but src still empty)
        elif n.is_img and n.props.get("src") == "":
            n.add_inspect(
                severity="warning",
                code="image-fetch-failed",
                message=f"<img> {n.name!r} has empty src (fetch failed)",
                suggestion=(
                    "check the figma imageRef or run once online to repopulate the cache (--cache-dir). "
                    "If the node id is a nested-instance combo id, the Figma render API cannot "
                    "export it (avocado falls back to the nearest renderable ancestor)"
                ),
            )
        for c in n.children:
            stack.append(c)
    return []


# ── color helpers (minimal WCAG math) ─────────────────────────────────────────


def _parse_color(s: str) -> tuple[float, float, float] | None:
    """Parse '#RRGGBB' or 'rgba(r, g, b, a)' → (R, G, B) 0..1."""
    s = s.strip()
    if s.startswith("#") and len(s) == 7:
        try:
            r = int(s[1:3], 16) / 255
            g = int(s[3:5], 16) / 255
            b = int(s[5:7], 16) / 255
            return (r, g, b)
        except ValueError:
            return None
    if s.startswith("rgba("):
        parts = s.strip("rgba() ").split(",")
        if len(parts) >= 3:
            try:
                return (
                    float(parts[0]) / 255,
                    float(parts[1]) / 255,
                    float(parts[2]) / 255,
                )
            except ValueError:
                return None
    return None


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    """WCAG relative luminance."""

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _wcag_contrast(rgb1: tuple[float, float, float], rgb2: tuple[float, float, float]) -> float:
    """WCAG contrast ratio (1..21)."""
    l1 = _relative_luminance(rgb1)
    l2 = _relative_luminance(rgb2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


# ── registry ──────────────────────────────────────────────────────────────────


# All rule functions (no args beyond root). Each mutates nodes' .inspect lists.
RULES: list[Callable[[TreeNode], list[dict]]] = [
    rule_deep_nesting,
    rule_many_absolute_children,
    rule_low_contrast_text,
    rule_unstyled_image,
    rule_inline_style_too_long,
    rule_component_without_imports,
    rule_image_fetch_failed,  # FIX: image fetch failed
]


def run_all_inspect_rules(root: TreeNode) -> int:
    """Run all rules. Returns count of new warnings added."""
    before = sum(len(n.inspect) for n in _walk_all(root))
    for rule in RULES:
        rule(root)
    after = sum(len(n.inspect) for n in _walk_all(root))
    return after - before


def collect_all_warnings(root: TreeNode) -> list[dict]:
    """Flatten all node.inspect entries into a single list (for CLI output)."""
    out: list[dict] = []
    for n in _walk_all(root):
        for w in n.inspect:
            entry = dict(w)
            if n.figma_id:
                entry["figma_id"] = n.figma_id
            if n.name:
                entry["node_name"] = n.name
            out.append(entry)
    return out


def _walk_all(root: TreeNode):
    stack = [root]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.children)
