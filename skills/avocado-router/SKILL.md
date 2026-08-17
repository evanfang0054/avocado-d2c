---
name: avocado-router
description: "Use as the entry router when a user mentions avocado (the Figma-to-JSX CLI) or related antd tooling but their intent is ambiguous or spans multiple skills — e.g. \"avocado 怎么用\", \"不知道选哪个 skill\", \"avocado 能干什么\", \"avocado 总览\", \"帮我看看 avocado\", \"avocado 有哪些能力\", \"先告诉我用哪个\", \"avocado 整体架构\", \"avocado workflow\", \"组件库组件怎么用\", \"为什么没识别\", \"trace 调试\", \"antd\", or any avocado/antd-related request that doesn't clearly map to a single sub-skill. Also triggers for first-time users asking \"怎么开始 / 要配置什么 / 环境好了吗\" (routes to path-config's environment checklist). Routes to the right one of: avocado-d2c (生成 JSX), avocado-path-config (路径/配置), avocado-component-adapter (组件库适配：preset + 插件 + --trace-adapter 调试), avocado-visual-diff (网页 vs 设计稿 PNG 对比定位 DOM 差异，生成→对比→修复闭环). Also points to companion CLI antd (查询组件库 Props/demo/doc) when the question is about antd component library. If the user's intent is already specific (e.g. explicit \"转 JSX\" / \"改 preset\"), let the corresponding sub-skill trigger directly instead of this router."
---

# avocado-router

avocado skill 群的**总控路由**。用户提到 avocado 但意图模糊时，用本 skill 判断该走哪个子 skill。

> avocado 主包只提供 d2c（设计转代码）能力：`avocado <figma-url>` → JSX/CSS。

## 何时触发本 skill（路由器场景）

- 用户问"avocado 是什么 / 怎么用 / 能干什么 / 有哪些能力"
- 用户描述了问题但**不知道对应哪个 skill**（"我不确定该用哪个"）
- 用户的需求**跨多个 skill**（如"改 preset 后再生成验证"= avocado-component-adapter + d2c）
- 用户给一个模糊的 figma URL 说"帮我搞一下"
- **新用户开局问"我需要配置什么 / 环境好了吗 / 怎么开始"**（路由到 path-config 的环境检查）

## 新用户开局流程（最常见的入口）

用户第一次接触 avocado 通常会问"我要配置什么？"。标准流程：

### 1. 环境就绪检查（path-config 的"环境检查清单"段）
```
✅ avocado CLI             → avocado --version
✅ FIGMA_TOKEN             → ~/.avocado/config.yaml 或 env
✅ ~/.avocado/ 目录        → 首次运行自动创建（ensure_user_dirs）
```

### 2. 冒烟测试
```bash
avocado "<figma-url>" -o /tmp/out.jsx       # 单页 d2c
```

## 何时**不**触发（让子 skill 直接接）

明确意图的话术直接路由到子 skill，不要经总控：

| 用户原话（示例） | 直接路由到 |
|---|---|
| "把这个 Figma 转成代码" / "生成 JSX" / "导出" | `avocado-d2c` |
| "preset 放哪" / "找不到资源" / "改输出目录" | `avocado-path-config` |
| "加组件" / "antd.yaml" / "leaf 字段" / "blockNameMatch" / "写插件" | `avocado-component-adapter` |
| "为什么没识别" / "trace 调试" / "--trace-adapter" / "识别率低" | `avocado-component-adapter` |
| "对比网页和设计稿" / "还原度检查" / "差异在哪个 DOM" / "生成→对比→修复" | `avocado-visual-diff` |

## 4 个子 skill 导航

### avocado-d2c — Figma URL → JSX 生成
**核心职责**：把 Figma URL 转成 JSX + CSS（`avocado <url>` 主命令）。
**典型场景**：
- 用户给 figma URL 想要 React / HTML / Tailwind 代码
- 选 flag 组合（format / css / layout / component-lib）
- **preset 打包**（`--preset designer` HTML 预览 / `--preset dev` react+tailwind，**组件库需显式 `--component-lib`**）
- 处理 envelope error code
- 加速回归（cache/offline 模式）
**关键约束**：stdout 永远是 JSON envelope；error code 详见 `avocado schema`；输出必须确定性。

### avocado-path-config — 路径与配置体系
**核心职责**：avocado 的资源路径解析（4 层查找）+ 用户配置（`~/.avocado/`）。
**典型场景**：
- 用户问"preset 放哪 / 怎么自定义"
- "file not found" for antd.yaml / var-maps/antd.yaml
- 改输出目录 / 自定义组件库预设
- 验证 wheel 资源完整
**关键约束**：4 层查找单一真相源；不要硬编码 `Path(__file__).parents[N]`；token 4 层查找（CLI > env > cwd/.avocado 项目级 > ~/.avocado 用户级）。

### avocado-component-adapter — 组件库适配（preset + 插件）
**核心职责**：维护 antd.yaml 等组件映射文件 + 编写配套识别/提取插件。
**典型场景**：
- 加新组件到预设
- INSTANCE 识别不到（Figma name 不匹配 / compId 没收录）
- 加叶子组件（LabeledInput 等） / extractor
- blockNameMatch / variant / dynamicProps 字段问题
**关键约束**：ComponentMapping 9 字段（YAML camelCase ↔ Python snake_case）；blockNameMatch 数据驱动保护；leaf 字段判定（Button 不加，LabeledInput 加）；extractor 静默失败是合法降级。

