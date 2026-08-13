"""Tests for preset matching trace collection (preset_matches)."""

from __future__ import annotations

import pytest

from avocado.model.scene_node import SceneNode
from avocado.model.tree_node import TreeNode
from avocado.parser import trace
from avocado.parser.component import ComponentMapping, apply_component


@pytest.fixture(autouse=True)
def _clean_trace() -> None:
    trace.reset()
    trace.enable({"preset"})
    yield
    trace.reset()


def _inst(node_id: str, name: str, comp_id: str | None) -> SceneNode:
    return SceneNode(id=node_id, name=name, type="INSTANCE", component_id=comp_id)


def _tree(node_id: str = "1:1") -> TreeNode:
    return TreeNode(id=node_id, name="n", source_type="INSTANCE", tag_name="div")


def _mapping(*entries) -> list[ComponentMapping]:
    # 注意：ComponentMapping 是 dataclass，字段为 snake_case（component_id / block_name_match / dynamic_props）
    return [ComponentMapping(**e) for e in entries]


def test_component_id_match_records_matched_by() -> None:
    scene = _inst("1:1", "MyButton", "9:100")
    tree = _tree()
    m = _mapping({"name": "MyButton", "component_id": "9:100", "component": "Button", "package": "lib"})
    apply_component(scene, tree, m)
    recs = trace.records("preset_matches")
    assert recs and recs[0]["matched_by"] == "component_id"
    assert recs[0]["entry_short"]["componentId"] == "9:100"


def test_name_match_records_matched_by_name() -> None:
    scene = _inst("1:2", "Button", None)
    tree = _tree("1:2")
    m = _mapping({"name": "Button", "component": "Button", "package": "lib"})
    apply_component(scene, tree, m)
    assert trace.records("preset_matches")[0]["matched_by"] == "name"


def test_component_id_not_in_preset_records_unmatched() -> None:
    scene = _inst("1:3", "Mystery", "9:999")
    tree = _tree("1:3")
    apply_component(scene, tree, _mapping({"name": "Button", "component": "Button", "package": "lib"}))
    rec = trace.records("preset_matches")[0]
    assert "skipped_by" in rec and rec["skipped_by"] == "component_id_not_in_preset"
    assert "matched_by" not in rec  # unmatched 与 matched 靠 matched_by/skipped_by 区分，无 outcome 字段
    assert len(rec["reason"]) <= 200


def test_block_name_match_skip_records_reason() -> None:
    scene = _inst("1:4", "Form", None)
    tree = _tree("1:4")
    m = _mapping({"name": "Form", "component": "Form", "package": "lib", "block_name_match": True})
    apply_component(scene, tree, m)
    assert trace.records("preset_matches")[0]["skipped_by"] == "block_name_match_skip"


def test_no_component_id_name_no_match_classified() -> None:
    # INSTANCE 无 compId 且 name 无匹配 → name_no_match
    scene = _inst("1:5", "UnknownLayer", None)
    tree = _tree("1:5")
    apply_component(scene, tree, _mapping({"name": "Button", "component": "Button", "package": "lib"}))
    assert trace.records("preset_matches")[0]["skipped_by"] == "name_no_match"


def test_variant_downgrade_classified() -> None:
    # variants override 将 component 置空（原 component 非空）→ 放弃识别 → variant_downgrade
    scene = SceneNode(id="1:6", name="Tabs", type="INSTANCE", component_id="9:6",
                      component_properties={"Type": {"value": "Circular", "type": "VARIANT"}})
    tree = _tree("1:6")
    m = _mapping({
        "name": "Tabs", "component_id": "9:6", "component": "Tabs", "package": "lib",
        "variants": {"Type": {"Circular": {"component": ""}}},
    })
    apply_component(scene, tree, m)
    assert trace.records("preset_matches")[0]["skipped_by"] == "variant_downgrade"


def test_variant_hits_recorded_on_match() -> None:
    # 命中带 variants 的 entry → variant_hits 记录 field/value
    scene = SceneNode(id="1:7", name="Input", type="INSTANCE", component_id="9:7",
                      component_properties={"Size": {"value": "Small", "type": "VARIANT"}})
    tree = _tree("1:7")
    m = _mapping({
        "name": "Input", "component_id": "9:7", "component": "Input", "package": "lib",
        "variants": {"Size": {"Small": {"component": "LabeledInput"}}},
    })
    apply_component(scene, tree, m)
    rec = trace.records("preset_matches")[0]
    assert rec["matched_by"] == "component_id"
    assert {"field": "Size", "value": "Small"} in rec["variant_hits"]


def test_non_instance_not_recorded() -> None:
    scene = SceneNode(id="1:8", name="Frame", type="FRAME")
    tree = _tree("1:8")
    apply_component(scene, tree, _mapping({"name": "Frame", "component": "Frame", "package": "lib"}))
    assert trace.records("preset_matches") == []


