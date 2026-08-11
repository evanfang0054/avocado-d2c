"""avocado path resolution (single source of truth for the 4-layer lookup).

Priority: CLI flag > project level (cwd/.avocado/) > user level (~/.avocado/) > bundled _bundled/

Every resource type (preset/var-map/output/config) is looked up in this
order; the first hit wins.

The project level (cwd/.avocado/) is for development: in a monorepo with
multiple packages, a subdirectory can override the user-level default
(e.g. packages/avocado/.avocado/presets/ to test a new preset).
"""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path


def _user_avocado_root() -> Path:
    """~/.avocado/ root directory."""
    return Path.home() / ".avocado"


def _project_avocado_root() -> Path:
    """cwd/.avocado/ project-level root (dev scenario: override user-level defaults inside a monorepo)."""
    return Path.cwd() / ".avocado"


def ensure_user_dirs() -> Path:
    """Create ~/.avocado/{output,presets,var-maps,plugins} on first run.

    Idempotent: existing dirs are left untouched. Returns ~/.avocado/.
    """
    root = _user_avocado_root()
    root.mkdir(parents=True, exist_ok=True)
    for subdir in ("output", "presets", "var-maps", "plugins"):
        (root / subdir).mkdir(parents=True, exist_ok=True)

    # Copy bundled neutral example templates to the user dir as .example
    # files (with a teaching header). Component-library-specific assets
    # (e.g. a custom preset) are maintained by the user in ~/.avocado/.
    try:
        bundled = files("avocado._bundled")
        for resource, target_name, header_text in (
            (
                "presets/antd.yaml",
                "antd.yaml.example",
                "# avocado neutral example preset (Ant Design).\n"
                "# Copy to antd.yaml or use it as a template for your own preset.\n"
                "# Full field reference: docs/preset-guide.md\n\n",
            ),
        ):
            dst = (
                root / "presets" / target_name
                if "presets" in resource
                else root / "var-maps" / target_name
            )
            if dst.exists():
                continue
            try:
                src = bundled / resource
                content = src.read_text()
                dst.write_text(header_text + content)
            except (AttributeError, FileNotFoundError):
                pass  # Resource missing or unreadable — skip silently
    except Exception:
        pass  # Template copy failure must not block the main flow

    return root


def resolve_output_dir(cli_path: str | os.PathLike | None = None) -> Path:
    """Default ~/.avocado/output/; CLI or cwd/.avocado/output/ overrides."""
    if cli_path:
        return Path(cli_path)
    project = _project_avocado_root() / "output"
    if project.exists():
        return project
    return _user_avocado_root() / "output"


def resolve_preset(name: str, cli_path: str | os.PathLike | None = None) -> Path:
    """preset 4-layer lookup: CLI > cwd/.avocado/presets/ > ~/.avocado/presets/ > bundled."""
    if cli_path:
        return Path(cli_path)
    fname = name if name.endswith(".yaml") else f"{name}.yaml"
    # project level
    project = _project_avocado_root() / "presets" / fname
    if project.exists():
        return project
    # user level
    user = _user_avocado_root() / "presets" / fname
    if user.exists():
        return user
    # bundled
    bundled = files("avocado._bundled") / "presets" / fname
    return Path(str(bundled))


def resolve_var_map(name: str, cli_path: str | os.PathLike | None = None) -> Path:
    """var-map 4-layer lookup (same pattern as preset)."""
    if cli_path:
        return Path(cli_path)
    fname = name if name.endswith(".yaml") else f"{name}.yaml"
    for root in (_project_avocado_root(), _user_avocado_root()):
        candidate = root / "var-maps" / fname
        if candidate.exists():
            return candidate
    bundled = files("avocado._bundled") / "var-maps" / fname
    return Path(str(bundled))


def resolve_user_config() -> Path:
    """User global config file path: ~/.avocado/config.yaml (project-level cwd/.avocado/config.yaml takes precedence).

    Holds sensitive info (figma_token) + global defaults (output_dir etc.). File permission recommended 600.
    """
    project = _project_avocado_root() / "config.yaml"
    if project.exists():
        return project
    return _user_avocado_root() / "config.yaml"


def load_user_config() -> dict:
    """Read ~/.avocado/config.yaml (global defaults incl. figma_token).

    4-layer lookup: project-level cwd/.avocado/config.yaml > user-level ~/.avocado/config.yaml.
    Returns an empty dict when the file does not exist (does not force creation).

    The returned dict may contain:
        - figma_token: str (Figma Personal Access Token)
        - output_dir: str (overrides the default ~/.avocado/output/)
        - other user-defined defaults
    """
    import yaml

    for root in (_project_avocado_root(), _user_avocado_root()):
        candidate = root / "config.yaml"
        if candidate.exists():
            try:
                return yaml.safe_load(candidate.read_text()) or {}
            except Exception:
                return {}
    return {}


def resolve_token(cli_token: str | None = None) -> str | None:
    """Figma token 4-layer lookup: CLI flag > env var > ~/.avocado/config.yaml > project level.

    Args:
        cli_token: value passed explicitly via the --token flag (highest priority)

    Returns:
        the token string, or None (when not found, the caller decides how to report)
    """
    if cli_token:
        return cli_token
    env_token = os.environ.get("FIGMA_TOKEN")
    if env_token:
        return env_token
    cfg = load_user_config()
    return cfg.get("figma_token")
