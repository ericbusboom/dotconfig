"""Commands report the resolved paths they use; errors include them."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dotconfig import paths
from dotconfig.cli import cli
from dotconfig.reencrypt import reencrypt_all


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "config"
    (cfg / "prod").mkdir(parents=True)
    (cfg / "prod" / "public.env").write_text("export FOO=bar\n")
    return cfg


def _runner():
    return CliRunner()


def test_load_prints_config_root_and_key_file(project):
    r = _runner().invoke(cli, ["-c", str(project), "load", "prod"])
    assert r.exit_code == 0, r.output
    assert f"config root: {project.resolve()} (option)" in r.output
    assert f"key file: {paths.key_path()} (env)" in r.output


def test_load_discovered_source(project):
    r = _runner().invoke(cli, ["load", "prod"])
    assert r.exit_code == 0, r.output
    assert "(discovered)" in r.output


def test_load_quiet_suppresses_path_lines(project):
    r = _runner().invoke(cli, ["-c", str(project), "load", "prod", "-q"])
    assert r.exit_code == 0, r.output
    assert "config root:" not in r.output
    assert "key file:" not in r.output
    assert "Written to" in r.output


def test_load_stdout_unchanged_and_paths_on_stderr(project):
    r = _runner().invoke(cli, ["-c", str(project), "load", "prod", "-S"])
    assert r.exit_code == 0, r.output
    assert "config root:" not in r.stdout
    assert "key file:" not in r.stdout
    assert "FOO=bar" in r.stdout
    assert "config root:" in r.stderr and "key file:" in r.stderr
    q = _runner().invoke(cli, ["-c", str(project), "load", "prod", "-S", "-q"])
    assert q.stdout == r.stdout
    assert q.stderr == ""


def test_load_json_stdout_is_pure_json(project):
    r = _runner().invoke(
        cli, ["-c", str(project), "load", "prod", "--json", "--flat", "-S"]
    )
    assert json.loads(r.stdout) == {"FOO": "bar"}
    assert "config root:" in r.stderr


def test_save_prints_paths_and_quiet(project, tmp_path):
    env = tmp_path / ".env"
    _runner().invoke(cli, ["-c", str(project), "load", "prod", "-q"])
    assert env.exists()
    r = _runner().invoke(cli, ["-c", str(project), "save"])
    assert r.exit_code == 0, r.output
    assert "config root:" in r.output and "key file:" in r.output
    q = _runner().invoke(cli, ["-c", str(project), "save", "-q"])
    assert "config root:" not in q.output and "key file:" not in q.output


def test_init_prints_config_root_and_quiet(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("dotconfig.cli.init_config"), patch("dotconfig.cli.run_hook"):
        r = _runner().invoke(cli, ["init"])
        assert "config root:" in r.output
        q = _runner().invoke(cli, ["init", "-q"])
        assert "config root:" not in q.output


def test_reencrypt_decrypt_error_includes_paths(tmp_path, capsys):
    cfg = tmp_path / "config"
    (cfg / "dev").mkdir(parents=True)
    (cfg / "dev" / "secrets.yaml").write_text("ENC(x)")
    with patch("dotconfig.reencrypt._is_sops_encrypted", return_value=True), \
         patch("dotconfig.reencrypt._decrypt_sops", return_value=None), \
         pytest.raises(SystemExit):
        reencrypt_all(cfg)
    err = capsys.readouterr().err
    assert "failed to decrypt" in err
    assert f"config root: {cfg.resolve()}" in err
    assert f"key file: {paths.key_path()}" in err


def test_load_decrypt_error_includes_paths(project, capsys):
    from dotconfig.load import _read_file_content

    f = project / "prod" / "secrets.env"
    f.write_text("ENC")
    with patch("dotconfig.load._is_sops_encrypted", return_value=True), \
         patch("dotconfig.load._decrypt_sops", return_value=None), \
         pytest.raises(SystemExit):
        _read_file_content(f, project / "sops.yaml")
    err = capsys.readouterr().err
    assert f"config root: {project.resolve()}" in err
    assert f"key file: {paths.key_path()}" in err


def test_key_created_lines_show_full_paths(project, tmp_path):
    src = tmp_path / "mykey"
    src.write_text("PRIVATE")
    with patch("dotconfig.key._encrypt_sops", return_value=True):
        r = _runner().invoke(cli, ["-c", str(project), "key", "save", str(src)])
    assert r.exit_code == 0, r.output
    assert str(project / "keys" / "mykey") in r.output
