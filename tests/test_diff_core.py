"""Tests for the diff comparison core and the pure save planners."""

from pathlib import Path
from unittest.mock import patch

import pytest

from dotconfig.diff import DiffError, compare_env, compare_file, normalize
from dotconfig.save import (
    SavePlanError,
    plan_save_config,
    plan_save_file,
    save_config,
    save_file,
)

ENV = """\
# CONFIG_DEPLOY=dev
# CONFIG_LOCAL=alice

#@dotconfig: public (dev)
APP=example.com
PORT=3000

#@dotconfig: secrets (dev)
TOKEN=abc123

#@dotconfig: public-local (alice)
QR=http://x/

#@dotconfig: secrets-local (alice)
"""


def _fake_encrypt(content, filepath, sops_config=None):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)
    return True


def _fake_decrypt(filepath, sops_config=None):
    return filepath.read_text()


def _snapshot(root: Path):
    return {p: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def cfg(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def fake_sops():
    with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt), \
         patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
        yield


class TestNormalize:
    def test_strips_export_prefix(self):
        assert normalize("export A=1\nB=2") == ["A=1", "B=2"]

    def test_strips_trailing_whitespace(self):
        assert normalize("A=1   \nB=2\t\n") == ["A=1", "B=2"]

    def test_strips_edge_blank_lines_keeps_inner(self):
        assert normalize("\n\nA=1\n\nB=2\n\n\n") == ["A=1", "", "B=2"]

    def test_drops_metadata(self):
        text = "# CONFIG_DEPLOY=dev\n#@dotconfig: public (dev)\n_VERSION=3\nA=1\n"
        assert normalize(text) == ["A=1"]

    def test_empty(self):
        assert normalize("") == []


class TestPlanners:
    def test_plan_config_writes_nothing(self, tmp_path, cfg):
        env = tmp_path / ".env"
        env.write_text(ENV)
        plan = plan_save_config(env, cfg)
        assert _snapshot(cfg) == {}
        assert list(cfg.iterdir()) == []
        dests = [(w.dest.relative_to(cfg).as_posix(), w.encrypted) for w in plan.writes]
        assert dests == [
            ("dev/public.env", False),
            ("dev/secrets.env", True),
            ("local/alice/public.env", False),
        ]
        assert plan.needs_unlock

    def test_plan_config_error_raises(self, tmp_path, cfg):
        with pytest.raises(SavePlanError):
            plan_save_config(tmp_path / "missing.env", cfg)
        bad = tmp_path / "bad.env"
        bad.write_text("A=1\n")
        with pytest.raises(SavePlanError):
            plan_save_config(bad, cfg)

    def test_plan_file_writes_nothing(self, tmp_path, cfg):
        src = tmp_path / "app.env"
        src.write_text("NAME=x\nAPI_SECRET=hunter22hunter22\n")
        plan = plan_save_file("dev", None, "app.env", cfg, source=src)
        assert list(cfg.iterdir()) == []
        assert [w.encrypted for w in plan.writes] == [False, True]

    def test_plan_file_missing_source_raises(self, tmp_path, cfg):
        with pytest.raises(SavePlanError):
            plan_save_file("dev", None, "nope.txt", cfg, source=tmp_path / "nope.txt")

    def test_save_config_executes_plan(self, tmp_path, cfg):
        env = tmp_path / ".env"
        env.write_text(ENV)
        save_config(env, cfg)
        assert (cfg / "dev" / "public.env").read_text() == "APP=example.com\nPORT=3000\n"
        assert (cfg / "dev" / "secrets.env").read_text() == "TOKEN=abc123\n"


class TestCompareEnv:
    def test_missing_saved_is_all_added(self, tmp_path, cfg):
        env = tmp_path / ".env"
        env.write_text(ENV)
        result = compare_env(env, cfg)
        assert result.changed
        pub = next(f for f in result.files if f.path == cfg / "dev" / "public.env")
        assert not pub.saved_exists
        assert "+APP=example.com" in pub.diff
        assert str(cfg / "dev" / "public.env") in pub.diff
        assert list(cfg.iterdir()) == []  # read-only

    def test_clean_after_save(self, tmp_path, cfg):
        env = tmp_path / ".env"
        env.write_text(ENV)
        save_config(env, cfg)
        result = compare_env(env, cfg)
        assert not result.changed
        assert result.text == ""

    def test_edits_show_in_public_and_secret(self, tmp_path, cfg):
        env = tmp_path / ".env"
        env.write_text(ENV)
        save_config(env, cfg)
        before = _snapshot(cfg)
        env.write_text(ENV.replace("PORT=3000", "PORT=4000").replace("abc123", "zzz"))
        result = compare_env(env, cfg)
        assert result.changed
        assert "-PORT=3000" in result.text and "+PORT=4000" in result.text
        assert "-TOKEN=abc123" in result.text and "+TOKEN=zzz" in result.text
        assert _snapshot(cfg) == before

    def test_export_and_whitespace_ignored(self, tmp_path, cfg):
        env = tmp_path / ".env"
        env.write_text(ENV)
        save_config(env, cfg)
        env.write_text(ENV.replace("APP=example.com", "export APP=example.com   "))
        assert not compare_env(env, cfg).changed
        assert not compare_env(env, cfg, add_export=True).changed

    def test_override_deploy_compares_other_deployment(self, tmp_path, cfg):
        env = tmp_path / ".env"
        env.write_text(ENV)
        save_config(env, cfg)
        result = compare_env(env, cfg, override_deploy="prod")
        assert result.changed
        assert any("prod" in str(f.path) for f in result.files)

    def test_errors_raise_diff_error(self, tmp_path, cfg):
        with pytest.raises(DiffError):
            compare_env(tmp_path / "missing.env", cfg)
        bad = tmp_path / "bad.env"
        bad.write_text("A=1\n")
        with pytest.raises(DiffError):
            compare_env(bad, cfg)

    def test_decrypt_failure_raises_not_exits(self, tmp_path, cfg):
        env = tmp_path / ".env"
        env.write_text(ENV)
        save_config(env, cfg)
        with patch("dotconfig.load._is_sops_encrypted", return_value=True), \
             patch("dotconfig.load._decrypt_sops", return_value=None):
            with pytest.raises(DiffError):
                compare_env(env, cfg)

    def test_encrypted_saved_decrypted_in_memory_only(self, tmp_path, cfg):
        env = tmp_path / ".env"
        env.write_text(ENV)
        save_config(env, cfg)
        before = _snapshot(cfg)
        secrets = cfg / "dev" / "secrets.env"
        with patch("dotconfig.load._is_sops_encrypted", side_effect=lambda p: p == secrets), \
             patch("dotconfig.load._decrypt_sops", return_value="TOKEN=abc123\n") as dec:
            result = compare_env(env, cfg)
        assert dec.called
        assert not result.changed
        assert _snapshot(cfg) == before


class TestCompareFile:
    def test_missing_saved_file_all_added(self, tmp_path, cfg):
        src = tmp_path / "app.yaml"
        src.write_text("a: 1\nb: 2\n")
        result = compare_file("dev", None, "app.yaml", cfg, source=src)
        assert result.changed
        assert "+a: 1" in result.text
        assert list(cfg.iterdir()) == []

    def test_same_then_changed(self, tmp_path, cfg):
        src = tmp_path / "app.yaml"
        src.write_text("a: 1\nb: 2\n")
        save_file("dev", None, "app.yaml", cfg, source=src)
        assert not compare_file("dev", None, "app.yaml", cfg, source=src).changed
        src.write_text("a: 1\nb: 3\n")
        result = compare_file("dev", None, "app.yaml", cfg, source=src)
        assert result.changed
        assert "-b: 2" in result.text and "+b: 3" in result.text

    def test_split_secret_companion_compared(self, tmp_path, cfg):
        src = tmp_path / "svc.yaml"
        src.write_text("name: x\napi_key: sk_live_abcdefghijklmnop\n")
        save_file("dev", None, "svc.yaml", cfg, source=src)
        assert not compare_file("dev", None, "svc.yaml", cfg, source=src).changed
        src.write_text("name: x\napi_key: sk_live_changedchangedxx\n")
        assert compare_file("dev", None, "svc.yaml", cfg, source=src).changed

    def test_error_raises_diff_error(self, tmp_path, cfg):
        with pytest.raises(DiffError):
            compare_file("dev", None, "nope.yaml", cfg, source=tmp_path / "nope.yaml")
        with pytest.raises(DiffError):
            compare_file(None, None, "x.yaml", cfg)
