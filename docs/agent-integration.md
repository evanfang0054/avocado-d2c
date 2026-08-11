# Agent Integration Guide

> AI agent 调用 avocado CLI 的标准流程。
> 相关契约：stdout JSON envelope（格式与 error code 字典以 `avocado schema` 为准）。

## 1. 标准调用流程

```
agent task
    │
    ▼
1. avocado schema                   # 自省：发现所有命令/flags/error codes
    │
    ▼
2. avocado <url>                    # 生成 JSX（默认 agent-native JSON envelope）
    │       ↳ ok=true? → 继续
    │       ↳ ok=false? → 看 error.code → 修参数/token 后重试
    ▼
3. (agent 决策)                    # 基于 envelope.data 决定下一步
```

## 2. 阶段 1：自省（schema）

```bash
avocado schema
```

输出 JSON envelope，agent 解析后获得：
- 所有命令清单（含 args/flags）
- 所有 error code 字典（含 hint）
- 版本号

agent 应**首先调用 schema** 来发现可用能力（不要硬编码命令名/flags）。

```python
import subprocess, json

r = subprocess.run(["avocado", "schema"], capture_output=True, text=True)
spec = json.loads(r.stdout)["data"]
supported_commands = {c["name"] for c in spec["commands"]}
error_codes = spec["error_codes"]  # snake_case only (camelCase aliases removed)
```

## 3. 阶段 2：生成 JSX（gen）

```bash
avocado <figma-url> --no-beautify -o out.jsx
```

### 关键 flags

| Flag | 默认 | 用途 |
|---|---|---|
| `-o, --output PATH` | stdout | 写到文件（envelope.data.artifacts.jsxPath） |
| `--token TEXT` | env FIGMA_TOKEN | Figma Personal Access Token |
| `--cache-dir PATH` | None | 镜像 Figma 数据到本地（加速重跑） |
| `--offline` | False | 只读 cache，零网络（需先在线跑一次） |
| `--component-lib TEXT` | None | 组件库预设（如 `antd`） |
| `--css {inline,tailwind,class}` | tailwind | CSS 形态 |
| `--format {react,html}` | react | 输出结构 |
| `--layout {flex,absolute}` | flex | 布局策略 |
| `--no-beautify` | False | 跳过 JSX 美化（调试用，更快） |
| `--human` | False | 切换人类模式（彩色 stderr，stdout JSX） |

### 成功响应

```python
envelope = json.loads(r.stdout)
assert envelope["ok"] is True
data = envelope["data"]
jsx = data["jsx"]            # JSX 文本（即使 -o 写文件也会回传）
inspect_warnings = data["inspect"]  # list[dict]
```

### 常见错误及处理

| Error code | 含义 | 修复 |
|---|---|---|
| `invalid_argument` | URL 不合法 / 互斥冲突 | 检查 URL 格式 `?node-id=...`、`--components` vs `--component-lib` |
| `figma_not_found` | token 缺失/无效 | 设 `FIGMA_TOKEN` 环境变量或 `--token` |

```python
if not envelope["ok"]:
    code = envelope["error"]["code"]
    if code == "invalid_argument":
        # 让用户修参数
        pass
    elif code == "figma_not_found":
        # 提示 token
        pass
```

## 4. Agent 决策模式

### 模式 A：错误重试

```python
def gen_with_retry(url, max_retries=3):
    for i in range(max_retries):
        r = subprocess.run(["avocado", url, "--no-beautify"], capture_output=True, text=True)
        env = json.loads(r.stdout)
        if env["ok"]:
            return env["data"]["jsx"]
        code = env["error"]["code"]
        if code == "figma_rate_limited":
            time.sleep(2 ** i)
            continue
        if code == "invalid_argument":
            raise ValueError(env["error"]["message"])
        # 其他错误：直接抛
        raise RuntimeError(f"{code}: {env['error']['message']}")
```

## 5. 退出码约定

| Exit Code | 含义 |
|---|---|
| 0 | 成功（`ok: true`） |
| 1 | 业务错误（`ok: false`，error code 在 ERROR_CODES 字典里） |
| 2 | 参数错误（`invalid_argument`，argparse/click 解析层） |
| 127 | 命令未找到（shell 层，avocado 未装） |

agent 应**同时检查 returncode 和 envelope.ok**：
- returncode=0 → envelope.ok=True（一定）
- returncode!=0 → envelope.ok=False（一定）
- envelope 是 stdout 解析的 JSON，是真相源；returncode 用于 shell 流程控制

## 6. 常见陷阱

1. **`avocado <url>` 默认 envelope 模式**：不要解析 stdout 文本找 JSX 字符串——它在 `envelope.data.jsx`。
2. **`--human` 切换不自动**：isatty 检测会破坏 agent 可重现性，必须显式 flag。
3. **`-o` 不影响 envelope**：即使 `-o` 写文件，envelope 仍然回传 jsx 文本（agent 检查用）。
4. **offline 模式需要预热**：第一次必须在线跑 `--cache-dir`，否则 `--offline` 会 `figma_cache_miss`。
5. **stderr 不是契约**：envelope 在 stdout；stderr 只用于诊断（彩色警告、inspect 信息），agent 不应解析 stderr。

## 7. 参考

- Envelope 契约：`avocado schema`（实现 in `packages/avocado/src/avocado/envelope.py`）
- 实现源码：`packages/avocado/src/avocado/{envelope.py, cli.py, commands/}`
- 测试：`packages/avocado/tests/test_{envelope,cli_envelope}.py`
