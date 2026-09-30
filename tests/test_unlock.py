"""Tests for `dotconfig age unlock` (temp SOPS_AGE_KEY_FILE only; never the real key)."""

import os
import pty
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
def fake_passphrase(monkeypatch):
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


@pytest.fixture
def locked(store, recovery, fake_passphrase):
    """Key wrapped with passphrase + recovery identity, then plain key removed."""
    kf, secret, pub = store
    idf, rpub = recovery
    res = keywrap.wrap([
        keywrap.MethodSpec("passphrase", "pass", None, "passphrase"),
        keywrap.MethodSpec("identity", "recovery", rpub, "recovery", idf),
    ])
    assert all(r.ok for r in res)
    kf.unlink()
    return kf, secret, pub, idf


def _unlock(*args):
    return CliRunner().invoke(cli, ["age", "unlock", *args])


def test_already_unlocked(store):
    kf, secret, pub = store
    keystore.save_sidecar({"public_key": pub, "methods": []})
    r = _unlock()
    assert r.exit_code == 0
    assert "already unlocked" in r.output


def test_unlocked_key_mismatch_refuses_overwrite(store):
    kf, _, _ = store
    keystore.save_sidecar({"public_key": "age1other", "methods": []})
    r = _unlock()
    assert r.exit_code != 0
    assert "refusing" in r.output


def test_default_order_passphrase_when_no_gui(locked, monkeypatch):
    kf, secret, pub, _ = locked
    monkeypatch.setattr(keywrap, "is_gui_session", lambda: False)
    r = _unlock()
    assert r.exit_code == 0, r.output
    assert kf.read_text().strip() == secret
    assert (kf.stat().st_mode & 0o777) == 0o600
    assert secret not in r.output
    assert not list(kf.parent.glob(".*.tmp"))


def test_default_order_se_then_yubikey_then_pass(locked, monkeypatch):
    kf, secret, pub, _ = locked
    tried = []
    monkeypatch.setattr(keywrap, "is_gui_session", lambda: True)
    monkeypatch.setattr(keywrap, "device_present", lambda k: True)
    # fake se + yubikey entries that fail to decrypt
    sc = keystore.load_sidecar()
    for kind in ("se", "yubikey"):
        (kf.parent / f"keys.txt.{kind}.age").write_bytes(b"junk")
        sc["methods"].append({"file": f"keys.txt.{kind}.age", "kind": kind})
    keystore.save_sidecar(sc)
    real = keywrap._decrypt_method

    def spy(m, ident):
        tried.append(m.method_id)
        return real(m, ident)

    monkeypatch.setattr(keywrap, "_decrypt_method", spy)
    r = _unlock()
    assert r.exit_code == 0, r.output
    assert tried == ["se", "yubikey", "pass"]
    assert kf.read_text().strip() == secret


def test_se_skipped_without_gui_yubikey_skipped_without_device(locked, monkeypatch):
    kf, secret, pub, _ = locked
    sc = keystore.load_sidecar()
    for kind in ("se", "yubikey"):
        (kf.parent / f"keys.txt.{kind}.age").write_bytes(b"junk")
        sc["methods"].append({"file": f"keys.txt.{kind}.age", "kind": kind})
    keystore.save_sidecar(sc)
    monkeypatch.setattr(keywrap, "is_gui_session", lambda: False)
    monkeypatch.setattr(keywrap, "device_present", lambda k: False)
    tried = []
    real = keywrap._decrypt_method
    monkeypatch.setattr(keywrap, "_decrypt_method",
                        lambda m, i: (tried.append(m.method_id), real(m, i))[1])
    assert _unlock().exit_code == 0
    assert tried == ["pass"]


def test_with_selects_method_and_failure_lists_others(locked):
    kf, secret, pub, _ = locked
    r = _unlock("--with", "nosuch")
    assert r.exit_code != 0
    assert "pass" in r.output and "recovery" in r.output
    assert not kf.exists()


def test_with_pass(locked):
    kf, secret, _, _ = locked
    assert _unlock("--with", "pass").exit_code == 0
    assert kf.read_text().strip() == secret


def test_failure_lists_remaining_methods(locked, monkeypatch):
    kf, _, _, _ = locked
    monkeypatch.setattr(keywrap, "is_gui_session", lambda: False)
    (kf.parent / "keys.txt.pass.age").write_bytes(b"corrupt")
    r = _unlock()
    assert r.exit_code != 0
    assert "--with recovery" in r.output
    assert not kf.exists()


