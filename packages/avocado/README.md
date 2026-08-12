# avocado 🥑

*Figma Design-to-Code 工具 —— 一条命令把 Figma 节点转成 React JSX / HTML + CSS。*

[![PyPI version](https://img.shields.io/pypi/v/avocado-d2c.svg?style=flat-square)](https://pypi.org/project/avocado-d2c/)
[![License](https://img.shields.io/badge/license-GPLv3-blue.svg?style=flat-square)](../../LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg?style=flat-square)](pyproject.toml)

`avocado` 是一个纯 Python 实现的 Figma D2C（Design-to-Code）包：输入 Figma 节点 URL，输出可直接交付的 React JSX 或 HTML + CSS。既给前端开发者日常出码，也给 AI agent 程序化调用。

```bash
# 30 秒上手
pip install avocado-d2c
avocado init --token figd_xxxxx
avocado "https://www.figma.com/design/XXXX/Login?node-id=10:20" -o out.jsx
```

## 特性

- **一键出码**：Figma URL → React JSX 或 HTML，支持 Tailwind / inline style / 独立 CSS 文件三种形态
- **业务组件识别**：加载组件库预设（内置 antd 示例），把 Figma INSTANCE 节点替换成真实业务组件（Button / Input / Select…），也可以接入自己的组件库
- **离线加速**：把 Figma 数据镜像到本地缓存，之后零网络重跑，单页 47s → 0.19s（约 250× 加速）
- **Agent 原生**：stdout 默认输出 JSON envelope，错误码带 actionable hint，支持 `schema` 自省命令，AI agent 可稳定程序化消费
- **CSS 变量替换**：把 Figma Variable binding 转成 `var(--name, fallback)`，下游主题系统可直接接管
- **后处理优化**：继承上提、去默认值、折叠单子节点、语义标签等一组固定顺序的优化 pass，输出干净可控

## 安装

```bash
pip install avocado-d2c        # 需要 Python >= 3.11
```

开发模式（在包目录下可编辑安装 + 测试依赖）：

```bash
pip install -e ".[dev]"
```

## 快速开始

### 1. 配置 token

```bash
avocado init --token figd_xxxxx
# 或使用环境变量：export FIGMA_TOKEN="figd_xxxxx"
```

token 在 figma.com → Settings → Personal access tokens 生成。查找顺序：`--token` flag > `FIGMA_TOKEN` 环境变量 > `cwd/.avocado/config.yaml` > `~/.avocado/config.yaml`。

### 2. 生成代码

```bash
avocado "https://www.figma.com/design/XXXX/Login?node-id=10:20" -o out.jsx
```

URL 必须包含 `?node-id=...`（在 Figma 里右键节点 → Copy link 复制完整链接）。也可用 `python -m avocado <url>`。

## 命令

| 命令 | 用途 |
|---|---|
| `avocado <figma-url>` | 核心：Figma URL → JSX / HTML |
| `avocado init` | 配置 figma_token（交互式或 `--token` 非交互式） |
| `avocado schema` | 输出全部命令 / flag / 错误码 JSON 清单（agent 自省用） |
| `avocado paths` | 打印资源路径 + 4 层查找顺序 |
| `avocado --version` | 打印版本号 |

## 特性演示

### 业务组件识别

```bash
avocado "<figma-url>" --component-lib antd -o Card.jsx
# Figma INSTANCE → <Button> / <Input> / <Select>，未识别的实例会在 envelope 中列出
```

自建组件库：首次运行 `avocado init` 会在 `~/.avocado/presets/` 生成带教学注释的 `antd.yaml.example` 模板，编辑一份 YAML 映射即可接入自家组件。

### 离线加速

```bash
# 第一次：在线出码，同时把 Figma 数据镜像到本地缓存
avocado "<figma-url>" --cache-dir ~/.avocado/output/figma_cache -o out.jsx

# 之后：完全离线，零网络，秒级返回
avocado "<figma-url>" --cache-dir ~/.avocado/output/figma_cache --offline -o out.jsx
```

缓存按 file_key + node_id 分键，多个设计稿可共用一个缓存目录，换输出模式（react/html、tailwind/inline/class）无需重新拉取。

### Agent 集成

stdout 永远是单一 JSON envelope（不混入日志），退出码 `0` 成功 / `1` 业务错误 / `2` 参数错误 / `130` 中断：

```json
{
  "ok": true,
  "data": {
    "jsx": "import React from \"react\";\n...",
    "output_type": "react",
    "code_location": "/abs/path/out.jsx",
    "recognition": { "instances": 25, "recognized": 20, "rate_percent": "80.00%" },
    "timing": { "duration_seconds": 0.15 }
  }
}
```

失败时返回 error code + hint，如 `figma_rate_limited`（退避重试）、`invalid_argument`（改参数，不要重试）、`figma_auth_failed`（让用户重新生成 token）。先跑 `avocado schema` 可自省全部命令 / flag / 错误码，`avocado paths` 查看资源路径。

## 输出模式

| 组合 | 形态 | 场景 |
|---|---|---|
| **react + tailwind**（默认） | `<div className="flex p-4" style={{"opacity":0.5}}>` | 生产交付 |
| **react + inline** | `<div style={{"display":"flex","padding":"16px"}}>` | 像素级还原 |
| **react + class** | `<div className="frame-2">` + `.css` | 中后台可控样式表 |
| **html + tailwind** | `<div class="flex p-4">` | 静态落地页 |
| **html + inline** | `<div style="display:flex;padding:16px">` | 邮件 / iframe / 预览 |
| **html + class** | `<div class="frame-2">` + `.css` | 传统网页 |

## 包结构

```
src/avocado/
├── cli.py              # 入口：avocado <url> 主命令 + schema/init/paths 子命令
├── envelope.py         # agent-native 输出层：stdout 统一 JSON envelope
├── api/                # Figma REST 客户端 + 缓存、tree-sitter JSX 美化器
├── parser/             # Figma JSON → 中间表示 + 组件识别 + 优化 pass
├── generator/          # JSX / HTML / CSS / Tailwind 输出
├── model/              # SceneNode / TreeNode 两棵内部树
└── _bundled/           # 内置资源：presets/antd.yaml 等
```

## 文档

- [5 分钟快速上手](../../docs/quickstart.md) — 最短路径跑通
- [用户手册](../../docs/user-guide.md) — 完整命令 / flag / 典型场景 / FAQ
- [Agent 集成指南](../../docs/agent-integration.md) — AI agent 程序化调用标准流程
- [Preset 开发指南](../../docs/preset-guide.md) — 组件库映射 YAML 字段说明

## License

[GPL-3.0](../../LICENSE)，见 [LICENSE](../../LICENSE)。
