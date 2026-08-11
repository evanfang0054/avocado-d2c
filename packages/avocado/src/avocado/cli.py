"""avocado CLI entry point.

Scope:
    avocado <figma-url> -o <output.jsx>
    avocado <figma-url> --stdout

Adds layout, components, and beautify integration.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from avocado.api.figma import (
    FigmaAuthError,
    FigmaCacheMissError,
    FigmaClient,
    FigmaError,
    FigmaNotFoundError,
    FigmaRateLimitError,
    parse_figma_url,
)
from avocado.envelope import emit_error, emit_ok
from avocado.generator.codegen import render_jsx
from avocado.generator.css_class import apply_css_class, render_css_block
from avocado.model.scene_node import SceneNode
from avocado.model.tree_node import TreeNode
from avocado.parser.component import load_mapping, load_preset
from avocado.parser.css_variable import collect_variables
from avocado.parser.inspect import collect_all_warnings, run_all_inspect_rules
from avocado.parser.node_mapper import map_node
from avocado.parser.optimize import (
    apply_auto_group_variance,
    apply_semantic_tags,
    gap_to_margin,
    promote_inherited_styles,
    reround_class_map,
    reround_styles,
    strip_default_styles,
    unwrap_single_child,
)
from avocado.parser.var_map import load_var_map
from avocado.plugins.base import build_registry, default_plugin_dirs


def _sanitize_ansi(text: str) -> str:
    """FIX: strip area ANSI color escape codes (\\x1b[31m etc.).

    Third-party subprocess (Figma fetch etc.) error output may contain color
    control chars; embedding them in envelope warnings breaks the JSON plain-text
    semantics (grep/regex/area rendering all suffer).
    """
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text) if text else text


def _human_error(msg: str, hint: str | None = None, exit_code: int = 2) -> None:
    """FIX: unified human-mode error output (message + optional hint).

    Previously the --human branches only did click.echo(f"error: {msg}") without
    a hint, carrying less info than JSON mode. Use this function uniformly: print
    the error line first, then the hint line (if any).
    """
    click.echo(f"error: {msg}", err=True)
    if hint:
        click.echo(f"hint: {hint}", err=True)
    sys.exit(exit_code)


@click.command()
@click.argument(
    "url",
    type=str,
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write output JSX file (default: stdout).",
)
@click.option(
    "--token",
    envvar=None,  # FIX: don't let Click swallow FIGMA_TOKEN — resolve_token handles it
    help="Figma Personal Access Token (or set FIGMA_TOKEN env var).",
)
@click.option(
    "--cache-dir",
    "cache_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Developer mode: mirror fetched Figma data (node JSON + images) "
    "into this directory. Re-runs read from cache instead of the network.",
)
@click.option(
    "--offline",
    is_flag=True,
    default=False,
    help="Offline mode: read node JSON + images ONLY from --cache-dir. "
    "No network calls. Requires --cache-dir populated by a prior online run.",
)
@click.option(
    "--depth",
    type=int,
    default=None,
    help=(
        "Max tree depth when fetching from Figma API. "
        "Warning: low values (1-5) significantly truncate the tree; "
        "Figma designs typically nest 10-20 levels. "
        "Use depth >= 20 for full coverage, or omit for unlimited."
    ),
)
@click.option(
    "--inspect/--no-inspect",
    default=True,
    help="Emit inspect-draft warnings to stderr.",
)
@click.option(
    "--beautify/--no-beautify",
    "beautify_flag",
    default=True,
    help="Post-process output with the built-in JSX beautifier (default: on). "
    "Pass --no-beautify to emit raw codegen output.",
)
@click.option(
    "--components",
    "--components-file",
    "components",
    # FIX: don't use exists=True (Click would validate first, before the business
    # mutual-exclusion check). Validate manually in the business logic (main, ~line 296)
    # so the mutual-exclusion check reports first.
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="YAML file with INSTANCE → business component mapping. "
    "FIX: alias --components-file is more explicit (distinct from the --component-lib preset name).",
)
@click.option(
    "--component-lib",
    "component_lib",
    type=str,
    default=None,
    help="Built-in component library preset name (e.g. 'antd'). "
    "Loads presets/<name>.yaml. Mutually exclusive with --components.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["react", "html", "inline", "tailwind"], case_sensitive=False),
    default="react",
    help=(
        "Output structure: 'react' (default, full .jsx file with "
        "export default function wrapper) or 'html' (HTML fragment). "
        "'inline'/'tailwind' are deprecated aliases, use --css instead."
    ),
)
@click.option(
    "--css",
    "css_form",
    type=click.Choice(["inline", "tailwind", "class"], case_sensitive=False),
    default="tailwind",
    help="CSS form: 'tailwind' (default, className + leftover style), "
    "'inline' (style attr), or 'class' (extract to a .css file).",
)
@click.option(
    "--layout",
    type=click.Choice(["flex", "absolute"], case_sensitive=False),
    default="flex",
    help="Layout strategy: 'flex' (default) or 'absolute' (bbox-perfect).",
)
@click.option(
    "--css-vars/--no-css-vars",
    "css_vars",
    default=False,
    help="Emit var(--name, fallback) references for Figma Variable bindings. "
    "Default off; requires a var-map to resolve semantic names.",
)
@click.option(
    "--var-map",
    "var_map_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="YAML file mapping VariableID → semantic CSS variable name. "
    "If omitted with --component-lib, auto-loads var-maps/<lib>.yaml.",
)
# ── optimization passes ──
@click.option(
    "--precision",
    default="2",
    type=click.Choice(["0", "1", "2", "unset"], case_sensitive=False),
    help="Re-round numeric CSS values to N decimals (default '2'). "
    "'unset' leaves values untouched.",
)
@click.option(
    "--box-sizing",
    "box_sizing",
    default="content-box",
    type=click.Choice(["content-box", "border-box"], case_sensitive=False),
    help="Box-sizing for the leading <style> reset. Default "
    "'content-box' preserves original geometry. 'border-box' includes "
    "padding+border in width/height — width/height are NOT auto-recomputed.",
)
@click.option(
    "--gap-to-margin/--no-gap-to-margin",
    "gap_to_margin_flag",
    default=False,
    help="Replace flex gap with per-child margin-right/margin-bottom.",
)
@click.option(
    "--auto-group-variance/--no-auto-group-variance",
    "auto_group_variance_flag",
    default=False,
    help="Orient auto_group nodes via child-position variance.",
)
@click.option(
    "--inherit-promote/--no-inherit-promote",
    "inherit_promote_flag",
    default=True,
    help="Lift common inheritable CSS props (color, font-*, ...) up the tree.",
)
@click.option(
    "--strip-defaults/--no-strip-defaults",
    "strip_defaults_flag",
    default=True,
    help="Drop CSS properties whose value equals the spec default.",
)
@click.option(
    "--unwrap-single/--no-unwrap-single",
    "unwrap_single_flag",
    default=True,
    help="Collapse single-child FRAME/GROUP wrappers with no visual style.",
)
@click.option(
    "--human",
    "human",
    is_flag=True,
    default=False,
    help="Human-readable output (legacy click.echo to stdout/stderr). "
    "Default is agent-native JSON envelope on stdout (subcommand mode). "
    "Use --human to keep the legacy behavior (e.g. for shell pipes "
    "and old tests that parse stdout text). "
    "WARNING: --human breaks the JSON envelope contract on stdout "
    "(d2c emits raw JSX). AI agents should NOT use --human.",
)
@click.option(
    "--figma-id",
    "figma_id",
    is_flag=True,
    default=False,
    help="Emit data-figma-id debug attributes on every node (default: off, clean output). "
    "Turn on for traceability/debugging.",
)
@click.option(
    "--summary",
    "summary",
    is_flag=True,
    default=False,
    help="Reduce envelope size — omit jsx/css text, return only metadata + paths.",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    default=False,
    help="Validate URL + token + params without calling Figma API or writing files. "
    "Returns envelope with validated params + would_write paths. No side effects.",
)
@click.option(
    "--preset",
    "preset",
    type=click.Choice(["designer", "dev", "compare-ready"], case_sensitive=False),
    default=None,
    help="Bundled flag preset. designer=HTML full document + no data-figma-id; "
    "dev=react+tailwind (no component library); "
    "compare-ready=react+extracted css+summary. "
    "Explicit flags override preset on conflict (warning emitted).",
)
@click.option(
    "--html-fragment",
    "html_fragment",
    is_flag=True,
    default=False,
    help="Fall back to a bare <div> fragment (default: --format html emits a full HTML document with doctype)."
    "The designer preset defaults to a full document; add this flag to fall back to a fragment.",
)
@click.option(
    "--preview-centered",
    "preview_centered",
    is_flag=True,
    default=False,
    help="Add preview-centering styles to HTML output (gray bg + centered + shadow + rounded)."
    "On by default with the designer preset; off by default for plain --format html.",
)
def main(
    url: str,
    output: Path | None,
    token: str | None,
    depth: int | None,
    inspect: bool,
    beautify_flag: bool,
    cache_dir: Path | None,
    offline: bool,
    components: Path | None,
    component_lib: str | None,
    output_format: str,
    css_form: str,
    layout: str,
    css_vars: bool,
    var_map_path: Path | None,
    precision: str,
    box_sizing: str,
    gap_to_margin_flag: bool,
    auto_group_variance_flag: bool,
    inherit_promote_flag: bool,
    strip_defaults_flag: bool,
    unwrap_single_flag: bool,
    human: bool = False,
    figma_id: bool = False,
    summary: bool = False,
    dry_run: bool = False,
    preset: str | None = None,
    html_fragment: bool = False,
    preview_centered: bool = False,
) -> None:
    """Convert a Figma node URL to JSX code.

    URL must include ?node-id=... e.g.
      avocado "https://www.figma.com/design/XXXX/Title?node-id=10:20"

    \b
    Subcommands (subcommand mode):
      avocado schema                 Output JSON envelope with all commands/flags
      avocado init                   Configure figma_token (interactive)

    Default (no subcommand): agent-native JSON envelope on stdout.
    Use --human for legacy colored stderr output (shell pipes).
    """
    # //FIX: pass the warnings array through to the envelope (agents can see it)
    warnings: list[str] = []

    # FIX: forbid -o /dev/stdout (JSX + envelope both writing stdout breaks the JSON contract)
    # Also forbid /dev/null & /dev/zero: they accept writes but you can never
    # read the code back, so the "read output_path for the code" hint misleads.
    _rejected_output = {"/dev/stdout", "/dev/fd/1", "-", "/dev/null", "/dev/zero"}
    if output is not None:
        out_str = str(output)
        if out_str in _rejected_output:
            if human:
                click.echo(
                    f"error: -o {out_str!r} is not allowed "
                    "(would discard the generated code or mix with the JSON envelope)",
                    err=True,
                )
                sys.exit(2)
            emit_error(
                "invalid_argument",
                f"-o {out_str!r} is not allowed — the generated code would be lost "
                "or mixed with the JSON envelope on stdout",
                hint="omit -o to get JSX in data.jsx, or write to a real file path",
                exit_code=2,
            )
    # format_raw: user's raw --format input (before preset expansion / mapping).
    # Use ParameterSource to distinguish "user passed --format on CLI" from
    # "click default value" — the latter happens when --preset indirectly sets
    # --format (preset expansion below mutates output_format, so checking the
    # value alone can't tell us the user's intent).
    from click.core import ParameterSource as _PS

    _ctx_for_fmt = click.get_current_context()
    _fmt_source = _ctx_for_fmt.get_parameter_source("output_format")
    format_raw = output_format.lower() if _fmt_source == _PS.COMMANDLINE else None

    # FIX: record the start time, compute duration at emit_ok
    import time as _time

    _start_ts = _time.monotonic()

    # Deprecation shim: old --format inline|tailwind → new --format html
    # + --css inline|tailwind. Kept short-term for compatibility.
    if output_format.lower() in ("inline", "tailwind"):
        css_form = output_format.lower()
        output_format = "html"
        dep_msg = (
            f"--format {css_form} is deprecated (will be removed in a future release); "
            f"use --format html --css {css_form} instead"
        )
        click.echo(f"warning: {dep_msg}", err=True)
        warnings.append(dep_msg)

    # --preset expands bundled flag groups.
    # designer = --format html (full HTML document; data-figma-id off by default)
    # dev = --format react --css tailwind (no component library — add
    # --component-lib <name> explicitly when a preset is needed)
    # compare-ready = --format react --css class --summary
    # Conflict detection uses ctx.get_parameter_source to see if a flag
    # was explicitly passed by the user.
    preset_expanded: dict | None = None
    if preset is not None:
        _PRESETS: dict[str, dict[str, tuple]] = {
            # value tuple: (flag_dest_name, target_value, cli_flag_display)
            "designer": {
                "output_format": ("output_format", "html", "--format"),
                "preview_centered": ("preview_centered", True, "--preview-centered"),
            },
            "dev": {
                "output_format": ("output_format", "react", "--format"),
                "css_form": ("css_form", "tailwind", "--css"),
            },
            "compare-ready": {
                "output_format": ("output_format", "react", "--format"),
                "css_form": ("css_form", "class", "--css"),
                "summary": ("summary", True, "--summary"),
            },
        }
        preset_key = preset.lower()
        preset_def = _PRESETS[preset_key]
        ctx = click.get_current_context()
        from click.core import ParameterSource

        preset_expanded = {}
        for dest, (var_name, target_val, cli_display) in preset_def.items():
            # Check whether the user explicitly passed this flag (conflict)
            src = ctx.get_parameter_source(dest)
            explicit = src == ParameterSource.COMMANDLINE
            current_val = locals().get(var_name)
            if explicit and current_val != target_val:
                # Explicit flag conflicts with preset — explicit wins
                warnings.append(
                    f"preset '{preset_key}' sets {cli_display}={target_val!r}, "
                    f"but explicit {cli_display}={current_val!r} overrides "
                    f"(explicit flag takes precedence)"
                )
                preset_expanded[cli_display] = current_val
            else:
                # Preset applies (explicit same value or not passed)
                # Mutate the actual variable.
                if var_name == "output_format":
                    output_format = target_val
                elif var_name == "css_form":
                    css_form = target_val
                elif var_name == "summary":
                    summary = target_val
                elif var_name == "preview_centered":
                    preview_centered = target_val
                preset_expanded[cli_display] = target_val

    # FIX: mutual-exclusion check moved up front (before client init) to avoid a Python traceback.
    # FIX: depth check moved up front (before any Figma API call).
    if components is not None and component_lib is not None:
        msg = "--components and --component-lib are mutually exclusive"
        if human:
            click.echo(f"error: {msg}", err=True)
            sys.exit(2)
        emit_error("invalid_argument", msg, exit_code=2)
    if depth is not None and depth <= 0:
        msg = f"--depth must be > 0 (got {depth})"
        if human:
            click.echo(f"error: {msg}", err=True)
            sys.exit(2)
        emit_error("invalid_argument", msg, exit_code=2)
    # Low depth warning: Figma designs typically nest 10-20 levels, so low
    # values produce near-empty output. Don't fail — just surface a hint so
    # the user understands why the output is sparse.
    if depth is not None and depth < 5:
        warnings.append(
            f"--depth {depth} significantly truncates the tree "
            "(Figma designs typically nest 10-20 levels). "
            "Use depth >= 20 for full coverage, or omit for unlimited."
        )
    # FIX: when --var-map is passed explicitly the file must exist (otherwise Click path validation + silent later behavior)
    if var_map_path is not None and not var_map_path.exists():
        msg = f"--var-map file not found: {var_map_path}"
        if human:
            click.echo(f"error: {msg}", err=True)
            sys.exit(2)
        emit_error("invalid_argument", msg, exit_code=2)
    # FIX: --components file must exist + contain valid YAML
    if components is not None and not components.exists():
        msg = f"--components file not found: {components}"
        if human:
            click.echo(f"error: {msg}", err=True)
            sys.exit(2)
        emit_error("invalid_argument", msg, exit_code=2)

    try:
        ref = parse_figma_url(url)
    except FigmaError as e:
        # FIX: distinguish auth_failed / not_found / rate_limited / generic
        # so the agent can give the user accurate advice (swap token vs swap URL).
        # FIX: human mode also outputs a hint (same info as JSON mode)
        from avocado.envelope import ERROR_CODES as _EC

        if isinstance(e, FigmaAuthError):
            # FIX: when the message contains "no token", the hint should say "set" rather than "regenerate"
            # (a new user never set a token; it's not expired)
            _auth_hint = (
                "no FIGMA_TOKEN found — set FIGMA_TOKEN env var or run `avocado init`"
                if "no token" in str(e).lower()
                else _EC["figma_auth_failed"]["hint"]
            )
            if human:
                _human_error(f"figma auth: {e}", _auth_hint, exit_code=1)
            emit_error("figma_auth_failed", str(e), hint=_auth_hint)
            # FIX: distinguish figma_file_not_found vs figma_node_not_found via e.kind
            _kind = getattr(e, "kind", None)
            if _kind == "file":
                _code = "figma_file_not_found"
            elif _kind == "node":
                _code = "figma_node_not_found"
            else:
                _code = "figma_not_found"
            if human:
                _human_error(f"figma not found: {e}", _EC[_code]["hint"], exit_code=1)
            emit_error(_code, str(e))
        elif isinstance(e, FigmaRateLimitError):
            if human:
                _human_error(
                    f"figma rate limited: {e}", _EC["figma_rate_limited"]["hint"], exit_code=1
                )
            emit_error("figma_rate_limited", str(e))
        else:
            # FIX: give a concrete URL-fix hint based on the error message (not a generic "run avocado schema")
            _err_msg = str(e)
            if "not a valid figma url" in _err_msg or "cannot parse figma url" in _err_msg:
                _url_hint = (
                    "not a valid Figma URL. Expected figma.com/file/<key> or figma.com/design/<key> format. "
                    "Example: https://www.figma.com/design/XXXX/Title?node-id=1:2"
                )
            elif "node-id" in _err_msg:
                _url_hint = "URL is missing the ?node-id= parameter. Right-click the node in Figma → Copy link to get the full URL"
            else:
                _url_hint = _EC["invalid_argument"]["hint"]
            if human:
                _human_error(f"{e}", _url_hint, exit_code=2)
            emit_error("invalid_argument", f"bad URL: {e}", hint=_url_hint, exit_code=2)

    # Resolve component mapping early: --components takes precedence over
    # --component-lib. The mutual-exclusion check already ran up front (FIX:).
    if components is not None:
        # FIX: load_mapping may raise yaml.YAMLError or other parse exceptions
        try:
            component_mapping = load_mapping(components)
        except Exception as e:
            msg = f"invalid YAML in --components: {e}"
            if human:
                click.echo(f"error: {msg}", err=True)
                sys.exit(2)
            emit_error("invalid_argument", msg, exit_code=2)
    elif component_lib is not None:
        try:
            component_mapping = load_preset(component_lib)
        except (FileNotFoundError, ValueError) as e:
            # FIX: message no longer prefixes "unknown component library preset:"
            # (the message raised by component.py already contains this prefix)
            # FIX: also catch ValueError (user preset file with a broken structure,
            # e.g. missing components key) and report invalid_argument rather than internal_error.
            if human:
                click.echo(f"error: {e}", err=True)
                sys.exit(2)
            emit_error("invalid_argument", str(e), exit_code=2)
    else:
        component_mapping = []

    try:
        client = FigmaClient(
            token=token,
            cache_dir=cache_dir,
            offline=offline,
        )
    except FigmaError as e:
        # FIX: distinguish the failure type when client creation fails (mostly auth errors)
        # FIX: human mode also outputs a hint
        from avocado.envelope import ERROR_CODES as _EC

        if isinstance(e, FigmaAuthError):
            # FIX: when the message contains "no token", the hint should say "set" rather than "regenerate"
            _auth_hint2 = (
                "no FIGMA_TOKEN found — set FIGMA_TOKEN env var or run `avocado init`"
                if "no token" in str(e).lower()
                else _EC["figma_auth_failed"]["hint"]
            )
            if human:
                _human_error(f"figma auth: {e}", _auth_hint2, exit_code=1)
            emit_error("figma_auth_failed", str(e), hint=_auth_hint2)
        else:
            emit_error("invalid_argument", str(e), exit_code=2)
        return  # emit_error already sys.exit'ed; return as a guard against UnboundLocalError
    except (OSError, NotADirectoryError) as e:
        # FIX: mkdir fails when --cache-dir points to an uncreatable path (e.g. /dev/null/cannot);
        # FigmaClient.__init__ does not catch OSError, so wrap it uniformly as an envelope here
        ename = type(e).__name__
        if human:
            _human_error(
                f"cache dir: {ename}: {e}",
                "check --cache-dir points to a writable, creatable directory",
                exit_code=2,
            )
        emit_error(
            "invalid_argument",
            f"cannot create cache dir {cache_dir}: {ename}: {e}",
            hint="check --cache-dir points to a writable, creatable directory",
            exit_code=2,
        )
        return

    # FIX: --dry-run short-circuits — after validating URL + token + params + client creation,
    # it does not call the Figma API or write files; it returns validated params + would_write paths.
    # Lets agents probe parameter validity safely without polluting ~/.avocado/output/.
    if dry_run:
        from avocado.paths import resolve_token

        _ts = resolve_token(
            token
        )  # probe the token source again (so dry-run reports a missing token)
        _token_source = (
            "cli_flag"
            if token
            else (
                "env_var" if os.environ.get("FIGMA_TOKEN") else ("config_file" if _ts else "none")
            )
        )
        emit_ok(
            {
                "dry_run": True,
                "validated": {
                    "url": url,
                    "file_key": ref.file_key,
                    "node_id": ref.node_id,
                    "format": output_format,
                    "format_raw": format_raw,  # user's raw --format (None if preset/default)
                    "css": css_form,
                    "layout": layout,
                    "component_lib": component_lib,
                    "offline": offline,
                    "summary": summary,
                },
                "token_source": _token_source,
                "would_write": [str(output)] if output else [],
                "hint": "dry-run only validates params; it does not call the Figma API or write files. Remove --dry-run to run the real generation.",
            }
        )
        return

    try:
        doc_json = client.get_node(ref, depth=depth)
    except FigmaError as e:
        # FIX: distinguish auth_failed / not_found / rate_limited
        # FIX: human mode also outputs a hint
        from avocado.envelope import ERROR_CODES as _EC

        if isinstance(e, FigmaAuthError):
            # FIX: when the message contains "no token", the hint should say "set" rather than "regenerate"
            _auth_hint3 = (
                "no FIGMA_TOKEN found — set FIGMA_TOKEN env var or run `avocado init`"
                if "no token" in str(e).lower()
                else _EC["figma_auth_failed"]["hint"]
            )
            if human:
                _human_error(f"figma auth: {e}", _auth_hint3, exit_code=1)
            emit_error("figma_auth_failed", f"figma api: {e}", hint=_auth_hint3)
        elif isinstance(e, FigmaNotFoundError):
            # FIX: distinguish file vs node
            _kind = getattr(e, "kind", None)
            _code = (
                "figma_file_not_found"
                if _kind == "file"
                else ("figma_node_not_found" if _kind == "node" else "figma_not_found")
            )
            if human:
                _human_error(f"figma api: {e}", _EC[_code]["hint"], exit_code=1)
            emit_error(_code, f"figma api: {e}")
        elif isinstance(e, FigmaCacheMissError):
            # FIX: offline cache miss uses a dedicated code (not figma_not_found)
            if human:
                _human_error(f"figma cache miss: {e}", _EC["figma_cache_miss"]["hint"], exit_code=1)
            emit_error("figma_cache_miss", f"figma api: {e}")
        elif isinstance(e, FigmaRateLimitError):
            if human:
                _human_error(
                    f"figma rate limited: {e}", _EC["figma_rate_limited"]["hint"], exit_code=1
                )
            emit_error("figma_rate_limited", f"figma api: {e}")
        else:
            if human:
                _human_error(f"figma api: {e}", _EC["figma_not_found"]["hint"], exit_code=1)
            emit_error("figma_not_found", f"figma api: {e}")

    scene = SceneNode.from_dict(doc_json)

    # ── image prefetch ──
    # Single batched API call + concurrent download for all image nodes in
    # the tree. Without this, each VECTOR/INSTANCE/RECTANGLE rendered as
    # <img> triggers its own serial /v1/images request (1-3s each + rate
    # limit) — pages with 50-100+ icons take 3-5 minutes. Prefetch collapses
    # that to ⌈N/50⌉ API calls and 8-thread download fan-out.
    if not offline:
        from avocado.parser.image_prefetch import prefetch_image_nodes

        stats = prefetch_image_nodes(client, ref.file_key, scene)
        r_hit, r_fetch = stats["raster"]
        v_hit, v_fetch = stats["vector"]
        total = r_hit + r_fetch + v_hit + v_fetch
        # Image-prefetch logging is silent by default (meaningless to agents/new users).
        # Only printed when AVOCADO_VERBOSE=1 (for developer debugging; FIX: no -v flag).
        if total and os.environ.get("AVOCADO_VERBOSE"):
            click.echo(
                f"[info] image-prefetch raster={r_hit}hit+{r_fetch}fetch "
                f"vector={v_hit}hit+{v_fetch}fetch",
                err=True,
            )

    # Run user plugins: modify_json_schema, modify_style, etc.
    # Signal component mode to plugins via env var: name-based
    # recognizer plugins should no-op when the user didn't opt into
    # component recognition (--components / --component-lib), otherwise
    # they leak component-library imports into pure-div output.
    os.environ["AVOCADO_COMPONENT_MODE"] = (
        "1" if (components is not None or component_lib is not None) else "0"
    )
    plugin_dirs = default_plugin_dirs()
    registry = build_registry(*plugin_dirs)
    # register_extractor is called at import time to register the dynamicProps extractor. If it were
    # loaded after map_node, run_extractor would get an empty registry during component recognition,
    # silently dropping the props of all data-driven components (Steps/Tabs/Accordion...).

    tree = map_node(
        scene,
        client=client,
        file_key=ref.file_key,
        component_mapping=component_mapping,
        layout_mode=layout,
    )

    # ── post-parse optimization passes (pre-plugin) ──
    # Order matters:
    # 1. auto_group_variance — orient ambiguous containers first so
    # subsequent structural passes see a stable flex direction.
    # 2. inherit_promote — lift common inherited props before
    # strip_defaults touches them.
    # 3. strip_defaults — drop defaults now that inherit-promote
    # has consolidated values.
    # 4. unwrap_single_child — collapse wrappers after style is settled.
    # 5. gap_to_margin — last; depends on final flex-direction.
    if auto_group_variance_flag:
        apply_auto_group_variance(tree)
    if inherit_promote_flag:
        promote_inherited_styles(tree)
    if strip_defaults_flag:
        strip_default_styles(tree)
    if unwrap_single_flag:
        tree = unwrap_single_child(tree)
    if gap_to_margin_flag:
        gap_to_margin(tree)

    # 6. semantic_tags — rewrite tag_name for landmark nodes
    # (header/nav/main/footer/aside/article/section). Runs LAST
    # because it only touches tag_name, never style/layout — no
    # risk of breaking earlier passes. Zero visual impact (CSS
    # treats <header> same as <div>), but improves SEO/a11y/JDX
    # readability. Conservative: skips component/img/text nodes.
    apply_semantic_tags(tree)

    # Plugin loading moved BEFORE map_node (see above). Here we only
    # invoke the hooks that run on the fully-built tree.
    if registry.has("modify_json_schema"):
        tree = registry.call("modify_json_schema", None, tree)
    if registry.has("modify_style"):
        # Walk tree, apply modify_style per node
        stack = [tree]
        while stack:
            n = stack.pop()
            new_style = registry.call("modify_style", n, dict(n.style))
            n.style = new_style
            stack.extend(n.children)

    # ── CSS variable replacement ──
    css_collection = None  # set when css_vars=True; surfaced in envelope
    if css_vars:
        # FIX: error out when an explicit --var-map file is missing instead of silently ignoring it
        if var_map_path is not None and not var_map_path.exists():
            msg = f"--var-map file not found: {var_map_path}"
            if human:
                click.echo(f"error: {msg}", err=True)
                sys.exit(2)
            emit_error("invalid_argument", msg, exit_code=2)
        # FIX: explicit --var-map file exists but has broken YAML → invalid_argument
        # (consistent with --components, rather than silently returning {} so all var use fallback)
        if var_map_path is not None and var_map_path.exists():
            import yaml as _yaml

            try:
                _vm_test = _yaml.safe_load(var_map_path.read_text(encoding="utf-8"))
                if not isinstance(_vm_test, dict):
                    raise ValueError(f"top-level YAML is {type(_vm_test).__name__}, not a mapping")
            except Exception as e:
                msg = f"invalid YAML in --var-map: {e}"
                if human:
                    click.echo(f"error: {msg}", err=True)
                    sys.exit(2)
                emit_error("invalid_argument", msg, exit_code=2)
        var_map = load_var_map(var_map_path) if var_map_path and var_map_path.exists() else {}
        if not var_map_path and component_lib:
            # 4-layer lookup: cwd/.avocado/var-maps/ > ~/.avocado/var-maps/ > bundled _bundled/
            from avocado.paths import resolve_var_map

            auto = resolve_var_map(component_lib)
            if auto.exists():
                var_map = load_var_map(auto)
                # FIX: when auto-loading the var-map for a
                # --component-lib, a missing/broken file should not claim
                # the user also skipped auto-loading (they did pass it)
                if not var_map:
                    warnings.append(
                        f"--component-lib {component_lib} var-map file parsed to empty"
                        f" ({auto}); all CSS variable references will use fallback values"
                    )
        # FIX: warn when --css-vars is set without --var-map and without --component-lib auto-load
        if not var_map and not var_map_path and not component_lib:
            warnings.append(
                "--css-vars enabled but no --var-map given (and no --component-lib auto-load), "
                "all CSS variable references will use fallback values"
            )
        css_collection = collect_variables(scene, tree, var_map=var_map, with_fallback=True)
        # Warn when --var-map was provided but matched zero bindings — the user
        # explicitly opted in but the Figma file has no usable boundVariables
        # (or the VariableIDs don't match the var-map keys). Without this
        # warning the output silently uses fig-var-<short> names instead of
        # the semantic names the user expected.
        if css_collection.var_map_total > 0 and css_collection.var_map_matched == 0:
            _vm_src = (
                str(var_map_path)
                if var_map_path
                else (
                    f"--component-lib {component_lib} auto-load" if component_lib else "(unknown)"
                )
            )
            warnings.append(
                f"--var-map loaded from {_vm_src} but matched 0 / "
                f"{css_collection.var_map_total} bindings — possible causes: "
                "(1) the Figma file uses Styles not Variables; "
                "(2) var-map keys don't match this file's VariableIDs; "
                "(3) --depth too low returned shallow boundVariables. "
                "All CSS variable references will use fig-var-<short> fallback names."
            )

    # Run all inspectDraft rules. Warnings attach to tree nodes in-place;
    # the return value is intentionally discarded (call sites use tree.inspect).
    run_all_inspect_rules(tree)

    # Convert to Tailwind className form if requested.
    # css_form reflects the user's --css choice (defaults to tailwind).
    if css_form.lower() == "tailwind":
        from avocado.generator.tailwind import apply_tailwind

        apply_tailwind(tree)

    # CSS class extraction: must run AFTER all style passes
    # (inherit/strip/unwrap/gap) so the class map reflects the final
    # styles, but BEFORE reround so reround can sweep the class_map too.
    css_text: str | None = None
    class_map: dict[str, dict] = {}
    if css_form.lower() == "class":
        class_map = apply_css_class(tree)
        css_text = render_css_block(class_map)

    # Re-round numeric CSS to target precision. Must be the last
    # style mutation — other passes may write new numeric strings.
    if precision.lower() != "unset":
        p = int(precision)
        reround_styles(tree, p)
        if class_map:
            reround_class_map(class_map, p)
            css_text = render_css_block(class_map)

    # FIX: strip the _image_error diagnostic attribute before render_jsx so it doesn't leak into the output JSX.
    # Collect them into the image_errors list for the envelope warnings later.
    image_errors: list[str] = []
    _stack = [tree]
    while _stack:
        _n = _stack.pop()
        if hasattr(_n, "props"):
            ie = _n.props.pop("_image_error", None)
            if ie:
                image_errors.append(ie)
        _stack.extend(getattr(_n, "children", []) or [])

    # Render JSX. `box_sizing` injects a leading <style>*{box-sizing:...}</style>
    # so the output is self-contained for browser preview.
    # Only inject for non-default values. content-box is the browser
    # default — emitting <style>*{box-sizing:content-box}</style> is pure
    # noise (comparison with reference D2C output motivated this cleanup).
    box_sizing_arg = box_sizing if css_form.lower() != "class" else box_sizing
    if box_sizing_arg and box_sizing_arg.lower() == "content-box":
        box_sizing_arg = None  # default value — don't inject
    jsx = render_jsx(
        tree,
        indent=2,
        format=output_format,
        css=css_form,
        box_sizing=box_sizing_arg,
        emit_figma_id=figma_id,
    )

    # When --css class: also write a sibling .css file next to the JSX.
    css_path: Path | None = None
    if css_form.lower() == "class" and css_text and output:
        css_path = output.with_suffix(".css")
        # FIX: with -o file.css, css_path == output and the CSS would overwrite the JSX
        if css_path == output:
            warnings.append(
                f"-o path {output.name} ends with .css; the --css class CSS file"
                f" ({css_path.name}) will overwrite the JSX content. Use a .jsx suffix or another name"
            )
    elif css_form.lower() == "class" and css_text and not output:
        # Stdout mode: emit CSS as a fenced block on stderr so the JSX on
        # stdout remains parseable.
        pass

    beautified = False  # FIX: envelope passes through whether beautify applied successfully
    if beautify_flag:
        # FIX: HTML fragment is not beautified.
        # HTML output has two fatal flaws that make JS parsers report syntax errors:
        # 1. In the box-sizing `<style>*{box-sizing:...}</style>`, the CSS content
        # `{box-sizing:...}` is treated as a JSX expression container → `Expected '}', got ':'`
        # 2. HTML output is multi-root JSX (`<style>` adjacent to the body `<div>`), not wrapped
        # in a `<></>` Fragment → `Expected ';', '}' or <eof>`
        # An HTML fragment is not a valid JS/JSX module; codegen output is already canonical and stable,
        # no beautify normalization needed. Only React mode runs beautify.
        # Use an explicit note (not a warning) so users don't think "beautify failed".
        if output_format == "html":
            warnings.append(
                "beautify skipped for HTML output (HTML fragment is not a "
                "JS/JSX module; use --format react to enable beautify)"
            )
        else:
            # Optional: post-process through tree-sitter to normalize output
            try:
                from avocado.api.jsx_beautify import JsxBeautifyError, beautify

                jsx = beautify(jsx.rstrip()) + "\n"
                beautified = True
            except JsxBeautifyError as e:
                w = f"beautify failed, using raw output: {e}"
                click.echo(f"warning: {w}", err=True)
                warnings.append(w)
            except Exception as e:
                w = f"beautify failed, using raw output: {e}"
                click.echo(f"warning: {w}", err=True)
                warnings.append(w)

    # Requirement 3: HTML mode defaults to a full HTML document (doctype + viewport + body wrapper).
    # The --html-fragment flag reverts to the old bare <div> fragment behavior.
    # Wrapping happens after beautify (HTML mode already skips beautify, no conflict).
    # Issue 9: when preview_centered=True, add preview-centering styles (gray bg + centered + shadow).
    # --html-fragment only makes sense for HTML output; with react/other formats
    # the flag is silently meaningless, so warn instead of pretending it applies.
    if html_fragment and output_format.lower() != "html":
        warnings.append(
            f"--html-fragment is ignored for --format {output_format} "
            "(it only applies to --format html)"
        )
    html_wrapped = False
    if output_format.lower() == "html" and not html_fragment:
        from avocado.generator.html_doc import wrap_html_document

        jsx = wrap_html_document(jsx, root=tree, preview_centered=preview_centered)
        html_wrapped = True

    # Write artifacts to disk if -o was given. This happens in BOTH human and
    # envelope modes — the file is the source of truth for downstream tools
    # (renderers, diff scripts). Only the stdout/stderr presentation differs.
    # --summary has no effect under --human (stdout is raw JSX, not an
    # envelope) — surface a stderr warning instead of silently ignoring it.
    if human and summary:
        click.secho(
            "WARNING: --summary is ignored under --human "
            "(human mode emits raw JSX to stdout, not an envelope)",
            fg="yellow",
            err=True,
        )
    if output:
        # FIX: when -o points to an uncreatable path (e.g. /nonexistent_root/path.jsx) and
        # mkdir/write fails, wrap it uniformly as an envelope so a blank stdout doesn't crash AI agent json.loads
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(jsx, encoding="utf-8")
            click.echo(f"wrote {len(jsx)} bytes to {output}", err=True)
            if css_path and css_text:
                css_path.parent.mkdir(parents=True, exist_ok=True)
                css_path.write_text(css_text, encoding="utf-8")
                click.echo(f"wrote {len(css_text)} bytes to {css_path}", err=True)
        except (OSError, NotADirectoryError) as e:
            ename = type(e).__name__
            if human:
                click.echo(f"error: cannot write {output}: {ename}: {e}", err=True)
                sys.exit(2)
            emit_error(
                "invalid_argument",
                f"cannot write to {output}: {ename}: {e}",
                hint="check the -o path's parent dir exists and is writable",
                exit_code=2,
            )
    elif human:
        # --human + no -o: legacy behavior, JSX goes to stdout (parseable by
        # shell pipes). Envelope mode suppresses this — JSX is in data.jsx.
        # FIX: when --human is passed explicitly but stdout is piped (non-tty),
        # it's likely agent misuse. Add a prominent warning on stderr (does not affect stdout JSX).
        # Do not change stdout behavior (backward compatible with shell pipes/old tests).
        if not sys.stdout.isatty():
            click.secho(
                "WARNING: --human output piped to non-tty (likely agent misuse). "
                "stdout is raw JSX text, NOT JSON envelope. "
                "AI agents must NOT use --human — remove the flag for JSON envelope.",
                fg="red",
                bold=True,
                err=True,
            )
        click.echo(jsx)
        if css_form.lower() == "class" and css_text:
            click.echo("/* companion CSS */\n" + css_text, err=True)

    # Collect inspect warnings once (used by both human and envelope paths).
    inspect_warnings: list[dict] = []
    if inspect:
        inspect_warnings = collect_all_warnings(tree)
        # Human mode: render to stderr as colored lines.
        # Envelope mode: keep structured list, emit in data.inspect.
        if human:
            for w in inspect_warnings:
                sev = w.get("severity", "info")
                code = w.get("code", "?")
                msg = w.get("message", "")
                node_name = w.get("node_name", "")
                node_part = f" [{node_name!r}]" if node_name else ""
                click.echo(
                    f"[{sev}] {code}{node_part}: {msg}",
                    err=True,
                )

    # Compute the component recognition rate (agents/users quickly judge recognition quality)
    # denominator = INSTANCE nodes in the Figma design; numerator = nodes with tree.is_component=True
    def _count_instances(node) -> int:
        n = 0
        if getattr(node, "type", "") == "INSTANCE":
            n += 1
        for c in getattr(node, "children", []) or []:
            n += _count_instances(c)
        return n

    # FIX: count top-level INSTANCEs (parent not an INSTANCE).
    # recognition.instances includes nested INSTANCEs, which always understates the rate
    # (envelope 4.7% vs real 28.6%). top_level_instances is a more accurate denominator
    # for agents judging the real recognition rate.
    def _count_top_level_instances(node, parent_is_instance=False) -> int:
        n = 0
        is_inst = getattr(node, "type", "") == "INSTANCE"
        if is_inst and not parent_is_instance:
            n += 1
        for c in getattr(node, "children", []) or []:
            n += _count_top_level_instances(c, parent_is_instance=is_inst)
        return n

    def _count_components(node) -> int:
        n = 0
        if getattr(node, "is_component", False):
            n += 1
        for c in getattr(node, "children", []) or []:
            n += _count_components(c)
        return n

    instance_total = _count_instances(scene)
    top_level_instance_total = _count_top_level_instances(scene)
    component_recognized = _count_components(tree)
    recognition_rate = round(component_recognized / instance_total, 4) if instance_total else None
    # top-level recognition rate (top-level INSTANCE denominator, excluding nested INSTANCEs)
    top_level_recognition_rate = (
        round(component_recognized / top_level_instance_total, 4)
        if top_level_instance_total
        else None
    )

    # FIX: collect names of unrecognized INSTANCEs (actionable for agents)
    # collect all INSTANCE names from the scene tree (the tree structure may be altered by unwrap)
    def _collect_instance_names(node) -> list[str]:
        results: list[str] = []
        if getattr(node, "type", "") == "INSTANCE":
            nm = getattr(node, "name", "") or ""
            if nm:
                results.append(nm)
        for c in getattr(node, "children", []) or []:
            results.extend(_collect_instance_names(c))
        return results

    all_instance_names = _collect_instance_names(scene)

    # FIX: collect a structured list of unrecognized INSTANCEs (name + componentId)
    # for agents to extract programmatically (rather than parsing hint text)
    def _collect_unrecognized_instances(scene_node, tree_node) -> list[dict]:
        """Walk the scene tree, find INSTANCE nodes that are unrecognized in the tree (name, componentId).

        After the unwrap/inherit_promote passes, the tree structure
        differs from the scene tree (index alignment shifts). Match by figma_id instead —
        first recursively collect the set of figma_ids with is_component=True from the tree,
        then walk the scene tree and check whether each INSTANCE id is in that set.
        """
        # first collect all is_component=True figma_ids from the tree
        recognized_ids: set[str] = set()

        def _collect_recognized_ids(node) -> None:
            if getattr(node, "is_component", False):
                fid = getattr(node, "figma_id", "") or ""
                if fid:
                    recognized_ids.add(fid)
            for c in getattr(node, "children", []) or []:
                _collect_recognized_ids(c)

        if tree_node:
            _collect_recognized_ids(tree_node)

        # then walk the scene tree checking INSTANCEs
        results: list[dict] = []

        def _walk_scene(node) -> None:
            if getattr(node, "type", "") == "INSTANCE":
                node_id = getattr(node, "id", "") or ""
                if node_id not in recognized_ids:
                    nm = getattr(node, "name", "") or ""
                    cid = getattr(node, "component_id", "") or ""
                    if nm:
                        results.append({"name": nm, "component_id": cid})
            for c in getattr(node, "children", []) or []:
                _walk_scene(c)

        _walk_scene(scene_node)
        return results

    # ── subcommand mode: agent-native envelope output ──
    # Default (human=False): emit JSON envelope to stdout with structured
    # data (jsx, css, artifacts, inspect). --human preserves legacy
    # click.echo behavior for shell pipes and old tests.
    #
    # When -o writes a file, the envelope no longer includes the jsx string (agents don't need it).
    # inspect warnings stay in the envelope (consumable by agents), but in -o mode they go to friendly stderr output.
    if not human:
        artifacts: dict = {}
        if output:
            artifacts["jsxPath"] = output
            if css_path:
                artifacts["cssPath"] = css_path
        data = {}
        # FIX: --summary mode does not inline jsx/css text (saves ~18KB of stdout)
        # agents get metadata + paths only, and read the file when they need the code.
        # -o mode already omits jsx; --summary additionally skips jsx inlining without -o.
        if not output and not summary:
            data["jsx"] = jsx
        data["jsx_omitted"] = summary or bool(output)
        # FIX: jsx_omitted=true means "the envelope omits the jsx text", not "no code was generated".
        # With -o the code is actually written to disk; an AI seeing jsx_omitted=true might misjudge.
        # Add a hint clarifying: the code is on disk, just read output_path.
        if output and data["jsx_omitted"]:
            if "hints" not in data:
                data["hints"] = []
            data["hints"].append(
                f"jsx text is not inlined in the envelope (jsx_omitted=true), but the code "
                f"was written to output_path ({output}). Read `cat {output}` for the code, no need to rerun"
            )
        # FIX: with --summary and no -o, agents can't get the code.
        # Add a code_location field so agents can programmatically tell where the code is (null = not on disk, rerun needed).
        if summary and not output:
            data["code_location"] = None  # explicit null: code not written to disk
            if "hints" not in data:
                data["hints"] = []
            data["hints"].append(
                "jsx/css text omitted (--summary) and not written to disk (no -o). "
                "To get the code: (1) rerun without --summary (jsx returns to stdout data.jsx); "
                "(2) add `-o <file>` to write to disk (envelope data.output_path returns the path)"
            )
        # FIX: with -o, add output_path at the top level (agents don't dig into artifacts)
        if output:
            data["output_path"] = output
            data["code_location"] = str(output)  # code is on disk
            if css_path:
                data["css_path"] = css_path
        # FIX: the data.jsx field name is fixed but its content may be html (user passed --format html).
        # Add an output_type field so agents know the content format and don't treat it as React JSX.
        data["output_type"] = output_format  # "react" or "html"
        # FIX: -o mode no longer prints inspect warnings line by line anywhere —
        # the envelope already contains inspect_summary, the full inspect array is no longer emitted .
        # Previously -o mode did click.echo(inspect, err=True) line by line, cluttering stderr,
        # and a user's 2>&1 would pollute the stdout JSON.
        data["artifacts"] = artifacts
        # FIX: beautified + warnings array (agents can see beautify failures + deprecations etc.)
        data["beautified"] = beautified
        if warnings:
            # FIX: sanitize ANSI escape codes (beautify failure info may contain color control chars)
            data["warnings"] = [_sanitize_ansi(w) for w in warnings]
        # /FIX: the envelope does not emit the full inspect array by default (only inspect_summary).
        # AVOCADO_VERBOSE no longer reverts to the full inspect array ; only inspect_summary is emitted.
        # For the full inspect, use a future --inspect-detail flag or read stderr directly.
        if inspect_warnings:
            from collections import Counter

            by_code = Counter(w.get("code", "?") for w in inspect_warnings)
            by_severity = Counter(w.get("severity", "info") for w in inspect_warnings)
            data["inspect_summary"] = {
                "total": len(inspect_warnings),
                "by_code": dict(by_code),
                "by_severity": dict(by_severity),
            }
            data["inspect_count"] = len(inspect_warnings)
            # FIX: add a hint when inspect_count > 100 (d2c output quality may suffer)
            # FIX: add "how to reduce" suggestions
            if len(inspect_warnings) > 100:
                if "hints" not in data:
                    data["hints"] = []
                data["hints"].append(
                    f"inspect_count={len(inspect_warnings)} is unusually high "
                    f"(normal <30), d2c output quality may suffer. To reduce: "
                    f"(1) add --component-lib <name> to improve INSTANCE recognition; "
                    f"(2) check the Figma design for deep nesting (refactor or unwrap); "
                    f"(3) use --css class to shorten inline styles"
                )
            # FIX: map key inspect by_code items to hints (agent-readable)
            # FIX: branch on the current mode.component_lib state (avoid AI loops)
            # FIX: keep only mappings with actionable advice (don't restate inspect_summary numbers)
            # instance-not-recognized → add component_lib / check componentId alias
            # image-fetch-failed → run online to populate the cache
            # others (deep-nesting/long-inline-style etc.) stay exclusive to inspect_summary; hints don't duplicate
            _inspect_hint_map = {
                "instance-not-recognized": ("{suffix}"),
                # FIX: hint for image fetch failures (actionable: populate the cache)
                "image-fetch-failed": "{n} image(s) fetch failed (src empty) — check the figma imageRef or run online to populate the cache",
            }
            for code, count in by_code.items():
                tpl = _inspect_hint_map.get(code)
                if tpl and count > 0:
                    if "hints" not in data:
                        data["hints"] = []
                    if code == "instance-not-recognized":
                        # FIX: don't suggest "--component-lib" again
                        # when a component lib is already active (avoid AI loop)
                        # FIX: f-string references count (not undefined n)
                        if component_lib is not None or components is not None:
                            suffix = (
                                f"{count} INSTANCE node(s) not recognized — "
                                f"preset coverage is insufficient, check the "
                                f"preset for a matching componentId alias "
                                f"(same name, different compId is valid)"
                            )
                        else:
                            suffix = (
                                f"{count} INSTANCE node(s) not recognized — "
                                f"add --component-lib <name> or check preset coverage"
                            )
                        data["hints"].append(tpl.format(suffix=suffix, n=count))
                    else:
                        data["hints"].append(tpl.format(n=count))
        # FIX: --summary also omits css text (consistent with jsx; schema promises omit jsx+css)
        if css_text and not output and not summary:
            data["css"] = css_text
        if css_text and summary and not output:
            data["css_omitted"] = True
        # Requirement 3: flip the HTML-mode hint (full document is now the default; only fragment mode hints)
        if output_format.lower() == "html":
            if html_fragment:
                if "hints" not in data:
                    data["hints"] = []
                data["hints"].append(
                    "format=html --html-fragment: outputs a bare <div> fragment. "
                    "To open directly in a browser you must wrap it in <!DOCTYPE html><html><body> yourself"
                )
            elif not html_wrapped:
                # should not happen (HTML mode wraps by default unless there's a bug) — defensive hint
                pass
            else:
                # full-document mode: no hint needed by default, but knowing it's wrapped is valuable for agent integration
                if "hints" not in data:
                    data["hints"] = []
                data["hints"].append(
                    "format=html outputs a full HTML document by default (doctype + viewport meta + body wrapper), "
                    "openable directly in a browser for preview. To embed a fragment in an existing page, add --html-fragment"
                )
        # Recognition rate summary (agents quickly judge recognition quality)
        if instance_total:
            # FIX: collect structured unrecognized_instances (always in the recognition object)
            from collections import Counter

            unrecognized_list = _collect_unrecognized_instances(scene, tree)
            # dedupe + take top 10 (avoid envelope bloat)
            name_counts = Counter(u["name"] for u in unrecognized_list)
            top_unrecognized = [
                {
                    "name": nm,
                    "count": cnt,
                    "component_id": next(
                        (u["component_id"] for u in unrecognized_list if u["name"] == nm), ""
                    ),
                }
                for nm, cnt in name_counts.most_common(10)
            ]
            data["recognition"] = {
                "instances": instance_total,
                "top_level_instances": top_level_instance_total,  # top-level instances whose parent is not an INSTANCE
                "recognized": component_recognized,
                "rate": recognition_rate,
                "rate_percent": f"{recognition_rate * 100:.1f}%",
                "top_level_rate": top_level_recognition_rate,  # top-level recognition rate (more accurate)
                "top_level_rate_percent": (
                    f"{top_level_recognition_rate * 100:.1f}%"
                    if top_level_recognition_rate is not None
                    else None
                ),
                "unrecognized_instances": top_unrecognized,  # FIX: structured field (agents can extract programmatically)
                # FIX: document the difference between recognition.instances (all INSTANCEs in the
                # scene tree) and inspect_summary.instance-not-recognized (unrecognized INSTANCEs in the
                # optimized tree). Counts differ because: (1) recognition counts from the original scene
                # tree while inspect counts from the optimized tree (unwrap/inherit_promote may change
                # node structure); (2) inspect only warns about unrecognized INSTANCEs. Agents should use
                # recognition.rate to judge the recognition rate.
                # top_level_instances excludes nested INSTANCEs (whose parent is an INSTANCE),
                # closer to the real recognition rate (nested INSTANCEs are not recognized individually).
                "_note": "instances = total INSTANCE nodes in original Figma scene tree; "
                "top_level_instances = top-level INSTANCE (parent not INSTANCE), "
                "more accurate denominator for recognition rate. "
                "inspect_summary.instance-not-recognized counts from optimized tree "
                "(may differ due to unwrap/inherit_promote passes). "
                "use recognition.rate for overall recognition stats; "
                "use top_level_rate for accurate per-page recognition; "
                "use inspect_summary.instance-not-recognized for per-node warnings. "
                "Numerator counts all tree nodes with is_component=True "
                "(including non-INSTANCE nodes that plugins marked via name "
                "matching), while denominator only counts INSTANCE nodes — "
                "so rate can exceed 100% when plugins recognize additional "
                "components. Check plugins_applied[*].presets_used to see "
                "which preset library the plugin loaded.",
            }
            # //FIX: without --component-lib, recognition is inevitably 0% —
            # don't blame "abnormally low", guide the user to add --component-lib instead.
            # FIX: avoid duplicating the inspect instance-not-recognized hint (emit the component-lib hint only once)
            # FIX: low-recognition attribution hint — predict fidelity impact (d2c has no fidelity
            # field, so only predictively hint "low recognition may hurt fidelity")
            if recognition_rate is not None and recognition_rate < 0.50:
                if "hints" not in data:
                    data["hints"] = []
                # Dedup: already emitted a "--component-lib <name>" hint?
                _has_comp_lib_hint = any("--component-lib" in h for h in data["hints"])
                if not (components is not None or component_lib is not None):
                    if not _has_comp_lib_hint:
                        data["hints"].append(
                            "no --component-lib specified, component presets are "
                            "not loaded (add --component-lib <name> to recognize "
                            "INSTANCE components and improve fidelity)"
                        )
                    # Requirement 4: fidelity attribution prediction when recognition is low
                    data["hints"].append(
                        f"recognition.rate {recognition_rate * 100:.1f}% is low; "
                        f"unrecognized INSTANCEs fall back to generic div rendering (visual fidelity "
                        f"may be unaffected, but code maintainability suffers)"
                    )
                else:
                    # FIX: list unrecognized INSTANCE names + actionable suggestion
                    # unrecognized_instances is already in the recognition object (FIX:)
                    top_names = [u["name"] for u in top_unrecognized]
                    data["hints"].append(
                        f"recognition rate {recognition_rate * 100:.1f}% is low; "
                        f"the figma file may not match the preset (check component name/ID). "
                        f"Low recognition may hurt visual fidelity; "
                        f"unrecognized INSTANCEs fall back to generic divs"
                    )
                    if top_names:
                        data["hints"].append(
                            f"top unrecognized INSTANCE names: {top_names}. "
                            f"Check if the preset has matching entries (add componentId alias if missing)"
                        )
        # FIX: warning for image fetch failures (_image_error was already stripped before render_jsx)
        if image_errors:
            if "warnings" not in data:
                data["warnings"] = []  # fresh list (don't reuse the already-sanitized warnings)
            for ie in image_errors[:5]:  # cap at 5 to avoid bloat
                data["warnings"].append(_sanitize_ansi(f"image: {ie}"))
            if len(image_errors) > 5:
                data["warnings"].append(
                    _sanitize_ansi(f"image: ... and {len(image_errors) - 5} more fetch failures")
                )
            # FIX: give an actionable hint for offline cache misses in warnings
            if offline:
                data["hints"] = data.get("hints", [])
                data["hints"].append(
                    f"{len(image_errors)} image(s) fetch failed in offline mode. "
                    f"Run online once with --cache-dir to populate, or remove --offline"
                )
        # FIX: in cache_dir/offline mode image srcs are absolute local paths; adjust for collaboration
        if cache_dir or offline:
            if "hints" not in data:
                data["hints"] = []
            data["hints"].append(
                "image src uses absolute local cache paths (--cache-dir/--offline mode); "
                "replace with CDN URLs or relative paths before sharing"
            )
        # FIX: token_source (so agents know which source actually provided the token)
        # FIX: Click no longer uses envvar=FIGMA_TOKEN, so a non-None token is always a CLI flag.
        # resolve_token handles the env > config.yaml fallback.
        from avocado.paths import load_user_config, resolve_token

        actual_token = resolve_token(token)
        if token is not None and actual_token == token:
            data["token_source"] = "cli_flag"
        elif os.environ.get("FIGMA_TOKEN") and actual_token == os.environ.get("FIGMA_TOKEN"):
            data["token_source"] = "env_var"
        elif actual_token:
            cfg = load_user_config() or {}
            if cfg.get("figma_token") == actual_token:
                data["token_source"] = "config_file"
            else:
                data["token_source"] = "unknown"
        # FIX:：fetch_source（cache hit / network fetch）
        # FIX: --offline no longer falls back to the network (uniformly raises FigmaCacheMissError),
        # so with offline=True fetch_source is always "cache" (we only get here on a cache hit).
        if offline:
            data["fetch_source"] = "cache"
        else:
            data["fetch_source"] = "network" if cache_dir is None else "cache"
        # FIX: mode (flag-combination summary) + duration (elapsed seconds)
        # FIX: put timing in a sub-object (duration_seconds is non-deterministic; separating it
        # lets agents know the other envelope fields are deterministic)
        data["mode"] = {
            "format": output_format,
            "format_raw": format_raw,  # FIX: the user's raw --format input (before mapping)
            "css": css_form,
            "layout": layout,
            "offline": offline,
            "beautify": beautify_flag,
            "component_lib": component_lib,
            # FIX: complete the key flags (mode fully reproduces the output conditions)
            "css_vars": css_vars,
            "precision": precision,
            "box_sizing": box_sizing,
            "figma_id": figma_id,
            "depth": depth,
            "has_output": output is not None,
            # Requirement 2/3: preset + html_fragment fields (agents can trace the effective config)
            "preset": preset,
            "html_fragment": html_fragment,
            "html_wrapped": html_wrapped,
            "preview_centered": preview_centered,
            # FIX: include effective values of the 5 pipeline pass switches (agents can reproduce output exactly)
            "passes": {
                "inherit_promote": inherit_promote_flag,
                "strip_defaults": strip_defaults_flag,
                "unwrap_single_child": unwrap_single_flag,
                "gap_to_margin": gap_to_margin_flag,
                "auto_group_variance": auto_group_variance_flag,
            },
        }
        # Requirement 2: preset_expanded (agents can trace the flags after the preset expands)
        if preset_expanded is not None:
            data["preset_expanded"] = preset_expanded
        # Report plugins applied + presets they load internally.
        # ``mode.component_lib`` only reflects the CLI flag; plugins may call
        # ``load_preset(name)`` inside hooks, which changes the actual output
        # but is invisible to the envelope. Listing
        # ``plugins_applied[*].presets_used`` lets agents see the real preset
        # in use. Plugins opt in by setting ``presets_used`` on the Plugin
        # subclass (defaults to empty when the plugin doesn't load any preset).
        if registry.plugins:
            data["plugins_applied"] = [
                {"name": p.name, "presets_used": list(p.presets_used)} for p in registry.plugins
            ]
            data["mode"]["_plugins_note"] = (
                "component_lib only reflects the CLI --component-lib flag; "
                "plugins_applied[*].presets_used lists presets loaded inside "
                "plugin hooks (invisible to the flag). When presets_used is "
                "non-empty, the generated code may import components from "
                "those preset libraries even if component_lib is None."
            )
        # Surface var-map hit rate so agents can tell whether --var-map
        # actually applied. ``matched`` counts bindings whose VariableID was
        # in the var-map (semantic name used); ``total`` counts all bindings
        # encountered. When matched=0 the output falls back to fig-var-<short>
        # names — see warnings for actionable hints.
        if css_collection is not None:
            data["var_map_applied"] = {
                "matched": css_collection.var_map_matched,
                "total": css_collection.var_map_total,
            }
        # FIX: explain when beautify=True but beautified=False (tie it to warnings)
        if beautify_flag and not beautified:
            data["mode"]["_beautify_note"] = (
                "beautify=True (user requested) but beautified=False (beautify failed); "
                "see warnings for error details"
            )
        data["timing"] = {
            "duration_seconds": round(_time.monotonic() - _start_ts, 3),
            "_note": "non-deterministic field (timing varies per run); all other envelope fields are deterministic for the same input",
        }
        # FIX: tool identity (AI consumers know which tool/version produced the output)
        try:
            from importlib.metadata import version as _meta_ver

            _ver = _meta_ver("avocado")
        except Exception:
            _ver = "unknown"
        data["name"] = "avocado"
        data["version"] = _ver
        emit_ok(data)


def collect_inspect(node: TreeNode) -> list[dict]:
    """Walk tree, gather all inspect warnings."""
    out: list[dict] = []
    stack = [node]
    while stack:
        n = stack.pop()
        out.extend(n.inspect)
        stack.extend(n.children)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# schema / init / paths subcommand integration (subcommand mode)
# ─────────────────────────────────────────────────────────────────────────────
# Design trade-off (KISS): do not refactor main into a click.group (high risk of
# breaking 384 tests); use a lightweight dispatcher that forwards when sys.argv[1]
# matches a known subcommand name, and passes through to main otherwise. Thus:
# - `avocado <url>` goes to gen by default (main behavior unchanged)
# - `avocado schema` / `avocado --help` both work
# - `avocado init` / `avocado paths` etc. dispatch directly

# Known subcommand names (forward on first argv token match)
_KNOWN_SUBCOMMANDS = {"schema", "init", "paths"}


def cli() -> None:
    """avocado CLI main entry point (console_script points here).

    Dispatch logic:
        avocado <url> [...]      → main() (gen default)
        avocado schema           → _dispatch_schema()
        avocado --version / -V   → print the version (envelope or plain text)
        avocado --help / -h      → main() (click prints help incl. subcommand notes)
        anything else            → main()
    """
    # sys.argv[0] is the program name (avocado), [1] is the first user token
    first = sys.argv[1] if len(sys.argv) > 1 else None
    if first is None:
        # FIX: running bare with no args returns a command-list envelope (ok:true),
        # not invalid_argument. A new user's first action is running avocado bare; seeing
        # error + exit 2 would be confusing. Structure matches --help (but ok:true vs error).
        # FIX: add a warning (consistent with --help)
        # FIX: add first-use guidance (init)
        from avocado.paths import resolve_token

        _has_token = bool(resolve_token())
        emit_ok(
            {
                "name": "avocado",
                "description": "Figma Design-to-Code tool (Figma URL → JSX + CSS)",
                "commands": [
                    {"name": "avocado <url>", "description": "Generate JSX from Figma URL"},
                    {
                        "name": "avocado schema",
                        "description": "Output JSON envelope with all commands/flags/error codes",
                    },
                    {"name": "avocado init", "description": "Configure figma_token"},
                    {"name": "avocado paths", "description": "Print all resource paths"},
                    {"name": "avocado --version", "description": "Print version"},
                ],
                "warning": (  # M15: consistent with the --help warning
                    "--human flag breaks the JSON envelope contract on stdout "
                    "(d2c emits raw JSX text, not JSON). AI agents must NOT use --human. "
                    "--human is for legacy shell pipes only."
                ),
                "hint": (
                    "First time? Run `avocado init` to configure figma_token (or set the FIGMA_TOKEN env var), "
                    'then run `avocado "<figma-url>" -o out.jsx` to generate code. '
                    "Full command list: `avocado schema`"
                )
                if not _has_token
                else (
                    "Run `avocado <figma-url>` to generate code, or `avocado schema` for full command details"
                ),
            }
        )
    elif first in ("--version", "-V", "-v"):  # FIX: -v short option also supported
        _print_version()
    elif first in ("--help", "-h"):  # FIX: --help returns a JSON envelope
        emit_ok(
            {
                "name": "avocado",
                "description": "Figma Design-to-Code tool (Figma URL → JSX + CSS)",
                "commands": [
                    {"name": "avocado <url>", "description": "Generate JSX from Figma URL"},
                    {
                        "name": "avocado schema",
                        "description": "Output JSON envelope with all commands/flags/error codes",
                    },
                    {"name": "avocado init", "description": "Configure figma_token"},
                    {"name": "avocado paths", "description": "Print all resource paths"},
                    {"name": "avocado --version", "description": "Print version"},
                ],
                "warning": (  # FIX: explicitly warn that --human breaks the JSON contract
                    "--human flag breaks the JSON envelope contract on stdout "
                    "(d2c emits raw JSX text, not JSON). AI agents must NOT use --human. "
                    "--human is for legacy shell pipes only."
                ),
                "hint": "Run `avocado schema` for full flag details, or `avocado <url>` to generate code",
            }
        )
    elif first in _KNOWN_SUBCOMMANDS:
        # pop the subcommand name from argv so the dispatcher sees a clean argv
        # (keeping sys.argv[0] as the program name)
        sub = sys.argv.pop(1)
        if sub == "init":
            _dispatch_init()
        elif sub == "paths":
            _dispatch_paths()
        else:  # schema
            _dispatch_schema()
    elif first == "help":
        # FIX: `avocado help` is an alias for --help (new users instinctively type it).
        # Identical to `avocado --help`.
        emit_ok(
            {
                "name": "avocado",
                "description": "Figma Design-to-Code tool (Figma URL → JSX + CSS)",
                "commands": [
                    {"name": "avocado <url>", "description": "Generate JSX from Figma URL"},
                    {
                        "name": "avocado schema",
                        "description": "Output JSON envelope with all commands/flags/error codes",
                    },
                    {"name": "avocado init", "description": "Configure figma_token"},
                    {"name": "avocado paths", "description": "Print all resource paths"},
                    {"name": "avocado --version", "description": "Print version"},
                ],
                "warning": (  # FIX: explicitly warn that --human breaks the JSON contract
                    "--human flag breaks the JSON envelope contract on stdout "
                    "(d2c emits raw JSX text, not JSON). AI agents must NOT use --human. "
                    "--human is for legacy shell pipes only."
                ),
                "hint": "Run `avocado schema` for full flag details, or `avocado <url>` to generate code",
            }
        )
    elif first in _UNSUPPORTED_SUBCOMMANDS:
        # Looks like a subcommand but is not implemented (init/version/config/help etc.) —
        # Don't call the API treating it as a URL; give a clear error instead.
        # FIX: removed the conditional local import of emit_error (already imported at module top, line 26).
        # Python static scoping treats emit_error inside cli as a local variable,
        # causing UnboundLocalError when other except branches (e.g. Click UsageError) call emit_error.
        emit_error(
            "invalid_argument",
            f"unknown subcommand: {first!r}",
            hint="supported: avocado <url> | avocado schema | avocado init | avocado paths | avocado --version",
            exit_code=2,
        )
    elif _looks_like_typoed_command(first):
        # FIX: a short all-lowercase token looks more like a typo'ed subcommand than a figma file_key.
        # Previously `avocado badcommand` was treated as a bare file_key (>= 8 alnum passes validation)
        # and hit the Figma API for a 404, while the user actually wanted a command error.
        _hint = (
            "not a figma URL or file_key. Did you mean a subcommand? "
            "supported: avocado <url> | avocado schema | "
            "avocado init | avocado paths | avocado --version"
        )
        _msg = f"unknown subcommand or invalid argument: {first!r}"
        if "--human" in sys.argv[1:]:
            # human mode prints colored text to stderr (consistent with main's bad-URL handling)
            click.echo(f"error: {_msg}", err=True)
            click.echo(f"hint: {_hint}", err=True)
            sys.exit(2)
        emit_error("invalid_argument", _msg, hint=_hint, exit_code=2)
    else:
        # Default to main (gen path) — all existing behavior unchanged
        # parse_figma_url inside main rejects non-URL strings
        # (invalid_argument + exit 2), no more accidental Figma API calls.
        # FIX: catch Click's UsageError (invalid choice / path not found etc.),
        # convert to a JSON envelope instead of Click's default Usage text.
        # standalone_mode=False makes Click raise instead of sys.exit'ing itself.
        # Note: emit_error/emit_ok already sys.exit + emit the envelope internally,
        # so SystemExit is not caught (avoid duplicate output).
        try:
            main(standalone_mode=False)
        except click.exceptions.UsageError as e:
            msg = str(e.message) if hasattr(e, "message") and e.message else str(e)
            # FIX: when a user passes a non-d2c format name as --format, clarify the difference
            # (some format names belong to a separate companion tool and are not valid here)
            _external_format_names = {
                "flex_inline",
                "flex_tw",
                "abs_inline",
                "react_tw",
                "html_inline",
            }
            hint = None
            for cm in _external_format_names:
                if cm in msg:
                    hint = (
                        f"'{cm}' is not a valid d2c --format value. "
                        f"d2c --format accepts: react, html, inline, tailwind."
                    )
                    break
            # FIX: --human mode also outputs Click's UsageError (e.g. missing url) as colored stderr
            if hint is None:
                hint = (
                    f"invalid argument: {msg}. "
                    f"Check the parameter name and legal values in the error message "
                    f"(choice-type errors list all valid options). "
                    f"Full flag list: `avocado schema`"
                )
            if "--human" in sys.argv[1:]:
                _human_error(msg, hint, exit_code=2)
            emit_error(
                "invalid_argument",
                msg,
                hint=hint,
                exit_code=2,
            )
        except click.exceptions.Abort:
            emit_error("invalid_argument", "aborted", exit_code=2)
        except KeyboardInterrupt:
            # FIX: on SIGINT interruption of the full pipeline, no longer emit_ok stale artifacts.
            # Click converts SIGINT to Abort, but a KeyboardInterrupt raised mid-pipeline never
            # reaches the Click context → intercept here. Unix convention: SIGINT exits 130.
            emit_error(
                "interrupted",
                "interrupted by user (SIGINT)",
                hint="the pipeline was interrupted. Partial artifacts may exist in --output-dir. Re-run to complete.",
                exit_code=130,
            )
        except (OSError, NotADirectoryError, FileExistsError) as e:
            # FIX: filesystem errors (mkdir failure / filename too long / disk full)
            # are uniformly wrapped as envelopes so a blank stdout doesn't crash AI agent json.loads
            ename = type(e).__name__
            emit_error(
                "invalid_argument",
                f"filesystem error: {ename}: {e}",
                hint=(
                    "check the path is writable and the directory exists. "
                    "For -o, ensure parent dirs exist. "
                    "For --cache-dir, ensure the path is a creatable directory. "
                    "Avoid /dev/null, overly long names, or read-only filesystems."
                ),
                exit_code=2,
            )
        except SystemExit:
            # emit_ok / emit_error already sys.exit + emit the envelope internally; don't handle again
            raise
        except Exception as e:
            # FIX: catch-all — any unexpected internal bug (NameError/ValueError/
            # AttributeError etc.) goes through the envelope so a blank stdout doesn't crash
            # AI agent json.loads. This is the last line of defense for the envelope contract.
            import traceback as _tb

            ename = type(e).__name__
            emit_error(
                "internal_error",
                f"unexpected {ename}: {e}",
                hint=(
                    f"this is an avocado internal bug. Report with the error message. "
                    f"Workaround: try different flags or --no-beautify. "
                    f"Detail: {_tb.format_exc().splitlines()[-1] if _tb.format_exc() else ''}"
                ),
            )


# Recognize tokens that look like commands but are unimplemented, avoiding API calls treating them as file_keys
# FIX: add "avocado" itself (clear error when the user types "avocado avocado")
_UNSUPPORTED_SUBCOMMANDS = {
    "avocado",  # program name mistyped as argument
    "version",
    "config",
    "configuration",
    "conf",
    "info",
    "doctor",
    "setup",
    "login",
    "list",
    "ls",
    "show",
}


def _looks_like_typoed_command(token: str) -> bool:
    """FIX: decide whether a token looks more like a typo'ed subcommand than a figma file_key.

    Real figma file_keys are mixed alphanumeric (upper/lowercase + digits), usually 22 chars
    (e.g. ``FIGMA_FILE_KEY_PLACEHOLDER_002``). A short all-lowercase string is almost never a valid
    file_key; it's more likely a mistyped subcommand name (e.g. ``avocado badcommand``).

    Criteria (all must hold):
    - all lowercase letters (``-`` allowed for compounds like ``component-lib``)
    - length <= 20 (figma file_keys are usually 22+)
    - no URL chars such as ``/`` ``:`` ``.`` ``?`` ``=``
    """
    if not token:
        return False
    # fix: flags starting with -- (--human/--no-beautify etc.) are not typos (neither file_key nor command)
    if token.startswith("-"):
        return False
    if any(c in token for c in "/:.?="):
        return False
    # all lowercase letters, or lowercase + hyphen
    if not all(c.islower() or c == "-" for c in token):
        return False
    return len(token) <= 20


def _print_version() -> None:
    """``avocado --version``: read the version from pyproject.toml and print it.

    agent-native: stdout emits a JSON envelope (version field).
    Stay human-friendly: with --human or a plain-text call, print "avocado X.Y.Z".
    """
    try:
        from importlib.metadata import version as _meta_version

        ver = _meta_version("avocado")
    except Exception:
        # fallback: read from pyproject.toml
        try:
            import tomllib
            from pathlib import Path

            pyproject = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
            data = tomllib.loads(pyproject.read_text())
            ver = data.get("project", {}).get("version", "unknown")
        except Exception:
            ver = "unknown"

    from avocado.envelope import emit_ok

    emit_ok({"version": ver, "name": "avocado"})


def _dispatch_schema() -> None:
    """``avocado schema`` subcommand dispatcher."""
    from avocado.commands.schema import run_schema_command

    # sys.argv already popped 'schema'; remaining may be --help / -h / --human
    # FIX: subcommand --help returns a JSON envelope (consistent with main --help)
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        from avocado.commands.schema import _SPEC

        emit_ok(
            {
                "name": "avocado schema",
                "description": "Output JSON envelope with all commands/flags/error codes",
                "args": [],
                "flags": _SPEC["commands"][7].get("flags", []),
                "hint": "avocado schema directly outputs the full capability description; no extra arguments needed",
                "examples": ["avocado schema"],
            }
        )
    # --human makes schema emit human-friendly text (agents still get JSON by default).
    # schema is an agent introspection command; the default envelope is a strong contract; --human switches to Markdown.
    # FIX: --human adds the full flags table + examples (previously only command names + descriptions
    # + error codes; new users couldn't see core flags like --format/--css/--layout to learn usage).
    if len(sys.argv) > 1 and sys.argv[1] == "--human":
        from avocado.commands.schema import _SPEC
        from avocado.envelope import ERROR_CODES

        click.echo("# avocado schema (human-readable)\n")
        # FIX: add a TL;DR (3-step quick start) at the top so newcomers aren't overwhelmed by the 189-line info wall
        click.echo("## TL;DR (3-step quick start)\n")
        click.echo("```bash")
        click.echo("# 1. Configure your figma token (first use)")
        click.echo("avocado init --token figd_xxxxx")
        click.echo("# 2. Generate JSX from a Figma URL")
        click.echo('avocado "https://www.figma.com/design/XXXX/T?node-id=10:20" -o out.jsx')
        click.echo("```\n")
        click.echo("Full command/flag list below, or `avocado schema` (JSON format).\n")

        # FIX: version from importlib.metadata (consistent with JSON mode), not from _SPEC
        try:
            from importlib.metadata import version as _meta_ver

            ver = _meta_ver("avocado")
        except Exception:
            ver = "unknown"
        click.echo(f"version: {ver}\n")

        click.echo("## commands\n")
        for cmd in _SPEC.get("commands", []):
            click.echo(f"### `{cmd.get('name', '')}`")
            click.echo(f"{cmd.get('description', '')}\n")
            # args (positional params)
            args = cmd.get("args", []) or []
            if args:
                click.echo("**args:**")
                for a in args:
                    _req = " (required)" if a.get("required") else ""
                    click.echo(f"- `{a.get('name')}`{_req} — {a.get('help', '')}")
                click.echo()
            # flags table: name/type/default/help
            flags = cmd.get("flags", []) or []
            if flags:
                click.echo("**flags:**")
                for f in flags:
                    _names = (
                        "/".join(f.get("name", []))
                        if isinstance(f.get("name"), list)
                        else str(f.get("name", ""))
                    )
                    _type = f.get("type", "str")
                    _default = f.get("default")
                    _default_s = "" if _default is None else f" = {_default}"
                    _env = f" (env: {f['envvar']})" if f.get("envvar") else ""
                    _choices = ""
                    if f.get("choices"):
                        _choices = f" [{', '.join(str(c) for c in f['choices'])}]"
                    click.echo(
                        f"- `{_names}` {_type}{_default_s}{_env} — {f.get('help', '')}{_choices}"
                    )
                click.echo()
            # examples
            examples = cmd.get("examples", []) or []
            if examples:
                click.echo("**examples:**")
                for ex in examples:
                    click.echo(f"  $ {ex}")
                click.echo()
        click.echo("## error codes\n")
        for code, info in ERROR_CODES.items():
            click.echo(f"- `{code}` (exit {info.get('exit_code', 1)}): {info.get('hint', '')}")
        sys.exit(0)
    # FIX: schema validates unknown flags (previously `avocado schema --nonexistent` returned ok:true)
    # --format json is accepted as a no-op for cross-command consistency: the
    # schema/paths/<url> commands all emit JSON envelopes by default, so the
    # flag is redundant here but agents can pass it without hitting an error.
    _schema_known_flags = {"-h", "--help", "--human", "--format", "json"}
    _unknown = [a for a in sys.argv[1:] if a.startswith("-") and a not in _schema_known_flags]
    if _unknown:
        emit_error(
            "invalid_argument",
            f"avocado schema does not accept flags: {_unknown}. "
            f"Schema outputs all capabilities with no arguments.",
            hint="run `avocado schema` with no flags, or `avocado schema --human` for Markdown output",
            exit_code=2,
        )
    run_schema_command()


def _dispatch_init() -> None:
    """``avocado init`` subcommand dispatcher."""
    from avocado.commands.init import run_init_command

    # FIX: reject extra positional args (e.g. `avocado init help`)
    # FIX: the --token value is not a positional (previously `init --token figd_xxx`
    # was misjudged as having an extra positional arg).
    skip_next = False
    positional = []
    for a in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if a == "--token":
            skip_next = True  # next token is the --token value
            continue
        if a.startswith("--token="):
            continue
        if not a.startswith("-"):
            positional.append(a)
    if positional:
        msg = f"init takes no positional args (got {positional!r})"
        if "--human" in sys.argv[1:]:
            click.echo(f"error: {msg}", err=True)
            sys.exit(2)
        emit_error("invalid_argument", msg, exit_code=2)

    # sys.argv already popped 'init'; remaining may be --help / -h
    # FIX: subcommand --help returns a JSON envelope (consistent with main --help)
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        emit_ok(
            {
                "name": "avocado init",
                "description": "Configure figma_token in ~/.avocado/config.yaml",
                "args": [],
                "flags": [
                    {
                        "name": "--human",
                        "type": "flag",
                        "default": False,
                        "help": "Interactive prompt (default in TTY)",
                    },
                    {
                        "name": "--token",
                        "type": "str",
                        "default": None,
                        "help": "Non-interactive: write token directly",
                    },
                ],
                # FIX: detailed interactive flow (what it asks + where it writes + overwrite behavior)
                "hint": (
                    "avocado init [--token FIGMA_TOKEN] or interactive input. "
                    "Interactive mode prompts for the figma token (get one at figma.com/settings), "
                    "and writes it to the figma_token field of ~/.avocado/config.yaml. "
                    "An existing token is overwritten (no backup needed). Press Ctrl+C to cancel"
                ),
                "examples": [  # FIX:                "avocado init --token figd_xxxxx",
                    "avocado init  # interactive (prompts for token)",
                ],
            }
        )
    # --human is the default (interactive); no flag also goes interactive; agent calls use the envelope
    human = sys.stdout.isatty() or "--human" in sys.argv[1:]
    # FIX: support non-interactive writes via --token
    token_arg = None
    for i, a in enumerate(sys.argv[1:], 1):
        if a == "--token" and i + 1 < len(sys.argv):
            token_arg = sys.argv[i + 1]
        elif a.startswith("--token="):
            token_arg = a.split("=", 1)[1]
    if token_arg:
        # FIX: token format validation (figma tokens have a figd_ prefix, length >= 20).
        # No API validation (avoid network dependency + latency), only a format sanity check.
        token_stripped = token_arg.strip()
        if not token_stripped or len(token_stripped) < 20:
            emit_error(
                "invalid_argument",
                f"--token value too short (got {len(token_stripped)} chars, "
                f"figma tokens are typically 40+ chars)",
                hint="check your token — Figma Personal Access Tokens start with 'figd_' and are 40+ chars",
                exit_code=2,
            )
        # FIX: token upper-bound validation (prevents a 10KB junk token from bloating config.yaml)
        if len(token_stripped) > 200:
            emit_error(
                "invalid_argument",
                f"--token too long (got {len(token_stripped)} chars, "
                f"figma tokens are typically 40-60 chars)",
                hint="check your token — a real Figma Personal Access Token is 40-60 chars",
                exit_code=2,
            )
        # FIX: reject tokens containing newlines (YAML injection defense)
        if "\n" in token_stripped or "\r" in token_stripped:
            emit_error(
                "invalid_argument",
                "--token must not contain newlines (YAML injection protection)",
                hint="tokens are single-line; check for copy/paste artifacts",
                exit_code=2,
            )
        # non-interactive: write the token straight to config.yaml
        from avocado.commands.init import _write_token_to_config

        _write_token_to_config(token_stripped)
        if human:
            click.secho("✓ Token saved!", fg="green", bold=True)
        emit_ok(
            {
                "ready": True,
                "token_saved": True,
                "hint": (
                    "token written to ~/.avocado/config.yaml (overwrites any "
                    "prior token). Format validated but not API-checked — run "
                    "`avocado <url>` once to verify it works."
                ),
            }
        )
        return
    run_init_command(human=human)


def _dispatch_paths() -> None:
    """``avocado paths`` subcommand dispatcher."""
    from avocado.commands.paths import run_paths_command

    # FIX: subcommand --help returns a JSON envelope (consistent with main --help)
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        emit_ok(
            {
                "name": "avocado paths",
                "description": "Print all resource paths + 4-layer lookup order",
                "args": [],
                "flags": [
                    {
                        "name": "--human",
                        "type": "flag",
                        "default": False,
                        "help": "Human-readable colored output (default is JSON envelope)",
                    },
                ],
                "hint": "avocado paths directly outputs the resource paths; no extra arguments needed",
                "examples": ["avocado paths"],
            }
        )
    human = "--human" in sys.argv[1:]
    run_paths_command(human=human)


if __name__ == "__main__":
    cli()