def test_identity_unlocks(locked):
    kf, secret, _, idf = locked
    r = _unlock("--identity", str(idf))
    assert r.exit_code == 0, r.output
    assert kf.read_text().strip() == secret
    assert (kf.stat().st_mode & 0o777) == 0o600


def test_wrong_identity_fails(locked, tmp_path):
    kf, _, _, _ = locked
    _, _, text = _gen()
    other = tmp_path / "other.txt"
    other.write_text(text)
    r = _unlock("--identity", str(other))
    assert r.exit_code != 0
    assert not kf.exists()


def test_public_key_mismatch_writes_nothing(store, recovery, fake_passphrase, tmp_path):
    kf, secret, pub = store
    idf, rpub = recovery
    keywrap.wrap([keywrap.MethodSpec("identity", "recovery", rpub, "recovery", idf)])
    kf.unlink()
    sc = keystore.load_sidecar()
    sc["public_key"] = "age1somethingelse"
    keystore.save_sidecar(sc)
    r = _unlock("--identity", str(idf))
    assert r.exit_code != 0
    assert "does not match" in r.output
    assert not kf.exists()


def test_creates_missing_directory(locked, monkeypatch):
    kf, secret, _, idf = locked
    new = kf.parent.parent / "fresh" / "nested" / "keys.txt"
    new.parent.mkdir(parents=True)
    for p in kf.parent.iterdir():
        shutil.copy(p, new.parent / p.name)
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(new))
    assert _unlock("--identity", str(idf)).exit_code == 0
    assert new.read_text().strip() == secret
    assert (new.stat().st_mode & 0o777) == 0o600


def test_write_creates_directory_when_missing(store, monkeypatch, tmp_path):
    new = tmp_path / "brand" / "new" / "keys.txt"
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(new))
    path = keystore.write_plain_key("AGE-SECRET-KEY-1X")
    assert path == new and new.exists()


def test_degraded_no_sidecar_identity(store, recovery):
    kf, secret, pub = store
    idf, rpub = recovery
    enc = subprocess.run(["age", "-r", rpub], input=secret.encode() + b"\n",
                         capture_output=True, check=True).stdout
    (kf.parent / "keys.txt.recovery.age").write_bytes(enc)
    kf.unlink()
    assert not keystore.sidecar_path().exists()
    r = _unlock("--identity", str(idf))
    assert r.exit_code == 0, r.output
    assert "degraded" in r.output
    assert kf.read_text().strip() == secret


def test_pending_leftovers_ignored(store, recovery):
    kf, secret, pub = store
    (kf.parent / "keys.txt.x.pending.age").write_bytes(b"junk")
    methods, from_sc = keywrap.list_wrapped()
    assert methods == [] and from_sc is False


def test_paste_without_tty_errors(locked):
    kf, _, _, _ = locked
    r = _unlock("--paste")
    assert r.exit_code != 0
    assert "TTY" in r.output
    assert not kf.exists()


def test_paste_and_identity_exclusive(locked):
    _, _, _, idf = locked
    assert _unlock("--paste", "--identity", str(idf)).exit_code != 0


def test_no_secret_input_options():
    params = {p.name for p in cli.commands["age"].commands["unlock"].params}
    assert params == {"with_method", "identity", "paste"}


def _run_pty(env, args, payload):
    code = "import sys; from dotconfig.cli import cli; cli()"
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, [sys.executable, "-c", code, *args], env)
    out = b""
    try:
        while b"hidden" not in out:  # wait for the prompt (getpass flushes input)
            out += os.read(fd, 4096)
        os.write(fd, payload)
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            out += chunk
    except OSError:
        pass
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), out.decode(errors="replace")


def test_paste_from_real_tty_no_echo(locked):
    kf, secret, pub, _ = locked
    env = dict(os.environ)
    code, out = _run_pty(env, ["age", "unlock", "--paste"], secret.encode() + b"\n")
    assert code == 0, out
    assert kf.read_text().strip() == secret
    assert secret not in out  # not echoed
    assert (kf.stat().st_mode & 0o777) == 0o600


def test_paste_wrong_key_mismatch(locked):
    kf, _, _, _ = locked
    other, _, _ = _gen()
    code, out = _run_pty(dict(os.environ), ["age", "unlock", "--paste"], other.encode() + b"\n")
    assert code != 0
    assert not kf.exists()


# ---------------------------------------------------------------------------
# unlock --identity with an encrypted identity: decrypt once, match by recipient
# ---------------------------------------------------------------------------

ENC_HEAD = b"age-encryption.org/v1\n-> scrypt fakesalt 18\nfakebody\n"


