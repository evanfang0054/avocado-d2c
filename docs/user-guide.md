# avocado 用户手册

> Figma Design-to-Code 工具 — 把 Figma 节点 URL 转成 JSX + CSS。

## avocado 能帮你做什么

1. **生成代码**：从 Figma URL 一键生成 React JSX 或 HTML（含 Tailwind / inline style / 独立 CSS 文件三种 CSS 模式）
2. **识别业务组件**：加载组件库预设（内置 antd 示例），把 Figma INSTANCE 节点替换成真实业务组件（Button / Input / Select 等）
3. **离线加速**：把 Figma 数据镜像到本地缓存，后续零网络重跑（单页 47s → 0.19s，250× 加速）
4. **agent 友好**：stdout 默认 JSON envelope，error code 带 actionable hint，AI agent 可程序化消费
5. **CSS 变量替换**：把 Figma Variable binding 转成 `var(--name, fallback)`，下游主题系统可接管

---

## 30 秒上手

```bash
pip install avocado-d2c
avocado init --token figd_xxxxx                          # 配置 Figma token
avocado "https://www.figma.com/design/XXXX/T?node-id=10:20" -o out.jsx
```

URL 必须含 `?node-id=...`（从 Figma 右键 "Copy link" 复制完整 URL）。

**`avocado init`** 会自动创建 `~/.avocado/{output,presets,var-maps,plugins}/` 目录，并在 `presets/` 放入带教学注释的 `antd.yaml.example` 模板（自建组件库的起点，见场景 F）。

---

## 命令清单（完整）

| 命令 | 用途 | 何时用 |
|---|---|---|
| `avocado <url>` | **核心**：Figma URL → JSX/HTML | 想要代码时 |
| `avocado schema` | 输出命令/flag/error code 清单 | 忘了有什么命令时 |
| `avocado init` | 配置 figma_token | 第一次使用 / token 过期 |
| `avocado paths` | 打印资源路径 + 4 层查找 | 找配置/缓存/产物在哪 |
| `avocado --version` | 打印版本号 | 确认版本 |

---

## 两类用户角色

### 角色 1：前端开发者（拿 JSX 集成到项目）

```bash
# 默认 React + Tailwind（最常用）
avocado "<figma-url>" -o Button.jsx

# 业务项目用组件库（INSTANCE → 真实业务组件；内置 antd 示例）
avocado "<figma-url>" --component-lib antd -o out.jsx

# 纯 HTML + inline style（静态页 / 邮件 / iframe）
avocado "<figma-url>" --format html --css inline -o out.html

# 抽 CSS class 到独立 .css 文件
avocado "<figma-url>" --css class -o out.jsx            # 同时生成 out.css
```

**拿到 JSX 后需要手动补**：
1. `npm install` 业务组件包（avocado 不验证 package.json）
2. `<ConfigProvider>` 主题包裹（antd 等组件需要根包裹）
3. 图片 src 替换为本地资源（默认指向 Figma CDN）
4. 文案外部化（硬编码文字改 `t('key')` i18n）

### 角色 2：AI agent / 自动化（程序化批量调用）

```bash
# 1. 先自省发现能力（不要硬编码命令名）
avocado schema                                         # 返回所有命令/flags/error code

# 2. 解析 JSON envelope（stdout 是 JSON，不是裸 JSX）
avocado "<url>" --summary -o out.jsx                   # --summary 省 ~18KB 流量
```

```python
import subprocess, json
r = subprocess.run(["avocado", url, "--summary", "-o", "out.jsx"],
                   capture_output=True, text=True)
env = json.loads(r.stdout)

if env["ok"]:
    d = env["data"]
    jsx_path = d.get("code_location") or d.get("output_path")
    inspect = d.get("inspect_summary", {})
    print(f"还原度提示: {inspect}")
else:
    code = env["error"]["code"]
    hint = env["error"]["hint"]
    if code == "figma_rate_limited":
        time.sleep(5); retry()      # 退避重试
    elif code == "invalid_argument":
        fix_params()                # 改参数（不要重试）
    elif code == "figma_auth_failed":
        ask_user_regen_token()      # 让用户重新生成 token
```