def test_combo_component_id_missing_priority() -> None:
    # compId 未收录 + name 命中 block 条目 → component_id_not_in_preset 为主因，block 并入 reason
    scene = _inst("1:9", "Form", "9:999")
    tree = _tree("1:9")
    m = _mapping({"name": "Form", "component": "Form", "package": "lib", "block_name_match": True})
    apply_component(scene, tree, m)
    rec = trace.records("preset_matches")[0]
    assert rec["skipped_by"] == "component_id_not_in_preset"
    assert "blockNameMatch" in rec["reason"]


def test_block_name_match_with_dynamic_props_matches_by_name() -> None:
    # block 条目带 dynamic_props → name 匹配放行（white-screen guard 例外）
    scene = _inst("1:10", "Steps", None)
    tree = _tree("1:10")
    m = _mapping({
        "name": "Steps", "component": "Steps", "package": "lib",
        "block_name_match": True, "dynamic_props": {"extractor": "steps_items"},
    })
    apply_component(scene, tree, m)
    assert trace.records("preset_matches")[0]["matched_by"] == "name"


def test_component_empty_preset_pattern_records_matched() -> None:
    # preset 定义 component:''（如 Icon/Placeholder）→ matched，不是 variant_downgrade
    scene = _inst("1:11", "Icon Left", "9:448")
    tree = _tree("1:11")
    m = _mapping({"name": "Icon Left", "component_id": "9:448", "component": "", "package": "lib"})
    apply_component(scene, tree, m)
    rec = trace.records("preset_matches")[0]
    assert "matched_by" in rec and rec["matched_by"] == "component_id"
    assert rec["entry_short"]["component"] == ""


def test_variant_no_matching_value_no_hits_key() -> None:
    # variant 表存在但值无匹配 → 不产生 variant_hits 键
    scene = SceneNode(id="1:12", name="Input", type="INSTANCE", component_id="9:7",
                      component_properties={"Size": {"value": "Huge", "type": "VARIANT"}})
    tree = _tree("1:12")
    m = _mapping({
        "name": "Input", "component_id": "9:7", "component": "Input", "package": "lib",
        "variants": {"Size": {"Small": {"component": "LabeledInput"}}},
    })
    apply_component(scene, tree, m)
    assert "variant_hits" not in trace.records("preset_matches")[0]


def test_trace_disabled_no_records() -> None:
    trace.disable()
    scene = _inst("1:13", "Button", "9:100")
    tree = _tree("1:13")
    m = _mapping({"name": "Button", "component_id": "9:100", "component": "Button", "package": "lib"})
    apply_component(scene, tree, m)
    assert trace.records("preset_matches") == []


def test_truncate_path_helper() -> None:
    from avocado.parser.trace import truncate_path
    assert truncate_path(["a", "b"]) == ["a", "b"]
    # 10 段 → 保留离节点最近 7 段 + "…" 前缀 = 8 元素，末元素为节点名
    assert truncate_path([f"n{i}" for i in range(10)]) == ["…", "n3", "n4", "n5", "n6", "n7", "n8", "n9"]


def test_matched_record_has_path() -> None:
    trace.enable({"preset"})
    scene = _inst("1:1", "Button", "9:100")
    tree = _tree()
    m = _mapping({"name": "Button", "component_id": "9:100", "component": "Button", "package": "lib"})
    apply_component(scene, tree, m, trace_path=["Page", "Section"])
    rec = trace.records("preset_matches")[0]
    assert rec["path"] == ["Page", "Section", "Button"]


def test_unmatched_record_has_path_truncated() -> None:
    trace.enable({"preset"})
    scene = _inst("1:2", "Deep", None)
    tree = _tree("1:2")
    m = _mapping({"name": "Other", "component": "X", "package": "lib"})
    apply_component(scene, tree, m, trace_path=[f"L{i}" for i in range(20)])
    rec = trace.records("preset_matches")[0]
    assert rec["path"][0] == "…"
    assert rec["path"][-1] == "Deep"
    assert len(rec["path"]) == 8


def test_map_node_threads_trace_path() -> None:
    from avocado.parser.node_mapper import map_node
    trace.enable({"preset"})
    scene = SceneNode(id="1:1", name="Page", type="FRAME", children=[
        SceneNode(id="1:2", name="Section", type="FRAME", children=[
            SceneNode(id="1:3", name="Button", type="INSTANCE", component_id="9:1"),
        ]),
    ])
    m = _mapping({"name": "Button", "component_id": "9:1", "component": "Button", "package": "lib"})
    map_node(scene, client=None, file_key="f", component_mapping=m, layout_mode="flex")
    recs = [r for r in trace.records("preset_matches") if "matched_by" in r]
    assert recs[0]["path"] == ["Page", "Section", "Button"]


def test_variant_downgrade_record_has_path() -> None:
    """variant_downgrade (recognition abandoned) also carries path."""
    trace.enable({"preset"})
    scene = SceneNode(
        id="1:20", name="Tabs", type="INSTANCE", component_id="9:20",
        component_properties={"Type": {"value": "Primary", "type": "VARIANT"}},
    )
    tree = _tree("1:20")
    m = _mapping(
        {"name": "Tabs", "component_id": "9:20", "component": "Tabs", "package": "lib",
         "variants": {"Type": {"Primary": {"component": ""}}}},
    )
    apply_component(scene, tree, m, trace_path=["Page", "Section"])
    rec = trace.records("preset_matches")[0]
    assert rec["skipped_by"] == "variant_downgrade"
    assert rec["path"] == ["Page", "Section", "Tabs"]


