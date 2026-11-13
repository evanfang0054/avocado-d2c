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

from avocado.api.figma import (
    FigmaAuthError,
    FigmaCacheMissError,
    FigmaError,
    FigmaNodeRef,
    FigmaNotFoundError,
    FigmaRateLimitError,
)
from avocado.envelope import emit_error, emit_ok
from avocado.generator.responsive import Frame, merge_frames
from avocado.generator.style_props import apply_style_prop_modes
from avocado.generator.tailwind import apply_tailwind
from avocado.model.scene_node import SceneNode
from avocado.parser.component import ComponentMapping
from avocado.parser.css_variable import collect_variables
from avocado.parser.inspect import collect_all_warnings, run_all_inspect_rules
from avocado.parser.node_mapper import map_node
from avocado.parser.optimize import reround_styles
from avocado.parser.passes import apply_parse_passes
from avocado.parser.var_map import load_var_map
from avocado.plugins.base import HookRegistry
from avocado.plugins.stages import apply_css_var_hook

_SPEC_HELP = "NAME=NODE_ID"


def _fail(message: str, code: str, human: bool, *, exit_code: int | None = None) -> None:
    """Report an error in the caller's mode (human stderr vs JSON envelope)."""
    if human:
        click.echo(f"error: {message}", err=True)
        sys.exit(exit_code or 1)
    if exit_code is None:
        emit_error(code, message)
    else:
        emit_error(code, message, exit_code=exit_code)


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


