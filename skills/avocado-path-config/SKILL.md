---
name: avocado-path-config
description: Use when an agent needs to find, customize, or override avocado's resource paths (presets, var-maps, output dir, user config) — covers the 4-layer lookup (CLI flag > cwd/.avocado/ > ~/.avocado/ > bundled), the ~/.avocado/ user directory layout, ensure_user_dirs() first-run behavior, editable install vs wheel bundle differences, and the hard rule against hardcoding Path(__file__).parents[N]. Triggers on "改配置", "preset 改", "var-map", "找不到资源", "wheel 打包", "~/.avocado", "路径错", "哪里放", and when adding new resource types or debugging "file not found" for bundled assets. Does NOT cover running d2c (avocado-d2c) or editing antd.yaml/plugin content (avocado-component-adapter).
---

# avocado-path-config

avocado 用户配置体系 + 路径解耦手册。avocado 可在任意 cwd 独立运行（不依赖 monorepo），所有用户态资源走 `~/.avocado/`。

## 何时触发

- 用户问"preset 放哪"、"var-map 怎么配"、"输出目录能改吗"
- agent 看到 "file not found" for `presets/antd.yaml` / `var-maps/antd.yaml`
- 用户想自定义组件库预设 / CSS 变量映射
- agent 改代码涉及资源路径（不要硬编码 `Path(__file__).parents[N]`）
- 打包 wheel 时验证资源完整

**不触发**：
- 改 antd.yaml 内容（加组件映射）/ 写插件 → `avocado-component-adapter`

## 新用户环境检查清单（首次配置）

> **新手先看**：[`docs/quickstart.md`](../../docs/quickstart.md)（5 分钟快速上手）。本段是路径/配置诊断。

用户第一次用 avocado 时，按这个清单验证就绪状态：

```bash
# 1. avocado CLI 可用
avocado --version                                    # 应输出版本号 JSON

# 2. FIGMA_TOKEN（4 层查找：CLI > env > cwd/.avocado/config.yaml > ~/.avocado/config.yaml）
cat ~/.avocado/config.yaml 2>/dev/null | grep token  # 或 echo $FIGMA_TOKEN

# 3. ~/.avocado/ 目录结构（首次运行自动创建）
ls ~/.avocado/                                       # 应有 output/presets/var-maps/plugins/ + presets/antd.yaml.example
```

**常见配置问题**：
- 美化失败 warning → 降级 raw 输出（envelope warnings 数组）；调试用 `--no-beautify`
- `figma_not_found` + offline 模式 → 缓存 miss，需先在线跑一次
- token 4 层都没找到 → 写 `~/.avocado/config.yaml` 的 `figma_token: figd_xxxx`

## 4 层查找单一真相源

`avocado.paths` 是所有 `resolve_*()` 函数的真相源。优先级（首次命中即用）：

```
CLI flag > cwd/.avocado/<resource>/ > ~/.avocado/<resource>/ > 包内 _bundled/<resource>/
```

### 不同资源的查找层数（不对称，agent 注意）

| 资源类型 | CLI flag | 项目级 | 用户级 | 包内 bundle | 总层数 |
|---|---|---|---|---|---|
| preset | `--components <path>` | `cwd/.avocado/presets/<name>.yaml` | `~/.avocado/presets/<name>.yaml` | `_bundled/presets/<name>.yaml` | **4 层** |
| var-map | `--var-map <path>` | `cwd/.avocado/var-maps/<name>.yaml` | `~/.avocado/var-maps/<name>.yaml` | `_bundled/var-maps/<name>.yaml` | **4 层** |
| output_dir | `--output-dir <path>` | `cwd/.avocado/output/` | `~/.avocado/output/`（默认） | — | **3 层** |
| **figma token** | `--token <str>` | `cwd/.avocado/config.yaml` 的 `figma_token` | `~/.avocado/config.yaml` 的 `figma_token` | — | **3 层 + 1 env** |
| **user config** | — | `cwd/.avocado/config.yaml` | `~/.avocado/config.yaml` | — | **2 层** |

## Token 与全局配置（paths.py 隐藏的 3 个函数）

除了 `resolve_*` 函数，paths.py 还有 **3 个 token/config 相关函数**：

### `resolve_token(cli_token)` — Figma token 4 层查找（含项目级 config）
```python
from avocado.paths import resolve_token
token = resolve_token(cli_token)  # 返回 str 或 None
```

