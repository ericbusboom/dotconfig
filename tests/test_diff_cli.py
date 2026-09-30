"""CLI tests for ``dotconfig diff`` (exit codes, output, read-only)."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dotconfig.cli import cli


def _fake_encrypt(content, filepath, sops_config=None):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)
    return True


def _fake_decrypt(filepath, sops_config=None):
    return filepath.read_text()


def _snapshot(root: Path):
    return {p: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture(autouse=True)
def fake_sops():
    with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt), \
         patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
        yield


@pytest.fixture
def proj(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    for d, app in (("dev", "dev.example.com"), ("prod", "example.com")):
        (cfg / d).mkdir(parents=True)
        (cfg / d / "public.env").write_text(f"APP={app}\nPORT=3000\n")
        (cfg / d / "secrets.env").write_text(f"TOKEN=tok_{d}\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(*args):
    return CliRunner().invoke(cli, list(args))


def _load(proj):
    r = run("load", "dev")
    assert r.exit_code == 0, r.output
    assert (proj / ".env").exists()


class TestDiffEnv:
    def test_clean_after_load(self, proj):
        _load(proj)
        r = run("diff")
        assert r.exit_code == 0, r.output
        assert r.output == ""

    def test_public_and_secret_edit(self, proj):
        _load(proj)
        env = proj / ".env"
        env.write_text(
            env.read_text()
            .replace("PORT=3000", "PORT=9999")
            .replace("TOKEN=tok_dev", "TOKEN=changed")
        )
        before = _snapshot(proj / "config")
        r = run("diff")
        assert r.exit_code == 1, r.output
        assert "+PORT=9999" in r.output and "-PORT=3000" in r.output
        assert "+TOKEN=changed" in r.output
        assert str(Path("config") / "dev" / "public.env") in r.output
        assert str(Path("config") / "dev" / "secrets.env") in r.output
        assert _snapshot(proj / "config") == before

    def test_diff_other_deployment(self, proj):
        _load(proj)
        r = run("diff", "prod")
        assert r.exit_code == 1
        assert "config/prod/public.env" in r.output
        assert "+APP=dev.example.com" in r.output

    def test_flags_match_positional(self, proj):
        _load(proj)
        r1 = run("diff", "prod")
        r2 = run("diff", "-d", "prod")
        assert r2.exit_code == 1
        assert r1.output == r2.output
        assert run("diff", "-d", "dev").exit_code == 0

    def test_mixing_positional_and_flags_is_usage_error(self, proj):
        _load(proj)
        assert run("diff", "dev", "-d", "dev").exit_code == 2

    def test_missing_deployment_exit_2(self, proj):
        _load(proj)
        r = run("diff", "nonexistent")
        assert r.exit_code == 2
        assert "unknown deployment" in r.output
        assert run("diff", "-l", "ghost").exit_code == 2

    def test_no_env_file_exit_2(self, proj):
        r = run("diff")
        assert r.exit_code == 2

    def test_unmanaged_env_exit_2(self, proj):
        (proj / ".env").write_text("A=1\n")
        assert run("diff").exit_code == 2

    def test_decrypt_failure_exit_2(self, proj):
        _load(proj)
        with patch("dotconfig.load._is_sops_encrypted", return_value=True), \
                patch("dotconfig.load._decrypt_sops", return_value=None):
            r = run("diff")
        assert r.exit_code == 2

    def test_no_hooks_run(self, proj):
        _load(proj)
        with patch("dotconfig.cli.run_hook") as hook:
            run("diff")
        hook.assert_not_called()


class TestDiffFile:
    def test_same_and_changed(self, proj):
        src = proj / "app.yaml"
        src.write_text("a: 1\n")
        assert run("save", "--file", str(src), "-d", "dev").exit_code == 0
        assert run("diff", "--file", str(src), "-d", "dev").exit_code == 0
        src.write_text("a: 2\n")
        before = _snapshot(proj / "config")
        r = run("diff", "--file", str(src), "-d", "dev")
        assert r.exit_code == 1
        assert "-a: 1" in r.output and "+a: 2" in r.output
        assert _snapshot(proj / "config") == before

    def test_missing_saved_copy_is_all_added(self, proj):
        src = proj / "new.yaml"
        src.write_text("x: 1\n")
        r = run("diff", "-f", str(src), "-d", "dev")
        assert r.exit_code == 1
        assert "+x: 1" in r.output
        assert not (proj / "config" / "dev" / "new.yaml").exists()

    def test_name_override(self, proj):
        src = proj / "scratch.yaml"
        src.write_text("x: 1\n")
        run("save", "--file", str(src), "-n", "real.yaml", "-d", "dev")
        assert run("diff", "-f", str(src), "-n", "real.yaml", "-d", "dev").exit_code == 0

    def test_missing_source_exit_2(self, proj):
        r = run("diff", "-f", str(proj / "nope.yaml"), "-d", "dev")
        assert r.exit_code == 2

    def test_name_without_file_is_usage_error(self, proj):
        assert run("diff", "-n", "x.yaml").exit_code == 2
