"""HTML document wrapper for `--format html` output.

By default `--format html` emits a complete HTML document (doctype + viewport
meta + body wrapper) so designers can open it directly in a browser to preview.
The `--html-fragment` flag reverts to the old bare `<div>` fragment behavior.

Issue 9: when `preview_centered=True`, add preview-centering styles (grey
background + centered + shadow) so mobile designs feel like a phone simulator
when previewed in a desktop browser. Enabled by default in the designer preset.

Minimal wrapper: only doctype / head (viewport + title) / body; no extra
styles injected. The box-sizing reset is still controlled by codegen.py
(injected into the `<style>` inside the fragment) to stay self-contained.
"""

from __future__ import annotations

from avocado.model.tree_node import TreeNode

# viewport meta: mobile designs default to a mobile viewport
_VIEWPORT_META = "width=device-width, initial-scale=1.0"

# Issue 9: preview-centering styles (grey bg + centered + shadow + rounded corners, simulating a phone preview)
_PREVIEW_STYLE = """<style>
  body.avocado-preview-host {
    margin: 0; padding: 40px 16px; min-height: 100vh;
    background: #f0f0f0;
    display: flex; justify-content: center; align-items: flex-start;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  body.avocado-preview-host > .avocado-preview {
    box-shadow: 0 4px 24px rgba(0,0,0,0.12);
    border-radius: 16px; overflow: hidden;
    background: #fff;
  }
</style>
"""


def _derive_title(root: TreeNode | None, fallback: str = "avocado output") -> str:
    """Derive <title> from the root node's name (designer-visible, readable). Falls back on failure."""
    if root is None:
        return fallback
    nm = getattr(root, "name", None) or ""
    nm = nm.strip()
    if not nm:
        return fallback
    # HTML <title> cannot contain < > & (browsers tolerate it, but escaping is safer)
    nm = nm.replace("<", "").replace(">", "").replace("&", "&amp;")
    return nm or fallback


def wrap_html_document(
    fragment: str,
    root: TreeNode | None = None,
    *,
    preview_centered: bool = False,
) -> str:
    """Wrap an HTML fragment into a complete HTML document.

    Args:
        fragment: the bare HTML fragment returned by codegen.render_jsx(format="html", ...)
            (including the box-sizing `<style>` reset + the body `<div>` tree)
        root: the TreeNode root, used to derive <title> (default title when None)
        preview_centered: Issue 9; when True, add preview-centering styles (grey bg +
            centered + shadow) so mobile designs feel like a phone simulator in a
            desktop browser. Enabled by default in the designer preset, disabled by
            default for plain --format html (preserving original behavior).

    Returns:
        The complete HTML document string.
    """
    title = _derive_title(root)
    # Don't re-format the fragment (keep codegen's indentation + box-sizing injection)
    if preview_centered:
        # Issue 9: add a class to body, wrap the fragment in a .avocado-preview div
        return (
            "<!DOCTYPE html>\n"
            '<html lang="zh-CN">\n'
            "<head>\n"
            '  <meta charset="UTF-8">\n'
            f'  <meta name="viewport" content="{_VIEWPORT_META}">\n'
            f"  <title>{title}</title>\n"
            f"{_PREVIEW_STYLE}"
            "</head>\n"
            '<body class="avocado-preview-host">\n'
            '<div class="avocado-preview">\n'
            f"{fragment}"
            "</div>\n"
            "</body>\n"
            "</html>\n"
        )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        f'  <meta name="viewport" content="{_VIEWPORT_META}">\n'
        f"  <title>{title}</title>\n"
        "</head>\n"
        "<body>\n"
        f"{fragment}"
        "</body>\n"
        "</html>\n"
    )
