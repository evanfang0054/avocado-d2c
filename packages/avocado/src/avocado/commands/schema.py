"""avocado schema introspection command.

Outputs the full command/flag/error-code list for agent self-introspection.

Design (KISS):
- A hand-maintained ``_SPEC`` dict is the single source of truth (no dynamic
  click introspection — it depends on unstable click internals).
- Kept in sync with cli.py manually; a test guards against drift.
- Output envelope (success):
    {"ok": true, "data": {"commands": [...], "errorCodes": {...}, "version": "..."}}
"""

from __future__ import annotations

from avocado.envelope import ERROR_CODES, emit_ok

# ─────────────────────────────────────────────────────────────────────────────
# Single source of truth: _SPEC dict
# ─────────────────────────────────────────────────────────────────────────────
# Maintenance rule: adding a flag in cli.py must sync here.
# test_schema_command_outputs_json asserts valid JSON;
# content completeness: _SPEC is the single source of truth for commands/flags/error codes

_SPEC: dict = {
    "commands": [
        {
            "name": "avocado <url>",
            "invoke_as": "avocado <url>",  # callable name (for agent programmatic invocation)
            "description": "Default command: Figma URL -> JSX (agent-native, JSON envelope by default)",
            "args": [
                {
                    "name": "url",
                    "required": True,
                    "type": "str",
                    "help": "Figma node URL (must include ?node-id=...)",
                },
            ],
            "flags": [
                {
                    "name": ["-o", "--output"],
                    "type": "Path",
                    "default": None,
                    "help": "Write output JSX file (default: stdout)",
                },
                {
                    "name": ["--token"],
                    "type": "str",
                    "default": None,
                    "envvar": "FIGMA_TOKEN",
                    "help": "Figma Personal Access Token",
                },
                {
                    "name": ["--cache-dir"],
                    "type": "Path",
                    "default": None,
                    "help": "Mirror fetched data to this dir",
                },
                {
                    "name": ["--offline"],
                    "type": "flag",
                    "default": False,
                    "help": "Read ONLY from --cache-dir, no network",
                },
                {
                    "name": ["--depth"],
                    "type": "int",
                    "default": None,
                    "help": (
                        "Max tree depth when fetching from Figma API. "
                        "Warning: low values (1-5) significantly truncate the tree; "
                        "Figma designs typically nest 10-20 levels. "
                        "Use depth >= 20 for full coverage, or omit for unlimited"
                    ),
                },
                {
                    "name": ["--inspect", "--no-inspect"],
                    "type": "flag",
                    "default": True,
                    "help": "Emit inspect-draft warnings to stderr",
                },
                {
                    "name": ["--beautify", "--no-beautify"],
                    "type": "flag",
                    "default": True,
                    "help": "Post-process output with the built-in JSX beautifier (auto-skipped when --format html; HTML is not a JS/JSX module)",
                },
                {
                    "name": ["--components", "--components-file"],
                    "type": "Path",
                    "default": None,
                    "help": "YAML file with INSTANCE → business component mapping "
                    "(alias --components-file is clearer, distinct from --component-lib preset name)",
                },
                {
                    "name": ["--component-lib"],
                    "type": "str",
                    "default": None,
                    "help": "Built-in component library preset name (e.g. 'antd')",
                },
                {
                    "name": ["--format"],
                    "type": "choice",
                    "choices": ["react", "html", "inline", "tailwind"],
                    "default": "react",
                    "help": "Output structure (inline/tailwind deprecated → use --css)",
                },
                {
                    "name": ["--css"],
                    "type": "choice",
                    "choices": ["inline", "tailwind", "class"],
                    "default": "tailwind",
                    "help": "CSS form (className+leftover / inline / extracted .css)",
                },
                {
                    "name": ["--layout"],
                    "type": "choice",
                    "choices": ["flex", "absolute"],
                    "default": "flex",
                    "help": "Layout strategy",
                },
                {
                    "name": ["--css-vars", "--no-css-vars"],
                    "type": "flag",
                    "default": False,
                    "help": "Emit var(--name, fallback) references",
                },
                {
                    "name": ["--var-map"],
                    "type": "Path",
                    "default": None,
                    "help": "YAML file mapping VariableID → semantic CSS variable name",
                },
                {
                    "name": ["--precision"],
                    "type": "choice",
                    "choices": ["0", "1", "2", "unset"],
                    "default": "2",
                    "help": "Re-round numeric CSS values to N decimals",
                },
                {
                    "name": ["--box-sizing"],
                    "type": "choice",
                    "choices": ["content-box", "border-box"],
                    "default": "content-box",
                    "help": "Box-sizing for leading <style> reset",
                },
                {
                    "name": ["--gap-to-margin", "--no-gap-to-margin"],
                    "type": "flag",
                    "default": False,
                    "help": "Replace flex gap with per-child margin "
                    "(envelope field: mode.passes.gap_to_margin)",
                },
                {
                    "name": ["--auto-group-variance", "--no-auto-group-variance"],
                    "type": "flag",
                    "default": False,
                    "help": "Orient auto_group via variance "
                    "(envelope field: mode.passes.auto_group_variance)",
                },
                {
                    "name": ["--inherit-promote", "--no-inherit-promote"],
                    "type": "flag",
                    "default": True,
                    "help": "Lift common inheritable props "
                    "(envelope field: mode.passes.inherit_promote)",
                },
                {
                    "name": ["--strip-defaults", "--no-strip-defaults"],
                    "type": "flag",
                    "default": True,
                    "help": "Drop CSS props equal to spec default "
                    "(envelope field: mode.passes.strip_defaults)",
                },
                {
                    "name": ["--unwrap-single", "--no-unwrap-single"],
                    "type": "flag",
                    "default": True,
                    "help": "Collapse single-child wrappers "
                    "(envelope field: mode.passes.unwrap_single_child)",
                },
                {
                    "name": ["--human"],
                    "type": "flag",
                    "default": False,
                    "help": "Human-readable progress on stderr; for d2c, stdout emits raw JSX (breaks JSON envelope). AI agents must NOT use --human. Default: JSON envelope",
                },
                {
                    "name": ["--figma-id"],
                    "type": "flag",
                    "default": False,
                    "help": "Emit data-figma-id debug attributes on every node (default: off, clean output). Turn on for traceability/debugging",
                },
                {
                    "name": ["--summary"],
                    "type": "flag",
                    "default": False,
                    "help": "Omit jsx/css text from envelope (metadata + paths only, saves ~18KB)",
                },
                {
                    "name": ["--dry-run"],
                    "type": "flag",
                    "default": False,
                    "help": "Validate URL+token+params without API call or file writes (no side effects)",
                },
                {
                    "name": ["--preset"],
                    "type": "choice",
                    "choices": ["designer", "dev", "compare-ready"],
                    "default": None,
                    "help": "Bundled flag preset. designer=HTML full document; "
                    "dev=react+tailwind (no component library); "
                    "compare-ready=react+extracted css+summary. "
                    "Explicit flags override preset on conflict (warning)",
                },
                {
                    "name": ["--html-fragment"],
                    "type": "flag",
                    "default": False,
                    "help": "Fall back to a bare <div> fragment (default: --format html emits a full HTML document)",
                },
                {
                    "name": ["--preview-centered"],
                    "type": "flag",
                    "default": False,
                    "help": "Add preview-centering styles to HTML output (gray bg + centered + shadow + rounded). designer preset enables by default",
                },
                {
                    "name": ["--trace-adapter"],
                    "type": "str",
                    "default": None,
                    "help": "Opt-in adapter debug tracing. Bare flag enables all modules (preset/extractor/hook); "
                    "comma-separated subset filters (e.g. --trace-adapter=preset). Adds data.trace to the envelope: "
                    "preset match details (matched_by/skipped_by + reason), extractor outputs and plugin hook stats. "
                    "Deterministic; default off (zero envelope impact)",
                },
            ],
            "examples": [
                'avocado "https://www.figma.com/design/XXXX/Title?node-id=10:20" -o out.jsx',
                'avocado "https://www.figma.com/design/XXXX/Title?node-id=10:20" --component-lib antd -o out.jsx',
                'avocado "https://www.figma.com/design/XXXX/Title?node-id=10:20" --cache-dir /tmp/cache --offline -o out.jsx',
                'avocado "https://www.figma.com/design/XXXX/Title?node-id=10:20" --figma-id --format html -o out.html',
                'avocado "https://www.figma.com/design/XXXX/Title?node-id=10:20" --preset designer -o out.html',
                'avocado "https://www.figma.com/design/XXXX/Title?node-id=10:20" --preset dev -o out.jsx',
            ],
            "data_artifacts": {  # d2c envelope.data structure description (for agent introspection)
                "jsx": "Generated JSX text (echoed back to the envelope even when -o writes a file)",
                "css": "Optional; present only with --css class and non-empty css_text (omitted in --summary mode)",
                "inspect": "list[dict]; inspect rule warnings (deep-nesting/low-contrast, etc.)",
                "artifacts": {
                    "jsxPath": "Optional; absolute path written by -o (= output_path)",
                    "cssPath": "Optional; CSS file path written with --css class + -o (= css_path)",
                },
                "output_path": "Optional; top-level convenience field (= artifacts.jsxPath, agent-friendly)",
                "css_path": "Optional; top-level convenience field (= artifacts.cssPath)",
                "code_location": "Code written to disk (null=not written, rerun needed; str=written)",
                "jsx_omitted": "bool; True with --summary or -o (jsx text not in envelope)",
                "css_omitted": "bool; True with --summary (css text not in envelope)",
                "inspect_summary": "dict; inspect warnings aggregated by code",
                "recognition": "dict; INSTANCE component recognition stats (total/recognized/unrecognized)",
                "mode": "dict; summary of the requested flag combination (format/css/layout)",
                "warnings": "list[str]; non-fatal warnings (beautify failure/deprecation)",
                "timing": "dict; includes duration_seconds (non-deterministic field)",
                "trace": "Optional; present only with --trace-adapter. preset_matches{total,matched,unmatched,unmatched_details,matched_samples} / extractor_outputs[{component,extractor,path,success,keys,sample}] / plugin_hooks[{plugin,hook,nodes_affected,sample_names}]. Deterministic; for adapter authoring debug",
            },
        },
        {
            "name": "avocado init",
            "invoke_as": "avocado init",
            "description": "Configure figma_token into ~/.avocado/config.yaml (interactive or envelope)",
            "args": [],
            "examples": [
                "avocado init --token figd_xxxxx  # non-interactive",
                "avocado init  # interactive",
            ],
            "flags": [
                {
                    "name": ["--human"],
                    "type": "flag",
                    "default": False,
                    "help": "Human-readable interactive output (agent mode emits envelope)",
                },
                {
                    "name": ["--token"],
                    "type": "str",
                    "default": None,
                    "help": "Non-interactive: write the token straight to config.yaml",
                },
            ],
        },
        {
            "name": "avocado paths",
            "invoke_as": "avocado paths",
            "description": "Print all resource paths + 4-layer lookup order",
            "args": [],
            "examples": [
                "avocado paths  # view resource paths + 4-layer lookup",
            ],
            "flags": [
                {
                    "name": ["--human"],
                    "type": "flag",
                    "default": False,
                    "help": "Human-readable colored output (default: JSON envelope)",
                },
            ],
        },
    ],
    "error_codes": ERROR_CODES,
    # FIX: global flags (all commands support them; not repeated in each command flags)
    "global_flags": [
        {
            "name": ["--help", "-h"],
            "type": "flag",
            "default": False,
            "help": "Show command help (returns JSON envelope with flags/examples/hint)",
        },
        {
            "name": ["--version", "-V", "-v"],
            "type": "flag",
            "default": False,
            "help": "Show avocado version",
        },
    ],
    # FIX: mark non-deterministic fields (agents skip them when diffing envelopes)
    "non_deterministic_fields": [
        "timing.duration_seconds",
        "data.timing.duration_seconds",
    ],
    "_non_deterministic_note": (
        "The fields above vary across runs even for the same input (timestamps/durations). "
        "Agents should ignore them when diffing envelopes"
    ),
}


def run_schema_command() -> None:
    """``avocado schema`` introspection command.

    Output envelope::

        {
            "ok": true,
            "data": {
                "commands": [...],     # all commands
                "errorCodes": {...},   # envelope.ERROR_CODES dict
                "version": "..."       # avocado version (from importlib.metadata)
            }
        }
    """
    # Get version (KISS: fallback to "unknown" on failure, no emit_error)
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            v = version("avocado")
        except PackageNotFoundError:
            v = "unknown"
    except ImportError:
        v = "unknown"

    emit_ok(
        {
            "name": "avocado",
            "commands": _SPEC["commands"],
            "error_codes": _SPEC["error_codes"],  # FIX: snake_case only (camelCase removed)
            "version": v,
        }
    )
