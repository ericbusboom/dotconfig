"""Tests for dotconfig.cli — positional args, classifier, multi-layer."""

from pathlib import Path
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from dotconfig.cli import _classify_load_args, _classify_save_args, cli


# ---------------------------------------------------------------------------
# Classifier — strict (load)
# ---------------------------------------------------------------------------

@pytest.fixture()
def stacked_config_dir(tmp_path: Path) -> Path:
    """A config/ with two deployments and two locals."""
    cfg = tmp_path / "config"
    for d in ("dev", "prod"):
        (cfg / d).mkdir(parents=True)
        (cfg / d / "public.env").write_text(f"APP_DEPLOY={d}\n")
        (cfg / d / "secrets.env").write_text(f"SECRET_{d.upper()}=s_{d}\n")
    for l in ("alice", "bob"):
        (cfg / "local" / l).mkdir(parents=True)
        (cfg / "local" / l / "public.env").write_text(f"APP_USER={l}\n")
    return cfg


class TestClassifyLoadArgs:
    def test_empty_input_returns_empty_lists(self, stacked_config_dir):
        deploys, locals_ = _classify_load_args((), stacked_config_dir)
        assert deploys == []
        assert locals_ == []

    def test_single_deploy(self, stacked_config_dir):
        deploys, locals_ = _classify_load_args(("dev",), stacked_config_dir)
        assert deploys == ["dev"]
        assert locals_ == []

    def test_single_local(self, stacked_config_dir):
        deploys, locals_ = _classify_load_args(("alice",), stacked_config_dir)
        assert deploys == []
        assert locals_ == ["alice"]

    def test_mixed_order_independent_across_types(self, stacked_config_dir):
        d1, l1 = _classify_load_args(("dev", "alice"), stacked_config_dir)
        d2, l2 = _classify_load_args(("alice", "dev"), stacked_config_dir)
        assert d1 == d2 == ["dev"]
        assert l1 == l2 == ["alice"]

    def test_multi_deploy_preserves_order(self, stacked_config_dir):
        deploys, _ = _classify_load_args(("prod", "dev"), stacked_config_dir)
        assert deploys == ["prod", "dev"]

    def test_multi_local_preserves_order(self, stacked_config_dir):
        _, locals_ = _classify_load_args(("bob", "alice"), stacked_config_dir)
        assert locals_ == ["bob", "alice"]

    def test_full_stack(self, stacked_config_dir):
        deploys, locals_ = _classify_load_args(
            ("dev", "prod", "alice", "bob"), stacked_config_dir
        )
        assert deploys == ["dev", "prod"]
        assert locals_ == ["alice", "bob"]

    def test_unknown_name_raises(self, stacked_config_dir):
        with pytest.raises(click.UsageError, match="unknown"):
            _classify_load_args(("nope",), stacked_config_dir)

    def test_duplicate_name_raises(self, stacked_config_dir):
        with pytest.raises(click.UsageError, match="duplicate"):
            _classify_load_args(("dev", "dev"), stacked_config_dir)

    def test_ambiguous_name_raises(self, tmp_path):
        cfg = tmp_path / "config"
        # 'shared' exists as both a deployment AND a local
        (cfg / "shared").mkdir(parents=True)
        (cfg / "shared" / "public.env").write_text("")
        (cfg / "local" / "shared").mkdir(parents=True)
        (cfg / "local" / "shared" / "public.env").write_text("")
        with pytest.raises(click.UsageError, match="ambiguous"):
            _classify_load_args(("shared",), cfg)


# ---------------------------------------------------------------------------
# Classifier — lenient (save)
# ---------------------------------------------------------------------------

class TestClassifySaveArgs:
    def test_empty_returns_nones(self):
        d, l = _classify_save_args(())
        assert d is None
        assert l is None

    def test_single_name(self):
        d, l = _classify_save_args(("dev",))
        assert d == "dev"
        assert l is None

    def test_two_names(self):
        d, l = _classify_save_args(("dev", "alice"))
        assert d == "dev"
        assert l == "alice"

    def test_three_names_rejected(self):
        with pytest.raises(click.UsageError, match="at most two"):
            _classify_save_args(("dev", "alice", "bob"))

    def test_duplicate_rejected(self):
        with pytest.raises(click.UsageError, match="duplicate"):
            _classify_save_args(("dev", "dev"))

    def test_does_not_check_existence(self):
        # Lenient classifier doesn't care if directories exist
        d, l = _classify_save_args(("brand_new_deploy", "brand_new_user"))
        assert d == "brand_new_deploy"
        assert l == "brand_new_user"


# ---------------------------------------------------------------------------
# CLI integration — load command
# ---------------------------------------------------------------------------

