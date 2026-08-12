# ComponentMapping Schema 与 extractor 详解

> antd.yaml 等 preset 文件的完整字段参考。SKILL.md 是速查；本文档解释**每个字段的行为**。

## ComponentMapping dataclass（真相源）

`packages/avocado/src/avocado/parser/component.py`：

```python
@dataclass
class ComponentMapping:
    """One entry in the user's component mapping table."""

    component: str               # 组件库组件名（必填）
    package: str = ""            # npm 包名（默认空，保留 Figma SVG）
    props: dict = field(default_factory=dict)  # 静态 props

    # 匹配条件（至少一个）
    name: str | None = None      # Figma 节点 name（大小写不敏感，精确匹配）
    component_id: str | None = None  # Figma componentSet ID

    # variant props（新增）
    variant_properties: dict = field(default_factory=dict)  # variant → component props
    variants: dict = field(default_factory=dict)            # variant → 切换 component
    dynamic_props: dict = field(default_factory=dict)       # Python extractor 名 → 数组 prop

    # leaf 字段（新增）
    leaf: bool = False           # 叶子组件清空 Figma children
```

## 字段详解

### component（必填）
antd 组件名。空字符串 `""` 表示**保留 Figma SVG**（用于 Icon）。

```yaml
- name: "Icon"
  component: ""              # ← 不映射到任何 组件库组件，保留 Figma 原始 SVG
```

### package
npm 包名。dataclass 默认 `""`（component.py:47）——component 非空时必须显式给 package（否则 codegen 不生成 import）；`component: ""`（Icon 保留 SVG 模式）时 package 无意义。

### props
静态 props，所有匹配的 INSTANCE 都用这些 props。

```yaml
- name: "Button"
  component: "Button"
  props:
    type: "default"
    block: true              # bare boolean，输出 block 而非 block=
```

### name（匹配条件 1）
Figma 节点 name，**大小写不敏感**，**精确匹配**。

```yaml
- name: "Button"             # 匹配 Figma 节点 name == "Button" / "BUTTON" / "button"
  component: "Button"
```

**Figma head-noun 命名习惯**：设计师常按"形容词 + 名词"命名（`'Primary Button'` 而非 `'Button'`），name 精确匹配会漏。此时需要 componentId alias。

### component_id（匹配条件 2）
Figma componentSet ID。**更精确**，survives renames。

```yaml
- name: "Button"
  component_id: "9:1043"     # 从 Figma URL 或 JSON 查
  component: "Button"
```

**优先级**：componentId 匹配 > name 匹配。

**关键变更**：`test_no_duplicate_names` 改为按 `(name, component_id)` 去重——**同 name 不同 compId 合法**。

### variant_properties
Figma variant 值 → 组件库组件 prop。

```yaml
- name: "Button"
  component_id: "9:1043"
  component: "Button"
  variant_properties:
    Size: "Small"            # Figma variant "Size=Small" → component prop size="small"
    Type: "Primary"          # Figma variant "Type=Primary" → component prop type="primary"
```

**实现**：`apply_component()` 读 Figma `componentProperties[type=VARIANT]`，应用 variantProperties 映射。

### variants
Figma variant 值 → **切换 component**（不只是 prop）。

```yaml
- name: "Input"
  component: "Input"         # fallback（无 variant 匹配时）
  variants:
    Basic: { component: "LabeledInput", leaf: true }
    "Phone Number": { component: "PhoneInput", leaf: true }
    "Text Area": { component: "LabeledTextArea", leaf: true }
    Default: { component: "LabeledInput", leaf: true }
```

**实现**：`recognize()` 中 `dataclasses.replace(matched, component=..., package=..., leaf=new_leaf)`。

**必须传 leaf**：
```python
# ✅ 正确
new_leaf = override.get("leaf", matched.leaf)
dataclasses.replace(matched, component=..., package=..., leaf=new_leaf)

# ❌ 错误
dataclasses.replace(matched, component=..., package=...)  # leaf 保持 False
```

### dynamic_props
复杂组件需要从 Figma 子节点提取数组数据。

```yaml
- name: "Steps"
  component: "Steps"
  dynamic_props:
    extractor: "steps_items"  # register_extractor 注册的 extractor 名
```

**实现**：
1. `apply_component()` 读 `dynamic_props.extractor`
2. 调 `run_extractor(extractor_name, figma_node)`（核心包 registry 分发）
3. 把返回的 dict 合并到 `tree.props`
4. **静默失败**：extractor 抛异常或返回 {}，不阻断流程

### leaf
叶子组件清空 Figma children。

```yaml
- name: "LabeledInput"
  component: "LabeledInput"
  leaf: true                 # ← 清空 children，避免双重渲染
```

**问题场景**：`apply_component` 识别 INSTANCE 后保留 Figma DOM 作为 children。叶子组件（LabeledInput）自带内部 DOM（input + border + label），保留 Figma DOM 会双重渲染：
- 重复边框
- 错位文字
- 视觉混乱

**实现**：`leaf=true` 时 `apply_component` 清空 `tree.children` 和 `tree.text_content`。

#### 加 leaf 的判定

| 加 `leaf: true` | 不加 leaf |
|---|---|
| LabeledInput / LabeledTextArea / PhoneInput | Button（children 是 button 文字） |
| Switch | Stepper（需 case-by-case） |
| 自带完整 DOM 不需要 Figma children | Icon（`component: ''` 保留 SVG） |

#### Helper Text 保留

Figma 设计稿可能在 LabeledInput 子树内包含 组件不渲染的元素：
- Helper Text "Please enter your details..."
- Error Message
- Hint Text

