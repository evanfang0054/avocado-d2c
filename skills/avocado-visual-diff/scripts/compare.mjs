#!/usr/bin/env node
/**
 * avocado-visual-diff / compare.mjs
 *
 * 网页截图 vs 设计稿 PNG 的像素级对比 + DOM 归因。
 *
 * 用法:
 *   node compare.mjs <design.png> <url> [options]
 *
 * 选项:
 *   --out-dir <dir>            输出目录 (默认 ./visual-diff-out)
 *   --viewport <WxH>           视口尺寸 (默认 1280x800)
 *   --full-page                全页截图 (默认只截视口)
 *   --device-scale-factor <n>  截图 DPR (默认 1; 设计稿按 1x 导出时保持 1)
 *   --threshold <0..1>         odiff 颜色差异阈值 (默认 0.1, 越小越严格)
 *   --no-antialiasing          关闭反锯齿像素豁免 (默认开启)
 *   --diff-color <hex>         差异高亮色 (默认 #ff0000, 与 odiff 保持一致)
 *   --min-region-px <n>        过滤小于 n 像素的差异区域 (默认 8)
 *   --max-regions <n>          最多报告的区域数 (默认 20)
 *   --wait-for <selector>      截图前等待选择器出现
 *   --timeout <ms>             页面加载超时 (默认 30000)
 *   --ignore-regions <s>       忽略区域 "x1,y1,x2,y2;x1,y1,x2,y2" (设计稿像素坐标)
 *   --no-headless              有头模式调试
 *
 * 输出:
 *   stdout 永远是单一 JSON envelope (对齐 avocado 契约):
 *     {"ok":true,"data":{...,"regions":[{...,"candidates":[...]}]}}
 *   人类可读信息走 stderr。退出码 0=对比成功(无论是否 match), 1=错误。
 */
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { compare as odiffCompare } from 'odiff-bin';
import pngjs from 'pngjs';

const { PNG } = pngjs;

/* ------------------------------------------------------------------ */
/* arg parsing                                                        */
/* ------------------------------------------------------------------ */
function parseArgs(argv) {
  const args = { positional: [], outDir: 'visual-diff-out', viewport: [1280, 800],
    fullPage: false, dsf: 1, threshold: 0.05, antialiasing: true,
    diffColor: '#ff0000', minRegionPx: 8, maxRegions: 20,
    waitFor: null, timeout: 30000, ignoreRegions: [], headless: true };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => argv[++i];
    switch (a) {
      case '--out-dir': args.outDir = next(); break;
      case '--viewport': {
        const m = /^(\d+)x(\d+)$/.exec(next());
        if (!m) throw new Error('--viewport 格式应为 WxH，如 1280x800');
        args.viewport = [Number(m[1]), Number(m[2])];
        break;
      }
      case '--full-page': args.fullPage = true; break;
      case '--device-scale-factor': args.dsf = Number(next()); break;
      case '--threshold': args.threshold = Number(next()); break;
      case '--no-antialiasing': args.antialiasing = false; break;
      case '--diff-color': args.diffColor = next(); break;
      case '--min-region-px': args.minRegionPx = Number(next()); break;
      case '--max-regions': args.maxRegions = Number(next()); break;
      case '--wait-for': args.waitFor = next(); break;
      case '--timeout': args.timeout = Number(next()); break;
      case '--ignore-regions': {
        const s = next();
        for (const part of s.split(';')) {
          const m = /^(\d+),(\d+),(\d+),(\d+)$/.exec(part.trim());
          if (!m) throw new Error('--ignore-regions 格式应为 x1,y1,x2,y2;...');
          args.ignoreRegions.push({ x1: +m[1], y1: +m[2], x2: +m[3], y2: +m[4] });
        }
        break;
      }
      case '--no-headless': args.headless = false; break;
      default:
        if (a.startsWith('-')) throw new Error(`未知选项: ${a}`);
        args.positional.push(a);
    }
  }
  if (args.positional.length !== 2) {
    throw new Error('用法: node compare.mjs <design.png> <url> [options]');
  }
  [args.design, args.url] = args.positional;
  return args;
}

