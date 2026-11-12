"""``--responsive`` flow: merge several design frames into one module.

The CLI contract is deliberately generic:

    avocado <url> --responsive mobile=1:2 --responsive tablet=1:3 \\
        --responsive desktop=1:4 --format react -o page.tsx

Frame labels, breakpoints and chrome-stripping patterns all come from the
command line; nothing project-specific lives in this module.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from avocado.api.figma import FigmaError, FigmaNodeRef
from avocado.envelope import emit_error, emit_ok
from avocado.generator.responsive import Frame, merge_frames
from avocado.generator.style_props import apply_style_prop_modes
from avocado.generator.tailwind import apply_tailwind
from avocado.model.scene_node import SceneNode
from avocado.parser.component import ComponentMapping
from avocado.parser.node_mapper import map_node
from avocado.parser.passes import apply_parse_passes
from avocado.plugins.base import HookRegistry

_SPEC_HELP = "NAME=NODE_ID"


def parse_frame_specs(specs: tuple[str, ...]) -> list[tuple[str, str]]:
    """Parse repeated ``NAME=NODE_ID`` specs into ordered (name, id) pairs."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in specs:
        if "=" not in raw:
            raise ValueError(f"--responsive expects {_SPEC_HELP}, got {raw!r}")
        name, node_id = (part.strip() for part in raw.split("=", 1))
        if not name or not node_id:
            raise ValueError(f"--responsive expects {_SPEC_HELP}, got {raw!r}")
        if name in seen:
            raise ValueError(f"duplicate responsive frame name {name!r}")
        seen.add(name)
        out.append((name, node_id.replace("-", ":")))
    if len(out) < 2:
        raise ValueError("--responsive needs at least two NAME=NODE_ID pairs")
    return out


def _strip_by_name(tree, patterns: list[str]) -> None:
    """Drop nodes whose layer name contains any of ``patterns`` (case-insensitive)."""
    if not patterns:
        return
    lowered = [p.lower() for p in patterns if p]

    def walk(node) -> None:
        node.children = [
            c for c in node.children if not any(p in (c.name or "").lower() for p in lowered)
        ]
        for child in node.children:
            walk(child)

    walk(tree)


def run_responsive(
    *,
    url: str,
    file_key: str,
    specs: tuple[str, ...],
    client,
    mapping: list[ComponentMapping],
    registry: HookRegistry,
    output: Path | None,
    output_format: str,
    css_form: str,
    layout: str,
    strip_nodes: tuple[str, ...],
    shared_min_nodes: int,
    component_name: str | None,
    depth: int | None,
    offline: bool,
    human: bool,
    token_source: str | None,
) -> None:
    """Build one tree per frame, merge, write and emit the envelope."""
    try:
        frames_spec = parse_frame_specs(specs)
    except ValueError as e:
        emit_error("invalid_argument", str(e), exit_code=2)
        return

    if output_format.lower() != "react":
        emit_error(
            "invalid_argument",
            "--responsive requires --format react (the merged module is React)",
            exit_code=2,
        )
        return
    if css_form.lower() != "tailwind":
        emit_error(
            "invalid_argument",
            "--responsive requires --css tailwind (shared subtrees are matched on "
            "className; other CSS forms are not supported yet)",
            exit_code=2,
        )
        return

    built: list[Frame] = []
    warnings: list[str] = []
    frame_meta: list[dict] = []

    for name, node_id in frames_spec:
        ref = FigmaNodeRef(file_key=file_key, node_id=node_id)
        try:
            doc = client.get_node(ref, depth=depth)
        except FigmaError as e:
            emit_error("figma_not_found", f"frame {name!r} ({node_id}): {e}")
            return

        scene = SceneNode.from_dict(doc)
        if scene is None or scene.box is None:
            emit_error(
                "figma_node_not_found",
                f"frame {name!r} ({node_id}) has no bounding box; is it a FRAME/SECTION?",
                exit_code=2,
            )
            return

        if not offline:
            from avocado.parser.image_prefetch import prefetch_image_nodes

            stats = prefetch_image_nodes(client, file_key, scene)
            for err in stats.get("errors", []):
                warnings.append(f"[{name}] {err}")

        tree = map_node(
            scene,
            client=client,
            file_key=file_key,
            component_mapping=mapping,
            layout_mode=layout,
        )
        _strip_by_name(tree, list(strip_nodes))
        tree = apply_parse_passes(
            tree,
            registry=registry,
            css_form=css_form,
            auto_group_variance=False,
            inherit_promote=True,
            strip_defaults=True,
            unwrap_single=True,
            gap_to_margin_enabled=False,
        )
        apply_style_prop_modes(tree)
        apply_tailwind(tree)

        built.append(Frame(name=name, tree=tree, width=scene.box.width))
        frame_meta.append({"name": name, "node_id": node_id, "width": scene.box.width})

    try:
        result = merge_frames(
            built,
            page_name=component_name,
            min_shared_nodes=shared_min_nodes,
        )
    except ValueError as e:
        emit_error("invalid_argument", str(e), exit_code=2)
        return

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result.code, encoding="utf-8")

    data = {
        "output_path": str(output) if output else None,
        "output_type": "react",
        "jsx_omitted": True,
        "code_location": str(output) if output else None,
        "artifacts": {"jsxPath": str(output)} if output else {},
        "responsive": {
            "frames": frame_meta,
            "breakpoints": result.breakpoints,
            "shared_components": result.shared_components,
            "stats": result.stats,
        },
        "mode": {
            "format": "react",
            "css": css_form,
            "layout": layout,
            "component_lib": None,
            "responsive": True,
            "strip_nodes": list(strip_nodes),
            "shared_min_nodes": shared_min_nodes,
        },
        "token_source": token_source,
        "warnings": warnings or None,
        "hint": (
            "merged module: one layout per frame + useResponsiveBreakpoint() + "
            "shared components for identical subtrees; wire data/state by replacing "
            "the literal text with props"
        ),
    }

    if human:
        click.echo(result.code)
        if warnings:
            for w in warnings:
                click.echo(f"warning: {w}", err=True)
        sys.exit(0)

    emit_ok(data)
