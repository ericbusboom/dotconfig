"""Tests for the locked-key guard (temp SOPS_AGE_KEY_FILE only; never the real key)."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dotconfig import keyguard, keystore
from dotconfig.key import get_key, load_key, pub_key, save_key, gen_key
from dotconfig.load import _decrypt_sops, load_config, load_file
from dotconfig.reencrypt import reencrypt_all
from dotconfig.save import _encrypt_sops, save_config, save_file


@pytest.fixture
def store(tmp_path, monkeypatch):
    d = tmp_path / "age"
    d.mkdir()
    kf = d / "keys.txt"
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(kf))
    monkeypatch.delenv("SOPS_AGE_KEY", raising=False)
    return kf


@pytest.fixture
def locked(store):
    (store.parent / "keys.txt.pass.age").write_bytes(b"x")
    return store


def test_locked_detection(store, monkeypatch):
    assert not keyguard.is_locked()  # no sidecar, no wrapped
    (store.parent / "keys.txt.pass.pending.age").write_bytes(b"x")
    assert not keyguard.is_locked()  # pending ignored
    (store.parent / "keys.txt.pass.age").write_bytes(b"x")
    assert keyguard.is_locked()
    monkeypatch.setenv("SOPS_AGE_KEY", "AGE-SECRET-KEY-1X")
    assert not keyguard.is_locked()
    monkeypatch.delenv("SOPS_AGE_KEY")
    store.write_text("AGE-SECRET-KEY-1X\n")
    assert not keyguard.is_locked()


def test_sidecar_only_is_locked(store):
    keystore.save_sidecar({"public_key": "age1abc", "methods": []})
    assert keyguard.is_locked()


def test_noninteractive_exits_75_with_message(locked, capsys):
    with pytest.raises(SystemExit) as e:
        keyguard.require_unlocked()
    assert e.value.code == 75
    assert "age key is locked — run: dotconfig unlock" in capsys.readouterr().err


def test_unlocked_noop(store):
    keyguard.require_unlocked()


def test_tty_accept_unlocks(locked, monkeypatch):
    monkeypatch.setattr(keyguard, "_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    with patch("dotconfig.keywrap.unlock") as unlock:
        keyguard.require_unlocked()
    unlock.assert_called_once()


def test_tty_decline_exits_75(locked, monkeypatch):
    monkeypatch.setattr(keyguard, "_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    with patch("dotconfig.keywrap.unlock") as unlock:
        with pytest.raises(SystemExit) as e:
            keyguard.require_unlocked()
    assert e.value.code == 75
    unlock.assert_not_called()


def test_tty_unlock_failure_exits_75(locked, monkeypatch):
    from dotconfig import keywrap
    monkeypatch.setattr(keyguard, "_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    with patch("dotconfig.keywrap.unlock", side_effect=keywrap.UnlockError("no")):
        with pytest.raises(SystemExit) as e:
            keyguard.require_unlocked()
    assert e.value.code == 75


def test_decrypt_and_encrypt_blocked_before_sops(locked, tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("a: 1\n")
    with patch("subprocess.run") as run:
        with pytest.raises(SystemExit) as e:
            _decrypt_sops(f)
        assert e.value.code == 75
        with pytest.raises(SystemExit) as e:
            _encrypt_sops("a: 1\n", f)
        assert e.value.code == 75
    run.assert_not_called()
    assert f.read_text() == "a: 1\n"  # not rewritten


def test_reencrypt_blocked(locked, tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "s.yaml").write_text("ENC")
    with patch("dotconfig.reencrypt._is_sops_encrypted", return_value=True), \
         patch("dotconfig.reencrypt._decrypt_sops") as dec:
        with pytest.raises(SystemExit) as e:
            reencrypt_all(cfg)
    assert e.value.code == 75
    dec.assert_not_called()


def test_key_get_load_pub_blocked(locked, tmp_path):
    cfg = tmp_path / "config"
    keys = cfg / "keys"
    keys.mkdir(parents=True)
    (keys / "k").write_text("ENC")
    with patch("dotconfig.key._is_sops_encrypted", return_value=True), \
         patch("dotconfig.key._decrypt_sops") as dec:
        for fn in (lambda: get_key("k", cfg, to_stdout=True),
                   lambda: load_key("k", cfg, tmp_path / "out"),
                   lambda: pub_key("k", cfg)):
            with pytest.raises(SystemExit) as e:
                fn()
            assert e.value.code == 75
    dec.assert_not_called()


def test_load_file_encrypted_blocked(locked, tmp_path):
    cfg = tmp_path / "config"
    (cfg / "dev").mkdir(parents=True)
    (cfg / "dev" / "app.yaml").write_text("sops:\n  version: 3\nfoo: ENC[x]\n")
    with patch("subprocess.run") as run:
        with pytest.raises(SystemExit) as e:
            load_file("dev", None, "app.yaml", cfg, None, True)
    assert e.value.code == 75
    run.assert_not_called()


def test_plain_load_unaffected_when_locked(locked, tmp_path):
    cfg = tmp_path / "config"
    (cfg / "dev").mkdir(parents=True)
    (cfg / "dev" / "public.env").write_text("A=1\n")
    out = tmp_path / ".env"
    load_config("dev", None, cfg, out)
    assert "A=1" in out.read_text()
