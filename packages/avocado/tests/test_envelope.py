"""Tests for envelope.py."""

import json
import sys
from pathlib import Path

import pytest

from avocado.envelope import ERROR_CODES, emit_error, emit_ok


def test_emit_ok_basic(capsys):
    """Success envelope: {"ok": true, "data": {...}}, exit 0."""
    with pytest.raises(SystemExit) as exc_info:
        emit_ok({"jsx": "<div/>"})
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == {"ok": True, "data": {"jsx": "<div/>"}}


def test_emit_ok_serializes_path(capsys):
    """Path values are automatically converted to str."""
    with pytest.raises(SystemExit):
        emit_ok({"path": Path("/tmp/out.jsx")})
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["data"]["path"] == "/tmp/out.jsx"


def test_emit_ok_serializes_bytes(capsys):
    """bytes values are automatically decoded."""
    with pytest.raises(SystemExit):
        emit_ok({"content": b"hello"})
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["data"]["content"] == "hello"


def test_emit_ok_serializes_set(capsys):
    """set values are automatically converted to a sorted list."""
    with pytest.raises(SystemExit):
        emit_ok({"modes": {"flex", "absolute"}})
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["data"]["modes"] == ["absolute", "flex"]


def test_emit_error_known_code(capsys):
    """Known error code: includes code/message/hint, exit_code taken from the dict."""
    with pytest.raises(SystemExit) as exc_info:
        emit_error("figma_not_found", "node 1:2 not found")
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is False
    assert data["error"]["code"] == "figma_not_found"
    assert data["error"]["message"] == "node 1:2 not found"
    assert "FIGMA_TOKEN" in data["error"]["hint"]


def test_emit_error_invalid_argument_exit_2(capsys):
    """invalid_argument's exit_code is 2 (argparse layer)."""
    with pytest.raises(SystemExit) as exc_info:
        emit_error("invalid_argument", "bad url")
    assert exc_info.value.code == 2


def test_emit_error_custom_hint_overrides(capsys):
    """Custom hint overrides the dict default."""
    with pytest.raises(SystemExit):
        emit_error("figma_not_found", "x", hint="custom hint here")
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["error"]["hint"] == "custom hint here"


def test_emit_error_unknown_code_falls_back(capsys):
    """Unknown code falls back to internal_error."""
    with pytest.raises(SystemExit) as exc_info:
        emit_error("totally_unknown_code", "x")
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["error"]["code"] == "internal_error"


def test_error_codes_dict_complete():
    """ERROR_CODES contains all required codes."""
    expected = {
        "figma_not_found",
        "figma_auth_failed",
        "figma_rate_limited",
        "figma_cache_miss",
        "invalid_argument",
        "internal_error",
        # FIX: split file vs node not found
        "figma_file_not_found",
        "figma_node_not_found",
        # FIX: dedicated code for SIGINT interruption (exit 130)
        "interrupted",
    }
    assert set(ERROR_CODES.keys()) == expected


def test_emit_ok_broken_pipe_silent_exit():
    """When the stdout pipe is closed, exit 0 silently (head/tail scenario)."""

    # This test is a bit complex to simulate; monkeypatch sys.stdout.write to raise BrokenPipeError
    class _BrokenStdout:
        def write(self, *a):
            raise BrokenPipeError()

        def flush(self):
            pass

    orig = sys.stdout
    sys.stdout = _BrokenStdout()
    try:
        with pytest.raises(SystemExit) as exc_info:
            emit_ok({"x": 1})
        assert exc_info.value.code == 0
    finally:
        sys.stdout = orig