查找顺序（**首次命中即用**）：
1. `cli_token`（CLI `--token` flag）
2. `FIGMA_TOKEN` 环境变量
3. `cwd/.avocado/config.yaml` 的 `figma_token` 字段（**项目级**，通过 `load_user_config()` 实现，项目级优先）
4. `~/.avocado/config.yaml` 的 `figma_token` 字段（用户级）

**注意**：代码里 `resolve_token` 直接调 `load_user_config()`，后者内部已实现项目级 > 用户级优先。**token 实际是 4 层查找**（CLI / env / 项目级 config / 用户级 config），不是 3 层。
**agent debug**："figma_token 读不到" 时，先检查 yaml 语法（YAML 错也返回 `{}`，静默不报错）。

### `avocado path` 命令 envelope 字段

```bash
avocado paths
```

```json
{
  "ok": true,
  "data": {
    "user_root": "~/.avocado",
    "output_dir": "/abs/path/output",
    "preset": "/abs/path/antd.yaml",
    "var_map": "/abs/path/antd.yaml",
    "user_config": "/abs/path/config.yaml",
    "lookup_order": [
      "CLI flag (--components, --var-map, --output-dir)",
      "cwd/.avocado/<resource>/ (project-level)",
      "~/.avocado/<resource>/ (user-level)",
      "package _bundled/<resource>/ (wheel bundle)"
    ],
    "output_artifacts": {
      "figma_cache": ".../figma_cache",
      "figma_json": ".../figma_json",
      "figma_orig": ".../figma_orig",
      "jsx": ".../jsx"
    },
    "_note": "editable install: preset/var_map 指向源码目录是正常的",
    "offline_cache_hint": "离线复跑传 --cache-dir <output_dir>/figma_cache（含 nodes/ 和 render/ 子目录）"
  }
}
```

### `resolve_user_config()` — 全局配置文件路径
```python
path = resolve_user_config()  # ~/.avocado/config.yaml 或 cwd/.avocado/config.yaml
```

### `load_user_config()` — 读 config.yaml 返回 dict
```python
cfg = load_user_config()  # dict，文件不存在或 YAML 解析失败返回 {}
```

**容错**：YAML 语法错也返回 `{}`（静默不报错）。agent debug "figma_token 读不到" 时，先检查 yaml 语法。

### config.yaml 示例
```yaml
# ~/.avocado/config.yaml
figma_token: figd_xxxxxxxxxxxxxxxxxxxx
```

## ~/.avocado/ 目录布局

首次运行 `avocado.paths.ensure_user_dirs()` 幂等创建：

```
~/.avocado/
├── output/           # 默认输出根目录
│   ├── figma_cache/  # Figma 节点 JSON + 图片
│   └── jsx/          # 生成的 JSX
├── presets/          # 用户自定义组件库预设
├── var-maps/         # 用户自定义 VariableID → CSS var 映射
└── plugins/          # 用户插件（avocado.plugins.base.default_plugin_dirs() 扫这里）
```

**plugins/ 说明**：avocado 插件系统（`@hook` 装饰器）扫 `./plugins`（项目 cwd）和 `~/.avocado/plugins`。放 `.py` 文件，实现 `modify_json_schema` / `modify_style` 钩子。

## 包内 _bundled/ 资源（wheel 安装即可用）

`packages/avocado/src/avocado/_bundled/` 包含：

```
_bundled/
├── presets/
│   └── antd.yaml        # antd 组件映射
└── var-maps/
    └── antd.yaml        # VariableID → 语义名
```

`pyproject.toml` 已配：
```toml
[tool.setuptools.package-data]
avocado = ["_bundled/**/*"]
```

读取方式（**必须用 importlib.resources，不要 Path(__file__)**）：
```python
from importlib.resources import files
bundled_path = files("avocado._bundled") / "presets" / "antd.yaml"
```

## 关键设计决策

### 1. editable install vs wheel
- `pip install -e packages/avocado` → 直接读源码 `_bundled/` 目录（开发场景，无需 build 同步）
- `pip install avocado-d2c`（wheel）→ wheel 含 `_bundled/`，importlib.resources 读取
- 两种方式行为一致

### 2. 项目级（cwd/.avocado/）覆盖用户级
用于研发场景：monorepo 内多包开发时，让某个子目录覆盖用户级默认。
例：`packages/avocado/.avocado/presets/antd.yaml` 用于测试新 preset，不影响 `~/.avocado/presets/antd.yaml`。

