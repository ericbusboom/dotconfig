"""Tests for dotconfig.keywrap (temp SOPS_AGE_KEY_FILE only; never the real key)."""

import shutil
import subprocess

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
    """A plain age identity standing in for an offline recovery key."""
    secret, pub, text = _gen()
    idf = tmp_path / "recovery-id.txt"
    idf.write_text(text)
    return idf, pub


@pytest.fixture
def fake_passphrase(monkeypatch):
    """Stub the age passphrase prompts via the runner seam (no TTY needed)."""
    real = keystore.runner

    def runner(cmd, input=None, interactive=False):
        if cmd[:2] == ["age", "-p"]:
            return subprocess.CompletedProcess(cmd, 0, b"PASS:" + input, b"")
        if cmd[:2] == ["age", "-d"] and "-i" not in cmd:
            blob = open(cmd[-1], "rb").read()
            if blob.startswith(b"PASS:"):
                return subprocess.CompletedProcess(cmd, 0, blob[5:], b"")
            return subprocess.CompletedProcess(cmd, 1, b"", b"bad passphrase")
        return real(cmd, input=input, interactive=interactive)

    monkeypatch.setattr(keystore, "runner", runner)


def _recovery_spec(recovery, label="recovery"):
    idf, pub = recovery
    return keywrap.MethodSpec("identity", keywrap.slugify_label(label), pub, label, idf)


def test_wrap_identity_success(store, recovery):
    kf, secret, pub = store
    before = kf.read_text()
    res = keywrap.wrap([_recovery_spec(recovery)], today="2026-10-01")
    assert [r.ok for r in res] == [True]
    wrapped = kf.parent / "keys.txt.recovery.age"
    assert wrapped.exists()
    assert (wrapped.stat().st_mode & 0o777) == 0o600
    sc = keystore.load_sidecar()
    assert sc["public_key"] == pub
    (m,) = sc["methods"]
    assert m["file"] == "keys.txt.recovery.age"
    assert m["kind"] == "identity"
    assert m["recipient"] == recovery[1]
    assert m["label"] == "recovery"
    assert m["verified"] == "2026-10-01"
    assert kf.read_text() == before
    assert not list(kf.parent.glob("*pending*"))


def test_failed_verification_deletes_file_and_others_unaffected(store, recovery):
    kf, secret, pub = store
    _, other_pub, _ = _gen()
    idf, _ = recovery
    # encrypted to a recipient the identity cannot open -> round trip fails
    bad = keywrap.MethodSpec("identity", "bad", other_pub, "bad", idf)
    good = _recovery_spec(recovery)
    res = keywrap.wrap([bad, good])
    assert [r.ok for r in res] == [False, True]
    assert not (kf.parent / "keys.txt.bad.age").exists()
    assert not list(kf.parent.glob("*pending*"))
    files = [m["file"] for m in keystore.load_sidecar()["methods"]]
    assert files == ["keys.txt.recovery.age"]


def test_no_overwrite_with_unverified(store, recovery):
    kf, secret, pub = store
    assert keywrap.wrap([_recovery_spec(recovery)])[0].ok
    wrapped = kf.parent / "keys.txt.recovery.age"
    good_bytes = wrapped.read_bytes()
    sidecar_before = keystore.sidecar_path().read_text()
    _, other_pub, _ = _gen()
    bad = keywrap.MethodSpec("identity", "recovery", other_pub, "recovery", recovery[0])
    res = keywrap.wrap([bad])
    assert not res[0].ok
    assert wrapped.read_bytes() == good_bytes
    assert keystore.sidecar_path().read_text() == sidecar_before
    assert not list(kf.parent.glob("*pending*"))


def test_rewrap_replaces_after_verification(store, recovery):
    kf, _, _ = store
    keywrap.wrap([_recovery_spec(recovery)], today="2026-10-01")
    old = (kf.parent / "keys.txt.recovery.age").read_bytes()
    assert keywrap.wrap([_recovery_spec(recovery)], today="2026-10-02")[0].ok
    assert (kf.parent / "keys.txt.recovery.age").read_bytes() != old
    (m,) = keystore.load_sidecar()["methods"]
    assert m["verified"] == "2026-10-02"


def test_mismatched_sidecar_public_key_refuses(store, recovery):
    kf, _, _ = store
    keystore.save_sidecar({"public_key": "age1other", "methods": []})
    with pytest.raises(keywrap.WrapError, match="differs"):
        keywrap.wrap([_recovery_spec(recovery)])
    assert not list(kf.parent.glob("*.age"))


