---
name: avocado-d2c
description: Use when an agent needs to generate JSX/CSS from a Figma URL using the avocado CLI — covers `avocado <url>` flag selection, JSON envelope parsing, error code handling, cache/offline modes, output format combinations (flex/absolute × react/html × inline/tailwind/class), component library presets, CSS variables, and debugging with --no-beautify. Triggers on "convert Figma", "generate JSX", "run avocado", "d2c", "Figma to code", "avocado flags", "FIGMA_TOKEN", and when handed a figma.com URL. Does NOT cover path/config customization (avocado-path-config) or antd.yaml/plugin maintenance (avocado-component-adapter).
---

# avocado-d2c

把 Figma 节点 URL 转成 JSX + CSS 的 agent 操作手册。对应 CLI：`avocado <url>`。

## 何时触发

- 用户给 figma URL 并要 JSX / React / HTML / Tailwind 代码
- 用户说"转一下"、"生成代码"、"导出"、"还原"设计稿
- 用户问 avocado CLI 的某个 flag 怎么用

## 首次使用：配置 token

```bash
# 方式 1：交互式（推荐新用户）
avocado init

# 方式 2：非交互式（agent 友好）
avocado init --token figd_xxxxx

# 方式 3：环境变量
export FIGMA_TOKEN="figd_xxxxx"

# 方式 4：直接写 ~/.avocado/config.yaml
echo "figma_token: figd_xxxxx" > ~/.avocado/config.yaml
```

**token 4 层查找**（首次命中即用）：CLI --token > env FIGMA_TOKEN > cwd/.avocado/config.yaml > ~/.avocado/config.yaml
**token 获取**：figma.com → Settings → Personal access tokens → Generate

**不触发**（路由到对应 skill）：
- 改 preset / var-map / ~/.avocado 配置 → `avocado-path-config`
- 改 antd.yaml / 加组件映射 / 写插件 → `avocado-component-adapter`

## 标准调用流程

### Step 1：先 schema 自省（agent 第一次接触 avocado 时）

```bash
avocado schema
```

stdout 是 JSON envelope：`{"ok": true, "data": {"name": "avocado", "commands": [...], "error_codes": {...}, "version": "..."}}`。
（`global_flags` / `non_deterministic_fields` 只存在于 `schema.py:_SPEC` 内部维护，**不输出**；命令/flag/error code 权威清单以 `commands` 为准。）
**永远不要硬编码命令名/flag**——先 schema 发现能力。

### Step 2：生成 JSX

```bash
avocado "<figma-url>" -o out.jsx
```

默认行为（1.0.0 起）：
- **stdout 是 JSON envelope**（不是裸 JSX），`data.jsx` 是生成的代码
- `-o` 写文件后 envelope 省略 `data.jsx`（`jsx_omitted=True`，与 `--summary` 一致）+ `data.output_path` + `data.code_location`，读 `data.output_path` 取代码
- 退出码：`0`=ok / `1`=业务错误 / `2`=参数错误 / `130`=SIGINT
- envelope 顶层含 `{"name":"avocado","version":"1.0.0"}`（工具身份识别）

### Step 3：解析 envelope（字段全集）

```python
import subprocess, json
r = subprocess.run(["avocado", url, "-o", "out.jsx"], capture_output=True, text=True)
env = json.loads(r.stdout)
if env["ok"]:
    d = env["data"]
    # 代码内容
    d.get("jsx")                          # JSX 文本（-o + --summary 时不输出）
    d.get("jsx_omitted")                  # bool，true 表示因 -o 或 --summary 省略
    d.get("css")                          # CSS class 模式才有（用 .get 防 KeyError）
    d.get("css_omitted")                  # bool
    d.get("code_location")                # str=落盘路径 / None=未落盘（--summary 无 -o 时）
    d.get("output_path")                  # -o 时等同于 code_location
    d.get("css_path")                     # --css class + -o 时的 css 文件路径
    d.get("output_type")                  # "react" 或 "html"
    d.get("artifacts", {})                # {"jsxPath": "...", "cssPath": "..."}
    d.get("beautified")                   # bool，美化是否真的应用了
    d.get("warnings", [])                 # 美化失败/deprecation 等非致命警告（含 _sanitize_ansi 处理）
    # inspect
    # d.get("inspect") 完整数组已不再输出（只有聚合的 inspect_summary；--human 下才逐条打 stderr）
    d.get("inspect_summary")              # 按 code 聚合的统计：{total, by_code, by_severity}
    d.get("inspect_count")                # int
    # 识别统计
    d.get("recognition", {})              # {instances, recognized, rate, rate_percent,
    #                                      top_level_instances, top_level_rate, top_level_rate_percent,
    #                                      unrecognized_instances: [{name,count,component_id}], _note}
    # flag 组合摘要
    d.get("mode")                         # {format, format_raw, css, layout, offline, beautify,
    #                                      component_lib, css_vars, precision, box_sizing,
    #                                      figma_id, depth, has_output, preset, html_fragment,
    #                                      html_wrapped, preview_centered, passes{}, _beautify_note?}
    d.get("preset_expanded")              # 仅 --preset 时：{"--format": "html", ...}（显式 flag 冲突时以显式值覆盖）
    # 来源 + 计时
    d.get("token_source")                 # cli_flag / env_var / config_file / unknown
    d.get("fetch_source")                 # cache / network（--offline 恒为 cache，不再 fallback 网络）
    d.get("timing", {}).get("duration_seconds")  # 非确定性（schema 标注）
    # hints（actionable）
    d.get("hints", [])                    # 中文 hints 数组
else:
    code = env["error"]["code"]           # 见下方 error code 字典
    hint = env["error"]["hint"]           # 中文 actionable hint
```

