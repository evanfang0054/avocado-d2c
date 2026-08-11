"""VariableID → semantic CSS variable name mapping.

Users provide a YAML file mapping Figma VariableIDs to
semantic CSS variable names (without the `--` prefix — CLI adds it).

Mapping file format (`var-maps/<lib>.yaml`):

    "VariableID:9810cffc.../15156:453": color-bg-primary
    "VariableID:9810cffc.../15156:454": color-text-primary

Load rules:
  - `--var-map <path>` explicit → load that file
  - `--component-lib <name>` without `--var-map` → auto-try `var-maps/<name>.yaml`
  - File missing → return empty dict (no error)
  - Keys not starting with `VariableID:` are skipped (with a stderr warning)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Valid CSS custom property identifier (relaxed): letters, digits, hyphens,
# underscores. Must start with a letter or underscore.
_CSS_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def load_var_map(path: str | Path | None) -> dict[str, str]:
    """Load a VariableID → semantic name mapping from a YAML file.

    Returns empty dict if path is None or file does not exist. Skips entries
    whose key doesn't start with `VariableID:` or whose value isn't a valid
    CSS identifier (emitting a stderr warning for each skip).
    """
    if path is None:
        return {}
    p = Path(path)
    if not p.exists():
        return {}

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        print(
            "warning: PyYAML not installed; var-map ignored",
            file=sys.stderr,
        )
        return {}

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"warning: failed to parse var-map {p}: {e}", file=sys.stderr)
        return {}

    if not isinstance(data, dict):
        return {}

    out: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key.startswith("VariableID:"):
            continue
        if not isinstance(value, str) or not _CSS_IDENT_RE.match(value):
            continue
        out[key] = value
    return out
