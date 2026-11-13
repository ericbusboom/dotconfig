import importlib
from pathlib import Path

import pytest

from dotconfig import keystore, paths


def test_key_path_env_override(monkeypatch, tmp_path):
    kf = tmp_path / "k.txt"
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(kf))
    assert paths.key_path() == kf
    assert paths.key_path_source() == "env"
    loc = {l.name: l for l in paths.user_locations()}["age key file"]
    assert loc.source == "env" and loc.path == kf and not loc.exists


def test_key_path_default(monkeypatch):
    monkeypatch.delenv("SOPS_AGE_KEY_FILE")
    assert paths.key_path() == Path.home() / ".config/sops/age/keys.txt"
    assert paths.key_path_source() == "default"


@pytest.mark.parametrize("xdg", [None, ""])
def test_user_config_default(monkeypatch, xdg):
    if xdg is None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
    assert paths.user_config_path() == Path.home() / ".config/dotconfig/config.yaml"
    assert paths.user_config_path_and_source()[1] == "default"


def test_user_config_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert paths.user_config_path() == tmp_path / "dotconfig/config.yaml"
    assert paths.user_config_path_and_source()[1] == "env"


def test_keystore_delegates_and_no_cycle(monkeypatch, tmp_path):
    kf = tmp_path / "keys.txt"
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(kf))
    assert keystore.key_path() == kf
    assert keystore.wrapped_path("pw") == tmp_path / "keys.txt.pw.age"
    assert keystore.sidecar_path() == tmp_path / "keys.txt.lock.yaml"
    importlib.reload(paths)  # paths must import without keystore


def test_inline_key_noted(monkeypatch):
    monkeypatch.setenv("SOPS_AGE_KEY", "AGE-SECRET-KEY-x")
    names = [l.name for l in paths.user_locations()]
    assert "age key (inline)" in names


def test_wrapped_listed(monkeypatch, tmp_path):
    kf = tmp_path / "keys.txt"
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(kf))
    (tmp_path / "keys.txt.pw.age").write_text("x")
    locs = [l for l in paths.user_locations() if l.name == "wrapped key"]
    assert locs[0].exists and locs[0].path.name == "keys.txt.pw.age"


def test_project_locations(tmp_path):
    root = tmp_path / "config"
    root.mkdir()
    (root / "sops.yaml").write_text("x")
    (tmp_path / ".env").write_text("x")
    locs = {l.name: l for l in paths.project_locations(root)}
    assert locs["sops.yaml"].exists
    assert not locs["dotconfig.yaml"].exists
    assert locs[".env"].exists and locs[".env"].path == tmp_path.resolve() / ".env"
    for n in ("AGENTS.md", "keys/", "files/", ".gitignore", ".gitattributes",
              "local public.env", "deploy secrets.env", ".env.secret"):
        assert n in locs


def test_all_locations_without_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    names = [l.name for l in paths.all_locations()]
    assert "config root" not in names and "user config" in names