**`--summary` 模式字段**（省 ~18KB 流量）：
```python
d["jsx_omitted"] == True                 # jsx/css 省略
d["css_omitted"] == True                 # （css 模式时）
d["code_location"] = None                # 提示 agent 用 -o 落盘（或重跑）
d["hints"] 会含 "use -o <file>" 提示
```

**`--dry-run` 模式字段**（验证参数不调 API 不写盘）：
```python
d["dry_run"] == True
d["validated"]                           # {url, file_key, node_id, format, css, layout,
#                                        component_lib, offline, summary}
d["token_source"]                        # 同上
d["would_write"]                         # [output_path] 或 []
d["hint"]                                # 提示去掉 --dry-run 真跑
```

## Flag 选择决策表

| 想要 | Flag 组合 |
|---|---|
| 默认 React 组件（推荐） | （默认）`--format react --css tailwind` |
| 纯 HTML + inline style | `--format html --css inline` |
| HTML + Tailwind CDN | `--format html --css tailwind` |
| 抽 CSS class 到独立 .css | `--format html --css class -o out.jsx`（同时写 out.css） |
| 抽 CSS class 但不写文件 | `--format html --css class`（CSS 走 stderr fenced block，stdout 仍是 JSX） |
| 绝对定位（设计稿无 Auto Layout） | `--layout absolute` |
| 业务组件库（antd） | `--component-lib antd` |
| CSS Variables 替换 | `--css-vars --var-map <name>` |
| 加速回归（同输入已跑过） | `--cache-dir /tmp/figcache`（在线 + 写缓存） |
| 零网络重跑 | `--cache-dir /tmp/figcache --offline` |
| 调试输出（跳过美化） | `--no-beautify`（codegen 原始输出，更快） |
| 调试加 data-figma-id 属性 | `--figma-id`（每个节点加 data-figma-id，traceability/debug 用，默认关） |
| 验证参数不调 API | `--dry-run`（验证 URL+token+params，不写文件，envelope 含 validated + would_write） |
| 瘦身 envelope | `--summary`（省 jsx/css 文本，加 jsx_omitted/css_omitted/code_location） |
| **preset 打包** | `--preset designer`（HTML 完整文档+预览居中+无 data-figma-id）/ `--preset dev`（react+tailwind，**组件库需显式 `--component-lib <name>`**）/ `--preset compare-ready`（react+class+summary） |
| **HTML 预览居中** | `--preview-centered`（灰底+居中+阴影，designer preset 默认开启） |
| **HTML 片段模式** | `--html-fragment`（退回裸 `<div>` 片段，默认 --format html 输出完整文档） |
| **清小数像素** | `--precision 0`（默认 `2` 保留 2 位小数；`0` 全取整到整数，平均偏移仅 ~0.08px；`1` 取整到 1 位；`unset` 用 Figma 原始 float32 值如 `99.66970825195312`） |
| 人类可读输出（彩色 stderr） | `--human` (**破坏 JSON 契约**：d2c stdout 输出 JSX 文本；schema/paths/init --human 输出 Markdown/彩色文本到 stdout，AI agent 一律不用 --human) |

## 互斥与优先级（务必遵守）

