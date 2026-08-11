"""End-to-end CLI tests — invoke the actual `avocado` binary via subprocess.

This is the contract verification layer: if anything in the entry point,
argument parsing, or output writing breaks, these tests catch it.

Two flavors:
  - Offline: uses fixture JSON, no network. Runs `avocado --help` etc.
  - Live: uses real Figma API (requires FIGMA_TOKEN). Skipped if missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _has_binary() -> bool:
    """Check if `avocado` is on PATH (i.e. pip install -e was run)."""
    return shutil.which("avocado") is not None


def _has_token() -> bool:
    return bool(os.environ.get("FIGMA_TOKEN"))


# ── offline: --help ──


@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
def test_cli_help_works() -> None:
    """`avocado --help` must exit 0 and return JSON envelope (FIX:).

    --help now returns JSON envelope with command list + hint
    (not Click Usage text). Flag details are in `avocado schema`.
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
    assert "url" in r.stdout.lower()


# ── offline: deprecation shim ──


@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
def test_cli_deprecated_format_inline_warns() -> None:
    """Old `--format inline` should warn and translate to --format html --css inline.

    We don't have FIGMA_TOKEN in offline mode, so the command will fail later,
    but the deprecation warning is emitted early — we just check stderr.
    """
    env = dict(os.environ)
    env.pop("FIGMA_TOKEN", None)
    r = subprocess.run(
        ["avocado", "https://www.figma.com/design/ABCDE/Title?node-id=1:2", "--format", "inline"],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert "--format inline is deprecated" in r.stderr
    assert "--format html --css inline" in r.stderr


@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
def test_cli_deprecated_format_tailwind_warns() -> None:
    """Old `--format tailwind` should warn and translate to --format html --css tailwind."""
    env = dict(os.environ)
    env.pop("FIGMA_TOKEN", None)
    r = subprocess.run(
        ["avocado", "https://www.figma.com/design/ABCDE/Title?node-id=1:2", "--format", "tailwind"],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert "--format tailwind is deprecated" in r.stderr
    assert "--format html --css tailwind" in r.stderr


# ── offline: bad URL ──


@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
def test_cli_bad_url_exits_nonzero() -> None:
    """Invalid URL must exit non-zero with stderr message.

    Uses --human to keep verifying the legacy stderr contract; the default
    agent-native mode emits a JSON envelope on stdout instead (covered by
    tests/test_cli_envelope.py).
    """
    r = subprocess.run(
        ["avocado", "--human", "not-a-figma-url-at-all"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode != 0
    assert "error" in r.stderr.lower() or "url" in r.stderr.lower()


@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
def test_cli_url_missing_node_id() -> None:
    """URL without ?node-id= must error out."""
    r = subprocess.run(
        ["avocado", "https://www.figma.com/design/ABCDE/Title"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode != 0


@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
def test_cli_no_token_exits(monkeypatch, tmp_path) -> None:
    """Completely no token (no env + no ~/.avocado/config.yaml) must fail gracefully.

    Token 4-layer lookup (CLI > env > ~/.avocado/config.yaml > project-level).
    The subprocess HOME points at tmp_path, ensuring config.yaml is also absent
    (monkeypatching Path.home only affects the current process; the subprocess is
    controlled via environment variables).
    """
    env = dict(os.environ)
    env.pop("FIGMA_TOKEN", None)
    env["HOME"] = str(tmp_path)  # subprocess home points at an empty dir (no config.yaml)
    r = subprocess.run(
        ["avocado", "--human", "https://www.figma.com/design/ABCDE/Title?node-id=1:2"],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert r.returncode != 0
    assert "token" in r.stderr.lower()


# ── live: real end-to-end against Figma API ──


LIVE_URL = (
    "https://www.figma.com/design/FIGMA_FILE_KEY_PLACEHOLDER_001/"
    "Sample-Page--Confirm-Dialog-?node-id=0-1"
)


@pytest.mark.live
@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
@pytest.mark.skipif(not _has_token(), reason="FIGMA_TOKEN not set")
def test_live_default_run(tmp_path: Path) -> None:
    """Full real-data run with default options (beautify on).

    Uses --human so the test keeps verifying the legacy file-output contract;
    the default agent-native mode would emit a JSON envelope on stdout
    instead (covered by tests/test_cli_envelope.py).
    """
    out_file = tmp_path / "default.jsx"
    r = subprocess.run(
        ["avocado", "--human", LIVE_URL, "-o", str(out_file)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert out_file.exists()
    content = out_file.read_text()
    assert "<div" in content
    assert "1732:4245" in content  # data-figma-id of root


@pytest.mark.live
@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
@pytest.mark.skipif(not _has_token(), reason="FIGMA_TOKEN not set")
def test_live_no_beautify_run(tmp_path: Path) -> None:
    """--no-beautify: raw codegen output (--human for legacy stdout contract)."""
    out_file = tmp_path / "nobeautify.jsx"
    r = subprocess.run(
        ["avocado", "--human", LIVE_URL, "--no-beautify", "-o", str(out_file)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0
    assert out_file.exists()
    content = out_file.read_text()
    assert "<div" in content
    assert "<img" in content  # VECTOR/image nodes


@pytest.mark.live
@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
@pytest.mark.skipif(not _has_token(), reason="FIGMA_TOKEN not set")
def test_live_tailwind_run(tmp_path: Path) -> None:
    """--format tailwind: should produce className attributes (--human legacy mode)."""
    out_file = tmp_path / "tw.jsx"
    r = subprocess.run(
        [
            "avocado",
            "--human",
            LIVE_URL,
            "--format",
            "tailwind",
            "--no-beautify",
            "-o",
            str(out_file),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0
    content = out_file.read_text()
    assert "className=" in content
    # flex-related class should appear (Confirm root has flex column)
    assert "flex" in content


@pytest.mark.live
@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
@pytest.mark.skipif(not _has_token(), reason="FIGMA_TOKEN not set")
def test_live_with_components_mapping(tmp_path: Path) -> None:
    """--components path.yaml: should recognize Button INSTANCE (--human legacy mode)."""
    components_yaml = tmp_path / "components.yaml"
    components_yaml.write_text(
        "components:\n  - name: 'Button'\n    component: 'Button'\n    package: 'antd'\n"
    )
    out_file = tmp_path / "with_comp.jsx"
    r = subprocess.run(
        [
            "avocado",
            "--human",
            LIVE_URL,
            "--components",
            str(components_yaml),
            "--no-beautify",
            "-o",
            str(out_file),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0
    content = out_file.read_text()
    assert "Button" in content


@pytest.mark.live
@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
@pytest.mark.skipif(not _has_token(), reason="FIGMA_TOKEN not set")
def test_live_inspect_warnings_to_stderr(tmp_path: Path) -> None:
    """Inspect warnings should appear on stderr (--human legacy mode)."""
    out_file = tmp_path / "inspect.jsx"
    r = subprocess.run(
        ["avocado", "--human", LIVE_URL, "--no-beautify", "-o", str(out_file)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0
    # stderr should contain warning lines like "[info] ..."
    assert "[info]" in r.stderr or "[warning]" in r.stderr


@pytest.mark.live
@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
@pytest.mark.skipif(not _has_token(), reason="FIGMA_TOKEN not set")
def test_live_stdout_when_no_output_flag() -> None:
    """Without -o, JSX should go to stdout (--human legacy mode)."""
    r = subprocess.run(
        ["avocado", "--human", LIVE_URL, "--no-beautify"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0
    assert "<div" in r.stdout
    # inspect warnings on stderr
    assert r.stderr  # non-empty


@pytest.mark.live
@pytest.mark.skipif(not _has_binary(), reason="avocado binary not installed")
@pytest.mark.skipif(not _has_token(), reason="FIGMA_TOKEN not set")
def test_live_no_inspect_flag_suppresses_warnings(tmp_path: Path) -> None:
    """--no-inspect: no warnings on stderr (--human legacy mode)."""
    out_file = tmp_path / "quiet.jsx"
    r = subprocess.run(
        ["avocado", "--human", LIVE_URL, "--no-beautify", "--no-inspect", "-o", str(out_file)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0
    # stderr should only contain the "wrote N bytes" message, no warnings
    assert "[info]" not in r.stderr
    assert "[warning]" not in r.stderr