def _inspect_summary(entries: list[dict]) -> dict:
    """Aggregate inspect warnings by code/severity (mirrors the single-frame shape)."""
    by_code: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for entry in entries:
        code = str(entry.get("code", "?"))
        by_code[code] = by_code.get(code, 0) + 1
        severity = str(entry.get("severity", "info"))
        by_severity[severity] = by_severity.get(severity, 0) + 1
    return {"total": len(entries), "by_code": by_code, "by_severity": by_severity}


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
    css_vars: bool = False,
    var_map_path: Path | None = None,
    var_fallback: str = "literal",
    component_lib: str | None = None,
    precision: str = "2",
    beautify_flag: bool = True,
    figma_id: bool = False,
    auto_group_variance: bool = False,
    gap_to_margin: bool = False,
    box_sizing: str = "content-box",
    inspect: bool = False,
    summary: bool = False,
    trace_adapter: str | None = None,
    inspect_warnings: list[dict] | None = None,
) -> None:
    """Build one tree per frame, merge, write and emit the envelope."""
    try:
        frames_spec = parse_frame_specs(specs)
    except ValueError as e:
        _fail(str(e), "invalid_argument", human, exit_code=2)
        return

    if output_format.lower() != "react":
        _fail(
            "--responsive requires --format react (the merged module is React)",
            "invalid_argument",
            human,
            exit_code=2,
        )
        return
    if css_form.lower() != "tailwind":
        _fail(
            "--responsive requires --css tailwind (shared subtrees are matched on "
            "className; other CSS forms are not supported yet)",
            "invalid_argument",
            human,
            exit_code=2,
        )
        return

    built: list[Frame] = []
    warnings: list[str] = []
    frame_meta: list[dict] = []
    var_matched = 0
    var_total = 0

    # Flags accepted by the shared CLI surface but not implemented for the
    # merged output: say so instead of silently doing nothing.
    for flag, active in (
        ("--box-sizing", box_sizing.lower() != "content-box"),
        ("--summary", summary),
        ("--trace-adapter", trace_adapter is not None),
    ):
        if active:
            warnings.append(f"{flag} is ignored with --responsive")

    # Resolve the var-map once (same precedence as the single-frame path:
    # explicit --var-map > auto-load for --component-lib > empty fallback).
    var_map: dict[str, str] = {}
    if var_map_path is not None and not var_map_path.exists():
        _fail(f"--var-map file not found: {var_map_path}", "invalid_argument", human, exit_code=2)
        return
    if var_map_path is not None:
        import yaml as _yaml

        try:
            _vm_test = _yaml.safe_load(var_map_path.read_text(encoding="utf-8"))
            if not isinstance(_vm_test, dict):
                raise ValueError(f"top-level YAML is {type(_vm_test).__name__}, not a mapping")
        except Exception as e:  # noqa: BLE001 — surface as invalid_argument
            _fail(f"invalid YAML in --var-map: {e}", "invalid_argument", human, exit_code=2)
            return
    if css_vars:
        var_map = load_var_map(var_map_path) if var_map_path else {}
        if not var_map_path and component_lib:
            from avocado.paths import resolve_var_map

            auto = resolve_var_map(component_lib)
            if auto.exists():
                var_map = load_var_map(auto)
                if not var_map:
                    warnings.append(
                        f"--component-lib {component_lib} var-map file parsed to empty ({auto}); "
                        "all CSS variable references will use fallback values"
                    )
        if not var_map and not var_map_path and not component_lib:
            warnings.append(
                "--css-vars enabled but no --var-map given (and no --component-lib auto-load), "
                "all CSS variable references will use fallback values"
            )

    for name, node_id in frames_spec:
        ref = FigmaNodeRef(file_key=file_key, node_id=node_id)
        try:
            doc = client.get_node(ref, depth=depth)
        except FigmaError as e:
            if isinstance(e, FigmaAuthError):
                code = "figma_auth_failed"
            elif isinstance(e, FigmaNotFoundError):
                code = "figma_node_not_found"
            elif isinstance(e, FigmaCacheMissError):
                code = "figma_cache_miss"
            elif isinstance(e, FigmaRateLimitError):
                code = "figma_rate_limited"
            else:
                code = "figma_not_found"
            _fail(f"frame {name!r} ({node_id}): {e}", code, human)
            return

        scene = SceneNode.from_dict(doc)
        if scene is None or scene.box is None:
            _fail(
                f"frame {name!r} ({node_id}) has no bounding box; is it a FRAME/SECTION?",
                "figma_node_not_found",
                human,
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
            auto_group_variance=auto_group_variance,
            inherit_promote=True,
            strip_defaults=True,
            unwrap_single=True,
            gap_to_margin_enabled=gap_to_margin,
        )
        run_all_inspect_rules(tree)
        if inspect:
            inspect_warnings = inspect_warnings if inspect_warnings is not None else []
            for entry in collect_all_warnings(tree):
                entry = dict(entry)
                entry.setdefault("frame", name)
                inspect_warnings.append(entry)
        if css_vars:
            collection = collect_variables(
                scene,
                tree,
                var_map=var_map,
                with_fallback=True,
                fallback_mode=var_fallback,
            )
            collection.variables = apply_css_var_hook(registry, collection.variables)
            var_matched += collection.var_map_matched
            var_total += collection.var_map_total
        apply_style_prop_modes(tree)
        apply_tailwind(tree)
        if precision.lower() != "unset":
            reround_styles(tree, int(precision))
        # `_image_error` is a diagnostic prop (mirrors the single-frame path);
        # never let it reach the merged module.
        stack = [tree]
        while stack:
            node = stack.pop()
            image_error = node.props.pop("_image_error", None)
            if image_error:
                warnings.append(f"[{name}] {image_error}")
            stack.extend(node.children)

        built.append(Frame(name=name, tree=tree, width=scene.box.width))
        frame_meta.append({"name": name, "node_id": node_id, "width": scene.box.width})

    try:
        result = merge_frames(
            built,
            page_name=component_name,
            min_shared_nodes=shared_min_nodes,
            emit_figma_id=figma_id,
        )
    except ValueError as e:
        _fail(str(e), "invalid_argument", human, exit_code=2)
        return

    code = result.code
    beautified = False
    if beautify_flag:
        try:
            from avocado.api.jsx_beautify import JsxBeautifyError, beautify

            code = beautify(code.rstrip()) + "\n"
            beautified = True
        except JsxBeautifyError as e:
            warnings.append(f"beautify failed, using raw output: {e}")
        except Exception as e:  # noqa: BLE001 — beautify must never break delivery
            warnings.append(f"beautify failed, using raw output: {e}")

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(code, encoding="utf-8")

    if css_vars and var_total:
        _where = (
            "keep their literal values"
            if var_fallback == "literal"
            else "fall back to fig-var-<short>"
        )
        if var_matched == 0:
            warnings.append(
                f"--var-map matched 0 / {var_total} variable bindings; unmatched variables "
                f"{_where} (check that the var-map was exported from this file)"
            )
        elif var_matched < var_total:
            warnings.append(
                f"--var-map matched {var_matched} / {var_total} variable bindings; "
                f"{var_total - var_matched} {_where} "
                "(the var-map may predate this file's variables)"
            )

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
        "var_map_applied": (
            {"matched": var_matched, "total": var_total} if css_vars else None
        ),
        "inspect": inspect_warnings or None,
        "inspect_summary": (
            _inspect_summary(inspect_warnings) if inspect_warnings else None
        ),
        "beautified": beautified,
        "mode": {
            "format": "react",
            "css": css_form,
            "layout": layout,
            "component_lib": component_lib,
            "responsive": True,
            "strip_nodes": list(strip_nodes),
            "shared_min_nodes": shared_min_nodes,
            "css_vars": css_vars,
            "var_fallback": var_fallback,
            "precision": precision,
            "figma_id": figma_id,
            "has_output": output is not None,
            "passes": {
                "inherit_promote": True,
                "strip_defaults": True,
                "unwrap_single_child": True,
                "gap_to_margin": gap_to_margin,
                "auto_group_variance": auto_group_variance,
            },
        },
        "token_source": token_source,
        "warnings": warnings or None,
        "hints": [
            "merged module: one layout per frame + useResponsiveBreakpoint() + "
            "shared components for identical subtrees; wire data/state by replacing "
            "the literal text with props"
        ],
    }

    if human:
        click.echo(code)
        if warnings:
            for w in warnings:
                click.echo(f"warning: {w}", err=True)
        sys.exit(0)

    emit_ok(data)
