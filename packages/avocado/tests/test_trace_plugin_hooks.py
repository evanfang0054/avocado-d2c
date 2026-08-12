"""Tests for plugin hook trace collection (plugin_hooks)."""

from __future__ import annotations

import pytest

from avocado.model.tree_node import TreeNode
from avocado.parser import trace
from avocado.plugins.base import HookRegistry, Plugin, hook


@pytest.fixture(autouse=True)
def _clean_trace() -> None:
    trace.reset()
    trace.enable({"hook"})
    yield
    trace.reset()


class _CountingPlugin(Plugin):
    name = "counting"

    @hook("modify_json_schema")
    def rewrite(self, _ignored, root):
        root.name = "rewritten"
        return root


class _StylePlugin(Plugin):
    name = "styler"

    @hook("modify_style")
    def style(self, node, style):
        return style


class _BrokenPlugin(Plugin):
    name = "broken"

    @hook("modify_json_schema")
    def boom(self, _ignored, root):
        raise RuntimeError("plugin boom")


def _tree() -> TreeNode:
    return TreeNode(
        id="1:1",
        name="root",
        source_type="FRAME",
        tag_name="div",
        children=[TreeNode(id="1:2", name="child", source_type="FRAME", tag_name="div")],
    )


def _big_tree(n: int) -> TreeNode:
    return TreeNode(
        id="1:1",
        name="root",
        source_type="FRAME",
        tag_name="div",
        children=[TreeNode(id=f"1:{i}", name=f"n{i}", source_type="FRAME", tag_name="div") for i in range(2, n + 1)],
    )


def test_hook_stats_recorded() -> None:
    reg = HookRegistry()
    reg.register(_CountingPlugin())
    root = _tree()
    reg.call("modify_json_schema", None, root)
    recs = trace.records("plugin_hooks")
    assert len(recs) == 1
    assert recs[0]["plugin"] == "counting"
    assert recs[0]["hook"] == "modify_json_schema"
    assert recs[0]["nodes_affected"] == 2  # root + child
    assert recs[0]["sample_names"] == ["child", "rewritten"]  # 埋点在 handler 之后，反映更新后状态


def test_per_node_hook_counts_one() -> None:
    # modify_style 是逐节点 hook：nodes_affected 固定 1，即使 node 有子树
    reg = HookRegistry()
    reg.register(_StylePlugin())
    root = _tree()
    reg.call("modify_style", root, dict(root.style))
    recs = trace.records("plugin_hooks")
    assert len(recs) == 1
    assert recs[0]["hook"] == "modify_style"
    assert recs[0]["nodes_affected"] == 1
    assert recs[0]["sample_names"] == []


def test_sample_names_truncated_and_sorted() -> None:
    reg = HookRegistry()
    reg.register(_CountingPlugin())
    root = _big_tree(12)
    reg.call("modify_json_schema", None, root)
    rec = trace.records("plugin_hooks")[0]
    assert rec["nodes_affected"] == 12
    assert len(rec["sample_names"]) == 10  # 截断到 10
    assert rec["sample_names"] == sorted(rec["sample_names"])  # 排序


def test_multi_handler_chain_records_each() -> None:
    reg = HookRegistry()
    reg.register(_CountingPlugin())
    reg.register(_StylePlugin())  # modify_style 无 modify_json_schema handler，不参与
    # 注册两个 modify_json_schema handler
    reg2 = HookRegistry()

    class _Second(Plugin):
        name = "second"

        @hook("modify_json_schema")
        def rewrite2(self, _ignored, root):
            return root

    reg2.register(_CountingPlugin())
    reg2.register(_Second())
    reg2.call("modify_json_schema", None, _tree())
    recs = trace.records("plugin_hooks")
    assert [r["plugin"] for r in recs] == ["counting", "second"]


def test_handler_exception_propagates_no_record() -> None:
    # handler 抛异常：异常照常传播，该 handler 不产生记录，之前记录保留
    reg = HookRegistry()

    class _GoodThenBroken(Plugin):
        name = "good"

        @hook("modify_json_schema")
        def good(self, _ignored, root):
            return root

    reg.register(_GoodThenBroken())
    reg.register(_BrokenPlugin())
    with pytest.raises(RuntimeError, match="plugin boom"):
        reg.call("modify_json_schema", None, _tree())
    recs = trace.records("plugin_hooks")
    assert len(recs) == 1  # 只有 good 的记录
    assert recs[0]["plugin"] == "good"


def test_no_tree_arg_hook_counts_one() -> None:
    # modify_css_var(dict) 无树参数 → nodes_affected=1, sample_names=[]
    class _VarPlugin(Plugin):
        name = "var"

        @hook("modify_css_var")
        def vars(self, vars_):
            return vars_

    reg = HookRegistry()
    reg.register(_VarPlugin())
    reg.call("modify_css_var", {})
    rec = trace.records("plugin_hooks")[0]
    assert rec["nodes_affected"] == 1
    assert rec["sample_names"] == []


def test_no_hook_runs_empty_array() -> None:
    reg = HookRegistry()
    root = _tree()
    reg.call("modify_json_schema", None, root)  # 无 handler
    assert trace.records("plugin_hooks") == []


def test_trace_disabled_no_records() -> None:
    trace.disable()
    reg = HookRegistry()
    reg.register(_CountingPlugin())
    reg.call("modify_json_schema", None, _tree())
    assert trace.records("plugin_hooks") == []
