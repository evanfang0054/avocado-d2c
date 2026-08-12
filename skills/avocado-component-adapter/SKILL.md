---
name: avocado-component-adapter
description: Use when an agent needs to adapt a component library to avocado — editing/extending preset YAML (antd.yaml etc.) AND writing the companion plugins (~/.avocado/plugins/*.py) that make presets work, OR debugging why a component is not recognized (--trace-adapter). Covers the ComponentMapping schema (9 fields: name/componentId match criteria, component/package/props/variantProperties/variants/dynamicProps/leaf), the blockNameMatch white-screen guard rules, componentId alias for cross-file same-component-different-id (Button has 7 entries covering 6 compId), when to add `leaf: true` (only for self-contained components like LabeledInput) vs not (Button needs children), dynamicProps extractors registered by user plugins via register_extractor, and how variants override propagates the leaf field. Also covers the Plugin base class contract (name/presets_used), the 6 hooks (modify_json_schema/modify_props/modify_style/modify_css_var/generate_template/inspect_draft) with signatures and return conventions, the name-recognizer template for recognizing non-INSTANCE layers by Figma name, and why modify_json_schema runs before unwrap (component protection). Also covers the --trace-adapter debug flag (preset match details / extractor outputs / plugin hook stats) for the adapter authoring loop. Triggers on "加组件", "antd.yaml", "preset 改", "组件识别", "INSTANCE 识别不到", "leaf 字段", "variant", "dynamicProps", "extractor", "componentId", "Figma 组件映射", "写插件", "plugin", "hook", "name-recognizer", "调试", "为什么没识别", "trace". Does NOT cover general path lookup (avocado-path-config), running d2c (avocado-d2c), or debugging pixel diff.
---

# avocado-component-adapter

组件库适配手册：preset 映射数据（antd.yaml 等）+ 配套插件（识别/提取逻辑）。preset 是 avocado 项目里约束最密集的 YAML 文件——错一个字段会让整个 React 树白屏。

## 何时触发

- 用户想加一个新组件到 组件库预设
- 组件库组件识别不到（Figma name 不匹配 / compId 没收录）
- 加叶子组件（LabeledInput/PhoneInput 等）
- INSTANCE 显示空 div / 双重渲染
- 加 dynamicProps extractor
- 用户问 blockNameMatch 是什么

**不触发**：
- 找 preset 文件路径 → `avocado-path-config`
- 改完 preset 后用 d2c 单页冒烟验证 → `avocado-d2c`
- 还原度问题不是组件识别引起 → `avocado-d2c`

## ComponentMapping schema（真相源）

> **schema 通用，不只 antd**：本 skill 以 bundled 的 `antd.yaml`（中性示例）讲解 schema 与维护规则，schema 对**任何 preset 通用**——包括用户自定义的组件库 preset（放在 `~/.avocado/presets/` 下的 yaml，与 bundled antd.yaml 结构相同，9 字段 ComponentMapping）。区别在：
> - **位置**：bundled preset 在 wheel 内（4 层查找最低层）；用户自定义 preset 在 `~/.avocado/presets/`（用户层，`avocado path-config` 可查）
> - **加载方式**：bundled preset 通过 `--component-lib <name>` 显式加载；用户自定义 preset 也可通过 name-based 识别插件加载（插件类声明 `PRESET = "<preset 名>"` 且 `presets_used = ["<preset 名>"]` 供 envelope `plugins_applied` 上报）
> - **范围**：用户 preset 可覆盖 bundled 没有的业务组件（如把 `Single Icon`/`Union` 等图标图层映射成 `<Icon name="..."/>` 一行——这是消灭"图标内嵌 5+ 层定位 div"病态的正解：一行组件替代多层定位 wrapper）
> - **增删组件流程一致**：往用户 preset 加映射照本 skill 的"加新组件的工作流"，`blockNameMatch` 白屏保护、`leaf` 判定、`dynamicProps` extractor 规则同样适用

`packages/avocado/src/avocado/parser/component.py:ComponentMapping` dataclass。

### YAML 键名 vs Python 字段名映射
**YAML 用 camelCase，Python dataclass 用 snake_case**：

| YAML 键 | Python 字段 | 类型 |
|---|---|---|
| `name` | `name` | str \| None |
| `componentId` | `component_id` | str \| None |
| `component` | `component` | str（必填） |
| `package` | `package` | str（默认 `""`） |
| `props` | `props` | dict |
| `variantProperties` | `variant_properties` | dict |
| `variants` | `variants` | dict |
| `dynamicProps` | `dynamic_props` | dict |
| `leaf` | `leaf` | bool（默认 False） |

### YAML 示例（完整字段）

```yaml
components:
  - name: "Button"                    # 匹配条件 1：Figma 节点 name（大小写不敏感，精确匹配）
    componentId: "9:1043"             # 匹配条件 2：Figma componentSet ID（更精确，survives renames）
    component: "Button"               # antd 组件名（必填）
    package: "antd"
    props:                            # 静态 props
      type: "default"
    variantProperties:                # variant 值 → component props
      size: "Small"
    variants:                         # variant 值 → 切换 component
      Basic: { component: "LabeledInput", leaf: true }
    dynamicProps:                     # extractor 名（register_extractor 注册）→ 提取的数组 prop
      extractor: "steps_items"
    leaf: false                       # 叶子组件清空 Figma children
```

### antd.yaml 实际统计（18 entry，bundled 中立示例）
| 字段 | 出现次数 | 说明 |
|---|---|---|
| `variantProperties:` | 1 | 仅 Button（type/size/danger 三个 variant 组） |
| `leaf: true` | 7 | Input 系列 + Select/Checkbox/Radio/Switch 等自带内部 DOM 的组件 |
| `leafExtras:` | 7 | 与 leaf 组件配套的额外元素保留列表 |
| `componentId:` | 0 | bundled 示例不含 compId alias（用户自建 preset 可加） |
| `dynamicProps:` | 0 | bundled 示例不含 extractor（由用户插件注册） |

**注**：这些字段是**少数派用法**——18 个 entry 里多数只用 `name` + `component` + `package` 三字段。

## 匹配优先级

```
1. componentId 精确匹配（最高优先级，survives renames）
2. name 大小写不敏感精确匹配（次优）
3. 无匹配 → 走默认 div 渲染
```

**关键变更**：`test_no_duplicate_names` 改为按 `(name, componentId)` 去重——**同 name 不同 compId 合法**（用于跨 figma file alias）。

## recognize() 完整识别流程（component.py:200-278）

agent 改识别逻辑时按此 5 步：

1. **非 INSTANCE** 返回 None（非 INSTANCE 节点不做组件识别）
2. **componentId 精确匹配**（最高优先级）：遍历 preset 找 `component_id == scene.component_id`
3. **name 匹配**（case-insensitive，trim）：
   - 若命中条目 `blockNameMatch: true` **且无** `dynamic_props` → **skip**（防白屏）
   - 否则用此 mapping
4. **variants override**（5 字段 override）：取首个匹配的 variant field，`dataclasses.replace` 克隆并切：
   - `component` / `package`（必覆盖）
   - `leaf`（**关键**：`new_leaf = override.get("leaf", matched.leaf)`，bool-ish 容错 + `_lookup_ci`）
   - `props`（merge，不是 replace）
5. **apply_component**（component.py:289-388）：
   - `variantProperties` 合并进 props
   - `dynamicProps` 调 extractor（静默失败返回 {}）
   - `leaf=True` 时清空 children + 保留 `leafExtras` 匹配的 extras

## variantProperties / variants / dynamicProps 三字段

### variantProperties
**用途**：Figma variant 值 → 组件库组件 prop。
```yaml
- name: "Button"
  componentId: "9:1043"
  component: "Button"
  variantProperties:
    Size: "Small"           # Figma variant "Size=Small" → component prop size="small"
    Type: "Primary"         # Figma variant "Type=Primary" → component prop type="primary"
```

实现：`apply_component()` 读 Figma `componentProperties[type=VARIANT]`，应用 `variantProperties`（variant 值 → component props）。

### variants
**用途**：Figma variant 值 → **切换 component**（不只是 prop）。
```yaml
- name: "Input"
  component: "Input"           # fallback
  variants:
    Basic: { component: "LabeledInput", leaf: true }
    "Phone Number": { component: "PhoneInput", leaf: true }
    "Text Area": { component: "LabeledTextArea", leaf: true }
```

实现：`recognize()` 中 `dataclasses.replace(matched, component=..., package=..., leaf=new_leaf)`。
**必须传 leaf**：`new_leaf = override.get("leaf", matched.leaf)`，否则 `name: Input` → LabeledInput 时 leaf 不生效（真实踩过坑）。

### dynamicProps
**用途**：复杂组件需要从 Figma 子节点提取数组数据（items/steps/labels）。
```yaml
- name: "Steps"
  component: "Steps"
  dynamicProps:
    extractor: "steps_items"  # register_extractor 注册的 extractor 名
```

实现：extractor 由用户插件通过 `register_extractor(name, fn)` 注册（核心包不内置），
`run_extractor()` 调度，**静默失败返回 {}**（不阻断流程）。extractor 编写规范见
[`docs/preset-guide.md`](../../docs/preset-guide.md)。

**常用 extractor 名**（用户插件可注册同名 extractor）：

**extractor 名与用途参考**：

| extractor 名 | 提取的 prop | 用途 |
|---|---|---|
| `button_container` | children | Button content |
| `tag_container` | children | Tag content |
| `alert_paths` | title/content/showIcon/showClose/showButton/buttonText | Alert |
| `dialog_container` | title/content/primaryButtonText/secondaryButtonText | Dialog |
| `radio_button` | label | Radio |
| `input_placeholder` | placeholder | Input |
| `select_input` | placeholder | Select |
| `steps_items` | items[title,description] | Steps |
| `tabs_items` | items[key,title] | Tabs |
| `summary_items` | items[title,content] | Summary |
| `data_row_items` | items/title/content | DataRow |
| `total_items` | itemList+totalTitle/total | Total |
| `card_meta` | cardBrand/cardNo/expiryMonth/expiryYear | CardMeta |
| `progress_bar` | text/percent/totalSteps/currentStep | Progress |
| `plan_details` | title/description/notice/min | PlanSummary |
| `accordion_content` | panels[title,content] | Accordion/Collapse |
| `icon_meta` | iconName | Icon |
| `link_text` | children | Link |

**关键**：extractor 静默失败是**合法降级路径**——不是 bug。例如 `Steps` 组件的 `steps_items` extractor 在某些 Figma 数据下 path mismatch 失败，`run_extractor` 返回 `{}`，组件降级为不带 items 的 div。antd.yaml 注释明确："steps_items extractor FAILS on Steps component, path mismatch" —— 这是已知降级，不要当 bug 修。

**可观测性**：extractor 返回空时 `apply_component` 会给该节点记一条 `extractor-empty` inspect（severity=info，component.py:343-350），聚合进 envelope `data.inspect_summary`。排查"items 为什么没提取"时先看 `inspect_summary.by_code["extractor-empty"]`。

## leaf 字段

**用途**：叶子组件清空 Figma children（组件库组件自带内部 DOM，不需要 Figma 子树）。

### 加 leaf 的判定
| 加 `leaf: true` | 不加 leaf |
|---|---|
| LabeledInput / LabeledTextArea / PhoneInput（自带 input + border + label） | Button（children `<span>label</span>` 是 button 文字） |
| Switch（自带 toggle UI） | Stepper（需 case-by-case 验证） |
| 自带完整 DOM 不需要 Figma children 的组件 | Icon（`component: ''` 保留 Figma SVG） |

**问题场景**：`apply_component` 识别 INSTANCE 后保留 Figma DOM 作为 children，导致 组件库组件内部样式 + Figma DOM 双重渲染（重复边框、错位文字、视觉混乱——react_tw 模式某页面"输入框没还原"根因）。

### Helper Text 保留
Figma 设计稿可能在 LabeledInput 子树内包含 组件不渲染的元素（Helper Text / Error Message）。`apply_component` 的 leaf 分支会**深度遍历整个子树**，匹配 `leafExtras`（"helper text"/"error message"/"hint text"/"helper"）的节点保留。

**传输机制**（容易踩坑）：
1. `apply_component` 把匹配的 extras 存到 `tree.props["_leaf_extras"]`（**不是 children**）
2. `tree.children = []` + `tree.text_content = ""` 清空原 Figma DOM
3. `node_mapper.py` caller 在父级构造 children 后，pop 出 `tree.props["_leaf_extras"]` 扁平化为兄弟节点

**关键约束**：
- **只匹配节点自身 name，不匹配后代**（避免把 "container" FRAME 整个拖出来带着 input field 再次双重渲染）
- 匹配是 **substring match**（`any(kw in nm for kw in ...)`）不是精确匹配
- `leafExtras` 是 tuple（有序）

## blockNameMatch（数据驱动组件保护）

preset 条目字段，替代旧的 `COMPLEX_DATA_COMPONENTS` 硬编码黑名单：

```yaml
- name: Form
  component: Form
  package: 'antd'
  blockNameMatch: true   # 无 dynamicProps 时 name 匹配被跳过
```

### 限制
- **只能通过 componentId 显式匹配**
- **name 匹配被跳过**（防止误识别）

### 为什么需要
这些组件需要 items/panels/steps 等数组 prop，preset 没有对应 extractor。缺 props 会让整个 React 树白屏。

### 例外：有 dynamicProps 的组件允许 name 命中
Steps / Tabs / Collapse / Total 等已通过用户插件注册的 extractor 解锁：
- Steps → `steps_items`
- Tabs → `tabs_items`
- 等等

**规则**：`recognize()` 检查 `m.dynamic_props`——有 dynamicProps 配置的组件（**即使设了 blockNameMatch**）允许 name 命中。

**不要为了"识别到了"而放开无 extractor 组件的 name 匹配**。

## componentId alias

### 问题
Figma 设计师按 head-noun 习惯命名 INSTANCE：
- `'Primary Button'` 而非 `'Button'`
- `'Tertiary Button'` / `'Back Button'` 同理
- `'Quantity Stepper'` 而非 `'Stepper'`
- `'Checkout'` 而非 `'Total'`

且**同一 组件库组件在不同 Figma file 有不同 componentSet ID**：
- file `FIGMA_FILE_KEY_PLACEHOLDER_002` 的 Button compId 是 `9:1043` / `9:1217` / `9:1449`
- file `FIGMA_FILE_KEY_PLACEHOLDER_003` 的是 `36587:38887` / `36587:38971`

### 解决
Button 现在有 **7 个 entry（1 个 name 匹配 + 6 个 componentId alias）**，覆盖 2 个 Figma file 的不同 compId：

```yaml
# entry 1：name 匹配（fallback）
- name: "Button"
  component: "Button"
  package: "antd"

# entry 2-4：file FIGMA_FILE_KEY_PLACEHOLDER_002 的 head-noun 变体
- name: "Primary Button"
  componentId: "9:1043"                 # ← 跨 file 同 name 不同 compId
  component: "Button"
  variantProperties: {Type: "Primary"}
- name: "Secondary Button"
  componentId: "9:1217"
  component: "Button"
- name: "Tertiary Button"
  componentId: "9:1449"
  component: "Button"

# entry 5：Back Button（icon 变体，同 Tertiary compId 不同 name）
- name: "Back Button"
  componentId: "9:1449"
  component: "Button"

# entry 6-7：file FIGMA_FILE_KEY_PLACEHOLDER_003 的 compId
- name: "Primary Button"
  componentId: "36587:38887"            # ← 不同 file 的同组件
  component: "Button"
  variantProperties: {Type: "Primary"}
- name: "Tertiary Button"
  componentId: "36587:38971"
  component: "Button"
```

**componentId 匹配优先于 name**，原 `name='Button'` 实例仍能走 name entry。
**去重键**：`(name, componentId)` 元组——同 name 不同 compId 合法，`test_no_duplicate_names` 已对齐。

### 不需要修的 name 变体
- **Icon 类**（`'Icon Left'` / `'Icon Right'` / `'Input Icon'`）：组件 Icon `component: ''` 故意保留 Figma SVG
- **Checkbox 类**：同理
- **纯数字 name**（`'1'` / `'2'`）：无规律
- **`'Frame xxxxxxxxxx'`**：Figma 默认命名
- **Slot / 具名容器槽位**：无规律

## 加新组件的工作流

### 任务 1：加一个有完整 extractor 支持的组件
```yaml
# 1. 在 ~/.avocado/presets/<name>.yaml 加 entry
- name: "MyComponent"
  componentId: "123:456"        # 从 Figma JSON 查
  component: "MyComponent"
  package: "@your-org/your-lib"
  dynamicProps:
    extractor: "mycomponent_items"  # register_extractor 注册的名字
```

```python
# 2. 在 ~/.avocado/plugins/my_extractors.py 写 extractor 并注册
from avocado.parser.component_extractors import register_extractor

def extract_mycomponent_items(node) -> list:
    """从 Figma 子节点提取 items 数组。"""
    items = []
    for child in node.get("children", []):
        # ... 提取逻辑
        items.append({...})
    return items

register_extractor("mycomponent_items", extract_mycomponent_items)
```

```bash
# 3. 测试
pytest tests/test_component_extractors.py -v
avocado <url> --component-lib <name> --dry-run  # 验证 preset 可解析 + extractor 已注册
```

### 任务 2：加叶子组件
```yaml
- name: "MyLeafComponent"
  componentId: "123:456"
  component: "MyLeafComponent"
  package: "antd"
  leaf: true                    # ← 关键
```

**验证**：用 d2c 单页冒烟验证（`avocado <url> --component-lib <name>`），确认 react_tw 模式无双重边框/双重文字。

### 任务 3：加 Button 变体（componentId alias）
1. 从 Figma JSON 查 componentId
2. 检查 antd.yaml 是否已有同 compId entry（有就加 name 到注释）
3. 若是新 compId，加独立 entry
4. 配 variantProperties 子集（Type / Size 等常见 variant 值）

### 任务 4：解锁数据驱动组件（blockNameMatch）
1. 先写 extractor（`~/.avocado/plugins/` 下，register_extractor 注册）
2. 用 extractor 名配 dynamicProps
3. 验证 `recognize()` 检查 `m.dynamic_props` 后允许 name 命中
4. **不要直接删 blockNameMatch 标记**（缺 extractor 的组件白屏）

## 插件编写（preset 的配套逻辑层）

preset 只是**数据**（组件映射表）；需要额外逻辑时写插件（如按层名识别非 INSTANCE 节点、modify_style 补样式、inspect_draft 加检查）。核心包不内置任何 extractor/recognizer（开源剥离后都是 migration asset），适配自己的组件库基本都要写插件——**不用深入 d2c 源码**，按本节约定即可。

### 发现与注册

插件是 `~/.avocado/plugins/*.py`（或 `./plugins/*.py` 项目级）的普通 Python 文件，`build_registry()` 自动发现。一个文件两种注册方式（二选一）：

```python
# 方式 1：模块级 plugin() 函数（优先，显式）
def plugin() -> Plugin:
    return MyPlugin()

# 方式 2：Plugin 子类扫描（fallback，文件里任意 Plugin 子类都会被实例化）
class MyPlugin(Plugin):
    ...
```

**加载失败只打 stderr warning，不阻断主流程**（`discover_plugins` 的 try/except）。

### Plugin 基类契约（plugins/base.py）

```python
from avocado.plugins.base import Plugin, hook

class MyPlugin(Plugin):
    name = "my-plugin"              # 必填，envelope plugins_applied[*].name 上报
    presets_used = ["my_lib"]         # 插件内部 load_preset 的 preset 名（供 envelope 上报真实 preset）

    @hook("modify_style")
    def add_unit(self, node, style):
        # node: TreeNode；style: dict
        return style                # ← 必须返回（modify_* 是"返回新 target"约定）
```

### 6 个 hook（签名 + 返回约定）

| hook | 签名 | 返回 | 运行时机 |
|---|---|---|---|
| `modify_json_schema` | `(_, root) -> root`（cli.py 以 `call("modify_json_schema", None, tree)` 两参调用，handler 形如 `(self, _ignored, root)`） | 新 root | **unwrap 之前**（组件先标记 → unwrap 保护） |
| `modify_props` | `(node, props) -> props` | 新 props | 渲染时逐节点 |
| `modify_style` | `(node, style) -> style` | 新 style | 渲染时逐节点 |
| `modify_css_var` | `(vars) -> vars` | 新 vars | CSS 变量表 |
| `generate_template` | `(root, code) -> code` | 新 JSX 字符串 | 最后 |
| `inspect_draft` | `(root) -> list[dict]` | 附加 warning 列表 | inspect 阶段 |

### 完整模板：name-recognizer（按层名识别非 INSTANCE 节点）

主管道只识别 INSTANCE；设计师把普通图层（FRAME/RECTANGLE/TEXT）忘了转组件时，用本插件补识别（用户自定义组件库的 name-recognizer 插件即此模板，如 `~/.avocado/plugins/my_recognizer.py`）：

```python
from avocado.model.tree_node import TreeNode
from avocado.parser.component import ComponentMapping, load_preset
from avocado.plugins.base import Plugin, hook

PRESET = "my_lib"  # 用哪个 preset 的 name 索引

class NameRecognizerPlugin(Plugin):
    name = "name-recognizer"
    presets_used = [PRESET]

    @hook("modify_json_schema")
    def recognize(self, _ignored, root: TreeNode) -> TreeNode:
        try:
            index = {}
            for m in load_preset(PRESET):
                if not m.name:
                    continue
                # 白屏保护：无 extractor 的 blockNameMatch 组件禁止 name 命中
                if m.block_name_match and not m.dynamic_props:
                    continue
                index[m.name.lower().strip()] = m
        except FileNotFoundError:
            return root  # preset 缺失 → no-op，不影响主流程
        stack = [root]
        while stack:
            n = stack.pop()
            if not n.is_component and not n.is_img:   # 不覆盖管道已识别的
                m = index.get((n.name or "").lower().strip())
                if m:
                    n.tag_name, n.is_component, n.component_package = m.component, True, m.package
                    for k, v in m.props.items():
                        n.props.setdefault(k, v)
            stack.extend(n.children)
        return root
```

**为什么 modify_json_schema 在 unwrap 前**：unwrap_single_child 会合并单子 wrapper；若 wrapper 层名匹配 preset 组件（如 "Body"→Text），unwrap 会把组件合并掉。`modify_json_schema` 先标记 `is_component` → unwrap 的 `is_component` 保护自动跳过它（Text 5→4 回归就是顺序错误导致的）。

### extractor（被 preset `dynamicProps.extractor` 引用）

```python
from avocado.parser.component_extractors import register_extractor

def steps_items(scene, path) -> dict:
    # scene: SceneNode；path: Figma 路径（"container > top > title" 或 __ROOT__）
    # 失败直接 raise 或返回 {} 都行——run_extractor 静默返回 {}
    return {"items": [...]}

register_extractor("steps_items", steps_items)  # import 时注册（模块顶层）
```

- 签名：`fn(scene: SceneNode, path: str | None) -> dict`
- **静默失败是合法降级**：返回 `{}` → 组件不带 items 渲染，不崩流程；`apply_component` 会记 `extractor-empty` inspect
- **覆盖同名 extractor 会打 stderr warning**（冲突可发现）

### 关键坑

1. **hook 必须返回 target**（modify_* / generate_template），否则链式调用吞掉前一个插件的修改
2. **插件 print 会被重定向到 stderr**（stdout 必须是单一 JSON envelope）——调试信息不会破坏契约
3. **presets_used 必须声明**，否则 envelope 看不到真实 preset（agent 以为没加载组件库）
4. **静默失败是设计**：extractor 失败、preset 缺失、插件加载失败都不阻断主流程
5. **同 hook 多插件 = 最后一个注册生效**（KISS：冲突由用户修插件，不做合并策略）

## 调试：--trace-adapter

适配最常见的问题是"为什么这个组件没被识别 / extractor 提取了什么"。`--trace-adapter` 把识别过程的**数据透传**到 envelope（opt-in，默认关闭零影响），不用读 d2c 源码。

### 用法

```bash
avocado <url> --cache-dir ... --offline --components mylib.yaml --trace-adapter        # 全开
avocado <url> ... --trace-adapter=preset        # 只看 preset 匹配链路
avocado <url> ... --trace-adapter=extractor     # 只看 extractor 输出
avocado <url> ... --trace-adapter=hook          # 只看插件 hook 统计
# 非法子集（如 --trace-adapter=foo）→ invalid_argument
```

### envelope 输出（data.trace）

| 块 | 内容 | 用途 |
|---|---|---|
| `preset_matches` | `total/matched/unmatched` 计数 + `unmatched_details`（全量：skipped_by + reason）+ `matched_samples`（top-10：matched_by + entry_short + variant_hits） | 看**为什么没识别**（compId 未收录 / name 不匹配 / blockNameMatch 跳过 / variant 降级） |
| `extractor_outputs` | component / extractor / path / success / keys / sample{items_len, first_title} | 看 extractor **实际提取了什么**（空返回也记录 success=false） |
| `plugin_hooks` | plugin / hook / nodes_affected / sample_names | 看 name-recognizer 等插件**影响哪些节点**（防误识别） |

### 适配闭环（4 步）

1. `--trace-adapter=preset` → 看 `unmatched_details` 的 `skipped_by` + `reason`，判断该补 compId alias / 改 name / 加 extractor
2. 改 `~/.avocado/presets/<lib>.yaml`
3. 重跑 → 看 `matched_samples` 确认 `matched_by` 命中（unmatched 中该节点消失）
4. 有 extractor/插件 → 看 `extractor_outputs` / `plugin_hooks` 核对数据；最后不带 trace 跑正式生成回归

**确定性**：trace 数据排序稳定（同输入同输出），可进回归 diff。

## 常见 agent 错误

1. **给 Button 加 leaf** → children 是 button 文字，清了就没 label
2. **给 Icon 加 component** → 组件 Icon 故意 `component: ''` 保留 Figma SVG
3. **放开 blockNameMatch 组件的 name 匹配** → 缺 extractor 的组件白屏
4. **variants override 不传 leaf** → `name: Input` → LabeledInput 时 leaf 不生效
5. **同 compId 加多个 entry** → `test_no_duplicate_names` 报错；应按 `(name, componentId)` 去重
6. **helper text 匹配后代 name** → 把 container FRAME 拖出来双重渲染
7. **改 antd.yaml 不跑覆盖率测试** → `test_preset_coverage.py` 要求 ≥95%

## 相关 skill

- [avocado-d2c](../avocado-d2c/SKILL.md) — 用 `--component-lib antd` 触发 preset 加载
- [avocado-path-config](../avocado-path-config/SKILL.md) — preset 文件 4 层查找

## 真相源

- ComponentMapping dataclass：`packages/avocado/src/avocado/parser/component.py`
- blockNameMatch + leaf/leafExtras 字段 + variantProperties/variants/dynamicProps：`packages/avocado/src/avocado/parser/component.py`
- extractor registry（register_extractor / run_extractor）：`packages/avocado/src/avocado/parser/component_extractors.py`
- **插件系统**（Plugin 基类 / hook 装饰器 / 6 hooks / discovery）：`packages/avocado/src/avocado/plugins/base.py`
- 内置示例 preset（antd，18 entry）：`packages/avocado/src/avocado/_bundled/presets/antd.yaml`
- 用户自建 preset/extractor 插件：`~/.avocado/presets/` + `~/.avocado/plugins/`（见 `docs/preset-guide.md`）
- **name-recognizer 插件实例**：用户本地 `~/.avocado/plugins/` 下的自定义识别/提取插件（开源核心包不内置任何 extractor/recognizer）
- 测试：`packages/avocado/tests/test_component_*.py` + `test_preset_coverage.py` + `test_preset_schema.py`
- leaf 字段 + Button alias：`docs/preset-guide.md`（leaf / componentId alias 章节）+ 根 `CLAUDE.md` 关键约束第 6 条（blockNameMatch 白屏保护）
