"""avocado init subcommand.

Guides a new user to configure figma_token into ~/.avocado/config.yaml.

Behavior:
- Detects the token via the 4-layer lookup (CLI > env > ~/.avocado/config.yaml > cwd/.avocado/config.yaml)
- Already configured → tell the user it is ready + show the current token source (masked)
- Not configured → guide the user to create a Personal Access Token in Figma Settings,
  ask them to paste the token and write it to ~/.avocado/config.yaml (chmod 600)
"""

from __future__ import annotations

import os


def _write_token_to_config(token: str) -> None:
    """FIX: non-interactive token write to ~/.avocado/config.yaml (for `avocado init --token X`).

    FIX: sanity-check the token contains no newline (prevents YAML injection — a newline can
    write extra YAML keys like `figd_AAAA\\nmalicious: pwned`).

    FIX: use yaml.safe_load/safe_dump instead of regex replacement.
    The old regex failed when config.yaml was already `{}` (empty YAML dict) —
    no match on `^figma_token:` -> append branch -> two top-level YAML documents (`{}\\nfigma_token: X`)
    -> parse failure -> token permanently lost.
    """
    import yaml

    from avocado.paths import _user_avocado_root

    # FIX: reject tokens containing newline / carriage return (YAML injection defense)
    if "\n" in token or "\r" in token:
        raise ValueError(
            f"token contains newline char (len={len(token)}); "
            f"refusing to write to config.yaml (YAML injection protection)"
        )
    config_path = _user_avocado_root() / "config.yaml"
    # FIX: parse the existing config with yaml.safe_load (empty file / {} / existing content are all safe)
    data: dict = {}
    if config_path.exists():
        try:
            raw = config_path.read_text().strip()
            if raw:
                parsed = yaml.safe_load(raw)
                if isinstance(parsed, dict):
                    data = parsed
        except yaml.YAMLError:
            # corrupted YAML overrides with an empty dict (do not keep the broken content)
            data = {}
    data["figma_token"] = token
    config_path.write_text(yaml.safe_dump(data, default_flow_style=False))
    config_path.chmod(0o600)


def run_init_command(human: bool = True) -> None:
    """``avocado init`` — guides a new user through configuration.

    Args:
        human: True = human-readable output (default); False = JSON envelope
    """
    from avocado.envelope import emit_ok
    from avocado.paths import (
        _user_avocado_root,
        ensure_user_dirs,
        load_user_config,
        resolve_token,
    )

    # 1. First make sure ~/.avocado/ dirs exist
    ensure_user_dirs()

    # 2. Detect the current token
    cli_token = None  # init takes no --token flag
    env_token = os.environ.get("FIGMA_TOKEN")
    config = load_user_config()
    config_token = config.get("figma_token") if isinstance(config, dict) else None

    # resolve_token 4-layer lookup (no cli_token → env > config)
    resolved = resolve_token(cli_token)

    # 3. Already configured → report ready
    if resolved:
        # mask: show only the first 8 chars + ...
        masked = resolved[:8] + "..." if len(resolved) > 8 else resolved
        if env_token and resolved == env_token:
            source = "FIGMA_TOKEN env var"
        elif config_token and resolved == config_token:
            source = "~/.avocado/config.yaml"
        else:
            source = "unknown"

        if human:
            import click

            click.secho("✓ avocado is ready!", fg="green", bold=True)
            click.echo(f"  token: {masked} (from {source})")
            click.echo(f"  config: {_user_avocado_root() / 'config.yaml'}")
            click.echo("")
            click.echo("Next steps:")
            click.echo("  avocado schema                          # see all commands")
            click.echo('  avocado "<figma-url>" -o out.jsx       # convert Figma to JSX')
        # FIX: envelope does not echo the token prefix (security: keep it out of agent context/logs)
        # prefix only in --human output; envelope returns only ready + source (no masked)
        emit_ok({"ready": True, "token_source": source})
        return

    # 4. Not configured → guide the user to paste a token
    if human:
        import click

        click.secho("Welcome to avocado!", fg="green", bold=True)
        click.echo("")
        click.echo("To convert Figma designs to JSX, you need a Figma Personal Access Token.")
        click.echo("")
        click.echo("How to get one:")
        click.echo("  1. Open https://www.figma.com/settings")
        click.echo("  2. Scroll to 'Personal access tokens'")
        click.echo("  3. Click 'Generate new token', give it a name (e.g. 'avocado')")
        click.echo("  4. Copy the token (starts with 'figd_')")
        click.echo("")
        token = click.prompt(
            "Paste your Figma token (or press Enter to skip)", default="", show_default=False
        )
        token = token.strip()
        if not token:
            click.echo("Skipped. Set FIGMA_TOKEN env var or edit ~/.avocado/config.yaml later.")
            emit_ok({"ready": False, "reason": "user_skipped"})
            return
    else:
        # JSON mode: non-interactive, tell the user to configure
        emit_ok(
            {
                "ready": False,
                "reason": "no_token",
                "hint": "set FIGMA_TOKEN env var, or run `avocado init` (interactive), "
                "or edit ~/.avocado/config.yaml with: figma_token: figd_xxxxxxxx",
            }
        )
        return

    # 5. Write to ~/.avocado/config.yaml (FIX: reuse _write_token_to_config,
    # use yaml.safe_load/safe_dump instead of regex replacement, avoiding two top-level documents for {})
    config_path = _user_avocado_root() / "config.yaml"
    _write_token_to_config(token)

    if human:
        click.secho("✓ Token saved!", fg="green", bold=True)
        click.echo(f"  config: {config_path} (chmod 600)")
        click.echo("")
        click.echo("Next steps:")
        click.echo("  avocado schema                          # see all commands")
        click.echo('  avocado "<figma-url>" -o out.jsx       # convert Figma to JSX')
    emit_ok({"ready": True, "token_saved": True, "config_path": str(config_path)})


def run_init_command_envelope() -> None:
    """JSON envelope variant (agent invocation, non-interactive)."""
    run_init_command(human=False)