- `--components <yaml>` 与 `--component-lib <name>` **互斥**，前者优先；错误在请求 Figma API 之前快速失败（Click `type=Path` 用 `exists=False`，业务内手动校验）
- `--var-map <path>` 显式 > `--component-lib` 自动走 4 层查找 > 空映射 fallback `fig-var-<short>`
- `--format inline/tailwind` 已**废弃**（保留兼容，加 deprecation warning），新代码用 `--css inline|tailwind|class`。`mode.format` 显示映射后值，`mode.format_raw` 保留原始输入
- `--css class` 必须在所有 style pass 之后；rerounded 后对 class_map 再跑一次（不要改顺序）
- `-o /dev/stdout` / `-o -` 被禁止（JSX + envelope 双重写 stdout 会破坏 JSON 契约）
- `--token "garbage"` 校验：长度 ≥20 + 提示 `figd_` 前缀（不做 API 校验避免网络依赖）

## Error Code（agent 必须按 code 分支处理）

> 完整真相源是 `avocado schema` 输出的 `error_codes`。当前 9 个（snake_case；camelCase 别名已删除）：
> NOTE：`figma_not_found` 进一步细化为 `figma_file_not_found`（URL file_key 错/无权限）vs `figma_node_not_found`（node-id 复制错/被删）。

| code | exit | hint | 触发场景 | agent 修复策略 |
|---|---|---|---|---|
| `figma_not_found` | 1 | check FIGMA_TOKEN and URL | 404 兜底（无法判定 file vs node） | 提示检查 URL 和 token |
| `figma_file_not_found` | 1 | URL file_key 错或无权限 | 整个 file 404 | 复制完整 Figma URL，确认 token 能访问该 file |
| `figma_node_not_found` | 1 | node-id 复制错或被删 | API 返回 null node | 从 Figma 右键 'Copy link' 重新复制 URL |
| `figma_auth_failed` | 1 | token invalid or expired | 401/403 | 提示用户重新生成 token，跑 `avocado init` |
| `figma_rate_limited` | 1 | retry in N seconds or reduce parallelism | 429 | 等待重试，单进程串行 |
| `figma_cache_miss` | 1 | run once online with --cache-dir first | `--offline` 模式 cache miss（不再 fallback） | 先去掉 `--offline` 跑一次补缓存 |
| `invalid_argument` | 2 | check the error message | 参数错误 | 改参数（不要重试） |
| `internal_error` | 1 | rerun in editable install for stack trace | 未知异常 | 看 stderr stack，必要时上报 |
| `interrupted` | 130 | re-run to complete | 用户 SIGINT 中断 | 重新运行 pipeline |

## 浏览器预览生成的 JSX

d2c 输出的 JSX 是片段，需要在浏览器看到效果取决于格式：

```bash
# React 模式（默认）：需要 Vite/Next.js 消费
avocado URL --format react -o out.jsx
# 输出 import React + export default function，需在 Vite/Next.js 项目里 import 使用
# 或用 create-vite 创建临时项目：
npm create vite@tmp preview -- --template react-ts && cp out.jsx tmp/src/App.tsx && cd tmp && npm i && npm run dev

# HTML 模式（默认输出完整文档，可直接浏览器打开）
avocado URL --format html --css inline --box-sizing border-box -o out.html
# 输出 self-contained 完整 HTML 文档（<!DOCTYPE html>+viewport+body 包裹）
# 直接 `open out.html` 即可浏览器预览
# 加 --preset designer 还含预览居中样式（灰底+居中+阴影）
avocado URL --preset designer -o out.html   # 一键设计师预览

# --html-fragment 退回旧的裸片段行为（嵌入已有页面时用）
avocado URL --format html --html-fragment -o fragment.html  # 只有 <div> 片段
```

## 加速回归（开发场景）

```bash
# 第一次：在线拉取 + 写本地缓存
avocado URL --cache-dir /tmp/figcache -o /tmp/out.jsx

# 后续：只读缓存，零网络（单页 ~250× 加速）
avocado URL --cache-dir /tmp/figcache --offline -o /tmp/out.jsx
```

`--offline` 模式：
- 缓存 miss 报 `figma_cache_miss`（不再 fallback 到网络；之前的 fallback 已移除）
- 不需要 FIGMA_TOKEN（但 cache miss 时仍需要在线补缓存）
- 返回的 image src 是本地路径（不是 CDN URL）

## 输出确定性（agent 改代码时遵守）

d2c 输出必须**确定性**（同输入同输出）——回归靠 diff 对比 JSX。
- `INHERITABLE_CSS_PROPS` 必须是 **tuple**，不是 frozenset（`parser/optimize/inherit_promote.py`）。frozenset 迭代顺序依赖进程 hash 随机化 → 同输入两次跑 className 顺序不同 → diff 失效。
- 只做成员判断的 frozenset（`_UNITLESS_NUMBER_SET`、`_VISUAL_STYLE_KEYS`）没问题。

