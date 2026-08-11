"""Figma REST API client.

(see project design docs), Figma REST API differs from Plugin SDK in some field names
and availability. We document differences inline.

Endpoints used:
  GET /v1/files/:key               full file (large; avoid)
  GET /v1/files/:key/nodes         specific nodes (preferred)
  GET /v1/images/:key              render nodes to PNG/JPG/SVG
  GET /v1/files/:key/images        imageRef → URL map (for IMAGE paint fills)
  GET /v1/me                       token verification
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

FIGMA_API_BASE = "https://api.figma.com"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RATE_LIMIT_STATUS = 429


class FigmaError(Exception):
    """Base error for Figma API failures."""


class FigmaAuthError(FigmaError):
    """Token invalid or insufficient permission."""


class FigmaNotFoundError(FigmaError):
    """File key or node id does not exist.

    FIX: the ``kind`` param distinguishes file vs node (so the agent knows whether to swap the file or the node-id).
    """

    def __init__(self, message: str, kind: str | None = None) -> None:
        super().__init__(message)
        # kind ∈ {"file", "node", None}; None keeps old callers working
        self.kind = kind


class FigmaFileNotFoundError(FigmaNotFoundError):
    """HTTP 404 — the whole file does not exist (or the token has no permission) — kind='file'."""


class FigmaNodeNotFoundError(FigmaNotFoundError):
    """API returned a null node — kind='node', node-id was copied wrong or deleted."""


class FigmaRateLimitError(FigmaError):
    """HTTP 429 — too many requests."""


class FigmaCacheMissError(FigmaError):
    """Cache miss in --offline mode (FIX:).

    Unlike FigmaNotFoundError (404): a cache miss means "not cached, run online once first".
    The agent should suggest `avocado <url> --cache-dir X` (without --offline).
    """


# ─── URL parsing ──────────────────────────────────────────────────────────────

# Accepts:
# https://www.figma.com/design/FILE_KEY/Title?node-id=0-1
# https://www.figma.com/file/FILE_KEY/Title?node-id=0:1
# plain file key "abc123"
_URL_RE = re.compile(r"figma\.com/(?:design|file)/([A-Za-z0-9_\-]+)(?:/[^\?]*)?")
# Figma node ids are "N:N" (URL form may use "-" instead of ":")
_NODE_ID_RE = re.compile(r"^\d+:\d+$")


@dataclass(frozen=True)
class FigmaNodeRef:
    """Reference to a specific node in a Figma file."""

    file_key: str
    node_id: str  # API form uses ":" e.g. "0:1"; URL form uses "-"

    @property
    def node_id_url_form(self) -> str:
        return self.node_id.replace(":", "-")


def parse_figma_url(url_or_key: str) -> FigmaNodeRef:
    """Parse a Figma URL or bare file key into a FigmaNodeRef.

    Reject strings that are clearly not a URL/file_key (e.g. "init"/"version")
    to avoid wasting requests on the Figma API. A bare file_key must be >= 8 alphanumeric chars.

    Raises:
        FigmaError: when the string is not a valid URL/file_key, the URL is
            missing ``?node-id=``, or the node-id has an invalid format.
    """
    if "figma.com" not in url_or_key:
        # Treat as bare file key
        # Reject strings that clearly do not look like a file_key.
        # Real Figma file_keys are alphanumeric mixed-case (usually 12-30 chars).
        # Short strings, special chars, and non-ASCII are all rejected.
        if len(url_or_key) < 8 or not url_or_key.isalnum():
            raise FigmaError(
                f"not a valid figma url or file_key: {url_or_key!r} "
                f"(expected figma.com URL or bare file_key >= 8 alphanumeric chars)"
            )
        # A bare file_key has no node-id — do not silently fall back to "0:0"
        # (that produces a confusing offline cache miss for node '0:0' later).
        raise FigmaError(
            f"bare file_key {url_or_key!r} has no node-id. "
            "Expected a full figma.com URL with ?node-id= (e.g. "
            "https://www.figma.com/design/XXXX/Title?node-id=1:2). "
            "Right-click the node in Figma → Copy link to get the full URL."
        )

    m = _URL_RE.search(url_or_key)
    if not m:
        raise FigmaError(f"cannot parse figma url: {url_or_key!r}")
    file_key = m.group(1)

    # Parse node-id from query string
    parsed = urlparse(url_or_key)
    qs = parse_qs(parsed.query)
    node_id_raw = qs.get("node-id", [None])[0]
    if node_id_raw is None:
        raise FigmaError(f"url missing ?node-id= query parameter: {url_or_key!r}")
    # URL form uses "-" but Figma API uses ":"
    node_id = node_id_raw.replace("-", ":")
    # Validate node-id format: Figma node ids are "N:N" (colon or dash
    # separator, URL form converts dash to colon above). Reject dots,
    # underscores, spaces, or any other separator — a malformed id would
    # otherwise surface later as a confusing API/cache error.
    if not _NODE_ID_RE.match(node_id):
        raise FigmaError(
            f"invalid node-id {node_id_raw!r} — expected 'N:N' or 'N-N' "
            f"(e.g. node-id=1732:5574 or node-id=1732-5574)"
        )
    return FigmaNodeRef(file_key=file_key, node_id=node_id)


# ─── Client ───────────────────────────────────────────────────────────────────


class FigmaClient:
    """Thin wrapper over Figma REST API with retry + rate-limit handling."""

    def __init__(
        self,
        token: str | None = None,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        session: requests.Session | None = None,
        cache_dir: str | Path | None = None,
        offline: bool = False,
    ) -> None:
        # token 4-layer lookup: CLI flag > env var > ~/.avocado/config.yaml > project level
        # See avocado.paths.resolve_token
        if not token:
            from avocado.paths import resolve_token

            token = resolve_token()
        if not token and not offline:
            raise FigmaAuthError(
                "no token: pass token=, set FIGMA_TOKEN env var, "
                "or put figma_token in ~/.avocado/config.yaml"
            )
        self._token = token
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = session or requests.Session()
        self._session.headers.update({"X-Figma-Token": token or ""})
        # Local cache (developer/offline mode): when cache_dir is set, all
        # network reads are mirrored to disk and, when offline=True, served
        # exclusively from disk (no network at all).
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._offline = offline
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ── cache helpers ─────────────────────────────────────────────────────────

    def _cache_key(self, *parts: str) -> Path:
        """Return a cache file path under cache_dir, hashing any unsafe part.

        Returns a synthesized path even when cache_dir is None (callers
        guard with `if self._cache_dir:` before using the path).
        """
        base = self._cache_dir or Path("/_no_cache")
        safe: list[str] = []
        for p in parts:
            # FIX: an over-long alphanumeric key (e.g. 10000 chars) exceeds the OS
            # 255-byte filename limit. Hash-truncate when length > 64 to keep filenames safe.
            if p.isalnum() and len(p) <= 64:
                safe.append(p)
            else:
                h = hashlib.sha1(p.encode()).hexdigest()[:12]
                safe.append(h)
        return base.joinpath(*safe)

    def _cache_get(self, key: Path) -> str | None:
        if self._cache_dir is None or not key.exists():
            return None
        return key.read_text()

    def _cache_json_get(self, key: Path) -> Any | None:
        raw = self._cache_get(key)
        if raw is None:
            return None
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            return None
        # FIX: valid JSON that is not a dict (e.g. string/list/number) makes
        # SceneNode.from_dict subscript d.get("children", []) directly → AttributeError.
        # Only accept a dict return; non-dict (corrupted cache) is treated as a miss.
        if not isinstance(d, dict):
            return None
        return d

    def _cache_put(self, key: Path, content: str | bytes | dict) -> Path:
        assert self._cache_dir is not None, "cache_dir not set"
        key.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict):
            key.write_text(json.dumps(content))
        elif isinstance(content, str):
            key.write_text(content)
        else:
            key.write_bytes(content)
        return key

    def _must_cache(self) -> None:
        """Raise if offline mode requested but no cache_dir configured."""
        if self._offline and self._cache_dir is None:
            raise FigmaError("--offline requires --cache-dir (local cache directory)")

    def _cache_dir_diagnostic(self) -> str:
        """Issue 8: list the actual structure of cache_dir on a cache miss to help designers locate the path.

        Common designer confusion: they pass `--cache-dir foo/figma_cache/` but avocado
        expects `foo/` (figma_cache is a subdirectory avocado creates internally). The
        diagnostic lists what was found under the current cache_dir so the designer can
        see the path is wrong (e.g. "you passed figma_cache/, but avocado expects its parent").
        """
        if self._cache_dir is None:
            return ""
        try:
            entries = list(self._cache_dir.iterdir())
        except (OSError, NotADirectoryError):
            return f" (cache-dir {self._cache_dir} does not exist or is unreadable)"
        # detect a common mistake: figma_cache/ was passed but the parent dir is expected
        subdirs = [e.name for e in entries if e.is_dir()]
        files = [e.name for e in entries if e.is_file()]
        parts = [f"cache-dir={self._cache_dir}"]
        if subdirs:
            parts.append(f"subdirs: {subdirs[:5]}")
        if files:
            parts.append(f"files: {files[:5]}")
        # if the cache_dir itself is named figma_cache, hint to pass the parent dir
        if self._cache_dir.name == "figma_cache":
            parts.append(
                "hint: you passed the figma_cache/ directory itself, but avocado expects its parent"
                f" ({self._cache_dir.parent}). Try `--cache-dir {self._cache_dir.parent}`"
            )
        # if a nodes/ subdir exists (path is correct, just the node is not cached)
        if "nodes" in subdirs:
            parts.append(
                "nodes/ subdir exists (path is correct), but the requested node is not cached"
            )
        return " (" + "；".join(parts) + ")"

    # ── public ──

    def verify_token(self) -> dict[str, Any]:
        """Verify token works; return /v1/me response."""
        return self._get("/v1/me")

    def get_node(
        self,
        ref: FigmaNodeRef,
        *,
        geometry: str = "paths",
        depth: int | None = None,
    ) -> dict[str, Any]:
        """Fetch a single node by ref. Returns the Figma API JSON dict.

        Args:
            ref: file_key + node_id
            geometry: "paths" (default, includes vector data) or "bbox"
            depth: optional max tree depth
        """
        params: dict[str, Any] = {"ids": ref.node_id, "geometry": geometry}
        if depth is not None:
            params["depth"] = depth
        path = f"/v1/files/{ref.file_key}/nodes"
        # Cache hit: offline/dev mode serves node JSON straight from disk.
        cache_key = self._cache_key("nodes", ref.file_key, ref.node_id, f"d{depth or 0}")
        if self._cache_dir and not self._offline:
            cached = self._cache_json_get(cache_key)
            if cached is not None:
                return cached
        if self._offline:
            cached = self._cache_json_get(cache_key)
            if cached is None:
                # FIX: on an offline cache miss for the requested depth, automatically
                # fall back to d0 (full depth, superset). Cache is stored as <node_hash>/d<depth>;
                # depth values other than 0/8 (e.g. d2/d4) always miss (fetch uses d8, the d2c CLI
                # may use other values). d0 is the full-depth superset containing all depths' data,
                # a safe fallback.
                if depth not in (0, None) and self._cache_dir is not None:
                    fallback_key = self._cache_key("nodes", ref.file_key, ref.node_id, "d0")
                    fallback_cached = self._cache_json_get(fallback_key)
                    if fallback_cached is not None:
                        return fallback_cached
                # FIX: --offline semantics are "Read ONLY, no network" (per schema).
                # Previously fell back to the network when a token existed and only warned,
                # violating the flag semantics; CI/offline debugging got a misleading ok:true.
                # Now it uniformly raises FigmaCacheMissError.
                # FIX: --offline without --cache-dir gives a clear message (no internal paths leaked).
                if self._cache_dir is None:
                    raise FigmaCacheMissError(
                        "offline mode requires --cache-dir (got none). "
                        "Run once online with --cache-dir to populate cache."
                    )
                raise FigmaCacheMissError(
                    f"offline cache miss for node {ref.node_id!r} "
                    f"(depth={depth}). Run once online with --cache-dir to populate."
                    + self._cache_dir_diagnostic()
                )
            return cached
        _offline_fallback = False
        try:
            resp = self._get(path, params=params)
        except FigmaError:
            raise
        # API returns {"nodes": {"<id>": {"document": {...}}}}
        # FIX: the Figma API returns {"nodes": {"<id>": null}} for a nonexistent/inaccessible
        # node-id; subscripting null directly raises TypeError. Check for None → friendly error.
        nodes = resp.get("nodes", {})
        node_data = nodes.get(ref.node_id)
        if node_data is None:
            # also check the url-form key (Figma sometimes returns the "-" form)
            alt = ref.node_id_url_form
            node_data = nodes.get(alt)
            if node_data is None:
                raise FigmaNodeNotFoundError(
                    f"node {ref.node_id!r} not found or inaccessible "
                    f"(check node-id in URL, or token file access). "
                    f"API response keys: {list(nodes.keys())}",
                    kind="node",
                )
            # alt key hit
            doc = node_data["document"]
            if self._cache_dir:
                self._cache_put(cache_key, doc)
            return doc
        doc = node_data["document"]
        if self._cache_dir:
            self._cache_put(cache_key, doc)
        return doc

    def get_image(
        self,
        ref: FigmaNodeRef,
        *,
        format: str = "png",
        scale: float = 1.0,
    ) -> str:
        """Render a node to image; return the temporary image URL.

        Note: this RE-RENDERS the node from scratch (different quality from
        original image fill). For nodes carrying an IMAGE paint fill, prefer
        get_image_fills() + looking up the imageRef — that returns the
        ORIGINAL image at full quality.
        """
        params = {
            "ids": ref.node_id,
            "format": format,
            "scale": scale,
        }
        path = f"/v1/images/{ref.file_key}"
        # Cache: dev/offline mode returns a local file path.
        cache_key = self._cache_key("render", ref.file_key, ref.node_id, f"{format}_s{scale}")
        if self._cache_dir and not self._offline:
            if cache_key.exists():
                return str(cache_key)
        if self._offline:
            if cache_key.exists():
                return str(cache_key)
            # FIX: without cache_dir, FigmaCacheMissError must not leak the /_no_cache/ path
            if self._cache_dir is None:
                raise FigmaCacheMissError(
                    "offline mode requires --cache-dir (got none). "
                    "Run once online with --cache-dir to populate cache."
                )
            raise FigmaCacheMissError(
                f"offline cache miss for image {ref.node_id!r}. "
                f"Run once online with --cache-dir to populate."
            )
        resp = self._get(path, params=params)
        images = resp.get("images", {})
        url = images.get(ref.node_id) or images.get(ref.node_id_url_form)
        if not url:
            raise FigmaNotFoundError(f"image render failed for {ref.node_id!r}: {resp}")
        if self._cache_dir:
            # Download the rendered image to cache and return the local path.
            try:
                r = self._session.get(url, timeout=self._timeout)
                r.raise_for_status()
                return str(self._cache_put(cache_key, r.content))
            except requests.RequestException:
                # Fall back to the temp URL on download failure.
                return url
        return url

    # ── batch image fetch ────────────────────────────────────────────
    # Figma's /v1/images/:key endpoint accepts a comma-separated `ids` list,
    # returning `{node_id: url}` for all of them in ONE request. Pages with
    # 50-100+ vector icons / image nodes used to take 3-5 minutes because
    # each node went through its own serial get_image call (1-3s each +
    # rate-limit backoff). This batch path collapses that to ⌈N/50⌉ API
    # calls + a concurrent download fan-out.
    _BATCH_IMAGE_CHUNK = 50  # Figma accepts larger but 50 keeps URLs short
    _BATCH_DOWNLOAD_WORKERS = 8  # threads for parallel PNG/SVG download

    def _batch_cache_key(self, file_key: str, node_id: str, fmt: str, scale: float) -> Path:
        return self._cache_key("render", file_key, node_id, f"{fmt}_s{scale}")

    def get_image_batch(
        self,
        file_key: str,
        node_ids: list[str],
        *,
        format: str = "png",
        scale: float = 1.0,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, str]:
        """Render multiple nodes to images in (mostly) one API call.

        Returns `{node_id: local_path_or_url}`. Nodes already in cache are
        served without any network call. The remaining ones are batched at
        50 IDs per /v1/images request, then their result URLs are downloaded
        concurrently (8 threads).

        Offline mode: only cache lookups; missing nodes are silently skipped
        (caller should detect via the returned dict — missing key = miss).
        Callers that need to know about misses can compare len(returned) vs
        len(node_ids).
        """
        if not node_ids:
            return {}

        # 1. Partition by cache-hit vs miss.
        results: dict[str, str] = {}
        misses: list[str] = []
        for nid in node_ids:
            ck = self._batch_cache_key(file_key, nid, format, scale)
            if self._cache_dir and ck.exists():
                results[nid] = str(ck)
            else:
                misses.append(nid)

        if not misses:
            return results

        # Offline: cannot fetch — return partial results.
        if self._offline:
            return results

        # 2. Batch API calls (50 IDs each).
        from concurrent.futures import ThreadPoolExecutor, as_completed

        nid_to_url: dict[str, str] = {}
        for i in range(0, len(misses), self._BATCH_IMAGE_CHUNK):
            chunk = misses[i : i + self._BATCH_IMAGE_CHUNK]
            params = {
                "ids": ",".join(chunk),
                "format": format,
                "scale": scale,
            }
            path = f"/v1/images/{file_key}"
            resp = self._get(path, params=params)
            images = resp.get("images", {})
            for nid, url in images.items():
                if url:
                    nid_to_url[nid] = url
            if on_progress:
                on_progress(len(results) + len(nid_to_url), len(node_ids))

        # 3. Concurrent download into cache.
        if self._cache_dir and nid_to_url:

            def _dl(nid_url: tuple[str, str]) -> tuple[str, str | None]:
                nid, url = nid_url
                ck = self._batch_cache_key(file_key, nid, format, scale)
                try:
                    r = self._session.get(url, timeout=self._timeout)
                    r.raise_for_status()
                    return nid, str(self._cache_put(ck, r.content))
                except requests.RequestException:
                    return nid, url  # fall back to temp URL

            with ThreadPoolExecutor(max_workers=self._BATCH_DOWNLOAD_WORKERS) as ex:
                futures = [ex.submit(_dl, item) for item in nid_to_url.items()]
                for f in as_completed(futures):
                    nid, path_or_url = f.result()
                    if path_or_url:
                        results[nid] = path_or_url
        else:
            # No cache_dir: return temp URLs directly.
            for nid, url in nid_to_url.items():
                results[nid] = url

        return results

    def get_image_fills(self, file_key: str) -> dict[str, str]:
        """Return {imageRef: url} for all image fills in a file.

        Uses GET /v1/files/:key/images. This is the authoritative source for
        original-quality image data: IMAGE paint fills reference an imageRef
        that this endpoint maps to a CDN URL.

        Cached per-instance; safe to call repeatedly.
        """
        cache_key = f"_imgfills_{file_key}"
        cached = getattr(self, cache_key, None)
        if cached is not None:
            return cached
        # Disk cache: imageRef → path relative to cache_dir (or URL fallback).
        disk_key = self._cache_key("fills", file_key, "images.json")
        if self._cache_dir and not self._offline:
            disk = self._cache_json_get(disk_key)
            if disk is not None:
                resolved = {k: self._resolve_fills_entry(v) for k, v in disk.items()}
                setattr(self, cache_key, resolved)
                return resolved
        if self._offline:
            disk = self._cache_json_get(disk_key)
            if disk is None:
                raise FigmaCacheMissError(
                    f"offline cache miss for image fills {file_key!r} (expected {disk_key})."
                )
            resolved = {k: self._resolve_fills_entry(v) for k, v in disk.items()}
            setattr(self, cache_key, resolved)
            return resolved
        path = f"/v1/files/{file_key}/images"
        resp = self._get(path)
        meta = resp.get("meta", {})
        images = meta.get("images", {}) if isinstance(meta, dict) else {}
        # API returns {imageRef: url}
        if self._cache_dir:
            # Download each original image to local cache so offline mode can
            # serve it without a (soon-expiring) signed CDN URL.
            local: dict[str, str] = {}
            for image_ref, url in images.items():
                img_key = self._cache_key("fills", file_key, "images", image_ref)
                if img_key.exists():
                    local[image_ref] = str(img_key.relative_to(self._cache_dir))
                    continue
                try:
                    r = self._session.get(url, timeout=self._timeout)
                    r.raise_for_status()
                    self._cache_put(img_key, r.content)
                    local[image_ref] = str(img_key.relative_to(self._cache_dir))
                except requests.RequestException:
                    local[image_ref] = url  # keep original URL as fallback
            setattr(self, cache_key, local)
            self._cache_put(disk_key, local)
            return local
        setattr(self, cache_key, images)
        return images

    def _resolve_fills_entry(self, value: str) -> str:
        """Resolve a cached image-fills entry to an absolute path or URL.

        Entries are stored as paths relative to cache_dir (current behavior)
        or absolute paths (legacy caches baked before a repo rename). URLs and
        existing paths pass through. Stale absolute paths whose tail matches a
        file under cache_dir are re-anchored.
        """
        if not self._cache_dir or not value:
            return value
        if value.startswith(("http://", "https://")):
            return value
        p = Path(value)
        if p.exists():
            return value
        # Relative path: anchor under cache_dir.
        if not p.is_absolute():
            anchored = self._cache_dir / p
            if anchored.exists():
                return str(anchored)
            return value
        # Legacy absolute path: try re-anchoring by tail under cache_dir.
        if "fills" in p.parts:
            tail = p.relative_to(*p.parts[: p.parts.index("fills")])
            anchored = self._cache_dir / tail
            if anchored.exists():
                return str(anchored)
        return value

    # ── internal ──

    def _get(self, path: str, *, params: dict | None = None) -> dict:
        url = f"{FIGMA_API_BASE}{path}"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                r = self._session.get(url, params=params, timeout=self._timeout)
            except requests.RequestException as e:
                last_exc = e
                time.sleep(0.5 * (attempt + 1))
                continue

            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                raise FigmaAuthError(f"figma auth failed ({r.status_code}): {r.text[:200]}")
            if r.status_code == 404:
                raise FigmaFileNotFoundError(
                    f"figma 404: {path} {r.text[:200]}",
                    kind="file",
                )
            if r.status_code == RATE_LIMIT_STATUS:
                # Exponential backoff
                wait = float(r.headers.get("Retry-After", 2**attempt))
                time.sleep(wait)
                last_exc = FigmaRateLimitError(f"rate limited; retry after {wait}s")
                continue
            # 5xx and other transient
            last_exc = FigmaError(f"figma {r.status_code}: {r.text[:200]}")
            time.sleep(0.5 * (attempt + 1))

        raise last_exc or FigmaError("exhausted retries")