**退出码**：`0`=成功 / `1`=业务错误 / `2`=参数错误 / `130`=SIGINT 中断。**只解析 stdout**，stderr 只是日志。

---

## 6 种输出模式（format × css）

| 组合 | tag / style 形态 | 场景 |
|---|---|---|
| **react + tailwind**（默认） | `<div className="flex p-4" style={{"opacity":0.5}}>` | 生产交付 |
| **react + inline** | `<div style={{"display":"flex","padding":"16px"}}>` | 像素级还原 |
| **react + class** | `<div className="frame-2">` + `.css` | 中后台可控样式表 |
| **html + tailwind** | `<div class="flex p-4">` | 静态落地页（Tailwind CDN） |
| **html + inline** | `<div style="display:flex;padding:16px">` | 邮件 / iframe / 即时预览 |
| **html + class** | `<div class="frame-2">` + `.css` | 传统网页 |

**Tailwind 不是 100% 覆盖**：无法映射的样式（如 hex 颜色 `#3a86ff`）会作为 leftover 留在 inline `style`，形成 className + style 混合输出。

**关键区别**：
- React 输出含 `import React` + `export default function`；style 是 camelCase 对象；`lineHeight` 强制 `"24px"` 字符串
- HTML 是裸 fragment（无 `<html>` 包裹）；属性是 `class`（不是 `className`）；style 是 kebab-case 字符串；可直接拖进浏览器

---

## d2c 命令的 flag（按场景）

### 格式 / CSS / 布局

| flag | 选项 | 默认 | 场景 |
|---|---|---|---|
| `--format` | `react` / `html` | `react` | React 项目用 react；静态页用 html |
| `--css` | `tailwind` / `inline` / `class` | `tailwind` | Tailwind 适合大多数场景；class 抽独立 .css |
| `--layout` | `flex` / `absolute` | `flex` | 无 Auto Layout 的稿子用 absolute |

### 组件库

| flag | 说明 |
|---|---|
| `--component-lib <name>` | 加载 preset（4 层查找：`--components` > `cwd/.avocado/presets/` > `~/.avocado/presets/` > 内置；内置 antd 示例） |
| `--components <yaml>` | 直接指定映射文件路径（与 `--component-lib` 互斥，临时实验用） |
| `--css-vars --var-map <name>` | CSS 变量替换（`var(--name, fallback)`） |

### 加速 / 缓存

| flag | 说明 |
|---|---|
| `--cache-dir <dir>` | 镜像 Figma 数据到本地（在线模式自动写） |
| `--offline` | 只读缓存零网络（必须先在线跑一次补缓存） |
| `--depth <N>` | 限制拉取树深度（调试用） |

### 调试 / 诊断

| flag | 说明 |
|---|---|
| `--dry-run` | 验证 URL+token+参数，不调 API、不写文件 |
| `--summary` | envelope 省略 jsx/css 文本，省 ~18KB（配 `-o` 落盘） |
| `--no-beautify` | 跳过 JSX 美化（输出 codegen 原始格式，更快） |
| `--no-inspect` | 关闭 inspect 警告 |
| `--figma-id` | 在每个节点输出 `data-figma-id` 调试属性（默认关闭，需要 traceability 时显式开启） |
| `--trace-adapter[=preset,extractor,hook]` | 适配调试透传：envelope 加 `data.trace`（preset 匹配链路 / extractor 输出含 error 分类 / 插件 hook 统计 / issues 聚合），opt-in 默认关；详见 `docs/preset-guide.md` 调试技巧章节 |
| `--human` | 彩色 stderr（**仅供 shell pipe 老用法，AI agent 禁用**） |

### 输出控制

| flag | 说明 |
|---|---|
| `-o / --output <file>` | 写文件（默认走 stdout envelope 的 `data.jsx`） |
| `--token <token>` | 或设 `FIGMA_TOKEN` 环境变量 |
| `--precision 0/1/2/unset` | 数值小数位（默认 2） |
| `--box-sizing content-box/border-box` | 默认 content-box **不注入 `<style>`**（CSS 默认值，注入纯冗余）；显式 `border-box` 才注入 reset |

---

## 典型场景

### 场景 A：第一次使用

```bash
pip install avocado-d2c
avocado init                                       # 交互式配 token
avocado "<figma-url>" -o /tmp/first.jsx            # 第一份代码
```