## 语义标签与代码质量边界（PR#29 / #28 决策）

生成代码含语义标签，按 CSS 形式**分模式**（零视觉保证——不注入任何 `<style>` reset）：

| CSS 形式 | 语义化范围 | 原因 |
|---|---|---|
| `tailwind` | h1-h6/p/ul/li/button + landmark（header/nav/main/footer/aside/article/section） | Tailwind preflight 已 reset UA 默认样式 |
| `inline` / `class` | 只 landmark（main/section/nav/article/aside/header/footer——纯 display:block，渲染与 div 完全一致） | 无 preflight，h1-h6/p/ul/li/button 有 UA 默认样式，语义化会破坏零视觉 |

**匹配规则**（宁少勿错——错误语义比无语义更糟，误导屏幕阅读器/SEO）：
- 页面 root FRAME → `<main>`
- name 精确 `Title`/`Heading`/`Headline` + font-size → `<h2>`（≥20px）/`<h3>`（≥16px），仅 tailwind
- name 精确 `Button`/`btn`（非组件节点）→ `<button>`，仅 tailwind
- name 列表 + 3+ 同前缀子 → `<ul>`/`<li>`，仅 tailwind
- **组件识别优先**：INSTANCE 识别为业务组件（如 `<Button>`）胜过原生 `<button>`——agent 不要误判"为什么这个 Button 不是 button"
- text 节点（`<span>`）不动

**嵌套层级边界**（#28 决策，agent 不要误判为 bug）：
- 结构性嵌套（卡片/区块/组件层层包裹）是 **Figma 源结构决定**——源嵌套深的任何 D2C 工具输出都深，强行合并破坏还原度
- icon 定位链（如 `Minus > Single Icon > Union > Minus Circular > img`）是绝对定位 **containing block 层叠**（每层 `absolute`/`relative` 有定位作用）——合并会改变定位坐标
- `unwrap_single_child` 已安全折叠所有"纯 wrapper"（无视觉/无定位作用），且**不注入 reset**
- icon 病态深嵌（5+ 层）的**正解是组件映射**（Single Icon/Union → `<Icon name="minus"/>` 一行替代 5 层定位 div），不是合并 div

**0px 冗余**：CSS 零值不需要单位，`padding: 0px 0px 12px 0px` → `0 0 12px 0` 已自动清理（HTML inline + React style 双通道）。

## 何时用 --no-beautify

`--no-beautify` 跳过美化，输出 codegen 原始 JSX：
- **调试更快**：跳过格式化
- **定位生成器问题**：看原始输出不被美化掩盖
- **不要在最终输出用**：beautify 默认开，输出更规整

## envelope data 字段（gen 命令完整清单）

```json
{
  "ok": true,
  "data": {
    "jsx": "...",            // JSX 文本（即使 -o 写文件也会回传；--summary 时省略）
    "jsx_omitted": false,    // 是否因 --summary 或 -o 省略
    "css": "...",            // 可选，仅 --css class 且 css_text 非空时
    "css_omitted": false,    // --summary 时省略
    "code_location": "/abs/path/out.jsx",  // str=落盘 / null=未落盘
    "output_path": "/abs/path/out.jsx",    // 同 code_location
    "css_path": "/abs/path/out.css",       // 可选，仅 --css class + -o 时
    "output_type": "react",  // "react" 或 "html"
    "artifacts": {
      "jsxPath": "...",      // -o 写入的绝对路径
      "cssPath": "..."       // 可选
    },
    "beautified": true,      // 美化是否真的应用了
    "warnings": [],          // 美化失败/deprecation/图片绝对路径 等非致命警告
    "inspect_summary": {     // 7 条 inspect 规则按 code 聚合
      "total": 3, "by_code": {"instance-not-recognized": 2}, "by_severity": {"warning": 2, "info": 1}
    },
    "inspect_count": 3,
    "recognition": {         // 仅 instance_total>0 时加入
      "instances": 25, "recognized": 20, "rate": 0.8, "rate_percent": "80.00%",
      "top_level_instances": 5, "top_level_rate": 0.6, "top_level_rate_percent": "60.00%",
      "unrecognized_instances": [{"name":"Primary Button","count":3,"component_id":"9:1043"}],
      "_note": "instances 统计 scene 树全量；inspect 统计优化后 tree 树（口径不同）"
    },
    "mode": {                // flag 组合摘要
      "format": "react", "format_raw": "react",  // format_raw 是原始输入（deprecation shim 前）
      "css": "tailwind", "layout": "flex",
      "offline": false, "beautify": true,
      "component_lib": null, "css_vars": false,
      "precision": 2, "box_sizing": null,
      "figma_id": false, "depth": null,
      "has_output": true,
      "passes": {"inherit_promote": true, "strip_defaults": true, "unwrap_single_child": true,
                 "gap_to_margin": false, "auto_group_variance": false},
      "_beautify_note": "..." // 可选，beautify=True 但 beautified=False 时关联 warnings
    },
    "token_source": "cli_flag",  // cli_flag/env_var/config_file/unknown
    "fetch_source": "cache",     // cache/network（--offline 恒为 cache）
    "timing": {              // ⚠️ 非确定性（schema 标注）
      "duration_seconds": 0.15,
      "_note": "non-deterministic field, exclude from diff comparison"
    },
    "hints": ["3 INSTANCE node(s) not recognized — add --component-lib antd"]
  }
}
```

