# Flag 决策树

> 详细版 flag 选择逻辑。SKILL.md 的决策表是速查；本文档解释**为什么**。

## 输出形态决策（4 维正交）

### 维度 1：`--format`（JSX 结构）
- `react`（默认）— 输出 `import` + `export default function` + `style={{}}` 对象 + lineHeight 字符串化
- `html` — 输出 HTML5 标签 + `style="..."` 字符串

**选择**：
- 下游是 React/Next.js/Vite 项目 → `react`
- 下游是静态 HTML / Vue / 邮件 / 直接浏览器打开 → `html`

### 维度 2：`--css`（CSS 形态）
- `tailwind`（默认）— `className="flex p-4"` + 剩余 inline style 作 fallback
- `inline` — 全部走 `style="..."` / `style={{}}`
- `class` — 抽 CSS class 到独立 `.css` 文件，节点 className 引用

**选择**：
- 想用 Tailwind CDN / 业务 Tailwind 工程 → `tailwind`
- 不想引 Tailwind，简单单文件 → `inline`
- 复杂样式，想复用 + 减小 JSX 体积 → `class`（同时输出 `out.css`）

### 维度 3：`--layout`（布局策略）
- `flex`（默认）— Figma Auto Layout → CSS Flexbox
- `absolute` — 所有 frame 走绝对定位回退

**选择**：
- 设计稿大量用 Auto Layout → `flex`（推荐）
- 设计稿纯绝对定位（无 Auto Layout）→ `absolute`
- 混合：`flex` 优先，无 Auto Layout 的 frame d2c 自动回退 absolute（不用切换）

### 维度 4：`--component-lib`（组件库预设）
- `None` — 输出纯 div/span
- `antd` — antd 18 entry 映射（bundled 中立示例，见 `avocado-component-adapter` skill）

**选择**：
- 下游用 antd → `--component-lib antd`
- 下游无组件库 / 自己写 → 不传

## 特殊场景组合

### React + antd（业务推荐）
```bash
avocado URL --format react --css tailwind --component-lib antd -o out.jsx
```

### 静态 HTML 原型
```bash
avocado URL --format html --css inline -o out.html
```

### CSS 抽取（设计还原 + 独立样式表）
```bash
avocado URL --format html --css class -o out.jsx  # 同时写 out.css
```

### 绝对定位还原（无 Auto Layout 设计稿）
```bash
avocado URL --layout absolute -o out.jsx
```

### CSS Variables 替换（接业务主题系统）
```bash
avocado URL --css-vars --var-map <name> -o out.jsx
# 输出 color: var(--color-primary, #1890ff) 形式
# 下游定义 --color-primary 就接管主题
```

## 不输出 `:root` 块（强制约束）

`--css-vars` **只生成** `var(--name, fallback)` 引用，**不生成** `:root { --x: ...; }`。

**理由**：下游项目（antd）有自己的主题系统。`var(--x, fallback)` 自带 fallback 让下游：
- 不定义 → 用设计稿当前值
- 定义了 → 接管主题

**不要"顺手"在生成的 JSX 里塞 `<style>` 块**。

## box-sizing 决策

默认 `content-box`，**不注入 `<style>` reset**。

| 选项 | 行为 | 影响 |
|---|---|---|
| `--box-sizing content-box`（默认） | 不注入 reset | width/height 是 content-box 语义 |
| `--box-sizing border-box` | 注入 `<style>*{box-sizing:border-box}</style>` | width/height 含 padding+border |

**警告**：`border-box` 下程序**不自动重算** width/height——还原度可能变化，由用户自负。

## 精度重写

`--precision N`（默认 `2`）正则重写 style 字符串值的数字部分：
- `precision=0` — 整数
- `precision=1` — 1 位小数
- `precision=2`（默认）— 2 位小数
- `precision=unset` — 不重写

**注意**：
- 必须在所有 style pass 之后
- 若已抽 class，reround 对 class_map 再跑一次
- 正则仅匹配 style/class_map 字符串值的前导数字，不动 className/props/text_content

## 默认开启的优化 pass（可关）

| Flag | 默认 | 用途 |
|---|---|---|
| `--inherit-promote` / `--no-inherit-promote` | 开 | 把所有叶子取相同值的可继承属性（color/font-*/text-*）提升到父级 |
| `--strip-defaults` / `--no-strip-defaults` | 开 | 删除 spec 默认值（flex-direction: row / opacity: 1 等） |
| `--unwrap-single` / `--no-unwrap-single` | 开 | 合并无视觉样式的单子 FRAME/GROUP wrapper |
| `--inspect` / `--no-inspect` | 开 | 输出 7 条 inspect 规则警告（聚合进 envelope `data.inspect_summary`；`--no-inspect` 关闭） |
| `--beautify` / `--no-beautify` | 开 | 内置 JSX 美化器（tree-sitter） |

默认关的：
| Flag | 默认 | 用途 |
|---|---|---|
| `--gap-to-margin` / `--no-gap-to-margin` | 关 | flex gap → 每子节点 margin |
| `--auto-group-variance` / `--no-auto-group-variance` | 关 | 用子节点 x/y 方差推 auto_group flex-direction |

## 调试加速组合

### 跳过美化（最快输出）
```bash
avocado URL --no-beautify -o out.jsx
```
**用途**：codegen 原始输出，调试 parser 时用。生产不要关美化（输出更规整）。

### 离线模式（250× 加速）
```bash
# 第一次：在线 + 写缓存
avocado URL --cache-dir /tmp/figcache -o out.jsx

# 后续：只读缓存，零网络
avocado URL --cache-dir /tmp/figcache --offline -o out.jsx
```

### 适配调试（--trace-adapter）
```bash
avocado URL --components mylib.yaml --trace-adapter=preset --summary   # 只看 preset 匹配链路
avocado URL ... --trace-adapter=preset,extractor,hook                  # 全开（含 extractor/插件/issues）
```
**用途**：看"为什么没识别"（unmatched 的 skipped_by + path + suggestion）、extractor error 分类、插件 hook 统计、issues 聚合。opt-in 默认关（envelope 零影响）。详见 component-adapter skill 调试章节。

### 深度限制（debug 用）
```bash
avocado URL --depth 3 -o out.jsx  # 只渲染 3 层深度
```

## 互斥规则（务必遵守）

- `--components <yaml>` 与 `--component-lib <name>` **互斥**，前者优先
- 错误在请求 Figma API 之前快速失败（节省一次网络请求）
- `--format inline/tailwind` 已**废弃**，新代码用 `--format react/html` + `--css inline/tailwind/class`

## 输出确定性（改代码时遵守）

d2c 输出必须**确定性**——还原度回归靠 diff 对比 JSX，非确定输出让对比失效。

- `INHERITABLE_CSS_PROPS` 必须是 **tuple**，不是 frozenset
- `parser/optimize/inherit_promote.py` 按它迭代，frozenset 迭代顺序依赖进程 hash 随机化 → 同输入两次跑 className 顺序不同
- 只做成员判断的 frozenset（`_UNITLESS_NUMBER_SET`、`_VISUAL_STYLE_KEYS`）没问题