### 场景 B：React + Tailwind（最常见）

```bash
avocado "<figma-url>" --component-lib antd -o Card.jsx
# Card.jsx 拷进 Vite/Next.js 项目，补 ConfigProvider + 图片本地化
```

### 场景 C：用组件库 + CSS 变量

```bash
avocado "<figma-url>" --component-lib antd --css-vars -o out.jsx
# INSTANCE 识别为业务组件 + 颜色/间距换成 var(--name, fallback)
```

### 场景 D：离线加速（多次重跑）

```bash
# 第一次：在线 + 写缓存
avocado "<figma-url>" --cache-dir ~/.avocado/output/figma_cache -o out.jsx

# 后续：完全离线（250× 加速）
avocado "<figma-url>" --cache-dir ~/.avocado/output/figma_cache --offline -o out.jsx
```

### 场景 E：一次转多个设计稿（批量）

avocado 一次处理一个 URL，多稿批量就是脚本循环。**多个稿子可以共用一个缓存目录**——缓存按 file_key + node_id 哈希分键，互不干扰：

```bash
# ① 在线批量跑一遍：出代码，同时把 n 个稿子镜像进同一个缓存目录
urls=(
  "https://www.figma.com/design/AAA/Login?node-id=10:20"
  "https://www.figma.com/design/BBB/Home?node-id=30:40"
  "https://www.figma.com/design/CCC/Profile?node-id=50:60"
)
i=1
for url in "${urls[@]}"; do
  avocado "$url" --cache-dir ~/.avocado/output/figma_cache -o "out_$i.jsx"
  i=$((i+1))
done

# ② 之后任意次数离线重跑：零网络，秒级返回（覆盖同名单输出）
i=1
for url in "${urls[@]}"; do
  avocado "$url" --cache-dir ~/.avocado/output/figma_cache --offline -o "out_$i.jsx"
  i=$((i+1))
done
```

要点：

- 换输出模式（react/html、tailwind/inline/class）不用重新拉 Figma，缓存已够
- 缓存 miss 报 `figma_cache_miss`，**不会偷偷走网络**——补跑一次在线即可
- 同一缓存目录可服务多个 file；团队共享缓存目录时注意离线模式下图片 src 是本地绝对路径，换机器需重新在线跑一次

### 场景 F：接入你自己的组件库

内置 antd 只是中立示例。把**你自己的组件库**接进来三步：

**① 建 preset 文件**（首次运行 `avocado init` 会在 `~/.avocado/presets/` 放一份带教学注释的模板 `antd.yaml.example`）：

```bash
avocado init   # 已配过 token 可跳过；作用是确保 ~/.avocado/ 目录结构存在
cp ~/.avocado/presets/antd.yaml.example ~/.avocado/presets/my-ui.yaml
```

**② 编辑 my-ui.yaml**：定义「Figma 组件 → 业务组件」映射，最小一条：

```yaml
components:
  - name: Button          # Figma INSTANCE 节点的 name（按名匹配）
    component: Button     # 生成的 JSX 标签名
    package: 'my-ui'      # import 语句的来源包名
```

共支持 9 个字段：`componentId`（跨 file 精确匹配）、`variantProperties`（变体 → prop 值）、`variants`（变体 → 换组件）、`leaf`（叶子组件防双重渲染）、`dynamicProps`（数组型 prop 提取）、`props`（静态注入）等，完整说明见 [Preset 开发指南](preset-guide.md)。

**③ 使用**：

```bash
avocado "<url>" --component-lib my-ui -o out.jsx
```

- **preset 查找顺序**：`--components <path>`（显式路径）> `cwd/.avocado/presets/<name>.yaml`（项目级）> `~/.avocado/presets/<name>.yaml`（用户级）> 包内内置。项目级随仓库走，适合团队共享 preset
- 临时实验可跳过建文件：`avocado "<url>" --components /path/to/any.yaml -o out.jsx`
- 配套 CSS 变量映射：同名 `var-maps/my-ui.yaml` 会在 `--component-lib` 时自动加载
- 识别率低：看 envelope 的 `recognition.unrecognized_instances` 列出未识别实例，往 preset 里补对应 `name` / `componentId`（详见 preset-guide.md 的「componentId alias 模式」）

