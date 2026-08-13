"""Tests for extractor output trace collection (extractor_outputs)."""

from __future__ import annotations

import pytest

from avocado.model.scene_node import SceneNode
from avocado.model.tree_node import TreeNode
from avocado.parser import trace
from avocado.parser.component import ComponentMapping, apply_component
from avocado.parser.component_extractors import register_extractor


@pytest.fixture(autouse=True)
def _clean_trace() -> None:
    trace.reset()
    trace.enable({"extractor"})
    yield
    trace.reset()


def _scene_with_children() -> SceneNode:
    return SceneNode(
        id="1:1",
        name="Steps",
        type="INSTANCE",
        component_id="9:1",
        children=[
            SceneNode(id="1:2", name="Step 1", type="FRAME"),
            SceneNode(id="1:3", name="Step 2", type="FRAME"),
        ],
    )


def _mapping_with_extractor(extractor: str = "steps_items") -> list[ComponentMapping]:
    return [ComponentMapping(name="Steps", component_id="9:1", component="Steps",
                             package="lib", dynamic_props={"extractor": extractor})]


def _apply(scene: SceneNode, mapping: list[ComponentMapping]) -> None:
    tree = TreeNode(id="1:1", name="Steps", source_type="INSTANCE", tag_name="Steps")
    apply_component(scene, tree, mapping)


def test_extractor_success_records_keys_and_sample() -> None:
    register_extractor(
        "steps_items",
        lambda scene, path: {"items": [{"title": "Step 1"}, {"title": "Step 2"}]},
    )
    _apply(_scene_with_children(), _mapping_with_extractor())
    rec = trace.records("extractor_outputs")[0]
    assert rec["component"] == "Steps"
    assert rec["extractor"] == "steps_items"
    assert rec["path"] is None  # 未配置 path → None
    assert rec["success"] is True
    assert rec["keys"] == ["items"]  # 精确列表（确定性排序）
    assert rec["sample"]["items_len"] == 2
    assert rec["sample"]["first_title"] == "Step 1"


def test_extractor_failure_recorded_not_silent() -> None:
    register_extractor("steps_items_empty", lambda scene, path: {})  # 空返回 = 降级
    _apply(_scene_with_children(), _mapping_with_extractor("steps_items_empty"))
    rec = trace.records("extractor_outputs")[0]
    assert rec["success"] is False
    assert rec["keys"] == []
    assert "sample" not in rec


def test_extractor_keys_sorted_deterministic() -> None:
    register_extractor(
        "steps_items_multi",
        lambda scene, path: {"zeta": [{"title": "z"}], "alpha": [{"title": "a"}]},
    )
    _apply(_scene_with_children(), _mapping_with_extractor("steps_items_multi"))
    assert trace.records("extractor_outputs")[0]["keys"] == ["alpha", "zeta"]


def test_extractor_sample_no_list_value() -> None:
    # 无 list 值 → 无 sample 键（不产生空 sample）
    register_extractor("steps_items_nolist", lambda scene, path: {"title": "x"})
    _apply(_scene_with_children(), _mapping_with_extractor("steps_items_nolist"))
    rec = trace.records("extractor_outputs")[0]
    assert rec["success"] is True
    assert "sample" not in rec


def test_extractor_sample_item_without_title() -> None:
    # item 无 title → 仅 items_len
    register_extractor("steps_items_notitle", lambda scene, path: {"items": [42]})
    _apply(_scene_with_children(), _mapping_with_extractor("steps_items_notitle"))
    rec = trace.records("extractor_outputs")[0]
    assert rec["sample"]["items_len"] == 1
    assert "first_title" not in rec["sample"]


def test_extractor_trace_disabled_no_records() -> None:
    trace.disable()
    register_extractor("steps_items_off", lambda scene, path: {"items": [{"title": "a"}]})
    _apply(_scene_with_children(), _mapping_with_extractor("steps_items_off"))
    assert trace.records("extractor_outputs") == []


def test_extractor_not_registered_error() -> None:
    trace.enable({"extractor"})
    _apply(_scene_with_children(), _mapping_with_extractor("does_not_exist"))
    rec = trace.records("extractor_outputs")[0]
    assert rec["success"] is False
    assert rec["error"] == "not_registered"
    assert "error_detail" not in rec


def test_extractor_exception_error() -> None:
    trace.enable({"extractor"})
    def boom(scene, path):
        raise RuntimeError("path mismatch on steps")
    register_extractor("steps_boom", boom)
    _apply(_scene_with_children(), _mapping_with_extractor("steps_boom"))
    rec = trace.records("extractor_outputs")[0]
    assert rec["success"] is False
    assert rec["error"] == "exception"
    assert "path mismatch on steps" in rec["error_detail"]
    assert len(rec["error_detail"]) <= 200


def test_extractor_empty_result_error() -> None:
    trace.enable({"extractor"})
    register_extractor("steps_empty", lambda scene, path: {})
    _apply(_scene_with_children(), _mapping_with_extractor("steps_empty"))
    rec = trace.records("extractor_outputs")[0]
    assert rec["success"] is False
    assert rec["error"] == "empty_result"
    assert "error_detail" not in rec


def test_extractor_exception_pipeline_survives() -> None:
    trace.enable({"extractor"})
    def boom(scene, path):
        raise ValueError("boom")
    register_extractor("steps_boom2", boom)
    tree = TreeNode(id="1:1", name="Steps", source_type="INSTANCE", tag_name="Steps")
    m = _mapping_with_extractor("steps_boom2")
    assert apply_component(_scene_with_children(), tree, m) is True
    assert tree.is_component is True
    assert trace.records("extractor_outputs")[0]["error"] == "exception"
