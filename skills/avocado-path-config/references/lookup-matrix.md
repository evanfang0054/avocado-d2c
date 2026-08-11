# 4 层查找决策矩阵

> avocado 路径解析的完整决策表。SKILL.md 是速查；本文档解释**为什么这样设计**。

## 4 层查找哲学

avocado 可在任意 cwd 独立运行（不依赖 monorepo）。设计目标：
```
pip install avocado-d2c && avocado <url>
```
开箱即用，无需 clone 本仓库。

### 为什么需要 4 层

| 层 | 用途 | 典型场景 |
|---|---|---|
| **CLI flag** | 一次性覆盖 | 调试 / CI 环境变量 |
| **cwd/.avocado/** | 项目级覆盖 | monorepo 内研发，让某子目录覆盖默认 |
| **~/.avocado/** | 用户级默认 | pip install 后开箱即用 |
| **包内 _bundled/** | 兜底 | wheel 安装时的内置资源 |

### 优先级（首次命中即用）

```
CLI flag > cwd/.avocado/ > ~/.avocado/ > 包内 _bundled/
```

## 资源类型 × 查找路径矩阵

### preset（组件库预设）
```python
from avocado.paths import resolve_preset
path = resolve_preset("antd")  # 自动加 .yaml 后缀
```

| 层 | 路径 |
|---|---|
| CLI | `--components <path>` 显式 |
| 项目级 | `cwd/.avocado/presets/antd.yaml` |
| 用户级 | `~/.avocado/presets/antd.yaml` |
| 包内 | `avocado/_bundled/presets/antd.yaml`（importlib.resources） |

### var-map（CSS 变量映射）
```python
from avocado.paths import resolve_var_map
path = resolve_var_map("antd")
```

| 层 | 路径 |
|---|---|
| CLI | `--var-map <path>` 显式 |
| 项目级 | `cwd/.avocado/var-maps/antd.yaml` |
| 用户级 | `~/.avocado/var-maps/antd.yaml` |
| 包内 | `avocado/_bundled/var-maps/antd.yaml` |

### output_dir（产物根目录）
```python
from avocado.paths import resolve_output_dir
path = resolve_output_dir()
```

| 层 | 路径 |
|---|---|
| CLI | `--output-dir <path>` 显式 |
| 项目级 | `cwd/.avocado/output/`（存在则用） |
| 用户级 | `~/.avocado/output/`（默认） |
| 包内 | — |

**所有产物**（figma_cache/figma_json/figma_orig/jsx 等）落在这一个根目录下。

### user_config（全局配置）
```python
from avocado.paths import resolve_user_config, load_user_config
path = resolve_user_config()      # 配置文件路径
cfg = load_user_config()          # dict，缺失或 YAML 错返回 {}
```

| 层 | 路径 |
|---|---|
| CLI | — |
| 项目级 | `cwd/.avocado/config.yaml` |
| 用户级 | `~/.avocado/config.yaml` |
| 包内 | — |

`config.yaml` 主要承载 `figma_token` 字段；`resolve_token()` 内部复用 `load_user_config()` 实现项目级 > 用户级优先。

## ensure_user_dirs() 首次运行行为

```python
from avocado.paths import ensure_user_dirs
ensure_user_dirs()  # 幂等，已存在不报错
```

首次调用创建：
```
~/.avocado/
├── output/
├── presets/
├── var-maps/
└── plugins/
```

**调用时机**：
- `avocado <url>` 主命令：main() 开头调

## editable install vs wheel bundle

### editable install（开发场景）
```bash
pip install -e packages/avocado
```
- 直接读源码 `_bundled/` 目录
- 不需要 build 同步
- 改 `_bundled/antd.yaml` 立即生效

### wheel install（用户场景）
```bash
pip install avocado-d2c
```
- wheel 含 `_bundled/`（pyproject.toml 已配 package-data）
- `importlib.resources.files("avocado._bundled")` 读取
- 路径可能在 site-packages 内（只读，不要尝试写入）

### 行为一致性
两种方式**行为一致**——4 层查找逻辑不区分安装方式。

## 关键约束（改路径相关代码务必遵守）

### 1. 不要硬编码 `Path(__file__).parents[N]`

**理由**：层级数会随目录重构变化。

```python
# 不要
preset_path = Path(__file__).resolve().parents[4] / "presets" / "antd.yaml"

# 走 paths.py
from avocado.paths import resolve_preset
preset_path = resolve_preset("antd")
```

**历史踩坑**：目录重构时，`Path(__file__).parents[3]` 因为目录变深而失效。

### 2. OUTPUT_DIR 单一来源

所有 pipeline 模块调 `paths.resolve_output_dir()`：

```python
from avocado.paths import resolve_output_dir
output_dir = resolve_output_dir()
```

### 3. 不要用旁路目录

```python
# 不要
extra_dir = output_dir.parent / "extra"  # 历史踩坑：extra/ 与 output/ 分叉
```

所有产物走 `resolve_output_dir()` 单一来源。

### 4. importlib.resources 读包内资源

```python
from importlib.resources import files
bundled_path = files("avocado._bundled") / "presets" / "antd.yaml"
return Path(str(bundled_path))
```

**理由**：wheel 安装后包内路径在 site-packages，但 importlib.resources 抽象掉具体路径。

## 验证 wheel 资源完整

```bash
# 1. 构建 wheel
pip install build
python -m build --wheel packages/avocado

# 2. 检查 _bundled 内容
unzip -l dist/avocado_d2c-*.whl | grep _bundled
# 应看到：
# avocado/_bundled/presets/antd.yaml
# avocado/_bundled/var-maps/antd.yaml

# 3. 安装到隔离环境验证
python -m venv /tmp/test-venv
/tmp/test-venv/bin/pip install dist/avocado_d2c-*.whl
/tmp/test-venv/bin/python -c "
from avocado.paths import resolve_preset
print(resolve_preset('antd'))
"  # 应输出 site-packages 内的路径
```

## pyproject.toml 配置

```toml
[tool.setuptools.package-data]
avocado = ["_bundled/**/*"]
```

**关键**：`_bundled/**/*` glob 让所有子目录资源进 wheel。

## 用户自定义工作流

### 任务 1：加自定义 preset
```bash
# 1. 复制默认 preset
cp ~/.avocado/presets/antd.yaml ~/.avocado/presets/mycompany.yaml

# 2. 编辑
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
# 临时
avocado URL --output-dir /tmp/myout -o out.jsx

# 项目级
mkdir -p .avocado/output
avocado URL -o out.jsx  # 自动用 .avocado/output/

# 用户级（默认行为）
avocado URL -o out.jsx  # 用 ~/.avocado/output/
```

### 任务 4：debug "file not found"
```bash
# 1. 看 envelope 版本
avocado schema | jq '.data.version'

# 2. 检查 4 层查找的每一层
ls ~/.avocado/presets/  # 用户级
ls .avocado/presets/    # 项目级

# 3. wheel 安装：检查包内资源
python -c "from importlib.resources import files; print(files('avocado._bundled') / 'presets' / 'antd.yaml')"

# 4. editable 安装：检查源码目录
ls packages/avocado/src/avocado/_bundled/presets/
```
