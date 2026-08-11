# var-maps — Figma VariableID 语义化映射

本目录存放 **VariableID → CSS 变量语义名** 的映射文件，供 `avocado --css-vars` 使用。

## 为什么需要这个文件

Figma REST API 不开放 `file_variables:read` scope，拿不到 Variable 的语义名（如 "color-bg-primary"），只能拿到 `VariableID:...`。所以让用户手填一份 YAML，CLI 在生成 JSX 时把 `var(--fig-var-xxx, fallback)` 替换成 `var(--color-bg-primary, #faf8f7)`。

## 文件命名

`<component_lib>.yaml`（与 `presets/<component_lib>.yaml` 对称）。

CLI 加载规则：
- `--var-map <path>` 显式指定 → 加载该文件
- `--component-lib <name>` 但没 `--var-map` → 自动尝试 `var-maps/<name>.yaml`（不存在不报错）
- 都不给 → 空映射，所有 binding 用 `fig-var-<short>` 形式

## 文件格式

```yaml
# Key: 从 Figma REST API boundVariables.id 直接复制的完整 VariableID
# Value: 语义化 CSS 变量名（不含 -- 前缀，CLI 自动加）
"VariableID:9810cffc.../15156:453": color-bg-primary
"VariableID:9810cffc.../15156:454": color-text-primary
```

### 校验规则

- Key 必须以 `VariableID:` 开头（不符合的条目静默跳过）
- Value 必须是合法 CSS 标识符（`^[A-Za-z_][A-Za-z0-9_-]*$`），不符合的跳过

## 如何获取 VariableID

### 方法 1：从 d2c 输出反推（推荐）

先不加 var-map 跑一次：

```bash
avocado URL --css-vars --no-beautify -o out.jsx
grep "fig-var-" out.jsx
# → var(--fig-var-15156-453, #faf8f7)
```

然后在 Figma 文件里搜索对应变量（颜色/字体/间距面板），找到这个 ID 对应的语义名，填到 YAML。

### 方法 2：从 Figma REST API 直接取

```bash
curl -H "X-Figma-Token: $FIGMA_TOKEN" \
  "https://api.figma.com/v1/files/<file_key>/nodes?ids=<node_id>" \
  | jq '.nodes[].document' | grep -A2 boundVariables
```

每个 `boundVariables.<prop>.id` 就是 `VariableID:...`。

### 方法 3：在 Figma UI 里查看

打开 Figma → 选中节点 → 右侧面板找 `Variables` → 把变量名和 VariableID 记下来（需要 dev mode 或插件辅助）。

## 输出效果

### inline 模式

```jsx
<div style={{
  backgroundColor: "var(--color-bg-primary, #faf8f7)",
  padding: "var(--spacing-md, 16px)",
}}>...</div>
```

### tailwind 模式

```jsx
<div className="bg-[var(--color-bg-primary,#faf8f7)] pt-[var(--spacing-md,16px)]">...</div>
```

## 不输出 `:root` 块（设计决策）

d2c 只在使用处输出 `var(--x, fallback)`，**不生成** `:root { --x: ...; }` 定义。理由：

- 下游组件库/主题系统可能自带 CSS 变量体系，`:root` 会让两套冲突
- `var(--x, fallback)` 自带 fallback：下游没定义 `--x` 就用设计稿当前值，定义了就自动接管
- KISS：不需要在生成的 JSX 里塞 `<style>` 块，美化流程零改动

下游项目在 `tailwind.config.js` 或全局 CSS 里定义这些变量即可。

## 支持的属性

| 类别 | Figma 属性 | CSS 属性 |
|---|---|---|
| 布局 | `cornerRadius`, `itemSpacing`, `paddingTop/Right/Bottom/Left`, `strokeWeight` | `border-radius`, `gap`, `padding-*`, `border-width` |
| 字体 | `fontSize`, `fontFamily`, `fontWeight` | `font-size`, `font-family`, `font-weight` |
| 颜色（paint 内嵌） | `fills[].boundVariables.color` | `background-color` |
| 颜色（stroke） | `strokes[].boundVariables.color` | （仅登记，不替换 — border 是复合值） |

**不支持**（KISS）：
- `individualStrokeWeights`（4 边不同 weight，复杂）
- `effects`（shadow blur + color 复合）
- `rectangleCornerRadii`（4 角不同 radius，复杂）