/* ------------------------------------------------------------------ */
/* helpers                                                            */
/* ------------------------------------------------------------------ */
function emitError(message, extra = {}) {
  process.stdout.write(JSON.stringify({
    ok: false, error: { code: 'visual_diff_error', hint: message, ...extra },
  }, null, 2) + '\n');
  process.exitCode = 1;
}

function emitOk(data) {
  process.stdout.write(JSON.stringify({ ok: true, data }, null, 2) + '\n');
}

function parseHexColor(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`--diff-color 需为 #rrggbb 格式: ${hex}`);
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/* ------------------------------------------------------------------ */
/* DOM 快照（在页面上下文执行：selector 生成需要真实 DOM）             */
/* ------------------------------------------------------------------ */
const DOM_SNAPSHOT_FN = () => {
  /** 稳定 CSS selector：id → nth-of-type 路径，最多 8 层 */
  const buildSelector = (el) => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 8) {
      const tag = node.tagName.toLowerCase();
      if (node.id) { parts.unshift(`#${CSS.escape(node.id)}`); break; }
      const parent = node.parentElement;
      let nth = 1;
      if (parent) {
        for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) {
          if (sib.tagName === node.tagName) nth++;
        }
        parts.unshift(`${tag}:nth-of-type(${nth})`);
      } else {
        parts.unshift(tag);
      }
      node = parent;
    }
    return parts.join(' > ');
  };

  const dpr = window.devicePixelRatio;
  const scroll = { x: window.scrollX, y: window.scrollY };
  const els = [];
  const walk = (el, depth) => {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) {
      const style = window.getComputedStyle(el);
      if (style.display !== 'none' && style.visibility !== 'hidden') {
        els.push({
          tag: el.tagName.toLowerCase(),
          selector: buildSelector(el),
          depth,
          x: Math.round((r.x + window.scrollX) * 100) / 100,
          y: Math.round((r.y + window.scrollY) * 100) / 100,
          w: Math.round(r.width * 100) / 100,
          h: Math.round(r.height * 100) / 100,
          text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120),
          role: el.getAttribute('role'),
          figmaId: el.getAttribute('data-figma-id'),
        });
      }
    }
    for (const child of el.children) walk(child, depth + 1);
  };
  walk(document.body, 0);
  return {
    dpr, scroll,
    docHeight: document.documentElement.scrollHeight,
    els,
  };
};

/* ------------------------------------------------------------------ */
/* pngjs helpers                                                      */
/* ------------------------------------------------------------------ */
function paintPixel(png, x, y, r, g, b) {
  const i = (png.width * y + x) * 4;
  png.data[i] = r; png.data[i + 1] = g; png.data[i + 2] = b; png.data[i + 3] = 255;
}

/**
 * 在 diff.png 上找 diffColor 像素，先膨胀 2px 桥接文字笔画间隙，
 * 再 8-连通域 BFS 聚类（避免中文/小字号文字被拆成几十个碎片区域）。
 * pixelArea 统计的是膨胀前原始差异像素数（真实差异量）。
 */
