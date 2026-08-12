"""Tests for --trace-adapter CLI flag, aggregation and schema sync."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from avocado.cli import _build_trace_data, _normalize_trace_adapter_argv, main
from avocado.parser import trace

URL = "https://www.figma.com/design/30wJJvfAAGLhXFkUt2OZOK/?node-id=1732:5574"


@pytest.fixture(autouse=True)
def _clean_trace() -> None:
    trace.reset()
    yield
    trace.reset()


# ── argv 预处理（cli() 入口，裸 flag → __all__） ─────────────────────────────


def test_normalize_bare_flag_to_all() -> None:
    assert _normalize_trace_adapter_argv(["url", "--trace-adapter"]) == [
        "url",
        "--trace-adapter=__all__",
    ]
    assert _normalize_trace_adapter_argv(["url", "--trace-adapter", "--summary"]) == [
        "url",
        "--trace-adapter=__all__",
        "--summary",
    ]
    assert _normalize_trace_adapter_argv(["url", "--trace-adapter=preset"]) == [
        "url",
        "--trace-adapter=preset",
    ]
    # 空格分隔值形式（--trace-adapter preset）保持原样，让 click 消费值
    assert _normalize_trace_adapter_argv(["url", "--trace-adapter", "preset"]) == [
        "url",
        "--trace-adapter",
        "preset",
    ]
    assert _normalize_trace_adapter_argv(["url", "--dry-run"]) == ["url", "--dry-run"]


# ── main 参数校验（非法子集 → invalid_argument，dry-run 前） ─────────────────


def test_trace_adapter_illegal_subset() -> None:
    r = CliRunner().invoke(main, [URL, "--dry-run", "--trace-adapter=foo"])
    assert r.exit_code == 2
    payload = json.loads(r.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_argument"
    assert "preset" in payload["error"]["hint"]


def test_trace_adapter_illegal_mixed_subset() -> None:
    r = CliRunner().invoke(main, [URL, "--dry-run", "--trace-adapter=preset,foo"])
    assert r.exit_code == 2
    assert json.loads(r.output)["error"]["code"] == "invalid_argument"


def test_trace_adapter_empty_subset() -> None:
    r = CliRunner().invoke(main, [URL, "--dry-run", "--trace-adapter="])
    assert r.exit_code == 2
    assert json.loads(r.output)["error"]["code"] == "invalid_argument"


def test_main_resets_trace_across_runs() -> None:
    # 跨 run 无泄漏：带 trace 的 run 后，无 trace 的 run 必须重置状态
    r1 = CliRunner().invoke(main, [URL, "--dry-run", "--trace-adapter=preset"])
    assert r1.exit_code == 0
    assert "preset" in trace.enabled_modules()
    r2 = CliRunner().invoke(main, [URL, "--dry-run"])
    assert r2.exit_code == 0
    assert trace.enabled_modules() == set()


# ── 聚合（_build_trace_data） ────────────────────────────────────────────────


def test_build_trace_data_aggregates_preset_matches() -> None:
    trace.enable({"preset"})
    trace.record("preset_matches", {"node_id": "1:2", "node_name": "B", "matched_by": "name", "entry_short": {"component": "B"}})
    trace.record("preset_matches", {"node_id": "1:1", "node_name": "A", "skipped_by": "name_no_match", "reason": "x"})
    trace.record("preset_matches", {"node_id": "1:3", "node_name": "C", "matched_by": "component_id", "entry_short": {"componentId": "9:3", "component": "C"}})
    data = _build_trace_data()
    pm = data["preset_matches"]
    assert pm["total"] == 3
    assert pm["matched"] == 2
    assert pm["unmatched"] == 1
    assert pm["total"] == pm["matched"] + pm["unmatched"]  # 聚合不变量
    # unmatched 全量、按 node_id 排序
    assert [u["node_id"] for u in pm["unmatched_details"]] == ["1:1"]
    # matched 样本按 node_id 排序
    assert [m["node_id"] for m in pm["matched_samples"]] == ["1:2", "1:3"]


def test_build_trace_data_matched_samples_capped_at_10() -> None:
    trace.enable({"preset"})
    # 乱序 node_id：cap 应取"排序后"前 10，不是插入前 10
    ids = [f"1:{i:02d}" for i in range(11, 0, -1)]  # 11..1 乱序
    for i in ids:
        trace.record("preset_matches", {"node_id": i, "node_name": "N", "matched_by": "name", "entry_short": {"component": "X"}})
    samples = _build_trace_data()["preset_matches"]["matched_samples"]
    assert len(samples) == 10
    assert [s["node_id"] for s in samples] == sorted(ids)[:10]


def test_build_trace_data_subset_filter() -> None:
    trace.enable({"preset"})
    trace.record("preset_matches", {"node_id": "1:1", "node_name": "A", "matched_by": "name", "entry_short": {"component": "A"}})
    trace.record("extractor_outputs", {"component": "S", "extractor": "e", "success": True, "keys": ["items"]})
    data = _build_trace_data()
    assert "preset_matches" in data
    assert "extractor_outputs" not in data
    assert "plugin_hooks" not in data


def test_build_trace_data_empty_when_disabled() -> None:
    assert _build_trace_data() == {}


def test_build_trace_data_sorts_extractor_and_hooks() -> None:
    trace.enable({"extractor", "hook"})
    trace.record("extractor_outputs", {"component": "B", "extractor": "e", "success": True})
    trace.record("extractor_outputs", {"component": "A", "extractor": "e", "success": True})
    trace.record("plugin_hooks", {"plugin": "b", "hook": "h", "nodes_affected": 1, "sample_names": []})
    trace.record("plugin_hooks", {"plugin": "a", "hook": "h", "nodes_affected": 1, "sample_names": []})
    data = _build_trace_data()
    assert [e["component"] for e in data["extractor_outputs"]] == ["A", "B"]
    assert [p["plugin"] for p in data["plugin_hooks"]] == ["a", "b"]


# ── schema 自省 ──────────────────────────────────────────────────────────────


def test_schema_declares_trace_adapter() -> None:
    from avocado.commands.schema import _SPEC

    main_cmd = next(c for c in _SPEC["commands"] if c["name"] == "avocado <url>")
    flags = main_cmd["flags"]
    assert any(f["name"] == ["--trace-adapter"] for f in flags)