def _sidecar_with_se(kf, secret, pub, rpub, rplain, tmp_path):
    """Sidecar with se + pass + recovery; wrapped files are real for pass (fake
    runner) and recovery, and a dummy file for se."""
    res = keywrap.wrap([
        keywrap.MethodSpec("passphrase", "pass", None, "passphrase"),
        keywrap.MethodSpec("identity", "recovery", rpub, "recovery", rplain),
    ])
    assert all(r.ok for r in res), res
    se = keystore.wrapped_path("se")
    se.write_bytes(b"dummy se wrapped")
    sc = keystore.load_sidecar()
    sc["methods"].insert(0, {"file": se.name, "kind": "se",
                             "recipient": "age1se1qexample", "label": "se"})
    keystore.save_sidecar(sc)
    kf.unlink()


@pytest.fixture
def enc_setup(store, fake_passphrase, tmp_path, monkeypatch):
    """Encrypted-identity scenario driven by a counting fake runner."""
    kf, secret, pub = store
    rsecret, rpub, rtext = _gen()
    idf = tmp_path / "enc-id.txt"
    idf.write_bytes(ENC_HEAD)
    rplain = tmp_path / "rplain.txt"
    rplain.write_text(rtext)
    _sidecar_with_se(kf, secret, pub, rpub, rplain, tmp_path)
    calls = []
    state = {"plain": rtext.encode(), "fail": False}
    inner = keystore.runner

    def runner(cmd, input=None, interactive=False, **kw):
        calls.append((list(cmd), input))
        if cmd[:2] == ["age", "-d"] and cmd[2:] == [str(idf)]:
            if state["fail"]:
                return subprocess.CompletedProcess(cmd, 1, b"", b"incorrect passphrase")
            return subprocess.CompletedProcess(cmd, 0, state["plain"], b"")
        return inner(cmd, input=input, interactive=interactive)

    monkeypatch.setattr(keystore, "runner", runner)
    return kf, secret, idf, calls, state, tmp_path


def test_encrypted_identity_decrypted_once_no_temp_file(enc_setup):
    kf, secret, idf, calls, _, tmp_path = enc_setup
    before = {p for p in tmp_path.rglob("*")}
    r = _unlock("--identity", str(idf))
    assert r.exit_code == 0, r.output
    assert kf.read_text().strip() == secret
    decrypts = [c for c, _ in calls if c[:2] == ["age", "-d"] and c[2:] == [str(idf)]]
    assert len(decrypts) == 1
    # identity never offered as a path; wrapped file opened via stdin with the bytes
    wrapped_calls = [(c, i) for c, i in calls if "-i" in c]
    assert wrapped_calls and all(c[c.index("-i") + 1] == "/dev/stdin"
                                 for c, _ in wrapped_calls)
    assert all(i and b"AGE-SECRET-KEY-" in i for _, i in wrapped_calls)
    assert not any(str(idf) in c for c, _ in calls if "-i" in c)
    # only the recovery file was tried; no se, no passphrase
    assert len(wrapped_calls) == 1 and wrapped_calls[0][0][-1].endswith(".recovery.age")
    new = {p for p in tmp_path.rglob("*")} - before
    assert {p.name for p in new} <= {kf.name}, new  # only the restored key


def test_encrypted_identity_wrong_passphrase_message(enc_setup):
    kf, _, idf, calls, state, _ = enc_setup
    state["fail"] = True
    r = _unlock("--identity", str(idf))
    assert r.exit_code != 0
    assert "passphrase was wrong" in r.output
    assert "age failed" not in r.output
    assert not kf.exists()
    assert sum(1 for c, _ in calls if c[2:] == [str(idf)]) == 1


def test_encrypted_identity_matching_no_method(enc_setup):
    kf, _, idf, calls, state, _ = enc_setup
    _, _, other = _gen()
    state["plain"] = other.encode()
    r = _unlock("--identity", str(idf))
    assert r.exit_code != 0
    assert "matches no wrapped file" in r.output
    assert "recovery" in r.output  # lists what was checked
    assert not kf.exists()
    assert not any("-i" in c for c, _ in calls)  # no per-method attempts


def test_encrypted_identity_with_recovery(enc_setup):
    kf, secret, idf, calls, _, _ = enc_setup
    r = _unlock("--with", "recovery", "--identity", str(idf))
    assert r.exit_code == 0, r.output
    assert kf.read_text().strip() == secret
    assert sum(1 for c, _ in calls if c[2:] == [str(idf)]) == 1


def test_plain_identity_never_tries_se(enc_setup):
    kf, secret, idf, calls, state, tmp_path = enc_setup
    plain = tmp_path / "plain-id.txt"
    plain.write_bytes(state["plain"])
    r = _unlock("--identity", str(plain))
    assert r.exit_code == 0, r.output
    assert kf.read_text().strip() == secret
    assert not any(c[-1].endswith(".se.age") for c, _ in calls if "-i" in c)


