"""Adapter debug trace collector (--trace-adapter).

Lightweight global singleton. No-op when disabled (zero overhead);
all record() calls are exception-safe so trace can never break the
main pipeline.

NOT thread-safe: check-then-append is not atomic. Safe today because
the pipeline is single-threaded; if trace is ever wired into a worker
pool (e.g. image prefetch), add a lock.
"""

from __future__ import annotations

_VALID_KINDS = {"preset_matches", "extractor_outputs", "plugin_hooks"}
# --trace-adapter 子集值 → trace kind（模块名与 kind 不同，必须映射）
_MODULE_TO_KIND = {
    "preset": "preset_matches",
    "extractor": "extractor_outputs",
    "hook": "plugin_hooks",
}
# kind -> list[dict]; only populated when enabled
_RECORDS: dict[str, list[dict]] = {k: [] for k in _VALID_KINDS}
_ENABLED: set[str] = set()


def enable(modules: set[str] | list[str]) -> None:
    """Enable trace for the given module subset (subset of preset/extractor/hook).

    Raises ValueError on an unknown module name so typos surface early
    (e.g. --trace-adapter=prese) instead of silently enabling nothing.
    """
    _ENABLED.clear()
    for m in modules:
        k = _MODULE_TO_KIND.get(m.lower())
        if k is None:
            raise ValueError(
                f"unknown trace module {m!r}; valid: {sorted(_MODULE_TO_KIND)}"
            )
        _ENABLED.add(k)


def disable() -> None:
    _ENABLED.clear()


def enabled_modules() -> set[str]:
    """Return enabled module names (preset/extractor/hook), not kinds."""
    return {m for m, k in _MODULE_TO_KIND.items() if k in _ENABLED}


def is_enabled(kind: str) -> bool:
    """Whether a trace kind (preset_matches/extractor_outputs/plugin_hooks) is active."""
    return kind in _ENABLED


def record(kind: str, entry: dict) -> None:
    """Record a trace entry for kind. No-op when the module is not enabled."""
    try:
        if kind not in _ENABLED:
            return
        _RECORDS[kind].append(entry)
    except Exception:
        pass  # zero-exception-risk: never break the pipeline


def records(kind: str) -> list[dict]:
    """Return a copy of recorded entries for kind."""
    return list(_RECORDS.get(kind, []))


def reset() -> None:
    """Clear all records and disable trace (call at each run start)."""
    for k in _RECORDS:
        _RECORDS[k] = []
    _ENABLED.clear()
