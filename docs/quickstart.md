# avocado 快速上手（5 分钟）

## 1. 配置 figma token

```bash
# 交互式（推荐新用户）
avocado init

# 非交互式（agent 友好）
avocado init --token figd_xxxxx

# 环境变量
export FIGMA_TOKEN="figd_xxxxx"
```

token 获取：figma.com → Settings → Personal access tokens → Generate

token 4 层查找：CLI `--token` > env `FIGMA_TOKEN` > `cwd/.avocado/config.yaml` > `~/.avocado/config.yaml`

## 2. 生成 JSX

```bash
# 默认 React + Tailwind
avocado "https://www.figma.com/design/XXXX/Title?node-id=10:20" -o out.jsx

# 加组件库预设（提升 INSTANCE 识别率；内置 antd 示例）
avocado "<url>" --component-lib antd -o out.jsx

# HTML + inline style
avocado "<url>" --format html --css inline -o out.html
```

URL 必须含 `?node-id=...`（从 Figma 右键 'Copy link' 复制完整 URL）。

## 3. 常用 flag

| 场景 | flag |
|---|---|
| 离线加速 | `--cache-dir ~/.avocado/output/figma_cache --offline` |
| 组件库预设 | `--component-lib antd` |
| 瘦身 envelope | `--summary`（省 jsx/css 文本，配 `-o` 落盘） |
| 验证参数 | `--dry-run`（不调 API、不写文件） |
| 绝对定位 | `--layout absolute` |
| CSS class 抽取 | `--css class`（同时输出 .css） |

## 下一步

- 完整命令/flag/error code：`avocado schema`
- 资源路径：`avocado paths`
