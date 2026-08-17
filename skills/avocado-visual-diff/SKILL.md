---
name: avocado-visual-diff
description: Use when an agent needs to compare a generated or live webpage against a design image (PNG) and locate WHICH DOM regions differ — visual regression verification, design fidelity checking, "对比网页和设计稿", "网页跟原图对比", "看看生成的页面哪里和设计稿不一样", "还原度检查", "diff 出差异区域", fixing a generated page by diffing it against the reference design, or iterating a "generate → compare → fix" loop. Covers running the bundled Playwright + odiff pipeline (`scripts/compare.mjs`), reading the JSON report (regions + DOM candidate selectors + data-figma-id), and using the report to repair code. Does NOT cover generating code from Figma (avocado-d2c) or adapting component presets (avocado-component-adapter).
---

# avocado-visual-diff

把「网页」和「原图/设计稿 PNG」做像素级对比，并把差异归因到 **DOM 区域**（给出 CSS selector、文本、data-figma-id），输出结构化报告。AI 依据报告修复生成代码，然后重跑对比验证——形成 **生成 → 对比 → 修复** 闭环。

对应脚本：`scripts/compare.mjs`（Playwright 截图 + odiff 像素对比 + 连通域聚类 + DOM 归因）。

## 何时触发

- 用户要「对比网页和设计稿/原图」「看还原度」「哪里不一样」「diff 差异」
- 用户给了设计稿 PNG + 网页链接（或本地文件），要求定位差异 DOM
- 修复闭环：先生成/改了代码，要验证效果再迭代

**不触发**（路由到对应 skill）：
- Figma URL → JSX 生成 → `avocado-d2c`
- 改 preset / 组件映射 → `avocado-component-adapter`

## 前置条件（首次使用）

```bash
cd skills/avocado-visual-diff/scripts
npm install            # playwright + odiff-bin + pngjs
npx playwright install chromium   # 首次下载浏览器（~130MB，一次性）
```

脚本依赖 Node.js ≥ 18。

## 标准调用流程

### Step 1：准备两个输入

1. **设计稿 PNG**：设计稿节点导出图（Figma 导出 PNG @1x；尺寸建议与截图视口一致，不一致时报告 `reason: "layout-diff"`）
2. **网页 URL**：用户提供的链接；本地生成的 HTML 先起静态服务再给 URL：

```bash
cd <生成目录> && python3 -m http.server 8000   # 或 npx serve
# url = http://localhost:8000/index.html
```

### Step 2：跑对比脚本

```bash
node scripts/compare.mjs <design.png> <url> [options]
```

常用组合：

```bash
# 默认：1280x800 视口截图
node scripts/compare.mjs design.png http://localhost:8000/ --out-dir /tmp/vdiff

# 全页对比 + 等待动态内容渲染
node scripts/compare.mjs design.png https://example.com --full-page --wait-for '.app-loaded' --out-dir /tmp/vdiff

# 严格阈值 + 忽略广告/动态区域（设计稿像素坐标）
node scripts/compare.mjs design.png http://localhost:8000/ --threshold 0.02 \
  --ignore-regions "0,0,300,80;900,0,1280,80" --out-dir /tmp/vdiff
```

**stdout 永远是单一 JSON envelope**（对齐 avocado 契约），人类信息走 stderr。

### Step 3：解析报告（字段全集）

```json
{
  "ok": true,
  "data": {
    "url": "http://localhost:8000/",
    "design": "/abs/design.png",
    "viewport": {"width": 1280, "height": 800},
    "fullPage": false,
    "dpr": 1,
    "match": false,
    "reason": "pixel-diff",
    "diffCount": 1090946,
    "diffPercentage": 2.95,
    "summary": [
      {
        "selector": "#pro-card",
        "tag": "div",
        "text": "Pro ¥399 无限项目…",
        "figmaId": "123:456",
        "regionIndexes": [0],
        "totalPixels": 69732,
        "maxOverlapRatio": 1
      }
    ],
    "regions": [
      {
        "index": 0,
        "pixelBbox": {"x1": 100, "y1": 200, "x2": 400, "y2": 260},
        "cssRect": {"x": 100, "y": 200, "width": 300, "height": 60},
        "pixelArea": 8000,
        "candidates": [
          {
            "selector": "div#pricing > div.card:nth-of-type(2) > h3",
            "tag": "h3",
            "depth": 5,
            "text": "Pro 套餐 ¥299/月",
            "role": null,
            "figmaId": "123:456",
            "rect": {"x": 100, "y": 200, "width": 300, "height": 60},
            "overlapRatio": 0.92
          }
        ]
      }
    ],
    "warnings": [],
    "artifacts": {
      "screenshot": "/tmp/vdiff/current.png",
      "diff": "/tmp/vdiff/diff.png",
      "overlay": "/tmp/vdiff/regions-overlay.png",
      "report": "/tmp/vdiff/report.json"
    }
  }
}
```