def test_suggestion_for_name_no_match() -> None:
    trace.enable({"preset"})
    scene = _inst("1:5", "Title", None)
    tree = _tree("1:5")
    apply_component(scene, tree, _mapping({"name": "Button", "component": "Button", "package": "lib"}))
    rec = trace.records("preset_matches")[0]
    assert rec["skipped_by"] == "name_no_match"
    assert "suggestion" in rec
    assert "- name: 'Title'" in rec["suggestion"]
    assert "<fill>" in rec["suggestion"]


def test_suggestion_for_component_id_not_in_preset() -> None:
    trace.enable({"preset"})
    scene = _inst("1:6", "Mystery", "9:999")
    tree = _tree("1:6")
    apply_component(scene, tree, _mapping({"name": "Button", "component": "Button", "package": "lib"}))
    rec = trace.records("preset_matches")[0]
    assert "componentId: '9:999'" in rec["suggestion"]
    assert len(rec["suggestion"]) <= 200


def test_suggestion_not_for_block_or_downgrade() -> None:
    trace.enable({"preset"})
    scene = _inst("1:7", "Form", None)
    tree = _tree("1:7")
    apply_component(scene, tree, _mapping({"name": "Form", "component": "Form", "package": "lib", "block_name_match": True}))
    assert "suggestion" not in trace.records("preset_matches")[0]


def test_suggestion_omitted_when_over_200() -> None:
    trace.enable({"preset"})
    scene = _inst("1:8", "X" * 300, None)
    tree = _tree("1:8")
    apply_component(scene, tree, _mapping({"name": "Button", "component": "Button", "package": "lib"}))
    assert "suggestion" not in trace.records("preset_matches")[0]


def test_suggestion_for_comp_id_with_block_skip() -> None:
    """compId missing + name blocked → still suggests (compId genuinely absent)."""
    trace.enable({"preset"})
    scene = _inst("1:9", "Form", "9:123")
    tree = _tree("1:9")
    apply_component(scene, tree, _mapping(
        {"name": "Form", "component": "Form", "package": "lib", "block_name_match": True}))
    rec = trace.records("preset_matches")[0]
    assert rec["skipped_by"] == "component_id_not_in_preset"
    assert "componentId: '9:123'" in rec["suggestion"]


def test_applied_variant_prop_hits_and_misses() -> None:
    trace.enable({"preset"})
    scene = SceneNode(id="1:9", name="Button", type="INSTANCE", component_id="9:9",
                      component_properties={"Type": {"value": "Primary", "type": "VARIANT"},
                                            "Size": {"value": "Huge", "type": "VARIANT"}})
    tree = _tree("1:9")
    m = _mapping({"name": "Button", "component_id": "9:9", "component": "Button", "package": "lib",
                  "variant_properties": {"Type": {"Primary": {"type": "primary"}}}})
    apply_component(scene, tree, m)
    applied = [r for r in trace.records("preset_matches") if r.get("event") == "applied"]
    assert len(applied) == 1
    assert applied[0]["variant_prop_hits"] == [{"field": "Type", "value": "Primary", "applied": ["type"]}]
    assert applied[0]["variant_prop_misses"] == [{"field": "Size", "value": "Huge"}]
    assert applied[0]["component"] == "Button"
    # trace collection must not change applied behavior — the variant prop is set
    assert tree.props["type"] == "primary"


def test_applied_leaf_dropped() -> None:
    trace.enable({"preset"})
    scene = SceneNode(id="1:10", name="Input", type="INSTANCE", component_id="9:10",
                      children=[SceneNode(id="1:11", name="helper text", type="TEXT")])
    tree = TreeNode(id="1:10", name="Input", source_type="INSTANCE", tag_name="div",
                    children=[TreeNode(id="1:11", name="helper text", source_type="TEXT", tag_name="span")])
    m = _mapping({"name": "Input", "component_id": "9:10", "component": "Input", "package": "lib",
                  "leaf": True, "leaf_extras": ("helper text",)})
    apply_component(scene, tree, m)
    applied = [r for r in trace.records("preset_matches") if r.get("event") == "applied"]
    assert applied[0]["leaf_dropped"]["children_count"] == 1
    assert applied[0]["leaf_dropped"]["kept_extras"] == ["helper text"]


def test_no_applied_record_without_details() -> None:
    trace.enable({"preset"})
    scene = _inst("1:12", "Button", "9:12")
    tree = _tree("1:12")
    m = _mapping({"name": "Button", "component_id": "9:12", "component": "Button", "package": "lib",
                  "props": {"type": "default"}})
    apply_component(scene, tree, m)
    assert all(r.get("event") != "applied" for r in trace.records("preset_matches"))
