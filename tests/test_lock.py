"""Tests for `dotconfig lock` (temp SOPS_AGE_KEY_FILE only; never the real key)."""

import builtins
import shutil
import subprocess
import sys

import pytest
from click.testing import CliRunner

from dotconfig import keystore, keywrap
from dotconfig.cli import cli

pytestmark = pytest.mark.skipif(
    shutil.which("age") is None or shutil.which("age-keygen") is None,
    reason="age not installed",
)


def _gen():
    out = subprocess.run(["age-keygen"], capture_output=True, text=True, check=True)
    text = out.stdout
    secret = [l for l in text.splitlines() if l.startswith("AGE-SECRET-KEY-")][0]
    pub = [l for l in (out.stdout + out.stderr).splitlines() if "ublic key:" in l][0]
    return secret, pub.split()[-1], text


@pytest.fixture
def store(tmp_path, monkeypatch):
    d = tmp_path / "age"
    d.mkdir(mode=0o700)
    kf = d / "keys.txt"
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(kf))
    secret, pub, _ = _gen()
    kf.write_text(secret + "\n")
    kf.chmod(0o600)
    return kf, secret, pub


@pytest.fixture
def recovery(tmp_path):
    secret, pub, text = _gen()
    idf = tmp_path / "recovery-id.txt"
    idf.write_text(text)
    return idf, pub


@pytest.fixture
def wrapped(store, recovery):
    kf, secret, pub = store
    idf, rpub = recovery
    res = keywrap.wrap([keywrap.MethodSpec("identity", "recovery", rpub, "recovery", idf)])
    assert all(r.ok for r in res)
    return kf, secret, pub, idf


def _lock(*args):
    return CliRunner().invoke(cli, ["lock", *args])


def test_lock_succeeds_with_wrapped_and_sidecar(wrapped):
    kf, secret, pub, _ = wrapped
    r = _lock()
    assert r.exit_code == 0, r.output
    assert not kf.exists()
    assert secret not in r.output
    assert "recovery" in r.output


def test_already_locked_exit_zero(store):
    kf, _, _ = store
    kf.unlink()
    r = _lock()
    assert r.exit_code == 0
    assert "already locked" in r.output


def test_refuses_without_wrapped_file(store):
    kf, _, pub = store
    keystore.save_sidecar({"public_key": pub, "methods": []})
    r = _lock()
    assert r.exit_code != 0
    assert kf.exists()
    assert "dotconfig key wrap" in r.output


def test_refuses_without_sidecar(store, recovery):
    kf, _, _ = store
    (kf.parent / "keys.txt.recovery.age").write_bytes(b"x")
    r = _lock()
    assert r.exit_code != 0
    assert kf.exists()
    assert "dotconfig key wrap" in r.output


def test_refuses_on_public_key_mismatch(wrapped):
    kf, _, _, _ = wrapped
    sc = keystore.load_sidecar()
    sc["public_key"] = "age1other"
    keystore.save_sidecar(sc)
    r = _lock()
    assert r.exit_code != 0
    assert kf.exists()
    assert "differs" in r.output


def test_refuses_when_wrapped_file_missing(wrapped):
    kf, _, _, _ = wrapped
    (kf.parent / "keys.txt.recovery.age").unlink()
    r = _lock()
    assert r.exit_code != 0
    assert kf.exists()


def test_force_deletes_and_warns(store):
    kf, _, _ = store
    r = _lock("--force")
    assert r.exit_code == 0, r.output
    assert not kf.exists()
    assert "UNRECOVERABLE" in r.output


def test_verified_not_gating(wrapped):
    kf, _, _, _ = wrapped
    sc = keystore.load_sidecar()
    for m in sc["methods"]:
        m.pop("verified", None)
    keystore.save_sidecar(sc)
    assert _lock().exit_code == 0
    assert not kf.exists()


def test_zero_fill_before_unlink(store, monkeypatch):
    kf, secret, _ = store
    seen = {}
    real_unlink = type(kf).unlink

    def spy(self, *a, **k):
        if self == kf:
            seen["content"] = kf.read_bytes()
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(type(kf), "unlink", spy)
    keywrap.scrub_file(kf)
    assert set(seen["content"]) == {0}
    assert not kf.exists()


def test_never_reads_stdin_or_prompts(wrapped, monkeypatch):
    kf, _, _, _ = wrapped

    def boom(*a, **k):
        raise AssertionError("prompted")

    monkeypatch.setattr(builtins, "input", boom)
    monkeypatch.setattr("getpass.getpass", boom)
    monkeypatch.setattr(sys, "stdin", None)
    r = _lock()
    assert r.exit_code == 0, r.output
    assert not kf.exists()


def test_wrap_records_identity_file_for_se_not_identity(store, recovery):
    kf, secret, pub = store
    idf, rpub = recovery
    res = keywrap.wrap([
        keywrap.MethodSpec("se", "se", rpub, "Secure Enclave", idf),
        keywrap.MethodSpec("identity", "recovery", rpub, "recovery", idf),
    ])
    assert all(r.ok for r in res)
    by_kind = {m["kind"]: m for m in keystore.load_sidecar()["methods"]}
    assert by_kind["se"]["identity_file"] == str(idf.resolve())
    assert "identity_file" not in by_kind["identity"]


def test_wrap_then_unlock_with_se_needs_no_identity(store, recovery, monkeypatch):
    kf, secret, pub = store
    idf, rpub = recovery
    # plain age identity standing in for the SE plugin identity
    res = keywrap.wrap([keywrap.MethodSpec("se", "se", rpub, "Secure Enclave", idf)])
    assert all(r.ok for r in res)
    assert _lock().exit_code == 0
    assert not kf.exists()
    r = CliRunner().invoke(cli, ["unlock", "--with", "se"])
    assert r.exit_code == 0, r.output
    assert kf.read_text().strip() == secret
