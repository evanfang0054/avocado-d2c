"""End-to-end acceptance tests for --trace-adapter.

Non-live tests use the checked-in fixture (tests/fixtures/02_confirm_frame)
for a deterministic offline loop; live tests need the local Figma cache.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from avocado.model.scene_node import SceneNode
from avocado.parser import trace
from avocado.parser.component import load_mapping
from avocado.parser.node_mapper import map_node

URL = "https://www.figma.com/design/30wJJvfAAGLhXFkUt2OZOK/?node-id=1732:5574"
CACHE = str(Path.home() / ".avocado" / "output" / "figma_cache")

# 中性示例 preset（零品牌词）：只含 Button，其余 INSTANCE（Title 等）未收录
MYLIB = """components:
- name: Button
  component: Button
  package: '@example/lib'
"""


@pytest.fixture(autouse=True)
def _clean_trace() -> None:
    trace.reset()
    yield
    trace.reset()


def _scene_from_fixture() -> SceneNode:
    """Build a scene from the checked-in fixture (offline deterministic)."""
    raw = json.loads(Path("tests/fixtures/02_confirm_frame/input.json").read_text())
    doc = next(iter(raw["nodes"].values()))["document"]
    return SceneNode.from_dict(doc)


def _run_map(scene: SceneNode, preset_path: Path):
    trace.reset()
    trace.enable({"preset"})
    tree = map_node(
        scene,
        client=None,
        file_key="f",
        component_mapping=load_mapping(preset_path),
        layout_mode="flex",
    )
    return tree, trace.records("preset_matches")


# ── 适配闭环（非 live，fixture 确定性） ──────────────────────────────────────


def test_unmatched_reason_visible_then_fix_confirms_match(tmp_path) -> None:
    preset = tmp_path / "mylib.yaml"
    preset.write_text(MYLIB)
    scene = _scene_from_fixture()
    _, recs = _run_map(scene, preset)
    # "Title" (compId 9:2251) 未收录 → unmatched，原因明确
    miss = [u for u in recs if u["node_name"] == "Title"]
    assert miss and miss[0]["skipped_by"] == "component_id_not_in_preset"
    # 补 entry 后命中
    preset.write_text(MYLIB + "- name: Title\n  componentId: '9:2251'\n  component: Title\n  package: '@example/lib'\n")
    _, recs2 = _run_map(scene, preset)
    hit = [m for m in recs2 if m["node_name"] == "Title" and "matched_by" in m]
    assert hit and hit[0]["matched_by"] == "component_id"


# ── live：真实 CLI + 本地缓存（CI 排除） ─────────────────────────────────────


def _run_cli(*args):
    """Invoke the real `avocado` binary (covers cli() argv normalization)."""
    r = subprocess.run(["avocado", *args], capture_output=True, text=True, timeout=60)
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None


@pytest.mark.live
def test_default_output_has_no_trace(tmp_path) -> None:
    preset = tmp_path / "mylib.yaml"
    preset.write_text(MYLIB)
    code, payload = _run_cli(URL, "--cache-dir", CACHE, "--offline", "--components", str(preset), "--summary")
    assert code == 0
    assert payload is not None and payload["ok"] is True
    assert "trace" not in payload["data"]


@pytest.mark.live
def test_trace_deterministic(tmp_path) -> None:
    preset = tmp_path / "mylib.yaml"
    preset.write_text(MYLIB)
    args = [URL, "--cache-dir", CACHE, "--offline", "--components", str(preset), "--summary", "--trace-adapter=preset"]
    _, a = _run_cli(*args)
    _, b = _run_cli(*args)
    assert a is not None and b is not None
    assert json.dumps(a["data"]["trace"], sort_keys=True) == json.dumps(b["data"]["trace"], sort_keys=True)


def test_unmatched_new_fields_fixture(tmp_path) -> None:
    """L4-1 A1 非 live 覆盖：fixture + 中性 preset 下 unmatched 记录带
    path/suggestion，_build_trace_data 组装出 preset_matches + issues。

    注：extractor_outputs / plugin_hooks 块在该环境无 extractor/插件无法产出，
    由 Task 3/4/5 单测 + live e2e 覆盖（GDD L4-1 A1 在非 live 环境按可确定性
    产出的块断言）。"""
    from avocado.cli import _build_trace_data

    preset = tmp_path / "mylib.yaml"
    preset.write_text(MYLIB)
    scene = _scene_from_fixture()
    _, recs = _run_map(scene, preset)
    miss = [u for u in recs if u["node_name"] == "Title"]
    assert miss and miss[0]["skipped_by"] == "component_id_not_in_preset"
    assert miss[0]["path"][-1] == "Title"          # path 末元素为节点名
    assert "componentId" in miss[0]["suggestion"]  # compId 未收录场景给骨架
    data = _build_trace_data()
    assert data["preset_matches"]["unmatched"] == len([r for r in recs if "skipped_by" in r])
    assert "issues" in data and data["issues"]["unmatched_by_name"]  # 派生块非空


def test_trace_parity_non_trace_output(tmp_path) -> None:
    """L4-2 A1 + L2-7 A2 非 live：trace 开启/关闭不改变非 trace 输出。

    同一 fixture 分别以 trace 关闭/开启跑 map_node，断言采集确实发生
    （防假阳性）且产物逐字段一致（trace 无副作用）。"""
    import dataclasses

    preset = tmp_path / "mylib.yaml"
    preset.write_text(MYLIB)
    scene = _scene_from_fixture()
    mapping = load_mapping(preset)
    trace.reset()
    tree_off = map_node(scene, client=None, file_key="f",
                        component_mapping=mapping, layout_mode="flex")
    off = dataclasses.asdict(tree_off)
    trace.reset()
    trace.enable({"preset", "extractor", "hook"})
    tree_on = map_node(scene, client=None, file_key="f",
                       component_mapping=mapping, layout_mode="flex")
    on = dataclasses.asdict(tree_on)
    assert trace.records("preset_matches")  # trace 开启时确实采集（防假阳性）
    assert on == off                         # 非 trace 输出逐字段一致
    trace.reset()
