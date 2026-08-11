"""avocado paths subcommand.

Prints avocado resource path layout to help users understand:
- ~/.avocado/ user config root
- 4-layer lookup order (CLI > cwd/.avocado/ > ~/.avocado/ > bundled _bundled/)
- Per-stage artifact locations (figma_cache/jsx, etc., the d2c stage outputs)
"""

from __future__ import annotations

from avocado.envelope import emit_ok
from avocado.paths import (
    _user_avocado_root,
    resolve_output_dir,
    resolve_preset,
    resolve_var_map,
)


def run_paths_command(human: bool = False) -> None:
    """``avocado paths`` - prints the path layout.

    Args:
        human: True = colored text output; False = JSON envelope (default, agent-friendly)
    """
    user_root = _user_avocado_root()
    output_dir = resolve_output_dir()
    preset = resolve_preset("antd")
    var_map = resolve_var_map("antd")

    paths_data = {
        "user_root": str(user_root),
        "output_dir": str(output_dir),
        "preset": str(preset),
        "var_map": str(var_map),
        "user_config": str(user_root / "config.yaml"),  # token lives here (figma_token field)
        "lookup_order": [
            "1. CLI flag (--output-dir / --components / --var-map)",
            "2. cwd/.avocado/<resource>/  (project-level override)",
            "3. ~/.avocado/<resource>/  (user-level default)",
            "4. bundled _bundled/<resource>/  (wheel bundle fallback)",
        ],
        "output_artifacts": {
            "figma_cache/": "Figma node JSON + images (avocado --offline reads here)",
            "jsx/": "JSX files written by -o (avocado <url> -o out.jsx)",
        },
        "_note": (
            "Under editable install (pip install -e), preset/var_map point at the source src/ dir — "
            "that is expected (importlib.resources reads the source); a published pip install points at the wheel _bundled/"
        ),
        # cache cleanup guide (d2c stage outputs)
        "cache_cleanup": (
            "Cache cleanup guide (by stage causality):\n"
            "  • delete figma_cache/ -> next `avocado URL --offline` re-pulls Figma node JSON + images\n"
            "  • delete jsx/ (or -o target) -> regenerates JSX\n"
        ),
        "for_designer": {
            "user_root": str(user_root),
            "output_dir": str(output_dir),
            "_hint": "paths designers care about: user root, output dir",
        },
        "for_engineer": {
            "preset": str(preset),
            "var_map": str(var_map),
            "user_config": str(user_root / "config.yaml"),
            "lookup_order": [
                "1. CLI flag (--output-dir / --components / --var-map)",
                "2. cwd/.avocado/<resource>/  (project-level override)",
                "3. ~/.avocado/<resource>/  (user-level default)",
                "4. bundled _bundled/<resource>/  (wheel bundle fallback)",
            ],
            "output_artifacts": {
                "figma_cache/": "Figma node JSON + images (avocado --offline reads here)",
                "jsx/": "JSX files written by -o",
            },
            "cache_cleanup": (
                "Cache cleanup guide (by stage causality):\n"
                "  • delete figma_cache/ -> next `avocado URL --offline` re-pulls\n"
                "  • delete jsx/ (or -o target) -> regenerates JSX\n"
            ),
            "_note": (
                "Under editable install (pip install -e), preset/var_map point at the source src/ dir — "
                "that is expected (importlib.resources reads the source); a published pip install points at the wheel _bundled/"
            ),
            "_hint": "paths engineers care about: preset/var_map/lookup_order/output_artifacts",
        },
    }

    if human:
        import click

        click.secho("avocado paths", fg="green", bold=True)
        click.echo("")
        click.secho("Paths for designers (for_designer):", fg="cyan", bold=True)
        click.echo("  User root:       " + str(user_root))
        click.echo("  Output dir:      " + str(output_dir))
        click.echo("")
        click.secho("Engineering paths (for_engineer):", fg="cyan", bold=True)
        click.echo("  Preset (antd):    " + str(preset))
        click.echo("  Var-map (antd):   " + str(var_map))
        click.echo("")
        click.secho("4-layer lookup:", fg="cyan")
        for line in paths_data["lookup_order"]:
            click.echo("  " + line)
        click.echo("")
        click.secho("Output artifacts:", fg="cyan")
        for k, v in paths_data["output_artifacts"].items():
            click.echo(f"  {k:16s} {v}")
        click.echo("")
        click.secho("Cache cleanup:", fg="cyan")
        click.echo(paths_data["cache_cleanup"])
        click.echo("")
        click.echo("")
        click.secho(f"note: {paths_data['_note']}", fg="yellow", dim=True)
        import sys as _sys_paths

        _sys_paths.exit(0)
    else:
        emit_ok(paths_data)
