"""Image node detection + rendering.

(see project design docs)

Detection rules:
  - FRAME/RECTANGLE with exactly one IMAGE paint → <img>
  - RECTANGLE with multiple fills where one is IMAGE → still <div> but
    with background-image
  - SLICE → always <img> (always renders as image)
  - VECTOR / LINE / STAR / POLYGON → <img> via Figma svg export

Image source resolution:
  - For nodes with IMAGE paint fill (imageRef), prefer the file-level
    /v1/files/:key/images endpoint → maps imageRef → original CDN URL.
    This is the ORIGINAL image data, at full quality.
  - For VECTOR / LINE / STAR / POLYGON / SLICE nodes (vector data), use
    /v1/images/:key?ids=NODE_ID (re-render to svg/png).
  - The node-level re-render is a FALLBACK for IMAGE fills because it
    re-rasterizes the node and produces different output than the
    original image file.

Output:
  - <img src="..." />  with width/height kept
  - For multiple IMAGE fills or mixed: fall back to background-image CSS
"""

from __future__ import annotations

import os
from pathlib import Path

import requests

from avocado.api.figma import FigmaClient, FigmaNodeRef
from avocado.model.scene_node import Paint, SceneNode
from avocado.model.tree_node import TreeNode

# ── detection ──


def is_image_node(scene: SceneNode) -> bool:
    """True if this node should render as <img>."""
    if scene.type == "SLICE":
        return True
    # VECTOR / LINE / STAR / POLYGON: leaf nodes with no children, render
    # as <img> via Figma svg export.
    # BOOLEAN_OPERATION is excluded — Figma API returns 404 when trying to
    # render a BOOLEAN_OPERATION node directly (it's an operation node, not
    # a renderable leaf). It falls through to <div>; the SOLID fill on it
    # is handled via the parent's style chain.
    if scene.type in ("VECTOR", "LINE", "STAR", "POLYGON"):
        return True
    # FRAME/RECTANGLE with single IMAGE paint
    visible_fills = [p for p in scene.fills if p.visible]
    if len(visible_fills) == 1 and visible_fills[0].type == "IMAGE":
        paint = visible_fills[0]
        # INSTANCE nodes: the IMAGE fill is sometimes the component-set
        # preview thumbnail from Figma's assets panel, marked by non-zero
        # rotation or filters (contrast/saturation/exposure). These
        # filters approximate the component's decorative look but don't
        # represent the actual instance visual (which is rendered by
        # children). Including such a thumbnail produces a wrong-image
        # bug (sample_page_001 "Recommended for you": thumbnail is a flat
        # 4-card preview with rotation=270 + saturation=-1, but the real
        # instance shows a clipped horizontal scroller with one card).
        # When the IMAGE fill has rotation/filters AND the INSTANCE has
        # children, fall through to <div> + children. INSTANCE without
        # rotation/filters (e.g. detail "Header" — real bg image + UI
        # overlay children) keeps the <img> path; children overlay on top.
        # FRAME/RECTANGLE always keep <img> (real bitmap fills).
        if (
            scene.type == "INSTANCE"
            and (scene.children or [])
            and (paint.rotation or paint.filters)
        ):
            return False
        # Image-fill fix: a FRAME with an IMAGE fill + visible children
        # should NOT become <img> — render_as_image clears children (line
        # 305), causing Bottom Sheet / overlay content to vanish. Instead
        # fall through to <div> + style.py's image fill background + children
        # rendered on top. Only FRAME/RECTANGLE with NO visible children
        # become <img> (pure bitmap).
        if scene.type in ("FRAME", "RECTANGLE"):
            visible_children = [c for c in (scene.children or []) if c.visible]
            if visible_children:
                return (
                    False  # has visible children: keep children + use the IMAGE fill as background
                )
        return True
    return False


def get_image_paint(scene: SceneNode) -> Paint | None:
    """Return the IMAGE paint if is_image_node is True."""
    for p in scene.fills:
        if p.visible and p.type == "IMAGE":
            return p
    return None


# ── rendering ──