### 3. OUTPUT_DIR 单一来源
**所有产物**（figma_cache/figma_json/figma_orig/jsx 等）走 `avocado.paths.resolve_output_dir()`。

**不要用旁路目录**：缓存/产物分散歧义。

### 4. ensure_user_dirs 创建时机
`ensure_user_dirs()` **mkdir 4 个目录**：`output/` / `presets/` / `var-maps/` / `plugins/`，并复制 bundled 中立示例到 `~/.avocado/presets/antd.yaml.example`（带教学注释头；已存在则跳过，复制失败静默忽略）。幂等，已存在不报错。

### 5. resolve_preset/var_map 返回的 bundled 路径要包 `Path(str(...))`
```python
# paths.py 实际代码
bundled = files("avocado._bundled") / "presets" / fname
return Path(str(bundled))   # ← 必须 Path(str(...)) 包裹
```
**理由**：`importlib.resources.files()` 返回 `Traversable` 对象，open 能用但传给 subprocess 会挂。包 `Path(str(...))` 才能拿到真实路径字符串。

### 6. 项目级路径基于 `Path.cwd()`（不是 git 根）
`_project_avocado_root()` 用 `Path.cwd()` 完全基于当前工作目录。
**踩坑**：在 `packages/avocado/` 跑和根目录跑会得到不同 preset 来源。换 cwd = 换项目级。

## 强制约束（改路径相关代码务必遵守）

### 不要硬编码 `Path(__file__).parents[N]`
**理由**：层级数会随目录重构变化。
```python
# 不要这样
preset_path = Path(__file__).resolve().parents[3] / "presets" / "antd.yaml"

# 走 paths.py
from avocado.paths import resolve_preset
preset_path = resolve_preset("antd")
```

### importlib.resources 读包内资源
```python
from importlib.resources import files
bundled_path = files("avocado._bundled") / "presets" / "antd.yaml"
return Path(str(bundled_path))
```

**理由**：wheel 安装后包内路径在 site-packages，但 importlib.resources 抽象掉具体路径。

## 常见 agent 任务

### 任务 1：用户想加自定义 preset
```bash
# 1. 复制默认 preset 到用户目录
cp ~/.avocado/presets/antd.yaml ~/.avocado/presets/mycompany.yaml

# 2. 编辑（参见 avocado-component-adapter skill）
$EDITOR ~/.avocado/presets/mycompany.yaml

# 3. 用
avocado URL --component-lib mycompany -o out.jsx
```

### 任务 2：项目级 preset 覆盖（研发）
```bash
mkdir -p .avocado/presets
cp ~/.avocado/presets/antd.yaml .avocado/presets/antd.yaml
# 改 .avocado/presets/antd.yaml 试新组件
avocado URL --component-lib antd -o out.jsx  # 自动读项目级
```

### 任务 3：改默认 output 目录
```bash
avocado URL -o out.jsx                                    # ~/.avocado/output/
avocado URL --output-dir /tmp/myout -o out.jsx            # /tmp/myout/
cd /myproject && avocado URL -o out.jsx                   # 若 /myproject/.avocado/output/ 存在则用它
```

### 任务 4：debug "file not found"
1. `avocado schema` 看 envelope 版本
2. 检查 4 层查找的每一层路径是否存在
3. wheel 安装：`python -c "from importlib.resources import files; print(files('avocado._bundled') / 'presets' / 'antd.yaml')"`
4. editable 安装：`ls packages/avocado/src/avocado/_bundled/presets/`

### 任务 5：验证 wheel 资源完整
```bash
pip install build && python -m build --wheel packages/avocado
unzip -l dist/avocado_d2c-*.whl | grep _bundled
# 应看到 _bundled/presets/antd.yaml 与 _bundled/var-maps/antd.yaml
```

## 相关 skill

- [avocado-d2c](../avocado-d2c/SKILL.md) — 用 preset / var-map 的主流程
- [avocado-component-adapter](../avocado-component-adapter/SKILL.md) — antd.yaml 内容编辑 / 写插件

## 真相源

- 实现入口：`packages/avocado/src/avocado/paths.py`
- 包内资源：`packages/avocado/src/avocado/_bundled/`
- pyproject package-data：`packages/avocado/pyproject.toml:[tool.setuptools.package-data]`