function clusterRegions(png, [dr, dg, db], minPx, maxRegions) {
  const { width, height, data } = png;
  const mask = new Uint8Array(width * height);
  for (let i = 0; i < mask.length; i++) {
    const j = i * 4;
    mask[i] = (Math.abs(data[j] - dr) + Math.abs(data[j + 1] - dg) + Math.abs(data[j + 2] - db)) <= 45 ? 1 : 0;
  }
  const dilated = dilate(mask, width, height, 2);

  const visited = new Uint8Array(width * height);
  const regions = [];
  const stack = [];

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x;
      if (visited[idx] || !dilated[idx]) continue;

      // BFS 8-邻域（在膨胀 mask 上）
      let minX = x, maxX = x, minY = y, maxY = y;
      let realCount = 0;
      stack.length = 0;
      stack.push(idx);
      visited[idx] = 1;
      while (stack.length) {
        const cur = stack.pop();
        const cx = cur % width, cy = (cur / width) | 0;
        if (mask[cur]) realCount++; // 原始差异像素计数
        if (cx < minX) minX = cx; if (cx > maxX) maxX = cx;
        if (cy < minY) minY = cy; if (cy > maxY) maxY = cy;
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            if (!dx && !dy) continue;
            const nx = cx + dx, ny = cy + dy;
            if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
            const nidx = ny * width + nx;
            if (visited[nidx] || !dilated[nidx]) continue;
            visited[nidx] = 1;
            stack.push(nidx);
          }
        }
      }
      if (realCount >= minPx) {
        regions.push({ x1: minX, y1: minY, x2: maxX, y2: maxY, pixelArea: realCount });
      }
    }
  }

  regions.sort((a, b) => b.pixelArea - a.pixelArea);
  return regions.slice(0, maxRegions);
}