---

## 输出产物长什么样

### d2c envelope（`avocado <url>` 输出）

```json
{
  "ok": true,
  "data": {
    "jsx": "import React from \"react\";\n...",
    "jsx_omitted": false,
    "output_type": "react",
    "code_location": "/abs/path/out.jsx",
    "artifacts": {"jsxPath": "/abs/path/out.jsx"},
    "inspect_summary": {
      "total": 12,
      "by_code": {"instance-not-recognized": 3, "deep-nesting": 1},
      "by_severity": {"info": 10, "warning": 2}
    },
    "recognition": {
      "instances": 25, "recognized": 20, "rate": 0.8,
      "rate_percent": "80.00%"
    },
    "mode": {"format": "react", "css": "tailwind", "layout": "flex"},
    "warnings": [],
    "timing": {"duration_seconds": 0.15},
    "hints": ["3 INSTANCE node(s) not recognized — add --component-lib <name>"]
  }
}
```

---

## FAQ

### Q: Figma URL 怎么复制才对？

在 Figma 里右键画板 / 节点 → **Copy link**。URL 必须含 `?node-id=10:20`，否则报 `invalid_argument`。

### Q: token 去哪拿？

figma.com → 右上头像 → **Settings** → **Personal access tokens** → Generate。然后 `avocado init` 或写到 `~/.avocado/config.yaml`。

token 4 层查找：`--token` flag > `FIGMA_TOKEN` env > `cwd/.avocado/config.yaml` > `~/.avocado/config.yaml`。

### Q: 生成的代码怎么跑起来看？

- **React 模式**：输出含 `import React` + `export default function`，需 Vite/Next.js 消费
  ```bash
  npm create vite@tmp preview -- --template react-ts
  cp out.jsx tmp/src/App.tsx && cd tmp && npm i && npm run dev
  ```
- **HTML 模式**：输出是自包含片段，包一层 `<html><body>...</body></html>` 即可浏览器打开
  ```bash
  echo "<html><body>$(cat out.html)</body></html>" > preview.html && open preview.html
  ```

### Q: 为什么我的 INSTANCE 没识别出来？

两种情况：
1. Figma 设计师命名不匹配预设（如起名 "Primary Button" 而非 "Button"）—— 加 `--component-lib <name>` 用 componentId 匹配
2. componentId 不在 preset —— 看 envelope 的 `recognition.unrecognized_instances` 字段，加 componentId alias 到 preset

### Q: 离线模式怎么用？为什么要先在线跑一次？

离线模式只读本地缓存。第一次必须在线跑 `--cache-dir DIR` 把 Figma 数据镜像到本地；之后 `--offline --cache-dir DIR` 零网络重跑（单页 47s → 0.19s）。

直接 `--offline` 不补缓存会报 `figma_cache_miss`。

### Q: 改稿后怎么重新生成？

同 URL 直接重跑（缓存会被新数据覆盖）。担心缓存旧可删 `~/.avocado/output/figma_cache/` 强制重 fetch。

### Q: 美化失败/输出很乱怎么办？

beautify 失败会自动降级为原始输出并附 warning（envelope `warnings` 数组）。调试 codegen 时可用 `--no-beautify` 跳过美化，输出仍可用，只是格式没那么规整。

### Q: `--human` flag 能用吗？

**AI agent 禁用**。`--human` 让 d2c stdout 输出裸 JSX 文本（破坏 JSON 契约），只给 shell pipe 老用法用。agent 一律不加 `--human`。

---

## 相关文档

- [5 分钟快速上手](quickstart.md) — 最短路径跑通
- [Agent 集成指南](agent-integration.md) — AI agent 程序化消费完整指南
- [Preset 开发指南](preset-guide.md) — 组件库映射 YAML 字段说明

## 文件位置

| 内容 | 路径 |
|---|---|
| 用户配置 + token | `~/.avocado/config.yaml` |
| 所有产物 | `~/.avocado/output/` |
| figma 缓存 | `~/.avocado/output/figma_cache/` |
| 自定义 preset / var-map | `~/.avocado/{presets,var-maps}/`（覆盖包内 `_bundled/`） |

跑 `avocado paths` 查看实际路径 + 4 层查找顺序。
