"""Tests for init's user-config integration (ticket 008-004)."""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from dotconfig import paths
from dotconfig.init import _parse_sops_keys, init_config

KEY_A = "age1" + "q" * 58
KEY_B = "age1" + "p" * 58
KEY_C = "age1" + "z" * 58


@pytest.fixture
def run_init(tmp_path):
    """Run init_config with a fake local key; returns (config_dir, run)."""
    config_dir = tmp_path / "config"

    def run(key=KEY_A, quiet=False):
        with (
            patch("dotconfig.init._discover_age_key", return_value="AGE-SECRET-KEY-1X"),
            patch("dotconfig.init._derive_public_key", return_value=key),
            patch("dotconfig.init._get_current_user", return_value="tester"),
        ):
            init_config(config_dir, quiet=quiet)

    return config_dir, run


def _write_user_config(entries):
    p = paths.user_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"public_keys": entries}))
    return p


def _keys(config_dir):
    return _parse_sops_keys((config_dir / "sops.yaml").read_text())


def _fake_encrypted(config_dir):
    d = config_dir / "dev"
    d.mkdir(parents=True, exist_ok=True)
    (d / "secrets.env").write_text("A=ENC[AES256_GCM,data:x]\nsops_version=3.9\n")


def test_missing_user_config_created_and_reported(run_init, capsys):
    config_dir, run = run_init
    uc = paths.user_config_path()
    assert not uc.exists()
    run()
    out = capsys.readouterr().out
    assert uc.exists()
    assert str(uc) in out
    data = yaml.safe_load(uc.read_text())
    assert data["public_keys"][0]["key"] == KEY_A
    assert "@" in data["public_keys"][0]["name"]
    label = data["public_keys"][0]["name"]
    assert dict(_keys(config_dir))[KEY_A] == label
    assert label in out


def test_listed_keys_added_with_labels(run_init, capsys):
    config_dir, run = run_init
    _write_user_config([{"key": KEY_B, "name": "bob"}, {"key": KEY_C}])
    run()
    keys = dict(_keys(config_dir))
    assert set(keys) == {KEY_A, KEY_B, KEY_C}
    assert keys[KEY_B] == "bob"
    out = capsys.readouterr().out
    assert "bob" in out


def test_rerun_is_noop(run_init, capsys):
    config_dir, run = run_init
    _write_user_config([{"key": KEY_B, "name": "bob"}])
    _fake_encrypted(config_dir)
    run()
    sops = config_dir / "sops.yaml"
    before = (sops.read_text(), sops.stat().st_mtime_ns)
    capsys.readouterr()
    run()
    out = capsys.readouterr().out
    assert (sops.read_text(), sops.stat().st_mtime_ns) == before
    assert "already up to date" in out
    assert "reencrypt" not in out


def test_readds_removed_key(run_init):
    config_dir, run = run_init
    _write_user_config([{"key": KEY_B, "name": "bob"}])
    run()
    (config_dir / "sops.yaml").write_text(
        "creation_rules:\n  - path_regex: '.+'\n    age: " + KEY_A + "\n"
    )
    run()
    assert {k for k, _ in _keys(config_dir)} == {KEY_A, KEY_B}


def test_existing_keys_and_labels_preserved_user_label_wins(run_init):
    config_dir, run = run_init
    config_dir.mkdir(parents=True)
    (config_dir / "sops.yaml").write_text(
        "creation_rules:\n  - path_regex: '.+'\n    key_groups:\n      - age:\n"
        f"          - {KEY_C}  # carol\n          - {KEY_B}  # old-bob\n"
    )
    _write_user_config([{"key": KEY_B, "name": "bob"}])
    run()
    keys = dict(_keys(config_dir))
    assert keys[KEY_C] == "carol"  # never removed, label kept
    assert keys[KEY_B] == "bob"  # user config label wins
    assert KEY_A in keys


def test_invalid_entries_warn_and_do_not_break(run_init, capsys):
    config_dir, run = run_init
    _write_user_config([{"key": "not-a-key"}, {"key": KEY_B, "name": "bob"}])
    run()
    cap = capsys.readouterr()
    assert "warning" in cap.err
    assert {k for k, _ in _keys(config_dir)} == {KEY_A, KEY_B}


def test_reencrypt_notice_when_changed_and_encrypted_files(run_init, capsys):
    config_dir, run = run_init
    run()
    _fake_encrypted(config_dir)
    _write_user_config([{"key": KEY_B, "name": "bob"}])
    capsys.readouterr()
    before = (config_dir / "dev" / "secrets.env").read_text()
    run()
    cap = capsys.readouterr()
    assert "dotconfig reencrypt" in cap.out + cap.err
    assert (config_dir / "dev" / "secrets.env").read_text() == before


def test_no_notice_without_encrypted_files(run_init, capsys):
    config_dir, run = run_init
    run()
    _write_user_config([{"key": KEY_B, "name": "bob"}])
    capsys.readouterr()
    run()
    cap = capsys.readouterr()
    assert "reencrypt" not in cap.out + cap.err


def test_quiet_suppresses_output_but_works(run_init, capsys):
    config_dir, run = run_init
    _write_user_config([{"key": KEY_B, "name": "bob"}])
    run(quiet=True)
    cap = capsys.readouterr()
    assert cap.out == ""
    assert {k for k, _ in _keys(config_dir)} == {KEY_A, KEY_B}


def test_isolation_never_touches_real_home(run_init):
    _, run = run_init
    run()
    assert str(paths.user_config_path()).startswith(
        str(Path(__import__("os").environ["XDG_CONFIG_HOME"]))
    )


# ---------------------------------------------------------------------------
# Real sops round trip
# ---------------------------------------------------------------------------


def _have(*tools):
    return all(shutil.which(t) for t in tools)


def _keygen():
    r = subprocess.run(["age-keygen"], capture_output=True, text=True, check=True)
    secret = pub = None
    for line in (r.stdout + r.stderr).splitlines():
        if line.startswith("AGE-SECRET-KEY-"):
            secret = line.strip()
        elif "ublic key:" in line:
            pub = line.split(":", 1)[1].strip()
    return secret, pub


@pytest.mark.skipif(not _have("sops", "age-keygen"), reason="sops/age not installed")
def test_real_sops_round_trip(tmp_path, monkeypatch):
    from dotconfig.reencrypt import reencrypt_all

    sec_a, pub_a = _keygen()
    sec_b, pub_b = _keygen()
    config_dir = tmp_path / "config"
    monkeypatch.setenv("SOPS_AGE_KEY", sec_a)

    def run():
        with (
            patch("dotconfig.init._discover_age_key", return_value=sec_a),
            patch("dotconfig.init._get_current_user", return_value="tester"),
        ):
            init_config(config_dir)

    run()
    assert dict(_keys(config_dir))[pub_a]

    secrets = config_dir / "dev" / "secrets.env"
    secrets.write_text("TOKEN=hunter2\n")
    sops_cfg = config_dir / "sops.yaml"
    subprocess.run(
        ["sops", "--config", str(sops_cfg), "-e", "-i",
         "--input-type", "dotenv", "--output-type", "dotenv", str(secrets)],
        check=True, capture_output=True,
    )

    _write_user_config([{"key": pub_b, "name": "bob"}])
    run()
    assert {k for k, _ in _keys(config_dir)} == {pub_a, pub_b}
    reencrypt_all(config_dir)

    # Bob alone can now decrypt.
    monkeypatch.setenv("SOPS_AGE_KEY", sec_b)
    r = subprocess.run(
        ["sops", "-d", "--input-type", "dotenv", "--output-type", "dotenv", str(secrets)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "hunter2" in r.stdout
