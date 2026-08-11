"""Tests for envelope ``format_raw`` field.

``format_raw`` records the user's raw ``--format`` input (before preset
expansion / deprecation mapping). The bug: it was computed before preset
expansion using only the click default value, so when ``--preset designer``
indirectly set ``--format html``, ``format_raw`` was wrongly recorded as the
click default ``"react"`` instead of ``None`` (preset is not user intent).

Fix uses ``click.ParameterSource`` to distinguish CLI-passed vs default.
These tests cover the 3 scenarios via ``--dry-run`` (no network, no token
beyond a dummy env var).
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from avocado.cli import main as cli_main

_URL = "https://www.figma.com/design/KEY/T?node-id=1:2"


def _run(args: list[str], monkeypatch) -> dict:
    """Invoke CLI with dummy token + dry-run; return parsed envelope."""
    monkeypatch.setenv("FIGMA_TOKEN", "dummy")
    runner = CliRunner()
    result = runner.invoke(
        cli_main,
        [_URL, "--dry-run", *args],
    )
    assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.stderr}"
    env = json.loads(result.output)
    assert env["ok"] is True, f"envelope not ok: {env}"
    return env


def test_format_raw_user_explicit_html(monkeypatch) -> None:
    """User passes ``--format html`` explicitly → format_raw = 'html'."""
    env = _run(["--format", "html"], monkeypatch)
    validated = env["data"]["validated"]
    assert validated["format"] == "html"
    assert validated["format_raw"] == "html"


def test_format_raw_user_explicit_react(monkeypatch) -> None:
    """User passes ``--format react`` explicitly → format_raw = 'react'."""
    env = _run(["--format", "react"], monkeypatch)
    validated = env["data"]["validated"]
    assert validated["format"] == "react"
    assert validated["format_raw"] == "react"


def test_format_raw_default_no_flag(monkeypatch) -> None:
    """User doesn't pass ``--format`` → format_raw = None (click default)."""
    env = _run([], monkeypatch)
    validated = env["data"]["validated"]
    # format reflects the click default ("react")
    assert validated["format"] == "react"
    # format_raw must be None: user didn't explicitly choose anything
    assert validated["format_raw"] is None


def test_format_raw_preset_designer_indirect_format(monkeypatch) -> None:
    """``--preset designer`` indirectly sets ``--format html`` → format_raw = None.

    Core bug: preset expands --format to 'html', but the user did not
    explicitly pass --format, so format_raw must be None (preset is not user
    intent). Previously format_raw was wrongly 'react' (the click default
    captured before preset expansion).
    """
    env = _run(["--preset", "designer"], monkeypatch)
    validated = env["data"]["validated"]
    # preset expands format → 'html'
    assert validated["format"] == "html"
    # user did not pass --format explicitly → format_raw must be None
    assert validated["format_raw"] is None


def test_format_raw_user_explicit_overrides_preset(monkeypatch) -> None:
    """User passes ``--format react`` + preset designer (which sets html).

    Explicit user flag wins → format='react' AND format_raw='react'.
    """
    env = _run(["--preset", "designer", "--format", "react"], monkeypatch)
    validated = env["data"]["validated"]
    # explicit flag wins over preset
    assert validated["format"] == "react"
    # user explicitly passed react → format_raw must reflect user input
    assert validated["format_raw"] == "react"
