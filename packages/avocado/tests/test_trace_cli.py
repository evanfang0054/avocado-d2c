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


def test_main_resets_trace_across_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    # 跨 run 无泄漏：带 trace 的 run 后，无 trace 的 run 必须重置状态
    # 干净 CI 环境没有 ~/.avocado/config.yaml；dry-run 在创建 FigmaClient 之后
    # 才短路，无 token 会 figma_auth_failed → exit 1，故注入假 token（不会真调 API）
    monkeypatch.setenv("FIGMA_TOKEN", "figd_" + "0" * 40)
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


# ── plugin 识别可见性（matched_by=plugin）───────────────────────────────────


def test_augment_plugin_matches_adds_plugin_records() -> None:
    from avocado.cli import _augment_plugin_matches
    from avocado.model.tree_node import TreeNode as TN

    trace.enable({"preset"})
    tree = TN(id="1:1", name="Page", source_type="FRAME", tag_name="div", children=[
        TN(id="1:2", name="Body", source_type="FRAME", tag_name="Text",
           is_component=True, component_package="lib"),
    ])
    _augment_plugin_matches(tree)
    recs = trace.records("preset_matches")
    assert len(recs) == 1
    assert recs[0]["matched_by"] == "plugin"
    assert recs[0]["node_id"] == "1:2"
    assert recs[0]["path"] == ["Page", "Body"]
    assert recs[0]["entry_short"] == {"component": "Text", "package": "lib"}


def test_augment_skips_already_recorded() -> None:
    from avocado.cli import _augment_plugin_matches
    from avocado.model.tree_node import TreeNode as TN

    trace.enable({"preset"})
    trace.record("preset_matches", {"node_id": "1:2", "node_name": "Body",
                                    "matched_by": "name", "entry_short": {"component": "Text"}})
    tree = TN(id="1:1", name="Page", source_type="FRAME", tag_name="div", children=[
        TN(id="1:2", name="Body", source_type="FRAME", tag_name="Text", is_component=True),
    ])
    _augment_plugin_matches(tree)
    assert len(trace.records("preset_matches")) == 1  # 不重复


def test_augment_noop_when_disabled() -> None:
    from avocado.cli import _augment_plugin_matches
    from avocado.model.tree_node import TreeNode as TN

    trace.disable()
    tree = TN(id="1:1", name="Page", source_type="FRAME", tag_name="div", children=[
        TN(id="1:2", name="Body", source_type="FRAME", tag_name="Text", is_component=True),
    ])
    _augment_plugin_matches(tree)
    assert trace.records("preset_matches") == []


def test_augment_plugin_path_truncated_on_deep_tree() -> None:
    """Deep tree → plugin record path is truncated (≤8, '…' prefix, node last)."""
    from avocado.cli import _augment_plugin_matches
    from avocado.model.tree_node import TreeNode as TN

    trace.enable({"preset"})
    # build a 10-level chain with the component at the deepest leaf
    root = TN(id="n0", name="L0", source_type="FRAME", tag_name="div")
    cur = root
    for i in range(1, 10):
        nxt = TN(id=f"n{i}", name=f"L{i}", source_type="FRAME", tag_name="div")
        cur.children = [nxt]
        cur = nxt
    cur.is_component = True
    cur.tag_name = "Text"
    cur.component_package = "lib"

    _augment_plugin_matches(root)
    recs = trace.records("preset_matches")
    assert len(recs) == 1
    assert recs[0]["path"][0] == "…"
    assert recs[0]["path"][-1] == "L9"
    assert len(recs[0]["path"]) == 8


# ── 聚合改造 + issues 派生 ──────────────────────────────────────────────────


def test_build_trace_data_splits_applied_details() -> None:
    trace.enable({"preset"})
    trace.record("preset_matches", {"node_id": "1:1", "node_name": "A",
                                    "matched_by": "name", "entry_short": {"component": "A"}})
    trace.record("preset_matches", {"event": "applied", "node_id": "1:1", "node_name": "A",
                                    "variant_prop_misses": [{"field": "Size", "value": "Huge"}]})
    data = _build_trace_data()
    pm = data["preset_matches"]
    assert pm["total"] == 1 and pm["matched"] == 1 and pm["unmatched"] == 0
    assert pm["applied_details"] == [{"node_id": "1:1", "node_name": "A",
                                      "variant_prop_misses": [{"field": "Size", "value": "Huge"}]}]


def test_issues_derived_from_records() -> None:
    trace.enable({"preset", "extractor"})
    trace.record("preset_matches", {"node_id": "1:1", "node_name": "Title",
                                    "skipped_by": "name_no_match", "reason": "x",
                                    "suggestion": "- name: 'Title'\n  component: <fill>\n  package: <fill>"})
    trace.record("preset_matches", {"node_id": "1:2", "node_name": "Title",
                                    "skipped_by": "name_no_match", "reason": "x",
                                    "suggestion": "- name: 'Title'\n  component: <fill>\n  package: <fill>"})
    trace.record("preset_matches", {"event": "applied", "node_id": "1:3", "node_name": "Input",
                                    "leaf_dropped": {"children_count": 2, "kept_extras": []}})
    trace.record("extractor_outputs", {"component": "Steps", "extractor": "e",
                                       "success": False, "error": "empty_result"})
    data = _build_trace_data()
    issues = data["issues"]
    assert issues["unmatched_by_name"][0] == {
        "name": "Title", "count": 2,
        "suggestion": "- name: 'Title'\n  component: <fill>\n  package: <fill>",
    }
    assert issues["leaf_drops"] == [{"node_name": "Input", "children_count": 2}]
    assert issues["extractor_failures"] == [{"component": "Steps", "extractor": "e", "error": "empty_result"}]


def test_issues_variant_miss_has_recommendation() -> None:
    """variant_prop_misses entries carry a recommendation so designers know
    whether to fix (and what happens if they don't)."""
    trace.enable({"preset"})
    trace.record("preset_matches", {"event": "applied", "node_id": "1:9", "node_name": "Button",
                                    "component": "Button",
                                    "variant_prop_misses": [{"field": "Size", "value": "Huge"}]})
    data = _build_trace_data()
    miss = data["issues"]["variant_prop_misses"][0]
    assert miss["component"] == "Button"
    assert miss["field"] == "Size"
    assert miss["value"] == "Huge"
    assert "recommendation" in miss


def test_issues_empty_when_no_problems() -> None:
    trace.enable({"preset"})
    trace.record("preset_matches", {"node_id": "1:1", "node_name": "A",
                                    "matched_by": "name", "entry_short": {"component": "A"}})
    data = _build_trace_data()
    assert "issues" not in data


# ── schema 自省同步 ─────────────────────────────────────────────────────────


def test_schema_describes_enhanced_trace() -> None:
    from avocado.commands.schema import _SPEC

    main_cmd = next(c for c in _SPEC["commands"] if c["name"] == "avocado <url>")
    trace_desc = main_cmd["data_artifacts"]["trace"]
    assert "applied_details" in trace_desc
    assert "issues" in trace_desc
    assert "error" in trace_desc
    assert "suggestion" in trace_desc
    flag = next(f for f in main_cmd["flags"] if f["name"] == ["--trace-adapter"])
    assert "issues" in flag["help"]
    assert "suggestion" in flag["help"]