**报告语义**：
- `match: true` → 像素级一致（注意：不是视觉一致，字体渲染/AA 差异可能被豁免；此时 `artifacts.diff` 为 null——odiff 只在有差异时产出 diff 图）
- `reason: "layout-diff"` → 两张图尺寸/布局不同：检查设计稿导出分辨率与截图视口/dpr 是否匹配
- **`summary` 优先看**：按责任元素聚合（同一元素多个碎片区域合并），`regionIndexes` 关联到 regions 明细；AI 修复时按 summary 逐个处理
- `regions[].candidates` 按「区域覆盖率 overlapRatio 降序 → depth 降序」排序，**candidates[0] 通常就是责任节点**；同一区域给 5 个候选是因为样式级差异（背景色/字体）可能落在容器而非叶子节点
- `candidates[].figmaId`：生成代码带 `--figma-id` 时存在，直接映射回 Figma 节点 id（见下）
- `artifacts.overlay`：截图 + 差异框叠加图，给用户/多模态模型看最直观

### Step 4：修复闭环（skill 的核心价值）

拿到 regions 后按序处理：

1. **定位代码**：`candidates[0].selector` 在生成代码里搜（avocado 输出有 data-figma-id 时直接搜 figmaId 更快）
2. **对照原图**：看 `artifacts.diff` / `overlay` 确认差异形态（文本？颜色？尺寸？位置？）
3. **修复**：改生成代码对应的样式/结构
4. **重跑验证**：同样的命令再跑一次，直到 `match: true` 或剩余 diff 属于可接受噪声（字体渲染、动效帧）

**多区域处理**：一次修一个 region，重跑确认该 region 消失再修下一个——避免一次改多处引入新差异无法归因。

## 与 avocado-d2c 的衔接

```bash
# 1. 生成（带 data-figma-id 便于归因回 Figma）
avocado "<figma-url>" --figma-id -o out.jsx

# 2. 起本地服务预览
python3 -m http.server 8000

# 3. 导出设计稿节点 PNG @1x 作为原图
# 4. 对比验证
node skills/avocado-visual-diff/scripts/compare.mjs design.png http://localhost:8000/ --out-dir /tmp/vdiff
```

## 常见坑（按频率）

1. **设计稿与截图尺寸不一致** → `reason: "layout-diff"`。设计稿导出 @1x，截图 dpr 默认 1；`--device-scale-factor 2` 时设计稿也要 @2x
2. **浅色差异漏检** → odiff 默认 threshold 0.1 太松（实测会漏掉 #fff vs #eef1ff 这类浅色背景差）；脚本默认已收紧到 **0.05**，仍漏检就继续降到 0.02
3. **动态内容误报**（时间戳/动画/轮播）→ 用 `--wait-for` 等稳定态；`--ignore-regions` 忽略固定噪声区；或脚本里固定测试数据
4. **字体渲染差异** → 同一台机器同一浏览器字体一致；跨机器 CI 用 `--threshold 0.1`（放宽）+ antialiasing 默认开
5. **红色元素误匹配** → 脚本按 diffColor 找差异像素，原图本身有红色元素时可能聚类冲突（warning 提示退回 bbox）；换 `--diff-color '#00ff00'` 即可
6. **networkidle 超时** → 脚本自动退回 domcontentloaded，不影响对比（长轮询页面正常现象，不是错误）
7. **candidates 全是容器**（body/main）→ 差异是布局级（尺寸/位置变化），改布局而不是改叶子样式
8. **单页元素上万** → 快照遍历成本上升但可用；页面过大考虑缩小视口或只测关键区域（`--viewport` + 设计稿对应裁剪）

## 判断差异归属的启发式

- `overlapRatio` 高 + depth 深 + text 短 → 叶子节点，直接改它
- 候选全是祖先链 → 差异可能是该子树整体的尺寸/位置/背景
- `text` 相同的两个候选 → 文本内容变了（对比 `text` 与设计稿标注）
- `figmaId` 存在时优先用——直接从 Figma 拿该节点的设计值（font-size/color/padding）对照

## 真相源

- 脚本：`skills/avocado-visual-diff/scripts/compare.mjs`（依赖 `package.json` 同目录）
- 对比引擎：odiff-bin（官方文档见 https://github.com/dmtrKovalenko/odiff）
- 截图引擎：Playwright（`page.screenshot`，fullPage 拼接坐标 = document 坐标 × dpr）