def _fake_decrypt(filepath: Path, sops_config=None):
    """Strip sops_ metadata to simulate decryption."""
    lines = filepath.read_text().splitlines()
    return "\n".join(l for l in lines if not l.startswith("sops_")) + "\n"


class TestLoadCliPositional:
    def test_positional_single_deploy(self, stacked_config_dir, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            result = runner.invoke(
                cli, ["load", "dev", "-c", str(stacked_config_dir)]
            )
        assert result.exit_code == 0, result.output
        env = (tmp_path / ".env").read_text()
        assert "# CONFIG_DEPLOY=dev" in env
        assert "APP_DEPLOY=dev" in env

    def test_positional_deploy_plus_local(self, stacked_config_dir, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            result = runner.invoke(
                cli, ["load", "dev", "alice", "-c", str(stacked_config_dir)]
            )
        assert result.exit_code == 0, result.output
        env = (tmp_path / ".env").read_text()
        assert "# CONFIG_DEPLOY=dev" in env
        assert "# CONFIG_LOCAL=alice" in env
        assert "APP_USER=alice" in env

    def test_positional_order_independent_across_types(
        self, stacked_config_dir, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            result = runner.invoke(
                cli, ["load", "alice", "dev", "-c", str(stacked_config_dir)]
            )
        assert result.exit_code == 0, result.output
        env = (tmp_path / ".env").read_text()
        # Same outcome as `load dev alice`
        assert "# CONFIG_DEPLOY=dev" in env
        assert "# CONFIG_LOCAL=alice" in env

    def test_positional_full_stack_section_order(
        self, stacked_config_dir, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            result = runner.invoke(
                cli,
                ["load", "dev", "prod", "alice", "bob", "-c", str(stacked_config_dir)],
            )
        assert result.exit_code == 0, result.output
        env = (tmp_path / ".env").read_text()
        assert "# CONFIG_DEPLOYS=dev,prod" in env
        assert "# CONFIG_LOCALS=alice,bob" in env

        # Sections appear in deploy-first, local-last, command-line order
        markers = [
            "#@dotconfig: public (dev)",
            "#@dotconfig: secrets (dev)",
            "#@dotconfig: public (prod)",
            "#@dotconfig: secrets (prod)",
            "#@dotconfig: public-local (alice)",
            "#@dotconfig: secrets-local (alice)",
            "#@dotconfig: public-local (bob)",
            "#@dotconfig: secrets-local (bob)",
        ]
        positions = [env.index(m) for m in markers]
        assert positions == sorted(positions)

    def test_legacy_flag_form_still_works(self, stacked_config_dir, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            result = runner.invoke(
                cli,
                ["load", "-d", "dev", "-l", "alice", "-c", str(stacked_config_dir)],
            )
        assert result.exit_code == 0, result.output
        env = (tmp_path / ".env").read_text()
        assert "# CONFIG_DEPLOY=dev" in env
        assert "# CONFIG_LOCAL=alice" in env

    def test_mixing_positional_and_flag_rejected(
        self, stacked_config_dir, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["load", "dev", "-l", "alice", "-c", str(stacked_config_dir)]
        )
        assert result.exit_code != 0
        assert "cannot mix" in result.output.lower()

    def test_unknown_name_rejected(self, stacked_config_dir, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["load", "nonexistent", "-c", str(stacked_config_dir)]
        )
        assert result.exit_code != 0
        assert "unknown" in result.output.lower()

    def test_duplicate_name_rejected(self, stacked_config_dir, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["load", "dev", "dev", "-c", str(stacked_config_dir)]
        )
        assert result.exit_code != 0
        assert "duplicate" in result.output.lower()

    def test_no_args_rejected(self, stacked_config_dir, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["load", "-c", str(stacked_config_dir)])
        assert result.exit_code != 0
        assert "deployment" in result.output.lower()

    def test_json_with_multi_layer_rejected(
        self, stacked_config_dir, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["load", "dev", "prod", "--json", "-c", str(stacked_config_dir)],
        )
        assert result.exit_code != 0
        assert "single" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI integration — save command
# ---------------------------------------------------------------------------

def _fake_encrypt(content: str, filepath: Path, sops_config=None) -> bool:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)
    return True


SAMPLE_MULTI_ENV = """\
# CONFIG_DEPLOYS=dev,prod
# CONFIG_LOCALS=alice,bob

#@dotconfig: public (dev)
APP_DEPLOY=dev

#@dotconfig: secrets (dev)
SECRET_DEV=s_dev

#@dotconfig: public (prod)
APP_DEPLOY=prod

#@dotconfig: secrets (prod)
SECRET_PROD=s_prod

#@dotconfig: public-local (alice)
APP_USER=alice

#@dotconfig: secrets-local (alice)

#@dotconfig: public-local (bob)
APP_USER=bob_overrides_alice

#@dotconfig: secrets-local (bob)
"""


class TestSaveCliPositional:
    def test_save_no_args_round_trips_multi_layer(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text(SAMPLE_MULTI_ENV)
        cfg = tmp_path / "config"
        runner = CliRunner()
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            result = runner.invoke(cli, ["save", "-c", str(cfg)])
        assert result.exit_code == 0, result.output
        # Each source layer got its own destination
        assert (cfg / "dev" / "public.env").exists()
        assert (cfg / "prod" / "public.env").exists()
        assert (cfg / "local" / "alice" / "public.env").exists()
        assert (cfg / "local" / "bob" / "public.env").exists()
        # Per-layer values went to per-layer files
        assert "APP_DEPLOY=dev" in (cfg / "dev" / "public.env").read_text()
        assert "APP_DEPLOY=prod" in (cfg / "prod" / "public.env").read_text()

    def test_save_positional_flattens_into_single_deploy(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text(SAMPLE_MULTI_ENV)
        cfg = tmp_path / "config"
        runner = CliRunner()
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            result = runner.invoke(cli, ["save", "newdev", "-c", str(cfg)])
        assert result.exit_code == 0, result.output
        # Only the single dest deployment exists
        assert (cfg / "newdev" / "public.env").exists()
        assert not (cfg / "dev").exists()
        assert not (cfg / "prod").exists()
        # Last-wins merge: prod overrode dev
        merged = (cfg / "newdev" / "public.env").read_text()
        assert "APP_DEPLOY=prod" in merged

    def test_save_legacy_flag_form_works(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text(SAMPLE_MULTI_ENV)
        cfg = tmp_path / "config"
        runner = CliRunner()
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            result = runner.invoke(cli, ["save", "-d", "newdev", "-c", str(cfg)])
        assert result.exit_code == 0, result.output
        assert (cfg / "newdev" / "public.env").exists()

    def test_save_mixing_positional_and_flag_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text(SAMPLE_MULTI_ENV)
        cfg = tmp_path / "config"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["save", "newdev", "-l", "alice", "-c", str(cfg)]
        )
        assert result.exit_code != 0
        assert "cannot mix" in result.output.lower()

    def test_save_too_many_positional_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text(SAMPLE_MULTI_ENV)
        cfg = tmp_path / "config"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["save", "a", "b", "c", "-c", str(cfg)]
        )
        assert result.exit_code != 0
        assert "at most two" in result.output.lower()

    def test_no_export_with_json_is_silent_noop(self, tmp_path, monkeypatch):
        """--no-export with --json/--yaml used to error; now it's a silent no-op
        because JSON/YAML output never carries the `export ` prefix."""
        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "config"
        (cfg / "prod").mkdir(parents=True)
        (cfg / "prod" / "public.env").write_text("export FOO=bar\n")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["load", "prod", "--no-export", "--json", "--flat", "-S", "-c", str(cfg)]
        )
        assert result.exit_code == 0, result.output
        import json
        data = json.loads(result.output)
        assert data == {"FOO": "bar"}

    def test_stdout_implies_no_export(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "config"
        (cfg / "prod").mkdir(parents=True)
        (cfg / "prod" / "public.env").write_text("export FOO=bar\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["load", "prod", "-S", "-c", str(cfg)])
        assert result.exit_code == 0, result.output
        assert "export " not in result.output
        assert "FOO=bar" in result.output

    def test_stdout_with_add_export_keeps_prefix(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "config"
        (cfg / "prod").mkdir(parents=True)
        (cfg / "prod" / "public.env").write_text("export FOO=bar\n")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["load", "prod", "-S", "--add-export", "-c", str(cfg)]
        )
        assert result.exit_code == 0, result.output
        assert "export FOO=bar" in result.output

    def test_file_output_default_keeps_export(self, tmp_path, monkeypatch):
        """No --stdout: file output preserves source style by default
        (no implicit transform)."""
        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "config"
        (cfg / "prod").mkdir(parents=True)
        (cfg / "prod" / "public.env").write_text("export FOO=bar\n")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["load", "prod", "-o", str(tmp_path / ".env"), "-c", str(cfg)]
        )
        assert result.exit_code == 0, result.output
        assert "export FOO=bar" in (tmp_path / ".env").read_text()

    def test_no_export_and_add_export_mutually_exclusive(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "config"
        (cfg / "prod").mkdir(parents=True)
        (cfg / "prod" / "public.env").write_text("FOO=bar\n")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["load", "prod", "--no-export", "--add-export", "-c", str(cfg)]
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()