def _preprocess_cover_image(
    src_path: str, scene: SceneNode, tree: TreeNode | None, scale_mode: str | None
) -> tuple[str, bool]:
    """Pre-crop/scale a local image file to the target box dimensions.

    Browsers and Figma use different image downscale algorithms (Figma uses a
    higher-quality bicubic-ish resampler; Chrome's <img> scaling is noticeably
    different for large downscale factors like 32x). When a 4096x2731 original
    is displayed at 128x120 via object-fit:cover, the pixel output diverges by
    3-5% purely from resampling — an unrecoverable fidelity gap.

    This function pre-processes the image at the Python layer (PIL LANCZOS)
    to match the *cover* result: center-crop to the box aspect ratio, then
    resize to exact box pixels. The <img> then renders at 1:1 with no
    browser-side scaling. We also strip object-fit:cover since the image is
    already the right size.

    Only runs when src is a local file path (offline/cache mode). HTTP URLs
    and vector types are returned unchanged.

    Returns (new_src_path, was_preprocessed).
    """
    if scale_mode not in ("FILL", "CROP", "STRETCH", None):
        return src_path, False
    # box: prefer explicit width/height on the tree node (already set by
    # layout pass). Fallback to scene bbox.
    w = tree.style.get("width") if tree is not None else None
    h = tree.style.get("height") if tree is not None else None
    if w is None or h is None:
        box = getattr(scene, "absolute_bounding_box", None) or {}
        w = box.get("width")
        h = box.get("height")
    if not w or not h:
        return src_path, False
    try:
        tw = int(round(float(str(w).replace("px", "").strip())))
        th = int(round(float(str(h).replace("px", "").strip())))
    except (TypeError, ValueError):
        return src_path, False
    if tw <= 0 or th <= 0:
        return src_path, False
    try:
        from PIL import Image
    except ImportError:
        return src_path, False
    try:
        img = Image.open(src_path)
        img.load()
    except Exception:
        return src_path, False
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    sw, sh = img.size
    if sw <= 0 or sh <= 0:
        return src_path, False
    if scale_mode == "STRETCH":
        # Distort to exact target dimensions (no aspect-ratio crop). The
        # browser would otherwise downscale the source on the fly via its
        # own (Chrome bicubic) resampler, diverging from Figma's Skia
        # resampler by 3-5% on large downscale factors (e.g. sample_pc
        # "Main Image" 4096x2732 → 568x500). Pre-resizing with LANCZOS
        # makes the browser render at 1:1.
        downscale = max(sw / tw, sh / th)
        scale_factor = 1 if downscale > 5.0 else 2
        tw_s, th_s = tw * scale_factor, th * scale_factor
        img = img.resize((tw_s, th_s), Image.LANCZOS)
        src = Path(src_path)
        out = src.with_name(f"{src.stem}_cover{tw_s}x{th_s}{src.suffix or '.png'}")
        try:
            img.save(out)
        except Exception:
            return src_path, False
        return str(out), True
    # cover (FILL/CROP/None): scale so the smaller dimension fills, then center-crop
    target_ratio = tw / th
    src_ratio = sw / sh
    if src_ratio > target_ratio:
        # source is wider — crop width
        new_w = int(round(sh * target_ratio))
        x0 = (sw - new_w) // 2
        img = img.crop((x0, 0, x0 + new_w, sh))
    elif src_ratio < target_ratio:
        new_h = int(round(sw / target_ratio))
        y0 = (sh - new_h) // 2
        img = img.crop((0, y0, sw, y0 + new_h))
    # Adaptive DPR: pick 1x or 2x pre-crop based on source/target ratio.
    # - When source is much larger than target (>5x downscale), 1x LANCZOS
    # preserves high-frequency detail better (memory pil_cover_precrop).
    # - When source is close to target (<5x), 2x lets the browser render 1:1
    # at deviceScaleFactor=2 instead of upsampling, eliminating the
    # browser's bicubic-upsample pass. Empirical testing on the d2c test
    # suite shows 2x wins for downscale factors 1-5 (majority of images).
    downscale = max(sw / tw, sh / th)
    if downscale > 5.0:
        scale_factor = 1
    else:
        scale_factor = 2
    tw_s, th_s = tw * scale_factor, th * scale_factor
    img = img.resize((tw_s, th_s), Image.LANCZOS)
    # Write next to source with a tag suffix; reuse on subsequent runs.
    src = Path(src_path)
    out = src.with_name(f"{src.stem}_cover{tw_s}x{th_s}{src.suffix or '.png'}")
    try:
        img.save(out)
    except Exception:
        return src_path, False
    return str(out), True