/** 8-邻域膨胀 radius 圈：桥接文字笔画间隙 */
function dilate(mask, w, h, radius) {
  const out = new Uint8Array(mask.length);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (!mask[y * w + x]) continue;
      const x0 = Math.max(0, x - radius), x1 = Math.min(w - 1, x + radius);
      const y0 = Math.max(0, y - radius), y1 = Math.min(h - 1, y + radius);
      for (let ny = y0; ny <= y1; ny++) {
        out.fill(1, ny * w + x0, ny * w + x1 + 1);
      }
    }
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* main                                                               */
/* ------------------------------------------------------------------ */
async function main() {
  const args = parseArgs(process.argv.slice(2));
  const outDir = path.resolve(args.outDir);
  fs.mkdirSync(outDir, { recursive: true });

  if (!fs.existsSync(args.design)) throw new Error(`设计稿文件不存在: ${args.design}`);

  console.error(`[avocado-visual-diff] 打开 ${args.url} (${args.viewport.join('x')}${args.fullPage ? ', full-page' : ''})`);
  const browser = await chromium.launch({ headless: args.headless });
  try {
    const page = await browser.newPage({
      viewport: { width: args.viewport[0], height: args.viewport[1] },
      deviceScaleFactor: args.dsf,
    });

    const navTimeout = args.timeout;
    await page.goto(args.url, { waitUntil: 'networkidle', timeout: navTimeout })
      .catch(async (e) => {
        // networkidle 超时不一定致命（长轮询页面）；退回 domcontentloaded 继续
        console.error(`[avocado-visual-diff] networkidle 超时，退回 domcontentloaded: ${e.message.split('\n')[0]}`);
        await page.goto(args.url, { waitUntil: 'domcontentloaded', timeout: navTimeout });
      });
    if (args.waitFor) {
      await page.waitForSelector(args.waitFor, { timeout: navTimeout });
    }

    /* ---- 同一时刻：DOM rect 快照 + 截图（快照先行，间隔毫秒级） ---- */
    const domSnapshot = await page.evaluate(DOM_SNAPSHOT_FN);
    const shotPath = path.join(outDir, 'current.png');
    await page.screenshot({ path: shotPath, fullPage: args.fullPage });
    console.error(`[avocado-visual-diff] 截图完成: ${shotPath} (${domSnapshot.els.length} 个可见元素入快照)`);

    /* ---- odiff 像素对比 ---- */
    const diffPath = path.join(outDir, 'diff.png');
    const odiffOptions = {
      threshold: args.threshold,
      antialiasing: args.antialiasing,
      diffColor: args.diffColor,
      captureDiffLines: true,
      captureDiffCols: true,
    };
    if (args.ignoreRegions.length) odiffOptions.ignoreRegions = args.ignoreRegions;

    let result;
    try {
      result = await odiffCompare(args.design, shotPath, diffPath, odiffOptions);
    } catch (e) {
      throw new Error(`odiff 对比失败: ${e.message}`);
    }
    console.error(`[avocado-visual-diff] odiff: match=${result.match} reason=${result.reason}` +
      (result.diffCount != null ? ` diffCount=${result.diffCount}` : ''));

    const warnings = [];
    if (!result.match && result.reason === 'file-not-exists') {
      throw new Error(`文件缺失: ${result.file}`);
    }

    /* ---- diff.png 连通域聚类（精确区域） ---- */
    // 注意：odiff 在 match=true 时不生成 diff.png，只在不匹配时才有差异图可读
    let regions = [];
    let diffPngValid = false;
    if (!result.match) {
      try {
        const diffPng = PNG.sync.read(fs.readFileSync(diffPath));
        regions = clusterRegions(diffPng, parseHexColor(args.diffColor), args.minRegionPx, args.maxRegions);
        diffPngValid = true;
      } catch (e) {
        warnings.push(`diff 图读取失败: ${e.message}`);
      }
    }

    // 兜底：pngjs 匹配不到（颜色冲突/输出异常）→ 用 diffLines/Cols 的整体 bbox
    if (!regions.length && !result.match && diffPngValid && result.diffLines && result.diffLines.length) {
      warnings.push('diff 图上未匹配到高亮色，退回 diffLines/diffCols 整体 bbox（区域精度下降）');
      const ys = result.diffLines, xs = result.diffCols;
      const x1 = Math.min(...xs), y1 = Math.min(...ys), x2 = Math.max(...xs), y2 = Math.max(...ys);
      regions = [{ x1, y1, x2, y2, pixelArea: (x2 - x1 + 1) * (y2 - y1 + 1) }];
    }

    if (!regions.length && !result.match) {
      warnings.push('未能从 diff 输出定位差异区域（可能是布局差异或颜色冲突）');
    }

    /* ---- 坐标换算 + DOM 归因 ---- */
    const { dpr, scroll, els } = domSnapshot;
    const toDocCss = (pxX, pxY) => ({
      x: pxX / dpr + (args.fullPage ? 0 : scroll.x),
      y: pxY / dpr + (args.fullPage ? 0 : scroll.y),
    });

    const attributed = regions.map((r, i) => {
      const topLeft = toDocCss(r.x1, r.y1);
      const bottomRight = toDocCss(r.x2, r.y2);
      const regionRect = {
        x: topLeft.x, y: topLeft.y,
        width: bottomRight.x - topLeft.x, height: bottomRight.y - topLeft.y,
      };
      const regionArea = regionRect.width * regionRect.height || 1;

      const candidates = els
        .map((el) => {
          const ix = Math.max(el.x, regionRect.x);
          const iy = Math.max(el.y, regionRect.y);
          const ex = Math.min(el.x + el.w, regionRect.x + regionRect.width);
          const ey = Math.min(el.y + el.h, regionRect.y + regionRect.height);
          const ow = Math.max(0, ex - ix);
          const oh = Math.max(0, ey - iy);
          const overlap = ow * oh;
          if (overlap <= 0) return null;
          const elArea = el.w * el.h || 1;
          return {
            selector: el.selector,
            tag: el.tag,
            depth: el.depth,
            text: el.text,
            role: el.role,
            figmaId: el.figmaId,
            rect: { x: el.x, y: el.y, width: el.w, height: el.h },
            overlapPx: Math.round(overlap * 100) / 100,
            // 差异区域被该元素覆盖的比例（0~1）
            overlapRatio: Math.round((overlap / regionArea) * 1000) / 1000,
          };
        })
        .filter(Boolean)
        .sort((a, b) =>
          b.overlapRatio - a.overlapRatio ||      // 完全覆盖区域的优先（区域归属）
          b.depth - a.depth ||                    // 同覆盖下叶子优先（越深越具体）
          a.text.length - b.text.length ||        // 文本短 = 更可能是叶子
          (a.rect.width * a.rect.height - b.rect.width * b.rect.height))
        .slice(0, 5);

      return {
        index: i,
        pixelBbox: { x1: r.x1, y1: r.y1, x2: r.x2, y2: r.y2 },
        cssRect: {
          x: Math.round(regionRect.x * 100) / 100,
          y: Math.round(regionRect.y * 100) / 100,
          width: Math.round(regionRect.width * 100) / 100,
          height: Math.round(regionRect.height * 100) / 100,
        },
        pixelArea: r.pixelArea,
        candidates,
      };
    });

    /* ---- 按责任元素聚合（同一 selector 的多个碎片区域合并） ---- */
    const summary = [];
    const byKey = new Map();
    for (const reg of attributed) {
      const c = reg.candidates[0];
      if (!c) continue;
      const key = `${c.tag}#${c.selector}`;
      let g = byKey.get(key);
      if (!g) {
        g = {
          selector: c.selector, tag: c.tag, text: c.text, figmaId: c.figmaId,
          regionIndexes: [], totalPixels: 0, maxOverlapRatio: 0,
        };
        byKey.set(key, g);
        summary.push(g);
      }
      g.regionIndexes.push(reg.index);
      g.totalPixels += reg.pixelArea;
      g.maxOverlapRatio = Math.max(g.maxOverlapRatio, c.overlapRatio);
    }
    summary.sort((a, b) => b.totalPixels - a.totalPixels);

    /* ---- overlay 图：在截图上画差异框 ---- */
    const overlayPath = path.join(outDir, 'regions-overlay.png');
    try {
      const shotPng = PNG.sync.read(fs.readFileSync(shotPath));
      const [cr, cg, cb] = parseHexColor('#ff2d55');
      for (const reg of attributed) {
        const x1 = Math.max(0, reg.pixelBbox.x1 - 2), y1 = Math.max(0, reg.pixelBbox.y1 - 2);
        const x2 = Math.min(shotPng.width - 1, reg.pixelBbox.x2 + 2);
        const y2 = Math.min(shotPng.height - 1, reg.pixelBbox.y2 + 2);
        for (let x = x1; x <= x2; x++) { paintPixel(shotPng, x, y1, cr, cg, cb); paintPixel(shotPng, x, y2, cr, cg, cb); }
        for (let y = y1; y <= y2; y++) { paintPixel(shotPng, x1, y, cr, cg, cb); paintPixel(shotPng, x2, y, cr, cg, cb); }
      }
      fs.writeFileSync(overlayPath, PNG.sync.write(shotPng));
    } catch (e) {
      warnings.push(`overlay 生成失败: ${e.message}`);
    }

    /* ---- 报告 ---- */
    const report = {
      url: args.url,
      design: path.resolve(args.design),
      capturedAt: new Date().toISOString(),
      viewport: { width: args.viewport[0], height: args.viewport[1] },
      fullPage: args.fullPage,
      dpr,
      docHeight: domSnapshot.docHeight,
      match: result.match,
      reason: result.reason || null,
      diffCount: result.diffCount ?? null,
      diffPercentage: result.diffPercentage ?? null,
      diffLinesCount: result.diffLines?.length ?? null,
      diffColsCount: result.diffCols?.length ?? null,
      regions: attributed,
      summary,
      warnings,
      artifacts: {
        screenshot: shotPath,
        diff: result.match ? null : diffPath,   // match=true 时 odiff 不产出 diff.png
        overlay: overlayPath,
        report: path.join(outDir, 'report.json'),
      },
    };
    fs.writeFileSync(path.join(outDir, 'report.json'), JSON.stringify(report, null, 2));
    console.error(`[avocado-visual-diff] 报告: ${path.join(outDir, 'report.json')} (${regions.length} 个差异区域)`);

    emitOk(report);
  } finally {
    await browser.close().catch(() => {});
  }
}

main().catch((e) => {
  const msg = String(e.message || e).replace(/\u001b\[[0-9;]*m/g, ''); // 去掉 ANSI
  emitError(msg, { stack: String(e.stack || '').split('\n').slice(0, 5).map((l) => l.replace(/\u001b\[[0-9;]*m/g, '')) });
});