**条件加入 vs 始终加入**：
- `jsx` 仅当 `not output and not summary`
- `css` 仅当 `css_text and not output and not summary`
- `warnings` 仅当 warnings 数组非空
- `inspect_summary` 仅当 inspect_warnings 非空
- `recognition` 仅当 `instance_total > 0`
- `_beautify_note` 仅当 beautify=True 但 beautified=False
- 其余字段始终加入

agent 用 `d.get(key)` 防止 KeyError（特别 `css` / `warnings` / `inspect_summary` / `recognition`）。

## inspect 7 条规则（parser/inspect.py:250-258 RULES）

每次跑 d2c 都会附加到 `data.inspect_summary`（除非 `--no-inspect`）：

| code | severity | 触发 | 说明 |
|---|---|---|---|
| `deep-nesting` | error ≥15 / warning ≥8 | 嵌套深度 > 8 | 输出难维护 |
| `many-absolute-children` | info | absolute 节点 > 5 子节点 | 考虑用 Auto Layout |
| `low-contrast` | warning | `<span>` 文本 WCAG AA < 4.5:1 | 暗文本/亮背景对比不足 |
| `img-no-size` | info | `<img>` 缺 width/height | 可能布局抖动 |
| `long-inline-style` | info | style 属性 > 8 个 | 考虑抽 CSS class |
| `component-no-package` | warning | 识别为组件但无 package | 用户需手动加 import |
| `image-fetch-failed` | warning | `<img>` 的 `_image_error` 或 `src=""` | FIX: image fetch 失败，检查 imageRef 或在线补缓存 |

inspect 警告同时进 `data.hints`（去重），关键 code 有 actionable 映射：
- `instance-not-recognized` → "add --component-lib antd"（已加组件库 时改说"覆盖不足，检查 componentId alias"——避免 AI 死循环）
- `image-fetch-failed` → "image fetch failed，检查 imageRef 或先在线补缓存"
- 其他 code → inspect_summary 独占

## stderr 进度行（不要当 error）

d2c 在 stderr 输出进度信息（**stdout 仍是干净的 JSON envelope**）：
- `[info] image-prefetch raster=Xhit+Yfetch vector=...` — 非 offline 时批量预取图片（VECTOR/INSTANCE/RECTANGLE）
- inspect 警告（若开）

agent 解析时只读 stdout，stderr 仅用于人类查看 / debug。

## 常见 agent 失败模式

1. **stdout 不是 JSX** → 是 JSON envelope，`data.jsx` 才是 JSX
2. **裸 `print()` 到 stdout** → 破坏 envelope 契约；agent 自己调 subprocess 时只解析 stdout
3. **重试 `invalid_argument`** → exit 2 是参数错误，改参数不要重试
4. **给 `--offline` 不给 `--cache-dir`** → 报错；先在线跑一次补缓存
5. **改了 pipeline 顺序** → 6 个优化 pass 顺序固定（见根 CLAUDE.md）

## 相关 skill

- [avocado-path-config](../avocado-path-config/SKILL.md) — 改配置 / preset / var-map
- [avocado-component-adapter](../avocado-component-adapter/SKILL.md) — 改组件库 preset / 写配套插件

## 真相源

- 实现入口：`packages/avocado/src/avocado/cli.py:main()`
- envelope 契约：`avocado/envelope.py`（error code 字典见 `avocado schema`）
- agent 集成示例：`docs/agent-integration.md`
- 命令清单真相源：`avocado/commands/schema.py:_SPEC`（cli.py 加 flag 必须同步更新）
- 版本号：以 `avocado schema` 输出的 `data.version` 为准（本文档 "1.0.0 起" 为撰写时版本）