def _recolor_vector_svg(src_path: str, scene: SceneNode) -> str | None:
    """Override fill colors in a re-rendered SVG to match the Figma node's paint.

    Figma's `/v1/images/:key?ids=...&format=svg` re-render always emits
    `fill="black"` for VECTOR/LINE/STAR/POLYGON nodes — even when the node's
    own `fills` paint is a SOLID gray/white/brand color. This makes the
    rendered icon darker than the design (e.g. a `#4b4a4a` gray icon
    renders as solid black).

    This function reads the SVG, looks up the node's first visible SOLID
    fill, and rewrites every `fill="..."` attribute to the target color.
    The recolored SVG is written next to the source with a `_c<hash>` suffix
    so subsequent runs can reuse it.

    Returns the new path on success, or None if the SVG couldn't be read,
    the node has no SOLID fill, or the fill is already black (no-op).
    """
    if not src_path or not isinstance(src_path, str):
        return None
    p = Path(src_path)
    try:
        svg = p.read_text(encoding="utf-8")
    except Exception:
        return None
    if not svg.lstrip().startswith("<svg"):
        return None

    # Look up first visible SOLID fill on the node.
    target_hex = None
    for paint in scene.fills or []:
        if not getattr(paint, "visible", True):
            continue
        if getattr(paint, "type", None) != "SOLID":
            continue
        col = getattr(paint, "color", None)
        if col is None:
            continue
        r = int(round(col.r * 255))
        g = int(round(col.g * 255))
        b = int(round(col.b * 255))
        target_hex = f"#{r:02x}{g:02x}{b:02x}"
        break
    if target_hex is None or target_hex.lower() == "#000000":
        # Already black — Figma's default. No rewrite needed.
        return None
    if 'fill="black"' not in svg and 'fill="#000000"' not in svg and 'fill="#000"' not in svg:
        # SVG has its own colors (already correctly rendered). Don't override.
        return None

    # Rewrite every `fill="..."` to the target color.
    import re

    new_svg = re.sub(r'fill="[^"]*"', f'fill="{target_hex}"', svg)

    # Cache key: hash of target color + source path stem.
    import hashlib

    h = hashlib.md5(f"{target_hex}:{p.name}".encode()).hexdigest()[:8]
    out = p.with_name(f"{p.stem}_c{h}{p.suffix or '.svg'}")
    try:
        out.write_text(new_svg, encoding="utf-8")
    except Exception:
        return None
    return str(out)


