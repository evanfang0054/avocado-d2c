"""Multi-frame responsive merge.

A Figma file usually documents the same page at several widths (mobile /
tablet / desktop) as separate frames. Converting them one by one produces N
near-duplicate files that drift apart; this module folds them into a single
React module:

    const BREAKPOINTS = [{ name: "mobile", minWidth: 0 }, ...];
    export function useResponsiveBreakpoint() { ... }   // matchMedia, no deps
    function PageMobileLayout() { ... }                  // one per frame
    export default function Page() { ... }               // switch on breakpoint

Subtrees that are byte-identical across frames are extracted once into shared
components, so editing a repeated row no longer means editing it N times.

Everything here is content-driven: breakpoint labels come from the CLI, shared
component names come from the node names, and no project-specific strings are
hardcoded.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field

from avocado.generator.codegen import _to_component_name, render_jsx
from avocado.model.tree_node import TreeNode

# Tailwind width/height utilities pinned to a fixed value (e.g. w-[390px],
# h-64). Root frames carry these from the design canvas; inside a responsive
# layout they must go, otherwise the mobile layout stays 390px wide on a
# 500px viewport.
_ROOT_SIZE_CLASS_RE = None  # compiled lazily to keep import cost flat


@dataclass
class Frame:
    """One design frame participating in the merge."""

    name: str  # CLI label, e.g. "mobile"
    tree: TreeNode
    width: float


@dataclass
class MergeResult:
    code: str
    breakpoints: list[dict]
    shared_components: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


# ── canonical subtree keys ──


def _canonical(node: TreeNode) -> str:
    """Deterministic content hash of a subtree.

    Excludes identity fields (id / figma_id / name) so the same visual block
    matches across frames, where ids and sometimes layer names differ.
    """
    parts = [
        node.tag_name or "div",
        node.text_content or "",
        repr(sorted((k, repr(v)) for k, v in node.props.items())),
        repr(sorted((k, repr(v)) for k, v in node.style.items())),
        ",".join(_canonical(c) for c in node.children),
    ]
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()


def _subtree_size(node: TreeNode) -> int:
    return 1 + sum(_subtree_size(c) for c in node.children)


def _walk_with_path(node: TreeNode, path: tuple[int, ...] = ()):
    yield path, node
    for i, child in enumerate(node.children):
        yield from _walk_with_path(child, path + (i,))


def _node_at(root: TreeNode, path: tuple[int, ...]) -> TreeNode:
    node = root
    for i in path:
        node = node.children[i]
    return node


# ── root normalisation ──


def _strip_fixed_size_classes(className: str) -> str:
    import re

    global _ROOT_SIZE_CLASS_RE
    if _ROOT_SIZE_CLASS_RE is None:
        # ``(?![\w-])`` instead of ``\b``: a class ending in ``]`` has no word
        # boundary (``]`` and whitespace are both non-word), so ``\b`` would
        # silently match nothing for arbitrary values like ``w-[390px]``.
        _ROOT_SIZE_CLASS_RE = re.compile(
            r"(?:^|\s)(?:min-|max-)?(?:w|h)-(?:\[[^\]]+\]|\d+(?:\.\d+)?)(?![\w-])"
        )
    cleaned = _ROOT_SIZE_CLASS_RE.sub(" ", className or "")
    return " ".join(cleaned.split())


def normalize_root(tree: TreeNode) -> None:
    """Drop canvas-pinned root size so the layout fills its viewport."""
    for key in ("width", "height", "min-width", "max-width", "min-height", "max-height"):
        tree.style.pop(key, None)
    className = tree.props.get("className")
    if isinstance(className, str):
        tree.props["className"] = (_strip_fixed_size_classes(className) + " w-full").strip()
    elif not className:
        tree.props["className"] = "w-full"


# ── shared subtree extraction ──


def _pick_shared(
    frames: list[Frame], *, min_nodes: int, max_components: int
) -> list[tuple[str, TreeNode, list[tuple[int, tuple[int, ...]]]]]:
    """Choose subtrees that appear in >=2 frames.

    Returns ``(name, representative_node, [(frame_index, path), ...])`` sorted
    by subtree size (largest first). Overlapping picks are skipped so a chosen
    subtree is never nested inside another chosen one.
    """
    occurrences: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
    representative: dict[str, TreeNode] = {}
    sizes: dict[str, int] = {}

    for fi, frame in enumerate(frames):
        for path, node in _walk_with_path(frame.tree):
            if not path:  # keep each frame's root as its layout
                continue
            size = _subtree_size(node)
            if size < min_nodes:
                continue
            key = _canonical(node)
            occurrences.setdefault(key, []).append((fi, path))
            representative.setdefault(key, node)
            sizes[key] = size

    candidates = [
        (key, occ)
        for key, occ in occurrences.items()
        if len({fi for fi, _ in occ}) >= 2
    ]
    candidates.sort(key=lambda kv: (-sizes[kv[0]], kv[0]))

    chosen: list[tuple[str, TreeNode, list[tuple[int, tuple[int, ...]]]]] = []
    used_paths: dict[int, list[tuple[int, ...]]] = {i: [] for i in range(len(frames))}
    used_names: set[str] = set()

    for key, occ in candidates:
        if len(chosen) >= max_components:
            break
        # Overlap guard: skip if any occurrence is an ancestor/descendant of a
        # path we already extracted in that frame.
        overlap = False
        for fi, path in occ:
            for used in used_paths[fi]:
                if (
                    path == used
                    or path[: len(used)] == used
                    or used[: len(path)] == path
                ):
                    overlap = True
                    break
            if overlap:
                break
        if overlap:
            continue

        rep = representative[key]
        base = _to_component_name(rep.name or "Section")
        name = f"Shared{base}"
        suffix = 2
        while name in used_names:
            name = f"Shared{base}{suffix}"
            suffix += 1
        used_names.add(name)

        for fi, path in occ:
            used_paths[fi].append(path)
        chosen.append((name, rep, occ))

    return chosen


def _replace_with_component(tree: TreeNode, path: tuple[int, ...], name: str) -> None:
    parent = _node_at(tree, path[:-1]) if len(path) > 1 else tree
    index = path[-1]
    original = parent.children[index]
    parent.children[index] = TreeNode(
        id=original.id,
        name=original.name,
        source_type=original.source_type,
        tag_name=name,
        is_component=True,
        props={},
        children=[],
    )


# ── rendering ──


def _render_named(tree: TreeNode, name: str, *, indent: int = 2) -> tuple[list[str], str]:
    """Render a subtree as a named function; returns (imports, function_body)."""
    code = render_jsx(
        tree,
        indent=indent,
        format="react",
        css="tailwind",
        component_name=name,
        emit_figma_id=False,
    )
    marker = "export default function"
    idx = code.index(marker)
    header = code[:idx]
    body = code[idx:].replace(marker, "function", 1).rstrip() + "\n"

    imports: list[str] = []
    for line in header.splitlines():
        line = line.strip()
        if not line.startswith("import "):
            continue
        if line.startswith("import React"):
            continue
        imports.append(line)
    return imports, body


def _breakpoints(frames: list[Frame]) -> list[dict]:
    """Mobile-first breakpoints from the frame widths (midpoint boundaries)."""
    ordered = sorted(frames, key=lambda f: f.width)
    out = [{"name": ordered[0].name, "minWidth": 0}]
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        out.append({"name": cur.name, "minWidth": int((prev.width + cur.width) / 2)})
    return out


def _hook_source(breakpoints: list[dict]) -> str:
    entries = ", ".join(f'{{ name: "{b["name"]}", minWidth: {b["minWidth"]} }}' for b in breakpoints)
    return f"""const BREAKPOINTS = [{entries}];

