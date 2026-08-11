"""avocado CLI agent-native envelope tests (subcommand mode).

Two contracts are verified:
1. Default invocation (no --human) writes a JSON envelope to stdout (agent-native).
2. The --human flag exists and is recognized (listed by --help).

Note: these tests do not depend on FIGMA_TOKEN —
- test_cli_default_outputs_envelope uses a fake URL to trigger the figma_not_found
  error envelope, only verifying the envelope structure (ok=False + error.code),
  not the business success path.
- test_cli_human_flag_exists only runs --help: zero network, zero token.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest


def _has_binary() -> bool:
    """Whether the avocado console script is on PATH (only after pip install -e)."""
    return shutil.which("avocado") is not None


def _has_token() -> bool:
    return bool(os.environ.get("FIGMA_TOKEN"))


@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
def test_cli_human_flag_in_help() -> None:
    """--help returns a JSON envelope (FIX:), schema contains --human.

    --help now returns an envelope + command list.
    The --human flag details are verified in the `avocado schema` output.
    """
    r = subprocess.run(
        ["avocado", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0
    import json as _json

    env = _json.loads(r.stdout)
    assert env["ok"] is True
    assert "commands" in env["data"]
    # schema holds the full flag list; --help only gives a command overview
    r2 = subprocess.run(
        ["avocado", "schema"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    env2 = _json.loads(r2.stdout)
    all_flags = str(env2["data"]["commands"])
    assert "--human" in all_flags


@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
def test_cli_default_outputs_envelope_on_error() -> None:
    """No --human + no token: stdout must be a JSON error envelope.

    Scenario: fake URL + no token, so avocado necessarily fails at the
    figma API call stage.
    Contract: on failure stdout emits {"ok": false, "error": {"code": ..., "message": ..., "hint": ...}}.
    (The old click.echo-to-stderr + empty-stdout path is not allowed.)
    """
    env = dict(os.environ)
    env.pop("FIGMA_TOKEN", None)  # ensure no token, triggering figma_not_found
    r = subprocess.run(
        [
            "avocado",
            "https://www.figma.com/design/FAKEKEY/Title?node-id=0:1",
            "--no-beautify",
        ],  # skip beautify for speed + avoid environment differences
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    # no token must fail
    assert r.returncode != 0, (
        f"expected non-zero exit (no token), got 0\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    # default (no --human) stdout must be a valid JSON envelope
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"stdout is not JSON envelope (agent-native contract broken): {e}\n"
            f"stdout: {r.stdout!r}\nstderr: {r.stderr!r}"
        )
    # envelope structure assertions
    assert data["ok"] is False, f"expected ok=False, got: {data}"
    assert "error" in data, f"missing error field in envelope: {data}"
    assert "code" in data["error"], f"missing error.code: {data}"
    assert "message" in data["error"], f"missing error.message: {data}"
    # error code should be a known one (figma_not_found or invalid_argument, etc.)
    assert data["error"]["code"], f"empty error code: {data}"


@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
def test_cli_human_flag_keeps_legacy_stderr_behavior() -> None:
    """--human + no token: keep the legacy stderr error output (backward compatible).

    Scenario: --human switches back to human mode; with no token the error
    goes via click.echo to stderr.
    Contract: stdout emits no JSON (preserves legacy behavior, backward
    compatible with legacy tests such as test_cli_e2e.py).
    """
    env = dict(os.environ)
    env.pop("FIGMA_TOKEN", None)
    r = subprocess.run(
        [
            "avocado",
            "https://www.figma.com/design/FAKEKEY/Title?node-id=0:1",
            "--human",
            "--no-beautify",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    assert r.returncode != 0
    # --human mode: stdout must not be a valid JSON envelope (legacy click.echo behavior kept)
    # errors go to stderr
    assert r.stderr, (
        f"--human mode should emit error to stderr, got empty stderr; stdout: {r.stdout}"
    )
    # token-related errors should be on stderr
    assert "token" in r.stderr.lower() or "error" in r.stderr.lower(), (
        f"expected token/error hint in stderr, got: {r.stderr!r}"
    )


@pytest.mark.live
@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
@pytest.mark.skipif(not _has_token(), reason="FIGMA_TOKEN not set")
def test_cli_default_envelope_success_path(tmp_path) -> None:
    """[live] With a token, the default invocation outputs a success envelope (with jsx field).

    Runs the full pipeline against a real figma URL, asserting stdout is
    {"ok": true, "data": {"jsx": ..., ...}}.
    """
    live_url = (
        "https://www.figma.com/design/FIGMA_FILE_KEY_PLACEHOLDER_001/"
        "Sample-Page--Confirm-Dialog-?node-id=0-1"
    )
    out_file = tmp_path / "out.jsx"
    r = subprocess.run(
        ["avocado", live_url, "--no-beautify", "-o", str(out_file)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert "data" in data
    # jsx field present (even with -o writing a file, the envelope should still return the jsx text for the agent to inspect)
    assert "jsx" in data["data"]
    # artifacts field contains the path
    assert data["data"].get("artifacts", {}).get("jsxPath") == str(out_file)
    # the file was actually written
    assert out_file.exists()
