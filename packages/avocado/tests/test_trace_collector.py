"""Tests for the adapter debug trace collector (--trace-adapter infra)."""

from __future__ import annotations

import pytest

from avocado.parser import trace


@pytest.fixture(autouse=True)
def _clean_trace() -> None:
    """Every test starts from a clean trace state (global singleton)."""
    trace.reset()
    yield
    trace.reset()


def test_disabled_collector_is_noop() -> None:
    trace.disable()
    trace.record("preset_matches", {"node_id": "1:1"})
    assert trace.records("preset_matches") == []


def test_enable_subset_records_only_that_kind() -> None:
    trace.enable({"preset"})
    trace.record("preset_matches", {"node_id": "1:1"})
    trace.record("extractor_outputs", {"component": "X"})
    assert len(trace.records("preset_matches")) == 1
    assert trace.records("extractor_outputs") == []


def test_enable_maps_module_names_to_kinds() -> None:
    # --trace-adapter=preset 传模块名，record 用 kind——映射必须自洽
    trace.enable({"preset"})
    assert trace.enabled_modules() == {"preset"}
    trace.record("preset_matches", {"node_id": "1:1"})
    assert len(trace.records("preset_matches")) == 1


def test_enable_unknown_module_raises() -> None:
    # 非法模块名必须报错（否则 --trace-adapter=prese 静默启用空集）
    with pytest.raises(ValueError, match="unknown trace module"):
        trace.enable({"prese"})
    assert trace.enabled_modules() == set()


def test_record_exception_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    # record 内部实现若抛异常，必须被吞掉（零异常风险）
    trace.enable({"preset"})

    class _BoomList(list):
        def append(self, item):  # type: ignore[override]
            raise RuntimeError("collector boom")

    # 替换目标记录列表为抛错对象（list.append 本身只读，不能直接 patch）
    monkeypatch.setitem(trace._RECORDS, "preset_matches", _BoomList())
    trace.record("preset_matches", {"node_id": "1:1"})  # 必须静默
    # 恢复后正常路径仍可用
    monkeypatch.undo()
    trace.record("preset_matches", {"node_id": "1:2"})
    assert len(trace.records("preset_matches")) == 1


def test_reset_clears_records_and_modules() -> None:
    trace.enable({"preset", "hook"})
    trace.record("preset_matches", {"node_id": "1:1"})
    trace.record("plugin_hooks", {"plugin": "p"})
    trace.reset()
    assert trace.records("preset_matches") == []
    assert trace.records("plugin_hooks") == []
    assert trace.enabled_modules() == set()