def render_as_image(
    scene: SceneNode,
    tree: TreeNode,
    *,
    client: FigmaClient | None,
    out_dir: Path | None = None,
    fmt: str | None = None,
    scale: float = 1.0,
) -> str | None:
    """Convert a TreeNode to <img> form, fetching the image URL.

    Args:
        scene: source SceneNode (for id + box)
        tree: target TreeNode to mutate
        client: FigmaClient (required to fetch image URL; pass None to skip
            fetching and just mark is_img)
        out_dir: if given, download the image to <out_dir>/<node-id>.<fmt>
            and use local path; otherwise use the temp Figma URL
        fmt: png / jpg / svg. If None, defaults to 'svg' for VECTOR-type
            nodes and 'png' otherwise.
        scale: render scale. 1.0 = node's natural size. Defaults to 1.0
            because the <img> tag's width/height matches bbox; using
            2.0 causes browser to CSS-scale the image (blurry/darker).

    Returns:
        src URL/path on success, None if fetch failed or skipped.
    """
    if not is_image_node(scene):
        return None

    # Default format: svg for vector-types, png for image-fills
    is_vector_type = scene.type in ("VECTOR", "LINE", "STAR", "POLYGON", "SLICE")
    if fmt is None:
        fmt = "svg" if is_vector_type else "png"

    tree.tag_name = "img"
    tree.is_img = True
    # img is a leaf — drop any children (shouldn't have any for VECTOR/etc,
    # but defensively clear)
    tree.children = []
    tree.text_content = None
    # Remove background-color if any (img doesn't show bg)
    tree.style.pop("background-color", None)
    # Padding on an <img> shrinks the rendered image inside the box — but a
    # FRAME with IMAGE fill doesn't actually inset the image by its padding
    # (padding only affects children, which an <img> doesn't have). Drop it.
    tree.style.pop("padding", None)

    # ── Drop flex layout props that would distort the image ──
    # When a FRAME with an IMAGE fill becomes <img>, its flex props
    # (flex-grow, flex-basis, etc.) are inherited from Figma Auto Layout
    # semantics but DON'T apply to images. An <img> should honor its
    # explicit width/height. Leaving flex-grow:1 + flex-basis:0 on an
    # <img> inside a flex column makes the image stretch to share the
    # parent's main axis, ignoring the explicit height.
    for k in (
        "flex-grow",
        "flex-basis",
        "flex-shrink",
        "align-self",  # stretch would also distort
        "flex-direction",
        "display",  # img is not a flex container
        "gap",
        "justify-content",
        "align-items",
        "padding",
        "min-width",
        "min-height",
    ):
        tree.style.pop(k, None)
    # In flex parent, an <img> with explicit width/height needs flex-shrink:0
    # to prevent the parent from shrinking it below its natural size.
    tree.style["flex-shrink"] = 0
    tree.style["flex-grow"] = 0

    # ── object-fit from Figma scaleMode ──
    # Figma IMAGE paint scaleMode → CSS object-fit:
    # FILL → cover (image fills bbox, may crop — Figma default for IMAGE)
    # FIT → contain (full image visible, may letterbox)
    # CROP → cover (Figma CROP uses explicit scaling; close enough)
    # STRETCH → fill (distort to fill — no cropping, stretches to fit)
    # TILE → none (CSS repeat handled separately)
    # The browser default `object-fit: fill` distorts images; we only set fill
    # when Figma explicitly requests STRETCH.
    paint = get_image_paint(scene)
    if paint is not None:
        if paint.scale_mode in ("FILL", "CROP"):
            tree.style["object-fit"] = "cover"
        elif paint.scale_mode == "FIT":
            tree.style["object-fit"] = "contain"
        elif paint.scale_mode == "STRETCH":
            tree.style["object-fit"] = "fill"
        elif paint.scale_mode in ("TILE", "TILE_L"):
            # rare; treat as cover
            tree.style["object-fit"] = "cover"
        else:
            # No scaleMode info — Figma default for IMAGE is FILL
            tree.style["object-fit"] = "cover"

    if client is None:
        # Dry run / no API call: emit placeholder src
        tree.props["src"] = f"// TODO: image for figma node {scene.id}"
        return None

    # ── prefer imageRef lookup for IMAGE paint fills ──
    # For FRAME/RECTANGLE with IMAGE paint, the original image is stored
    # as an imageRef in the file's image table. Use /v1/files/:key/images
    # to resolve imageRef → original CDN URL. This is the FULL-QUALITY
    # original image, not a re-render of the node.
    url: str | None = None
    if not is_vector_type:
        paint = get_image_paint(scene)
        if paint and paint.image_ref:
            file_key = os.environ.get("FIGMA_FILE_KEY")
            if file_key:
                try:
                    fills_map = client.get_image_fills(file_key)
                    url = fills_map.get(paint.image_ref)
                except Exception:
                    url = None

    # ── Fallback: node-level re-render (vector types or imageRef miss) ──
    if url is None:
        file_key = os.environ.get("FIGMA_FILE_KEY")
        if not file_key:
            # FIX: don't write TODO comment text (it would break JSX src
            # attribute validity). Use an empty string so the JSX stays valid
            # (src=""); the image node renders blank.
            tree.props["src"] = ""
            tree.props["_image_error"] = f"missing FIGMA_FILE_KEY for {scene.id}"
            return None
        ref = FigmaNodeRef(file_key=file_key, node_id=scene.id)
        try:
            url = client.get_image(ref, format=fmt, scale=scale)
        except Exception as e:
            # FIX: same as above — don't write a TODO comment; use an
            # empty src + an error marker. cli.py's main collects
            # _image_error and adds a warning to the envelope.
            tree.props["src"] = ""
            tree.props["_image_error"] = f"image fetch failed: {e}"
            return None

    # ── Offline cache: url may already be a local file path ──
    # In --cache-dir mode, get_image_fills/get_image return local file
    # paths instead of signed CDN URLs (which expire). Skip downloading.
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        # pre-crop/scale to box dimensions for cover-mode images,
        # eliminating browser-vs-Figma resampling divergence (3-5% on
        # large downscale factors). PIL is optional; silent no-op if absent.
        if not is_vector_type:
            paint_final = get_image_paint(scene)
            sm = paint_final.scale_mode if paint_final else None
            new_url, ok = _preprocess_cover_image(url, scene, tree, sm)
            if ok:
                tree.style.pop("object-fit", None)
                tree.props["src"] = new_url
                return new_url
        tree.props["src"] = url
        return str(url)

    if out_dir is not None:
        # Download to local
        out_dir.mkdir(parents=True, exist_ok=True)
        # safe filename
        safe_id = scene.id.replace(":", "_").replace(";", "_").replace("/", "_")
        local_path = out_dir / f"{safe_id}.{fmt}"
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            local_path.write_bytes(r.content)
            tree.props["src"] = str(local_path)
            return str(local_path)
        except Exception:
            # Fall back to URL
            tree.props["src"] = url
            return url

    tree.props["src"] = url
    return url