naive `children = []` 会丢掉这些。

**修复**：`apply_component` 的 leaf 分支会**深度遍历整个子树**，匹配 `leafExtras`（"helper text"/"error message"/"hint text"/"helper"）的节点保留，存到 `tree.props["_leaf_extras"]`。`node_mapper` 在父级构造 children 后把这些 extras 扁平化为兄弟节点。

**关键约束**：**只匹配节点自身 name，不匹配后代**。否则把 "container" FRAME 整个拖出来（带着 input field 一起，再次双重渲染）。

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

`recognize()` 检查 `m.dynamic_props`——有 dynamicProps 配置的组件（**即使设了 blockNameMatch**）允许 name 命中。

已解锁的（通过 extractor）：
- Steps → `steps_items`
- Tabs → `tabs_items`
- Collapse → `collapse_items`
- Total → `total_items`
- Summary → `summary_items`
- Filter → `filter_items`
- TabBar → `tabbar_items`

**规则**：不要为了"识别到了"而放开无 extractor 组件的 name 匹配。

## extractor 注册（register_extractor）

核心包只提供 registry（`packages/avocado/src/avocado/parser/component_extractors.py`），
extractor 函数由用户插件提供（`~/.avocado/plugins/` 下，导入时注册）：

```python
from avocado.parser.component_extractors import register_extractor

def extract_steps_items(node) -> dict:
    """从 Figma Steps 子节点提取 steps items 数组。"""
    items = []
    for child in node.get("children", []):
        if child.get("type") == "INSTANCE":
            items.append({
                "title": _extract_text(child, "title"),
                "description": _extract_text(child, "description"),
            })
    return {"items": items} if items else {}

register_extractor("steps_items", extract_steps_items)
```

`run_extractor(name, node, path)` 由核心包提供（静默失败返回 {}）：

```python
def run_extractor(name: str, node) -> dict:
    """调度 extractor，静默失败返回 {}（核心包 registry）。"""
    from avocado.parser.component_extractors import run_extractor as _core_run
    return _core_run(name, node, None)
```

### 加新 extractor 工作流

1. 在 `~/.avocado/plugins/my_extractors.py` 写函数 `extract_<name>_items(node) -> dict`
2. `register_extractor("<name>_items", fn)` 注册（模块导入时执行）
3. 在 preset 配 `dynamic_props: { extractor: "<name>_items" }`
4. 加测试 `tests/test_component_extractors.py`
5. 用 `from avocado.parser.component_extractors import available_extractors` 确认注册成功（schema 输出**不含**此字段；`available_extractors()` 是模块函数，供测试用）

## 加新组件工作流

### 场景 A：简单组件（无 variant / 无数组 prop）
```yaml
- name: "MyComponent"
  component_id: "123:456"        # 从 Figma JSON 查
  component: "MyComponent"
  package: "antd"
```

### 场景 B：带 variant 的组件
```yaml
- name: "MyComponent"
  component_id: "123:456"
  component: "MyComponent"
  variant_properties:
    Size: "Small"
    Type: "Primary"
```

### 场景 C：variant 切换 component
```yaml
- name: "Input"
  component: "Input"
  variants:
    Basic: { component: "LabeledInput", leaf: true }
    "Text Area": { component: "LabeledTextArea", leaf: true }
```

### 场景 D：需要 extractor
```yaml
- name: "MyList"
  component: "MyList"
  dynamic_props:
    extractor: "mylist_items"
```

```python
# 加 extractor（~/.avocado/plugins/my_extractors.py）
from avocado.parser.component_extractors import register_extractor

def extract_mylist_items(node) -> dict:
    items = []
    for child in node.get("children", []):
        items.append({"label": child.get("name", "")})
    return {"items": items} if items else {}

register_extractor("mylist_items", extract_mylist_items)
```

### 场景 E：叶子组件
```yaml
- name: "MyLeafComponent"
  component_id: "123:456"
  component: "MyLeafComponent"
  leaf: true
```

### 场景 F：跨 figma file alias
```yaml
# name 匹配 entry
- name: "Button"
  component: "Button"
  package: "antd"

# file A compId
- name: "Primary Button"
  component_id: "9:1043"
  component: "Button"
  package: "antd"
  variant_properties:
    Type: "Primary"

# file B compId（同组件不同 ID）
- name: "Primary Button"
  component_id: "36587:38887"
  component: "Button"
  package: "antd"
  variant_properties:
    Type: "Primary"
```

## 测试约束

### test_no_duplicate_names
按 `(name, component_id)` 去重——**同 name 不同 compId 合法**。

### test_preset_coverage
bundled antd.yaml 示例的自洽性检查：非空、至少 10 个 entry、每个 entry 解析到非空 component/package。

### test_preset_schema
YAML schema 校验（字段类型 / 必填项）。

### test_component_extractors
每个 extractor 单独测试，验证静默失败行为。

## 常见 agent 错误（再强调）

1. **给 Button 加 leaf** → children 是 button 文字，清了就没 label
2. **给 Icon 加 component** → 组件 Icon 故意 `component: ''` 保留 Figma SVG
3. **放开 blockNameMatch 组件的 name 匹配** → 缺 extractor 的组件白屏
4. **variants override 不传 leaf** → `name: Input` → LabeledInput 时 leaf 不生效
5. **同 compId 加多个 entry** → 测试报错；应按 `(name, component_id)` 去重
6. **helper text 匹配后代 name** → 把 container FRAME 拖出来双重渲染
7. **改 antd.yaml 不跑覆盖率测试** → `test_preset_coverage.py` 要求 ≥95%
