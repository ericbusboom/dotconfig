"""Tests for dotconfig.keystore (temp SOPS_AGE_KEY_FILE only; never the real key)."""

import os
import shutil
import stat
import subprocess

import pytest

from dotconfig import keystore

needs_age = pytest.mark.skipif(
    shutil.which("age") is None or shutil.which("age-keygen") is None,
    reason="age not installed",
)


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    d = tmp_path / "age"
    d.mkdir(mode=0o700)
    kf = d / "keys.txt"
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(kf))
    return kf


def _gen():
    out = subprocess.run(["age-keygen"], capture_output=True, text=True, check=True)
    secret = [l for l in out.stdout.splitlines() if l.startswith("AGE-SECRET-KEY-")][0]
    pub = [l for l in (out.stdout + out.stderr).splitlines() if "ublic key:" in l][0]
    return secret, pub.split()[-1]


def test_paths(keyfile):
    assert keystore.key_path() == keyfile
    assert keystore.wrapped_path("se") == keyfile.parent / "keys.txt.se.age"
    assert keystore.sidecar_path() == keyfile.parent / "keys.txt.lock.yaml"


def test_default_path(monkeypatch):
    monkeypatch.delenv("SOPS_AGE_KEY_FILE", raising=False)
    assert str(keystore.key_path()).endswith(".config/sops/age/keys.txt")


def test_sidecar_missing_is_empty(keyfile):
    assert keystore.load_sidecar() == {"public_key": None, "methods": []}


def test_sidecar_round_trip(keyfile):
    sc = {
        "public_key": "age1abc",
        "methods": [
            {"file": "keys.txt.se.age", "kind": "se", "recipient": "age1se1x",
             "label": "Mac", "verified": "2026-10-01"},
            {"file": "keys.txt.pass.age", "kind": "passphrase", "label": "pw"},
        ],
    }
    keystore.save_sidecar(sc)
    assert keystore.load_sidecar() == sc
    assert "AGE-SECRET-KEY" not in keystore.sidecar_path().read_text()
    assert not [p for p in keyfile.parent.iterdir() if p.name.endswith(".tmp")]


def test_write_plain_key_atomic_0600(tmp_path, monkeypatch):
    kf = tmp_path / "newdir" / "keys.txt"
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(kf))
    path = keystore.write_plain_key("AGE-SECRET-KEY-1FAKE")
    assert path == kf
    assert kf.read_text() == "AGE-SECRET-KEY-1FAKE\n"
    assert stat.S_IMODE(kf.stat().st_mode) == 0o600
    assert [p.name for p in kf.parent.iterdir()] == ["keys.txt"]


def test_write_plain_key_overwrites_and_never_prints(keyfile, capsys):
    keyfile.write_text("old")
    keystore.write_plain_key("AGE-SECRET-KEY-1NEW")
    cap = capsys.readouterr()
    assert "AGE-SECRET-KEY" not in cap.out + cap.err
    assert keyfile.read_text() == "AGE-SECRET-KEY-1NEW\n"


def test_dir_permission_warning(keyfile, capsys):
    os.chmod(keyfile.parent, 0o755)
    keystore.write_plain_key("AGE-SECRET-KEY-1X")
    assert "group/world" in capsys.readouterr().err


def test_no_warning_when_private(keyfile, capsys):
    keystore.write_plain_key("AGE-SECRET-KEY-1X")
    assert capsys.readouterr().err == ""


def test_failed_write_leaves_no_temp(keyfile, monkeypatch):
    def boom(*a, **k):
        raise OSError("nope")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        keystore.write_plain_key("AGE-SECRET-KEY-1X")
    assert list(keyfile.parent.iterdir()) == []


def test_missing_plugin_message(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda b: None if "plugin" in b else "/x/" + b)
    with pytest.raises(keystore.AgeToolError, match="age-plugin-yubikey.*Install it with"):
        keystore.age_encrypt_to_recipient(b"x", "age1yubikey1qabc")


def test_missing_age_message(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda b: None)
    with pytest.raises(keystore.AgeToolError, match="brew install age"):
        keystore.public_key_of("AGE-SECRET-KEY-1X")


def test_runner_seam_is_used(monkeypatch):
    calls = []

    def fake(cmd, input=None, interactive=False):
        calls.append((cmd, input, interactive))
        return subprocess.CompletedProcess(cmd, 0, stdout=b"CT", stderr=b"")

    monkeypatch.setattr(shutil, "which", lambda b: "/x/" + b)
    monkeypatch.setattr(keystore, "runner", fake)
    assert keystore.age_encrypt_to_recipient(b"pt", "age1abc") == b"CT"
    assert keystore.age_encrypt_passphrase(b"pt") == b"CT"
    assert calls[0][0] == ["age", "-r", "age1abc"]
    assert calls[1][0] == ["age", "-p"] and calls[1][2] is True


def test_locked_error_constants():
    assert keystore.EXIT_LOCKED == 75
    assert keystore.LockedKeyError().exit_code == 75
    assert "dotconfig unlock" in str(keystore.LockedKeyError())


@needs_age
def test_public_key_and_identity_round_trip(keyfile, tmp_path):
    secret, pub = _gen()
    assert keystore.public_key_of(secret) == pub
    # wrapper identity: plain age key stands in for a plugin
    wsecret, wpub = _gen()
    ident = tmp_path / "ident.txt"
    ident.write_text(wsecret + "\n")
    ct = keystore.age_encrypt_to_recipient(secret.encode(), wpub)
    wp = keystore.write_wrapped("recovery", ct)
    assert wp == keyfile.parent / "keys.txt.recovery.age"
    assert keystore.age_decrypt_identity(wp, ident).decode().strip() == secret


@needs_age
def test_decrypt_wrong_identity_fails(tmp_path):
    secret, _ = _gen()
    _, wpub = _gen()
    other, _ = _gen()
    ident = tmp_path / "other.txt"
    ident.write_text(other + "\n")
    wp = tmp_path / "x.age"
    wp.write_bytes(keystore.age_encrypt_to_recipient(secret.encode(), wpub))
    with pytest.raises(keystore.AgeToolError):
        keystore.age_decrypt_identity(wp, ident)
