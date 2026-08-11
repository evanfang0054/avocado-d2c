"""Tests for FigmaClient — runs against real Figma API (requires FIGMA_TOKEN).

Marked as 'live' so CI can skip; run locally with:
  pytest tests/test_figma_api.py -v -m live
"""

from __future__ import annotations

import os

import pytest

from avocado.api.figma import (
    FigmaAuthError,
    FigmaClient,
    FigmaError,
    parse_figma_url,
)

pytestmark = pytest.mark.live


# Canonical test fixture (see design docs)
TEST_URL = (
    "https://www.figma.com/design/FIGMA_FILE_KEY_PLACEHOLDER_001/"
    "Sample-Page--Confirm-Dialog-?node-id=0-1"
)


def _token() -> str | None:
    return os.environ.get("FIGMA_TOKEN")


@pytest.fixture
def client() -> FigmaClient:
    token = _token()
    if not token:
        pytest.skip("FIGMA_TOKEN not set")
    return FigmaClient(token=token)


def test_parse_url_design_form() -> None:
    ref = parse_figma_url(TEST_URL)
    assert ref.file_key == "FIGMA_FILE_KEY_PLACEHOLDER_001"
    assert ref.node_id == "0:1"
    assert ref.node_id_url_form == "0-1"


def test_parse_url_file_form() -> None:
    ref = parse_figma_url("https://www.figma.com/file/ABCDEF/Title?node-id=10:20")
    assert ref.file_key == "ABCDEF"
    assert ref.node_id == "10:20"


def test_parse_bare_key_rejected_without_node_id() -> None:
    """A bare file_key is rejected: it has no node-id to fetch.

    Previously this silently fell back to node_id='0:0', which produced a
    confusing offline cache miss for node '0:0'. Now it raises FigmaError
    with an actionable message (copy full URL from Figma).
    """
    with pytest.raises(FigmaError) as excinfo:
        parse_figma_url("abc123def")
    assert "no node-id" in str(excinfo.value)


def test_parse_bare_key_invalid_format_still_rejected() -> None:
    """Short/non-alphanumeric bare keys are rejected as before."""
    with pytest.raises(FigmaError):
        parse_figma_url("short")


def test_parse_full_url_with_node_id_still_works() -> None:
    """Full URLs with node-id parse normally (not affected by the fix)."""
    ref = parse_figma_url("https://www.figma.com/design/ABCDEF/Title?node-id=1732:5574")
    assert ref.file_key == "ABCDEF"
    assert ref.node_id == "1732:5574"


def test_parse_url_missing_node_id() -> None:
    with pytest.raises(FigmaError):
        parse_figma_url("https://www.figma.com/design/ABCDEF/Title")


def test_parse_url_invalid_node_id_dot_separator() -> None:
    """A dot-separated node-id (1732.5574) must be rejected as invalid."""
    with pytest.raises(FigmaError) as excinfo:
        parse_figma_url("https://www.figma.com/design/ABCDEF/Title?node-id=1732.5574")
    assert "invalid node-id" in str(excinfo.value)


def test_parse_url_invalid_node_id_underscore() -> None:
    """An underscore node-id must be rejected as invalid."""
    with pytest.raises(FigmaError):
        parse_figma_url("https://www.figma.com/design/ABCDEF/Title?node-id=1732_5574")


def test_parse_url_dash_node_id_converts_to_colon() -> None:
    """URL form uses '-' as separator; API form uses ':'. Both accepted."""
    ref = parse_figma_url("https://www.figma.com/design/ABCDEF/Title?node-id=1732-5574")
    assert ref.node_id == "1732:5574"


def test_token_required(monkeypatch: pytest.MonkeyPatch) -> None:
    # When no token anywhere (arg empty AND env unset AND config empty)
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    # FIX: resolve_token also checks ~/.avocado/config.yaml, so mock it
    monkeypatch.setattr("avocado.paths.load_user_config", lambda: {})
    with pytest.raises(FigmaAuthError):
        FigmaClient(token="")


def test_verify_token(client: FigmaClient) -> None:
    me = client.verify_token()
    assert "id" in me or "handle" in me  # API may differ


def test_get_node_confirm_frame(client: FigmaClient) -> None:
    ref = parse_figma_url(TEST_URL)
    doc = client.get_node(ref)
    assert doc["type"] == "FRAME"
    assert doc["name"] == "Confirm"
    assert len(doc["children"]) >= 1
