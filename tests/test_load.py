"""Tests for dotconfig.load"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dotconfig.load import load_config


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    """Return a populated temporary config/ directory."""
    cfg = tmp_path / "config"

    # Common env files
    (cfg).mkdir()
    (cfg / "dev.env").write_text(
        "APP_DOMAIN=example.com\nNODE_ENV=development\nPORT=3000\n"
    )
    (cfg / "prod.env").write_text(
        "APP_DOMAIN=prod.example.com\nNODE_ENV=production\nPORT=8080\n"
    )

    # Secrets directory (plain text for tests — no real SOPS)
    (cfg / "secrets").mkdir()
    (cfg / "secrets" / "dev.env").write_text("SESSION_SECRET=abc123\n")

    # Local overrides
    (cfg / "local").mkdir()
    (cfg / "local" / "alice.env").write_text(
        "DEV_DOCKER_CONTEXT=orbstack\nQR_DOMAIN=http://192.168.1.1:5173/\n"
    )

    # Local secrets directory
    (cfg / "secrets" / "local").mkdir()

    return cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_decrypt(filepath: Path):
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
        assert "# --- public (dev) ---" in out.read_text()

    def test_secrets_section_marker_present(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert "# --- secrets (dev) ---" in out.read_text()

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
        assert "# --- public-local (alice) ---" in out.read_text()

    def test_secrets_local_section_marker_present(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", config_dir, out)
        assert "# --- secrets-local (alice) ---" in out.read_text()

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
        idx_public = text.index("# --- public (dev) ---")
        idx_secrets = text.index("# --- secrets (dev) ---")
        idx_local = text.index("# --- public-local (alice) ---")
        idx_secrets_local = text.index("# --- secrets-local (alice) ---")
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
        (config_dir / "secrets" / "dev.env").unlink()
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert out.exists()

    def test_missing_local_file_warns_and_continues(self, config_dir, tmp_path, capsys):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "unknown_dev", config_dir, out)
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert out.exists()

    def test_sops_failure_gracefully_skipped(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", return_value=None):
            load_config("dev", None, config_dir, out)
        text = out.read_text()
        # Section marker still present; variables not included
        assert "# --- secrets (dev) ---" in text
        assert "SESSION_SECRET" not in text
