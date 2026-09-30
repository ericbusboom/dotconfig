"""Decrypted secret files are written 0600 atomically."""

import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from dotconfig.key import load_key
from dotconfig.load import load_config


def mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    cfg = tmp_path / "config"
    (cfg / "prod").mkdir(parents=True)
    (cfg / "prod" / "public.env").write_text("APP=1\n")
    (cfg / "prod" / "secrets.env").write_text("SECRET=ENC[x]\nsops_version=3\n")
    return cfg


def _dec(*_a, **_k):
    return "SECRET=real\n"


def test_load_env_mode(config_dir, tmp_path):
    out = tmp_path / ".env"
    with patch("dotconfig.load._decrypt_sops", side_effect=_dec):
        load_config("prod", None, config_dir, out)
    assert mode(out) == 0o600
    assert not list(tmp_path.glob(".*.tmp"))


def test_load_split_mode(config_dir, tmp_path):
    out = tmp_path / ".env"
    with patch("dotconfig.load._decrypt_sops", side_effect=_dec):
        load_config("prod", None, config_dir, out, split=True)
    assert mode(out) == 0o600
    assert mode(tmp_path / ".env.secret") == 0o600


def test_load_public_mode(config_dir, tmp_path):
    out = tmp_path / ".env"
    load_config("prod", None, config_dir, out, public_only=True)
    assert mode(out) == 0o600


def test_existing_loose_env_tightened(config_dir, tmp_path, capsys):
    out = tmp_path / ".env"
    out.write_text("OLD=1\n")
    out.chmod(0o644)
    with patch("dotconfig.load._decrypt_sops", side_effect=_dec):
        load_config("prod", None, config_dir, out)
    assert mode(out) == 0o600
    assert "SECRET=real" in out.read_text()
    assert "Tightened permissions" in capsys.readouterr().out


def test_existing_0600_env_no_message(config_dir, tmp_path, capsys):
    out = tmp_path / ".env"
    out.write_text("OLD=1\n")
    out.chmod(0o600)
    with patch("dotconfig.load._decrypt_sops", side_effect=_dec):
        load_config("prod", None, config_dir, out)
    assert "Tightened" not in capsys.readouterr().out


def test_key_load_mode(config_dir):
    keys = config_dir / "keys"
    keys.mkdir()
    (keys / "deploy").write_text("PLAIN KEY")
    with patch("dotconfig.key._is_sops_encrypted", return_value=False):
        load_key("deploy", config_dir=config_dir)
    assert mode(config_dir / "files" / "deploy") == 0o600
