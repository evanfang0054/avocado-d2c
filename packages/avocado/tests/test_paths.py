"""Tests for the 4-layer lookup in paths.py."""

from pathlib import Path

from avocado import paths


def test_resolve_output_dir_default(monkeypatch, tmp_path):
    """Default is ~/.avocado/output/."""
    fake_home = tmp_path / "fakehome"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    result = paths.resolve_output_dir()
    assert result == fake_home / ".avocado" / "output"


def test_resolve_output_dir_cli_overrides(monkeypatch, tmp_path):
    """CLI flag has the highest priority."""
    result = paths.resolve_output_dir(cli_path=str(tmp_path / "custom"))
    assert result == tmp_path / "custom"


def test_resolve_output_dir_project_level_overrides_user(monkeypatch, tmp_path):
    """cwd/.avocado/output/ overrides ~/.avocado/output/."""
    fake_home = tmp_path / "fakehome"
    cwd = tmp_path / "project"
    (cwd / ".avocado" / "output").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(Path, "cwd", lambda: cwd)
    result = paths.resolve_output_dir()
    assert result == cwd / ".avocado" / "output"


def test_resolve_preset_4_layers(monkeypatch, tmp_path):
    """preset 4-layer lookup: CLI > cwd/.avocado/presets/ > ~/.avocado/presets/ > bundled."""
    fake_home = tmp_path / "fakehome"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    # The bundled default always exists (_bundled/presets/antd.yaml), so it is always found
    result = paths.resolve_preset("antd")
    assert result.name == "antd.yaml"


def test_resolve_preset_cli_overrides(monkeypatch, tmp_path):
    """CLI --preset path is used directly."""
    custom = tmp_path / "custom-antd.yaml"
    custom.write_text("components: []")
    result = paths.resolve_preset("antd", cli_path=str(custom))
    assert result == custom


def test_ensure_user_dirs_creates_structure(monkeypatch, tmp_path):
    """First run creates ~/.avocado/{output,presets,var-maps,plugins}."""
    fake_home = tmp_path / "fakehome"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    avocado_root = paths.ensure_user_dirs()
    assert avocado_root == fake_home / ".avocado"
    assert (avocado_root / "output").is_dir()
    assert (avocado_root / "presets").is_dir()
    assert (avocado_root / "var-maps").is_dir()
    assert (avocado_root / "plugins").is_dir()


def test_ensure_user_dirs_idempotent(monkeypatch, tmp_path):
    """Repeated calls do not raise."""
    fake_home = tmp_path / "fakehome"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    paths.ensure_user_dirs()
    paths.ensure_user_dirs()  # no error
    assert paths.ensure_user_dirs().is_dir()


def test_resolve_token_from_user_config(monkeypatch, tmp_path):
    """Token is read from ~/.avocado/config.yaml (4-layer lookup)."""
    fake_home = tmp_path / "fakehome"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    cfg = fake_home / ".avocado" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('figma_token: "figd_fake123"\n')
    assert paths.resolve_token() == "figd_fake123"


def test_resolve_token_cli_overrides_config(monkeypatch, tmp_path):
    """CLI flag token has the highest priority."""
    fake_home = tmp_path / "fakehome"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    cfg = fake_home / ".avocado" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('figma_token: "figd_from_config"\n')
    assert paths.resolve_token(cli_token="figd_from_cli") == "figd_from_cli"


def test_resolve_token_none_when_no_source(monkeypatch, tmp_path):
    """Returns None when there is no source."""
    fake_home = tmp_path / "fakehome"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    assert paths.resolve_token() is None


def test_resolve_token_env_overrides_config(monkeypatch, tmp_path):
    """Environment variable takes precedence over config.yaml."""
    fake_home = tmp_path / "fakehome"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("FIGMA_TOKEN", "figd_from_env")
    cfg = fake_home / ".avocado" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('figma_token: "figd_from_config"\n')
    assert paths.resolve_token() == "figd_from_env"
