# Preset 开发指南

avocado preset 是 YAML 文件，定义「Figma 组件 → 业务组件」的映射规则。本文档教你如何编写和维护自己的 preset。

## 目录

- [快速开始](#快速开始)
- [9 字段完整说明](#9-字段完整说明)
- [componentId alias 模式（跨 file 双 compId）](#componentid-alias-模式跨-file-双-compid)
- [leaf 字段判定（什么时候加）](#leaf-字段判定什么时候加)
- [dynamicProps extractor 怎么写](#dynamicprops-extractor-怎么写)
- [variantProperties vs variants 区别](#variantproperties-vs-variants-区别)
- [blockNameMatch（数据驱动组件保护）](#blocknamematch数据驱动组件保护)
- [component: '' 模式（保留 Figma SVG）](#component--模式保留-figma-svg)

---

## 快速开始

```bash
# 1. 复制中立示例作为起点
cp ~/.avocado/presets/antd.yaml.example ~/.avocado/presets/my-ui.yaml

# 2. 编辑 my-ui.yaml，改 component/package 为你的组件库
vim ~/.avocado/presets/my-ui.yaml

# 3. 使用
avocado <url> --component-lib my-ui -o out.jsx

# 4. 验证
avocado paths  # 确认 preset 路径正确
avocado schema  # 确认 --component-lib flag 可识别
```

Preset 文件放在 4 层查找路径之一（首次命中即用）：
1. CLI flag `--components <path>`（显式路径，不走 name 查找）
2. `cwd/.avocado/presets/<name>.yaml`（项目级覆盖）
3. `~/.avocado/presets/<name>.yaml`（用户级默认）
4. 包内 `_bundled/presets/<name>.yaml`（wheel bundle 兜底）

---

## 9 字段完整说明

每个 preset entry 是一个 YAML dict，支持 9 个字段（YAML camelCase ↔ Python snake_case 自动转换）：

### 1. `name`（必需）

Figma INSTANCE 节点的 `name` 字段。d2c 用它做 name 匹配。

```yaml
- name: Button
  component: Button
  package: 'antd'
```

**head-noun 命名习惯**：Figma 设计师常按 head-noun 命名（如 `'Primary Button'` 而非 `'Button'`），这时用 `componentId` alias 匹配（见下文）。

### 2. `component`（必需，除非用 `variants` 分发）

映射到的业务组件名。d2c 生成的 JSX 里 `<component ...>` 的标签名。

```yaml
component: Button   # → <Button ...>
component: ''       # 空字符串，保留 Figma SVG（见「component: '' 模式」段）
```

### 3. `package`（必需）

npm 包名。d2c 生成的 import 语句用。

```yaml
package: 'antd'                # → import { Button } from 'antd'
package: '@your-org/your-lib'  # 任意组件库包名
```

### 4. `componentId`（可选，跨 file alias 用）

Figma componentSet 的 ID。当 `name` 匹配不到时（head-noun 命名 / 跨 file 不同 compId），用 componentId 精确匹配。

```yaml
- name: Button
  component: Button
  package: 'antd'
  componentId: '9:1043'        # mobile file
- name: Button
  component: Button
  package: 'antd'
  componentId: '36587:38887'   # PC file（同组件不同 file 不同 compId）
```

**同 name 不同 compId 合法**（去重 key 是 `(name, componentId)`）。详见 [componentId alias 模式](#componentid-alias-模式跨-file-双-compid)。

### 5. `variantProperties`（可选，Figma variant → 业务组件 prop）

把 Figma componentSet 的 variant 属性映射到业务组件的 prop。

```yaml
variantProperties:
  Variant:           # Figma variant 属性名
    Primary:         # Figma variant 值
      type: primary  # → <Button type="primary">
    Secondary:
      type: default
  Size:
    Large:
      size: large    # → <Button size="large">
    Small:
      size: small
```

d2c 读 Figma `componentProperties[type=VARIANT]`，匹配 variantProperties 的 key，把 value 写入 `tree.props`。

### 6. `variants`（可选，Figma variant → 切换组件）

当不同 variant 需要映射到**不同业务组件**时用（比 variantProperties 更强：换组件名，不只是 prop）。

```yaml
variants:
  Type:                    # Figma variant 属性名
    Radio Button:          # Figma variant 值
      component: Radio     # → 切换到 <Radio>（不是 <Checkbox>）
      package: 'antd'
    Default:
      component: Checkbox  # → 保持 <Checkbox>
      package: 'antd'
```

`variants` override 也读 `leaf` 字段。

### 7. `dynamicProps`（可选，Python extractor 从子节点提取复杂数据）

有些组件需要数组型 prop（如 Steps 的 `items`、Tabs 的 `panels`），Figma variant 无法表达。用 Python extractor 从子节点递归提取。

```yaml
dynamicProps:
  extractor: steps_items   # extractor 名（注册在 component_extractors.py）
```

d2c 调 `run_extractor("steps_items", scene_node)` → 返回 `{steps_items: [{title, description}, ...]}` → 写入 `tree.props`。详见 [dynamicProps extractor 怎么写](#dynamicprops-extractor-怎么写)。

### 8. `leaf`（可选，默认 false）

叶子组件标记。`leaf: true` 时 d2c 清空 `tree.children` 和 `tree.text_content`——因为业务组件自带内部 DOM（如 Input 自带 border + placeholder），Figma children 会导致双重渲染。

```yaml
- name: Input
  component: Input
  package: 'antd'
  leaf: true               # 清 children，避免 antd Input + Figma DOM 双重渲染
```

详见 [leaf 字段判定](#leaf-字段判定什么时候加)。

### 9. `props`（可选，静态 prop 注入）

固定 prop 值，不管 Figma variant 是什么都注入。

```yaml
- name: SafeArea
  component: SafeArea
  package: 'antd'
  props:
    platform: ios           # → <SafeArea platform="ios">（固定值）
```

---

## componentId alias 模式（跨 file 双 compId）

**问题**：Figma 设计师按 head-noun 命名（`'Primary Button'` 而非 `'Button'`），且同一组件在不同 Figma file 有不同 componentSet ID。

**解决**：为每个 compId 加独立 entry（同 name 不同 compId 合法，去重 key 是 `(name, componentId)`）。

```yaml
# Button 在 mobile file 的 compId
- name: Button
  component: Button
  package: 'antd'
  componentId: '9:1043'
- name: Button
  component: Button
  package: 'antd'
  componentId: '36587:38887'   # PC file 的 compId

# Icon Left 在 mobile + PC 的 compId（component:'' 保留 SVG）
- name: Icon Left
  component: ''
  package: 'antd'
  componentId: '36587:38873'   # mobile file
- name: Icon Left
  component: ''
  package: 'antd'
  componentId: '9:448'         # PC file
```

**匹配优先级**：componentId 精确匹配 > name 精确匹配。componentId 命中后直接用该 entry，不再做 name 匹配。

**怎么查 compId**：从 Figma JSON 的 `componentId` 字段读（`figma_cache/nodes/<file_key>/<hash>/d8` 或 `figma_json/<page>.json` 里 INSTANCE 节点的 `componentId`）。

```python
# 查某页所有 INSTANCE 的 compId
import json
data = json.load(open('~/.avocado/output/figma_json/sample_page.json'))
def walk(node):
    if node.get('type') == 'INSTANCE':
        print(f"{node['name']}: {node.get('componentId', '')}")
    for c in node.get('children') or []:
        walk(c)
walk(data)
```

---

## leaf 字段判定（什么时候加）

**加 `leaf: true`**：组件自带内部 DOM，Figma children 会导致双重渲染（重复边框、错位文字、视觉混乱）。

典型场景：
- Input / LabeledInput / PhoneInput / LabeledTextArea / Switch：自带 border + placeholder + label
- Checkbox / Radio（当作为独立组件用时）：自带 checkmark

**不加 `leaf`**：
- Button：children `<span>label</span>` 是 button 文字，组件把 children 当 label
- Card / Modal：children 是内容区域，业务组件需要 children
- Icon（`component: ''`）：保留 Figma SVG 子节点

**保留 Helper Text 等额外元素（leafExtras）**：Figma 可能在 LabeledInput 子树内包含组件
不渲染的元素（Helper Text / Error Message）。preset 条目可配 `leafExtras` 列表，leaf 分支
会深度遍历子树，匹配列表中关键字的节点保留为兄弟节点（不丢失）：

```yaml
- name: LabeledInput
  component: LabeledInput
  package: 'antd'
  leaf: true
  leafExtras: ['helper text', 'error message', 'hint text', 'helper']
```

**判定流程**：
1. 查业务组件文档——它是否自带内部 DOM（border/placeholder/label）？
2. 是 → `leaf: true`
3. 否（children 是内容）→ 不加 leaf
4. 不确定 → 不加 leaf，先用 d2c 生成 JSX 在浏览器里对一下 Figma 原稿（双重渲染会有明显视觉错位，加 leaf 后恢复）

---

## dynamicProps extractor 怎么写

**何时需要**：组件需要数组型 prop（items/panels/steps），Figma variant 无法表达。例如：
- Steps 需要 `items=[{title, description}, ...]`
- Tabs 需要 `panels=[{title, content}, ...]`
- Total 需要 `items=[{name, amount, currency}, ...]`

**机制**：核心包不内置 extractor。extractor 由用户插件注册（`register_extractor(name, fn)`），
preset 通过 `dynamicProps: {extractor: <name>}` 引用。插件放在 `./plugins` 或
`~/.avocado/plugins/`，avocado 自动发现并导入（导入时注册）。

**写法**：

1. **写 extractor 函数**（放插件文件，如 `~/.avocado/plugins/my_extractors.py`）：

```python
from avocado.parser.component_extractors import register_extractor


def _steps_items(scene_node, path=None) -> dict:
    """从 Steps INSTANCE 的子节点提取 items 数组。

    签名约定：接收 scene_node（SceneNode）+ path（可选），返回 dict（key 是 prop 名）。
    失败时返回 {}（静默失败，d2c 降级为不传 prop）。
    """
    items = []
    for child in scene_node.children or []:
        # 递归找子节点的 name/text/style
        title = _find_text(child, "Title")
        description = _find_text(child, "Description")
        if title:
            items.append({"title": title, "description": description or ""})
    return {"steps_items": items} if items else {}
```

2. **注册**（模块导入时）：

```python
register_extractor("steps_items", _steps_items)
```

3. **在 preset YAML 引用**：

```yaml
- name: Steps
  component: Steps
  package: 'antd'
  dynamicProps:
    extractor: steps_items            # ← register_extractor 注册的 key
```

4. **测试**：对 extractor 函数写单测（mock scene_node，验证返回 dict）；用
   `avocado schema` 的 `available_extractors` 字段确认注册成功。

**静默失败约定**：extractor 返回 `{}` 时 d2c 不传 prop（组件用默认值），不报错。这让 extractor 可以「尽力提取」，提取不到就降级。

---

## variantProperties vs variants 区别

两者都处理 Figma variant，但作用层级不同：

| 特征 | variantProperties | variants |
|---|---|---|
| 作用 | variant 值 → **prop 值** | variant 值 → **切换组件** |
| 层级 | 改 props（标签名不变） | 改 component + package（换标签） |
| 用途 | Button 的 Primary/Secondary → `type` prop | Checkbox 的 Radio Button variant → 换成 `<Radio>` |

```yaml
# variantProperties：同一组件，不同 prop 值
- name: Button
  component: Button
  variantProperties:
    Variant:
      Primary: { type: primary }    # <Button type="primary">
      Secondary: { type: default }  # <Button type="default">

# variants：不同 variant 换不同组件
- name: Checkbox
  component: Checkbox
  variants:
    Type:
      Radio Button:                  # Figma 选了 Radio Button variant
        component: Radio             # → 生成 <Radio>（不是 <Checkbox>）
        package: 'antd'
```

**何时用哪个**：组件名不变只用 variantProperties；组件名要换用 variants。可以同时用（variants 分发后，variantProperties 仍作用于分发后的组件）。

---

## blockNameMatch（数据驱动组件保护）

**问题**：有些组件需要数组 prop 但没有 extractor（如 Form/Guide/Tour），直接 name 匹配会让组件渲染但缺 prop → React 树白屏。

**解决**：preset 条目设 `blockNameMatch: true`，name 匹配被跳过（只能 componentId 精确匹配）。条目配置了 `dynamicProps` 时 name 匹配放行（extractor 会补 prop）。

```yaml
- name: Form
  component: Form
  package: 'antd'
  blockNameMatch: true      # 无 dynamicProps 时按 name 不匹配（防白屏）
```

**何时加**：
1. 组件需要数组 prop（items/panels/forms）
2. 没有对应的 dynamicProps extractor
3. 缺 prop 会让 React 树白屏（组件内部 map undefined 报错）

**判定流程**：
1. 组件需要数组 prop？ → 否：不加
2. 是 → 有 extractor？ → 是：加 dynamicProps，不加 blockNameMatch
3. 否（无 extractor）→ 加 blockNameMatch + preset 里加 entry（componentId 匹配仍可用）

---

## component: '' 模式（保留 Figma SVG）

**用途**：组件库没有通用 Icon 组件时，强制映射会破坏还原度（组件 Icon 渲染与 Figma 原生 SVG 不同）。

**解决**：`component: ''` 让 recognize() 命中（识别率提升），但 apply_component() 检测空 component 返回 False（不替换 DOM），保留 Figma 原生 SVG 渲染。

```yaml
- name: Icon
  component: ''
  package: 'antd'
  dynamicProps:
    extractor: icon_meta    # 提取 iconName 元数据（component:'' 也要有 dynamicProps 让测试过）

- name: Placeholder          # 无组件库对应，component:'' 保留 Figma 渲染
  component: ''
  componentId: '36587:38863'
  dynamicProps:
    extractor: icon_meta
```

**关键约束**：`component: ''` 的 entry **必须有** `dynamicProps`（否则 test_every_entry_has_component_or_variants 会失败，因为空字符串是 falsy）。用 `extractor: icon_meta` 是最安全的（Icon/Placeholder/Icon Left/Right 都用它）。

**效果**：识别率提升（INSTANCE 被标记 is\_component=True），但还原度不受影响（DOM 不变，仍是 Figma SVG/children）。

---

## 调试技巧

### 查看识别率

```bash
# 单页
avocado <url> --component-lib <name> -o out.jsx 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)['data']
r = d.get('recognition', {})
print(f'rate: {r.get(\"rate_percent\")}')
print(f'unrecognized: {r.get(\"unrecognized_instances\", [])[:5]}')
"
```

### 验证 preset YAML 合法

```bash
avocado <url> --component-lib <name> --dry-run  # 不调 API，验证 preset 可解析
```

### 测试不破坏现有还原度

加 preset entry 后，用 d2c 重新生成 JSX 并在浏览器里对一下 Figma 原稿，确认视觉无回归（`component: ''` 模式零副作用，DOM 不变）。

---

## 完整示例

参见 `_bundled/presets/antd.yaml`（Ant Design 中立示例，20+ 通用组件）与
`~/.avocado/presets/<your-lib>.yaml`（你自己的组件库预设）。自建 preset 的完整
字段与 extractor 注册见本文档各章节。
