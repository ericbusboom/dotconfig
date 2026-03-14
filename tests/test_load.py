"""Tests for dotconfig.load"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dotconfig.load import _decrypt_sops, load_config


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    """Return a populated temporary config/ directory."""
    cfg = tmp_path / "config"

    # Dev environment
    (cfg / "dev").mkdir(parents=True)
    (cfg / "dev" / "public.env").write_text(
        "APP_DOMAIN=example.com\nNODE_ENV=development\nPORT=3000\n"
    )
    (cfg / "dev" / "secrets.env").write_text("SESSION_SECRET=abc123\n")

    # Prod environment
    (cfg / "prod").mkdir(parents=True)
    (cfg / "prod" / "public.env").write_text(
        "APP_DOMAIN=prod.example.com\nNODE_ENV=production\nPORT=8080\n"
    )

    # Local overrides
    (cfg / "local" / "alice").mkdir(parents=True)
    (cfg / "local" / "alice" / "public.env").write_text(
        "DEV_DOCKER_CONTEXT=orbstack\nQR_DOMAIN=http://192.168.1.1:5173/\n"
    )

    return cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_decrypt(filepath: Path, sops_config=None):
    """Return file contents as-is (simulates successful sops decrypt)."""
    return filepath.read_text()


# ---------------------------------------------------------------------------
# load_config — happy paths
# ---------------------------------------------------------------------------

class TestLoadConfigCommonOnly:
    def test_output_file_is_created(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert out.exists()

    def test_metadata_header_written(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        text = out.read_text()
        assert "# CONFIG_COMMON=dev" in text
        assert "CONFIG_LOCAL" not in text

    def test_public_section_marker_present(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert "#@dotconfig: public (dev)" in out.read_text()

    def test_secrets_section_marker_present(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert "#@dotconfig: secrets (dev)" in out.read_text()

    def test_public_variables_included(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        text = out.read_text()
        assert "APP_DOMAIN=example.com" in text
        assert "NODE_ENV=development" in text

    def test_secret_variables_included(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert "SESSION_SECRET=abc123" in out.read_text()

    def test_no_local_sections_when_local_name_omitted(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        text = out.read_text()
        assert "public-local" not in text
        assert "secrets-local" not in text

    def test_file_ends_with_newline(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert out.read_text().endswith("\n")


class TestLoadConfigWithLocal:
    def test_config_local_metadata_written(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", config_dir, out)
        assert "# CONFIG_LOCAL=alice" in out.read_text()

    def test_public_local_section_marker_present(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", config_dir, out)
        assert "#@dotconfig: public-local (alice)" in out.read_text()

    def test_secrets_local_section_marker_present(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", config_dir, out)
        assert "#@dotconfig: secrets-local (alice)" in out.read_text()

    def test_local_variables_included(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", config_dir, out)
        text = out.read_text()
        assert "DEV_DOCKER_CONTEXT=orbstack" in text
        assert "QR_DOMAIN=http://192.168.1.1:5173/" in text

    def test_section_order(self, config_dir, tmp_path):
        """Public sections come before local sections."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", config_dir, out)
        text = out.read_text()
        idx_public = text.index("#@dotconfig: public (dev)")
        idx_secrets = text.index("#@dotconfig: secrets (dev)")
        idx_local = text.index("#@dotconfig: public-local (alice)")
        idx_secrets_local = text.index("#@dotconfig: secrets-local (alice)")
        assert idx_public < idx_secrets < idx_local < idx_secrets_local

    def test_prod_environment(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", return_value=None):
            load_config("prod", None, config_dir, out)
        text = out.read_text()
        assert "# CONFIG_COMMON=prod" in text
        assert "APP_DOMAIN=prod.example.com" in text


# ---------------------------------------------------------------------------
# load_config — error / edge cases
# ---------------------------------------------------------------------------

class TestLoadConfigErrors:
    def test_missing_common_env_exits(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with pytest.raises(SystemExit):
            load_config("nonexistent", None, config_dir, out)

    def test_missing_secrets_file_does_not_crash(self, config_dir, tmp_path, capsys):
        out = tmp_path / ".env"
        # Remove secrets file
        (config_dir / "dev" / "secrets.env").unlink()
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert out.exists()

    def test_missing_local_file_warns_and_continues(self, config_dir, tmp_path, capsys):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "unknown_dev", config_dir, out)
        captured = capsys.readouterr()
        assert "not found" in captured.err
        assert out.exists()

    def test_sops_failure_gracefully_skipped(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", return_value=None):
            load_config("dev", None, config_dir, out)
        text = out.read_text()
        # Section marker still present; variables not included
        assert "#@dotconfig: secrets (dev)" in text
        assert "SESSION_SECRET" not in text


# ---------------------------------------------------------------------------
# load_config — sops.yaml --config flag
# ---------------------------------------------------------------------------

class TestLoadConfigSopsConfig:
    def test_sops_config_passed_when_sops_yaml_exists(self, config_dir, tmp_path):
        """When config/sops.yaml exists, _decrypt_sops is called with its path."""
        sops_yaml = config_dir / "sops.yaml"
        sops_yaml.write_text("creation_rules: []\n")
        out = tmp_path / ".env"

        calls = []

        def capture_decrypt(filepath, sops_config=None):
            calls.append(sops_config)
            return filepath.read_text()

        with patch("dotconfig.load._decrypt_sops", side_effect=capture_decrypt):
            load_config("dev", None, config_dir, out)

        assert calls, "expected _decrypt_sops to be called"
        assert all(sc == sops_yaml for sc in calls)

    def test_sops_config_path_passed_when_sops_yaml_missing(self, config_dir, tmp_path):
        """When config/sops.yaml does not exist, sops_config path is still passed; --config is NOT used."""
        out = tmp_path / ".env"

        calls = []

        def capture_decrypt(filepath, sops_config=None):
            calls.append(sops_config)
            return filepath.read_text()

        with patch("dotconfig.load._decrypt_sops", side_effect=capture_decrypt):
            load_config("dev", None, config_dir, out)

        assert calls, "expected _decrypt_sops to be called"
        expected = config_dir / "sops.yaml"
        assert not expected.exists(), "sops.yaml should be absent for this test"
        assert all(sc == expected for sc in calls)

    def test_decrypt_sops_includes_config_flag_in_cmd(self, tmp_path):
        """_decrypt_sops passes --config to subprocess when sops_config exists."""
        sops_yaml = tmp_path / "sops.yaml"
        sops_yaml.write_text("creation_rules: []\n")
        secrets_file = tmp_path / "secrets.env"
        secrets_file.write_text("SECRET=value\n")

        mock_result = MagicMock()
        mock_result.stdout = "SECRET=value\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _decrypt_sops(secrets_file, sops_config=sops_yaml)

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "--config" in cmd
        assert str(sops_yaml) in cmd

    def test_decrypt_sops_no_config_flag_when_sops_yaml_missing(self, tmp_path):
        """_decrypt_sops omits --config when sops_config file does not exist."""
        sops_yaml = tmp_path / "sops.yaml"  # does not exist
        assert not sops_yaml.exists()
        secrets_file = tmp_path / "secrets.env"
        secrets_file.write_text("SECRET=value\n")

        mock_result = MagicMock()
        mock_result.stdout = "SECRET=value\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _decrypt_sops(secrets_file, sops_config=sops_yaml)

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "--config" not in cmd
