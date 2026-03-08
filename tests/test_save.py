"""Tests for dotconfig.save"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from dotconfig.save import parse_env_file, save_config


# ---------------------------------------------------------------------------
# Sample .env content
# ---------------------------------------------------------------------------

SAMPLE_ENV_COMMON_ONLY = """\
# CONFIG_COMMON=dev

# --- public (dev) ---
APP_DOMAIN=example.com
NODE_ENV=development
PORT=3000

# --- secrets (dev) ---
SESSION_SECRET=abc123
GITHUB_CLIENT_ID=gh_xxx
"""

SAMPLE_ENV_WITH_LOCAL = """\
# CONFIG_COMMON=dev
# CONFIG_LOCAL=alice

# --- public (dev) ---
APP_DOMAIN=example.com
NODE_ENV=development
PORT=3000

# --- secrets (dev) ---
SESSION_SECRET=abc123
GITHUB_CLIENT_ID=gh_xxx

# --- public-local (alice) ---
DEV_DOCKER_CONTEXT=orbstack
QR_DOMAIN=http://192.168.1.1:5173/

# --- secrets-local (alice) ---
"""

SAMPLE_ENV_WITH_LOCAL_SECRETS = """\
# CONFIG_COMMON=dev
# CONFIG_LOCAL=alice

# --- public (dev) ---
APP_DOMAIN=example.com

# --- secrets (dev) ---
SESSION_SECRET=abc123

# --- public-local (alice) ---
QR_DOMAIN=http://192.168.1.1:5173/

# --- secrets-local (alice) ---
PERSONAL_TOKEN=pt_secret
"""


# ---------------------------------------------------------------------------
# parse_env_file
# ---------------------------------------------------------------------------

class TestParseEnvFile:
    def test_common_name_extracted(self):
        common, _, _ = parse_env_file(SAMPLE_ENV_COMMON_ONLY)
        assert common == "dev"

    def test_local_name_none_when_absent(self):
        _, local, _ = parse_env_file(SAMPLE_ENV_COMMON_ONLY)
        assert local is None

    def test_local_name_extracted(self):
        _, local, _ = parse_env_file(SAMPLE_ENV_WITH_LOCAL)
        assert local == "alice"

    def test_public_section_parsed(self):
        _, _, sections = parse_env_file(SAMPLE_ENV_COMMON_ONLY)
        assert "public (dev)" in sections
        body = sections["public (dev)"]
        assert "APP_DOMAIN=example.com" in body
        assert "NODE_ENV=development" in body

    def test_secrets_section_parsed(self):
        _, _, sections = parse_env_file(SAMPLE_ENV_COMMON_ONLY)
        assert "secrets (dev)" in sections
        body = sections["secrets (dev)"]
        assert "SESSION_SECRET=abc123" in body

    def test_public_local_section_parsed(self):
        _, _, sections = parse_env_file(SAMPLE_ENV_WITH_LOCAL)
        assert "public-local (alice)" in sections
        body = sections["public-local (alice)"]
        assert "DEV_DOCKER_CONTEXT=orbstack" in body

    def test_secrets_local_section_empty(self):
        _, _, sections = parse_env_file(SAMPLE_ENV_WITH_LOCAL)
        # Section exists but has no variables
        body = sections.get("secrets-local (alice)", "")
        assert body == ""

    def test_secrets_local_section_with_content(self):
        _, _, sections = parse_env_file(SAMPLE_ENV_WITH_LOCAL_SECRETS)
        body = sections.get("secrets-local (alice)", "")
        assert "PERSONAL_TOKEN=pt_secret" in body

    def test_all_four_sections_present_with_local(self):
        _, _, sections = parse_env_file(SAMPLE_ENV_WITH_LOCAL)
        assert "public (dev)" in sections
        assert "secrets (dev)" in sections
        assert "public-local (alice)" in sections
        assert "secrets-local (alice)" in sections

    def test_empty_file_returns_nones(self):
        common, local, sections = parse_env_file("")
        assert common is None
        assert local is None
        assert sections == {}


# ---------------------------------------------------------------------------
# save_config — happy paths (SOPS mocked out)
# ---------------------------------------------------------------------------

def _fake_encrypt(content: str, filepath: Path) -> bool:
    """Simulates successful sops encrypt by writing plaintext."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)
    return True


@pytest.fixture()
def env_file(tmp_path: Path) -> Path:
    return tmp_path / ".env"


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    return d


class TestSaveConfigCommonOnly:
    def test_public_file_written(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_COMMON_ONLY)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        public = config_dir / "dev.env"
        assert public.exists()
        assert "APP_DOMAIN=example.com" in public.read_text()

    def test_secrets_file_written(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_COMMON_ONLY)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        secrets = config_dir / "secrets" / "dev.env"
        assert secrets.exists()
        assert "SESSION_SECRET=abc123" in secrets.read_text()

    def test_no_local_files_created(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_COMMON_ONLY)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        assert not (config_dir / "local").exists()

    def test_public_file_ends_with_newline(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_COMMON_ONLY)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        assert (config_dir / "dev.env").read_text().endswith("\n")


class TestSaveConfigWithLocal:
    def test_local_public_file_written(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        local_file = config_dir / "local" / "alice.env"
        assert local_file.exists()
        assert "DEV_DOCKER_CONTEXT=orbstack" in local_file.read_text()

    def test_empty_secrets_local_not_written(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        # secrets-local section is empty → no file created
        secrets_local = config_dir / "secrets" / "local" / "alice.env"
        assert not secrets_local.exists()

    def test_non_empty_secrets_local_written(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL_SECRETS)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        secrets_local = config_dir / "secrets" / "local" / "alice.env"
        assert secrets_local.exists()
        assert "PERSONAL_TOKEN=pt_secret" in secrets_local.read_text()

    def test_all_expected_files_created(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL_SECRETS)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        assert (config_dir / "dev.env").exists()
        assert (config_dir / "secrets" / "dev.env").exists()
        assert (config_dir / "local" / "alice.env").exists()
        assert (config_dir / "secrets" / "local" / "alice.env").exists()


# ---------------------------------------------------------------------------
# save_config — error / edge cases
# ---------------------------------------------------------------------------

class TestSaveConfigErrors:
    def test_missing_env_file_exits(self, config_dir, tmp_path):
        with pytest.raises(SystemExit):
            save_config(tmp_path / "nonexistent.env", config_dir)

    def test_missing_config_common_exits(self, env_file, config_dir):
        env_file.write_text("APP_DOMAIN=example.com\n")  # no CONFIG_COMMON
        with pytest.raises(SystemExit):
            save_config(env_file, config_dir)

    def test_sops_failure_warns_but_continues(self, env_file, config_dir, capsys):
        env_file.write_text(SAMPLE_ENV_COMMON_ONLY)
        with patch("dotconfig.save._encrypt_sops", return_value=False):
            save_config(env_file, config_dir)
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        # Public file should still be written
        assert (config_dir / "dev.env").exists()

    def test_sops_key_extracted_from_env(self, env_file, config_dir, monkeypatch):
        """SOPS_AGE_KEY_FILE inside .env is forwarded to the environment."""
        env_content = SAMPLE_ENV_COMMON_ONLY + "SOPS_AGE_KEY_FILE=/home/alice/.config/sops/keys.txt\n"
        env_file.write_text(env_content)
        monkeypatch.delenv("SOPS_AGE_KEY_FILE", raising=False)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        assert os.environ.get("SOPS_AGE_KEY_FILE") == "/home/alice/.config/sops/keys.txt"