def test_missing_plain_key_suggests_unlock(store, recovery):
    kf, _, _ = store
    kf.unlink()
    with pytest.raises(keywrap.WrapError, match="dotconfig age unlock"):
        keywrap.wrap([_recovery_spec(recovery)])


def test_add_second_method_preserves_first(store, recovery, fake_passphrase):
    kf, _, pub = store
    assert keywrap.wrap([_recovery_spec(recovery)])[0].ok
    first = (kf.parent / "keys.txt.recovery.age").read_bytes()
    spec = keywrap.MethodSpec("passphrase", "pass", None, "passphrase")
    assert keywrap.wrap([spec])[0].ok
    assert (kf.parent / "keys.txt.recovery.age").read_bytes() == first
    assert (kf.parent / "keys.txt.pass.age").exists()
    sc = keystore.load_sidecar()
    assert [m["kind"] for m in sc["methods"]] == ["identity", "passphrase"]
    assert "recipient" not in sc["methods"][1]
    assert sc["public_key"] == pub


def test_passphrase_failure_deletes_file(store, monkeypatch):
    kf, _, _ = store
    real = keystore.runner

    def runner(cmd, input=None, interactive=False):
        if cmd[:2] == ["age", "-p"]:
            return subprocess.CompletedProcess(cmd, 0, b"PASS:" + input, b"")
        if cmd[:2] == ["age", "-d"]:
            return subprocess.CompletedProcess(cmd, 1, b"", b"wrong passphrase")
        return real(cmd, input=input, interactive=interactive)

    monkeypatch.setattr(keystore, "runner", runner)
    spec = keywrap.MethodSpec("passphrase", "pass", None, "passphrase")
    res = keywrap.wrap([spec])
    assert not res[0].ok
    assert not (kf.parent / "keys.txt.pass.age").exists()
    assert keystore.load_sidecar()["methods"] == []


def test_missing_plugin_reports_install_and_key_untouched(store, recovery, monkeypatch):
    kf, _, _ = store
    before = kf.read_text()
    real_which = shutil.which
    monkeypatch.setattr(
        keystore.shutil, "which",
        lambda b, *a, **k: None if b == "age-plugin-se" else real_which(b, *a, **k),
    )
    spec = keywrap.MethodSpec("se", "se", "age1se1qqq", "Secure Enclave", recovery[0])
    res = keywrap.wrap([spec])
    assert not res[0].ok
    assert "brew install remko/age-plugin-se/age-plugin-se" in res[0].error
    assert kf.read_text() == before
    assert not (kf.parent / "keys.txt.se.age").exists()


def test_identity_roundtrip_uses_identity_flag(store, recovery, monkeypatch):
    seen = []
    real = keystore.runner

    def runner(cmd, input=None, interactive=False):
        seen.append(cmd)
        return real(cmd, input=input, interactive=interactive)

    monkeypatch.setattr(keystore, "runner", runner)
    assert keywrap.wrap([_recovery_spec(recovery)])[0].ok
    dec = [c for c in seen if c[:2] == ["age", "-d"]]
    assert dec and dec[0][2] == "-i" and dec[0][3] == str(recovery[0])


def test_build_specs_validation(store, recovery):
    with pytest.raises(keywrap.WrapError, match="nothing to wrap"):
        keywrap.build_specs()
    with pytest.raises(keywrap.WrapError, match="together"):
        keywrap.build_specs(recipient="age1x")
    with pytest.raises(keywrap.WrapError, match="--se needs the plugin recipient"):
        keywrap.build_specs(se=True)
    with pytest.raises(keywrap.WrapError, match="reserved"):
        keywrap.build_specs(recipient="age1x", label="SE", identity=recovery[0])
    (s,) = keywrap.build_specs(recipient="age1x", label="My USB Drive!",
                               identity=recovery[0])
    assert s.method_id == "my-usb-drive" and s.kind == "identity"


def test_cli_key_wrap_success_and_failure(store, recovery):
    kf, _, _ = store
    idf, pub = recovery
    r = CliRunner().invoke(cli, ["age", "wrap", "--recipient", pub, "--label",
                                 "recovery", "--identity", str(idf)])
    assert r.exit_code == 0, r.output
    assert (kf.parent / "keys.txt.recovery.age").exists()
    _, other_pub, _ = _gen()
    r = CliRunner().invoke(cli, ["age", "wrap", "--recipient", other_pub,
                                 "--label", "bad", "--identity", str(idf)])
    assert r.exit_code != 0
    assert not (kf.parent / "keys.txt.bad.age").exists()
    kf.unlink()
    r = CliRunner().invoke(cli, ["age", "wrap", "--passphrase"])
    assert r.exit_code != 0
