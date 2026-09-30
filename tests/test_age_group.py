"""Tests for the `dotconfig age` command group (temp SOPS_AGE_KEY_FILE only)."""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from dotconfig import keyguard
from dotconfig.cli import cli

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    kf = tmp_path / "age" / "keys.txt"
    kf.parent.mkdir()
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(kf))
    monkeypatch.delenv("SOPS_AGE_KEY", raising=False)
    return kf


def _run(*args):
    return CliRunner().invoke(cli, list(args))


@pytest.mark.parametrize("sub", ["status", "wrap", "unlock", "lock"])
def test_age_subcommands_exist(sub, keyfile):
    assert _run("age", sub, "--help").exit_code == 0
    assert set(cli.commands["age"].commands) == {"status", "wrap", "unlock", "lock"}


def test_age_status_locked_and_unlocked(keyfile, monkeypatch):
    from dotconfig import keys

    monkeypatch.setattr(keys, "_is_age_installed", lambda: True)
    keyfile.with_name("keys.txt.pass.age").write_text("x")
    r = _run("age", "status")
    assert r.exit_code == 0
    assert "state: locked" in r.output
    keyfile.write_text("# nothing\n")
    r = _run("age", "status")
    assert "state: unlocked" in r.output


def test_age_status_sops_age_key_warning(keyfile, monkeypatch):
    from dotconfig import keys

    monkeypatch.setattr(keys, "_is_age_installed", lambda: True)
    monkeypatch.setenv("SOPS_AGE_KEY", "not-a-key")
    r = _run("age", "status")
    assert "SOPS_AGE_KEY is set" in r.output


def test_age_lock_when_already_locked(keyfile):
    r = _run("age", "lock")
    assert r.exit_code == 0
    assert "already locked" in r.output


@pytest.mark.parametrize("args", [["unlock"], ["lock"], ["key", "wrap"], ["keys"]])
def test_old_commands_removed(args, keyfile):
    r = _run(*args)
    assert r.exit_code != 0
    assert "No such command" in r.output


def test_key_group_has_no_wrap():
    assert "wrap" not in cli.commands["key"].commands
    assert "SSH keys" in cli.commands["key"].help


def test_locked_message_text():
    assert keyguard.LOCKED_MESSAGE == "age key is locked — run: dotconfig age unlock"


def test_no_stale_command_strings():
    pat = re.compile(r"dotconfig (unlock|lock|key wrap|keys)\b")
    files = list((ROOT / "src" / "dotconfig").glob("*.py"))
    files += [ROOT / "src" / "dotconfig" / "agent_instructions.md", ROOT / "README.md"]
    stale = [f"{f.name}: {m.group(0)}" for f in files
             for m in pat.finditer(f.read_text())]
    assert stale == []


def test_age_status_unrecorded_wrapped_file_wording(keyfile, monkeypatch):
    from dotconfig import keys

    monkeypatch.setattr(keys, "_is_age_installed", lambda: True)
    keyfile.write_text("# nothing\n")
    keyfile.with_name("keys.txt.pass.age").write_text("x")
    r = _run("age", "status")
    assert r.exit_code == 0
    assert "not recorded; run: dotconfig age wrap --passphrase" in r.output
    assert "to verify and record it" in r.output
