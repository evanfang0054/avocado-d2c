"""Agent-native envelope output helper.

All avocado CLI commands use this module to emit a uniform JSON envelope on stdout:
  success: {"ok": true,  "data": {...}}
  failure: {"ok": false, "error": {"code": "...", "message": "...", "hint": "..."}}

Exit codes mirror the ok field: 0 = ok:True, non-zero = ok:False.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Error code dict (single source of truth)
ERROR_CODES: dict[str, dict[str, Any]] = {
    "figma_not_found": {"hint": "check FIGMA_TOKEN and the URL are correct", "exit_code": 1},
    "figma_file_not_found": {
        "hint": "URL file_key is wrong or no permission — copy the full Figma URL and verify the token can access the file",
        "exit_code": 1,
    },
    "figma_node_not_found": {
        "hint": "node-id is wrong or was deleted — right-click the node in Figma and 'Copy link' for the full URL",
        "exit_code": 1,
    },
    "figma_auth_failed": {
        "hint": "token is invalid or expired — check the FIGMA_TOKEN env var or config.yaml, reset with `avocado init --token <new>`",
        "exit_code": 1,
    },
    "figma_rate_limited": {
        "hint": "Figma API rate limited — retry in a few seconds or lower concurrency (--workers)",
        "exit_code": 1,
    },
    "figma_cache_miss": {
        "hint": "offline cache miss — run once online (drop --offline) with --cache-dir to populate. --cache-dir should point at the directory containing nodes/ and render/ subdirs (usually the figma_cache/ dir). See the diagnostic info at the end of error.message for the current cache-dir layout",
        "exit_code": 1,
    },
    "invalid_argument": {
        "hint": "invalid argument — check the parameter name and legal values in the error message; run avocado schema for the full command/flag list",
        "exit_code": 2,
    },
    "internal_error": {
        "hint": "avocado internal error — rerun under editable install to see the stack trace, or file an issue with the error message",
        "exit_code": 1,
    },
    "interrupted": {
        "hint": "user interrupted (SIGINT) — partial artifacts may exist; rerun to finish the pipeline",
        "exit_code": 130,
    },
}


class _EnvelopeJSONEncoder(json.JSONEncoder):
    """Handle non-JSON standard types like Path / bytes / set."""

    def default(self, obj):
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        if isinstance(obj, set):
            return sorted(obj)
        return super().default(obj)


def emit_ok(data: dict[str, Any], exit_code: int = 0) -> None:
    """Emit a success envelope to stdout and sys.exit(exit_code).

    Path / bytes / set values in data are serialized automatically.
    Circular references raise ValueError (caller should fix).
    Falls back to stderr on stdout write failure (e.g. closed pipe).

    UX FIX: BrokenPipe (downstream like head/jq closes the pipe) keeps the
    original exit_code and no longer forces exit(0) — otherwise
    `avocado "not-a-url" | jq` returned 0 on BrokenPipe and made AI agents
    misjudge it as success (it is actually invalid_argument exit=2).
    """
    envelope = {"ok": True, "data": data}
    try:
        text = json.dumps(envelope, cls=_EnvelopeJSONEncoder, ensure_ascii=False, indent=None)
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except (ValueError, TypeError) as e:
        # circular refs or non-serializable types: degrade to stderr, keep stdout clean
        sys.stderr.write(f"envelope serialization failed: {e}\n")
        sys.exit(1)
    except BrokenPipeError:
        # pipe closed (head/tail/jq etc.): keep original exit_code, don't force exit(0)
        # UX FIX: exit(0) previously made `avocado error | jq` misjudge success
        _silence_broken_pipe()
        sys.exit(exit_code)
    sys.exit(exit_code)


def emit_error(
    code: str,
    message: str,
    hint: str | None = None,
    exit_code: int | None = None,
) -> None:
    """Emit an error envelope to stdout and sys.exit(exit_code).

    code must be in ERROR_CODES (otherwise it falls back to internal_error).
    When hint is omitted it is taken from ERROR_CODES[code]["hint"].
    When exit_code is omitted it is taken from ERROR_CODES[code]["exit_code"].
    """
    if code not in ERROR_CODES:
        # unknown code: degrade to internal_error
        sys.stderr.write(f"envelope: unknown error code {code!r}, falling back to internal_error\n")
        code = "internal_error"
    if hint is None:
        hint = ERROR_CODES[code].get("hint")
    if exit_code is None:
        exit_code = ERROR_CODES[code].get("exit_code", 1)
    envelope = {
        "ok": False,
        "error": {"code": code, "message": message, "hint": hint},
    }
    try:
        text = json.dumps(envelope, ensure_ascii=False)
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        # UX FIX: keep exit_code, don't force exit(0)
        _silence_broken_pipe()
        sys.exit(exit_code)
    sys.exit(exit_code)


def _silence_broken_pipe() -> None:
    """Clean up stdout after BrokenPipe (avoid a second BrokenPipeError when the interpreter flushes on exit).

    Note: do NOT dup2 stderr — that breaks pytest's fd capture (learned the hard way in test_envelope.py).
    Python may print a "BrokenPipeError" traceback on exit after stdout is closed,
    but that only happens in extreme scenarios (stdout is a pipe and the downstream
    closes early). When an agent actually runs `avocado ... | jq`, jq reads the whole
    envelope before closing, so it does not trigger.
    Hence we only close stdout here, without more aggressive fd redirection.
    """
    try:
        sys.stdout.close()
    except Exception:
        pass