### avocado-visual-diff — 网页 vs 设计稿 PNG 对比（生成→对比→修复闭环）
**核心职责**：Playwright 截图 + odiff 像素对比 + DOM 归因，输出差异区域及责任元素（selector / text / figmaId）。
**典型场景**：
- 用户给设计稿 PNG + 网页 URL（或本地服务），要"对比差异 / 看还原度"
- 生成页面后验证还原度，修复后重跑对比（迭代闭环）
- 报告 `summary[].selector` 直接定位到要改的 DOM 节点
**关键约束**：stdout 是 JSON envelope（`regions` + `summary`）；设计稿 @1x 与截图 dpr 匹配；threshold 默认 0.05（0.1 会漏浅色差异）。

## 路由决策树

```
用户请求
   │
   ├─ 模糊/总览/跨多 skill？
   │   → 停在本 skill，用上面的导航表给建议
   │
   ├─ 提到 figma URL + "转代码/生成/导出"？
   │   → avocado-d2c
   │
   ├─ "preset/designer/dev/预览模式"？
   │   → avocado-d2c
   │
   ├─ "路径/放哪/找不到/preset 位置/wheel"？
   │   → avocado-path-config
   │
   ├─ "加组件/antd.yaml/识别不到/leaf/variant/写插件"？
   │   → avocado-component-adapter
   │
   ├─ "对比/还原度/差异 DOM/网页和设计稿"？
   │   → avocado-visual-diff
   │
   ├─ "组件库组件怎么用 / Props / demo / 项目里用了哪些组件"？
   │   → 直接查组件库官方文档；avocado 只负责 Figma → 代码映射
   │
   └─ 都不像？
       → 看下方"常见组合场景"，或者直接 `avocado schema` 自省 CLI 能力
```

## 常见组合场景（跨 skill 工作流）

### 场景 A：从零生成代码
1. **avocado-d2c** → 生成 JSX（`avocado <url> -o out.jsx`）

### 场景 B：加新组件到 组件库预设
1. **avocado-component-adapter** → 编辑 antd.yaml + 加 extractor / 写插件
2. **avocado-d2c** → 单页生成验证

### 场景 C：生成 → 对比 → 修复闭环（视觉还原）
1. **avocado-d2c** → 生成 JSX（建议 `--figma-id` 便于归因回 Figma 节点）
2. **avocado-visual-diff** → 起本地服务，设计稿 PNG vs 页面 URL 对比，读 `summary` 定位差异 DOM
3. 修复 → 重跑 **avocado-visual-diff** 验证到 `match: true`

### 场景 C：用户 pip install 后跑不起来
1. **avocado-path-config** → 检查 4 层查找
2. 若路径正常但仍报错 → 看 envelope error code（详见 `avocado schema`）

### 场景 D：查 组件库 Props / 示例
用户问"组件库 Button 有哪些 Props" / "LabeledInput 怎么用" / "项目里用了哪些 组件库组件" → **不要用 avocado skill**：avocado 只做 Figma → 代码转换，不提供组件库文档。直接查阅组件库官方文档 / 源码。

### 场景 E：生成 → 对比 → 修复闭环（视觉还原）
1. **avocado-d2c** → 生成 JSX（建议 `--figma-id` 便于归因回 Figma 节点）
2. **avocado-visual-diff** → 起本地服务，设计稿 PNG vs 页面 URL 对比，读 `summary` 定位差异 DOM
3. 修复 → 重跑 **avocado-visual-diff** 验证到 `match: true`

## 共同约束（所有子 skill 都遵守）

### envelope 契约
所有 avocado CLI 命令的 stdout 都是 JSON envelope：
```json
{"ok": true, "data": {...}} / {"ok": false, "error": {"code", "message", "hint"}}
```
退出码：0=ok / 1=业务错误 / 2=参数错误。

### 输出确定性
d2c 输出必须确定性（同输入同输出）。改任何"迭代后决定 style 插入顺序"的集合用 tuple 不用 frozenset。

### pipeline pass 实际顺序
```
── 5 个可选 style/structure pass ──
1. auto_group_variance → 2. inherit_promote → 3. strip_default_styles
→ 4. unwrap_single_child → 5. gap_to_margin
── always-on ──
6. semantic_tags
── 输出形态 ──
7. tailwind → 8. css_class → 9. reround
```
顺序不可乱（详见项目根 `CLAUDE.md`）。

### 路径解耦
所有资源路径走 `avocado.paths.resolve_*()` 4 层查找。不要硬编码 `Path(__file__).parents[N]`。

## 还是不确定？自省 CLI

如果用户的请求连总控都判断不了，让 agent 跑一次 schema 自省：

```bash
avocado schema
```

stdout 是 JSON envelope，含所有命令清单 + flags + error code 字典。这是 avocado CLI 能力的**单一真相源**（实现 in `avocado/commands/schema.py:_SPEC`）。

## 真相源

- 项目根 `CLAUDE.md` — 设计决策全貌
- `avocado schema` 命令 — 自省 CLI 能力（envelope 格式 + error code 字典）
- `docs/agent-integration.md` — agent 调用 avocado 标准流程