/** Current breakpoint name, driven by min-width media queries. */
export function useResponsiveBreakpoint() {{
  const [breakpoint, setBreakpoint] = React.useState(BREAKPOINTS[0].name);

  React.useEffect(() => {{
    const queries = BREAKPOINTS.slice(1).map((bp) => ({{
      name: bp.name,
      mql: window.matchMedia(`(min-width: ${{bp.minWidth}}px)`),
    }}));
    const update = () => {{
      const hit = [...queries].reverse().find((q) => q.mql.matches);
      setBreakpoint(hit ? hit.name : BREAKPOINTS[0].name);
    }};
    update();
    queries.forEach((q) => q.mql.addEventListener("change", update));
    return () => queries.forEach((q) => q.mql.removeEventListener("change", update));
  }}, []);

  return breakpoint;
}}
"""


def _page_component(frames: list[Frame], breakpoints: list[dict], page_name: str, layout_names: dict[str, str]) -> str:
    ordered = [b["name"] for b in breakpoints]
    default_name = ordered[0]
    lines = [
        f"export default function {page_name}() {{",
        "  const breakpoint = useResponsiveBreakpoint();",
    ]
    for name in ordered[1:]:
        lines.append(f'  if (breakpoint === "{name}") return <{layout_names[name]} />;')
    lines.append(f"  return <{layout_names[default_name]} />;")
    lines.append("}")
    return "\n".join(lines) + "\n"


def merge_frames(
    frames: list[Frame],
    *,
    page_name: str | None = None,
    min_shared_nodes: int = 8,
    max_shared_components: int = 12,
    indent: int = 2,
) -> MergeResult:
    """Fold N frame trees into one responsive module."""
    if len(frames) < 2:
        raise ValueError("responsive merge needs at least 2 frames")

    widths = [f.width for f in frames]
    if len(set(widths)) != len(widths):
        raise ValueError("frames must have distinct widths to derive breakpoints")

    ordered = sorted(frames, key=lambda f: f.width)
    trees = [copy.deepcopy(f.tree) for f in ordered]
    for tree in trees:
        normalize_root(tree)

    work = [Frame(name=f.name, tree=t, width=f.width) for f, t in zip(ordered, trees, strict=True)]

    shared = _pick_shared(
        work, min_nodes=min_shared_nodes, max_components=max_shared_components
    )
    for name, _rep, occ in shared:
        for fi, path in occ:
            _replace_with_component(work[fi].tree, path, name)

    imports: list[str] = []
    shared_bodies: list[str] = []
    for name, rep, _occ in shared:
        sub_imports, body = _render_named(rep, name, indent=indent)
        imports.extend(sub_imports)
        shared_bodies.append(body)

    derived_page = _to_component_name(ordered[0].tree.name or "ResponsivePage")
    page = page_name or derived_page
    layout_names: dict[str, str] = {}
    layout_bodies: list[str] = []
    for frame in work:
        layout = f"{page}{_to_component_name(frame.name)}Layout"
        layout_names[frame.name] = layout
        frame_imports, body = _render_named(frame.tree, layout, indent=indent)
        imports.extend(frame_imports)
        layout_bodies.append(body)

    breakpoints = _breakpoints(work)
    seen: set[str] = set()
    unique_imports = [ln for ln in imports if not (ln in seen or seen.add(ln))]

    sections = ['import React from "react";']
    if unique_imports:
        sections.append("\n".join(unique_imports))
    sections.extend(shared_bodies)
    sections.extend(layout_bodies)
    sections.append(_hook_source(breakpoints))
    sections.append(_page_component(work, breakpoints, page, layout_names))

    code = "\n\n".join(s.rstrip() for s in sections) + "\n"

    total_children = sum(_subtree_size(f.tree) for f in frames)
    shared_nodes = sum(_subtree_size(rep) * len(occ) for _n, rep, occ in shared)
    return MergeResult(
        code=code,
        breakpoints=breakpoints,
        shared_components=[name for name, _rep, _occ in shared],
        stats={
            "frames": len(frames),
            "nodes_before_merge": total_children,
            "nodes_replaced_by_shared": shared_nodes,
            "generated_lines": code.count("\n"),
        },
    )