def test_plain_identity_with_se_is_refused(enc_setup):
    kf, _, _, calls, state, tmp_path = enc_setup
    plain = tmp_path / "plain-id.txt"
    plain.write_bytes(state["plain"])
    r = _unlock("--with", "se", "--identity", str(plain))
    assert r.exit_code != 0
    assert "not a plugin identity" in r.output
    assert not any("-i" in c for c, _ in calls)


def test_plugin_identity_only_tries_plugin_methods(enc_setup, monkeypatch):
    kf, secret, _, calls, _, tmp_path = enc_setup
    stub = tmp_path / "se-id.txt"
    stub.write_text("# stub\nAGE-PLUGIN-SE-1QQQQQ\n")
    inner = keystore.runner

    def runner(cmd, input=None, interactive=False, **kw):
        if "-i" in cmd and cmd[-1].endswith(".se.age"):
            calls.append((list(cmd), input))
            return subprocess.CompletedProcess(cmd, 0, secret.encode() + b"\n", b"")
        return inner(cmd, input=input, interactive=interactive)

    monkeypatch.setattr(keystore, "runner", runner)
    monkeypatch.setattr(keystore, "_require", lambda b, i: None)
    r = _unlock("--identity", str(stub))
    assert r.exit_code == 0, r.output
    assert kf.read_text().strip() == secret
    tried = [c[-1] for c, _ in calls if "-i" in c]
    assert tried and all(t.endswith(".se.age") for t in tried)


def test_unlock_help_mentions_recovery_identity():
    r = CliRunner().invoke(cli, ["age", "unlock", "--help"])
    assert "--with recovery --identity" in r.output


def test_identity_kind_detection():
    assert keystore.identity_kind_of(b"age-encryption.org/v1\n...") == "encrypted"
    assert keystore.identity_kind_of(
        b"-----BEGIN AGE ENCRYPTED FILE-----\nxx") == "encrypted"
    assert keystore.identity_kind_of(b"# c\nAGE-PLUGIN-YUBIKEY-1Q\n") == "plugin"
    assert keystore.identity_kind_of(b"AGE-SECRET-KEY-1ABC\n") == "plain"


def _pty_drive(args, env, answers):
    """Run the CLI under a pty; answer each passphrase prompt from ``answers``."""
    code = "import sys; from dotconfig.cli import cli; cli()"
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, [sys.executable, "-c", code, *args], env)
    out, sent = b"", 0
    try:
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            out += chunk
            if out.lower().count(b"passphrase") > sent and sent < len(answers) \
                    and out.rstrip().endswith(b":"):
                os.write(fd, answers[sent] + b"\n")
                sent += 1
    except OSError:
        pass
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), out.decode(errors="replace")


def test_real_age_passphrase_identity_prompts_once(store, tmp_path):
    kf, secret, pub = store
    _, rpub, rtext = _gen()
    plain_id = tmp_path / "plain-rec.txt"
    plain_id.write_text(rtext)
    enc = tmp_path / "rec-enc.txt"
    code, out = _pty_drive_cmd(["age", "-p", "-o", str(enc), str(plain_id)],
                               [b"hunter2", b"hunter2"])
    assert code == 0 and enc.exists(), out
    assert keystore.identity_kind(enc) == "encrypted"
    res = keywrap.wrap([keywrap.MethodSpec("identity", "recovery", rpub, "recovery", plain_id)])
    assert all(r.ok for r in res), res
    se = keystore.wrapped_path("se")
    se.write_bytes(b"dummy")
    sc = keystore.load_sidecar()
    sc["methods"].insert(0, {"file": se.name, "kind": "se",
                             "recipient": "age1se1qexample", "label": "se"})
    keystore.save_sidecar(sc)
    kf.unlink()
    code, out = _pty_drive(["age", "unlock", "--identity", str(enc)],
                           dict(os.environ), [b"hunter2"])
    assert code == 0, out
    assert kf.read_text().strip() == secret
    assert out.lower().count("enter passphrase") == 1, out


def _pty_drive_cmd(cmd, answers):
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(cmd[0], cmd)
    out, sent = b"", 0
    try:
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            out += chunk
            if sent < len(answers) and out.lower().count(b"passphrase") > sent \
                    and out.rstrip().endswith(b":"):
                os.write(fd, answers[sent] + b"\n")
                sent += 1
    except OSError:
        pass
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), out.decode(errors="replace")
