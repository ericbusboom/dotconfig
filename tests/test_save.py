"""Tests for dotconfig.save"""

import os
from pathlib import Path
from unittest.mock import call, patch

import pytest

from dotconfig.save import _encrypt_sops, parse_env_file, save_config


# ---------------------------------------------------------------------------
# Sample .env content
# ---------------------------------------------------------------------------

SAMPLE_ENV_COMMON_ONLY = """\
# CONFIG_COMMON=dev

#@dotconfig: public (dev)
APP_DOMAIN=example.com
NODE_ENV=development
PORT=3000

#@dotconfig: secrets (dev)
SESSION_SECRET=abc123
GITHUB_CLIENT_ID=gh_xxx
"""

SAMPLE_ENV_WITH_LOCAL = """\
# CONFIG_COMMON=dev
# CONFIG_LOCAL=alice

#@dotconfig: public (dev)
APP_DOMAIN=example.com
NODE_ENV=development
PORT=3000

#@dotconfig: secrets (dev)
SESSION_SECRET=abc123
GITHUB_CLIENT_ID=gh_xxx

#@dotconfig: public-local (alice)
DEV_DOCKER_CONTEXT=orbstack
QR_DOMAIN=http://192.168.1.1:5173/
DEPLOYMENT=dev

#@dotconfig: secrets-local (alice)
"""

SAMPLE_ENV_WITH_LOCAL_SECRETS = """\
# CONFIG_COMMON=dev
# CONFIG_LOCAL=alice

#@dotconfig: public (dev)
APP_DOMAIN=example.com

#@dotconfig: secrets (dev)
SESSION_SECRET=abc123

#@dotconfig: public-local (alice)
QR_DOMAIN=http://192.168.1.1:5173/

#@dotconfig: secrets-local (alice)
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

    def test_legacy_markers_still_parsed(self):
        """Old-style # --- label --- markers are still recognised."""
        legacy = """\
# CONFIG_COMMON=dev

# --- public (dev) ---
APP_DOMAIN=example.com

# --- secrets (dev) ---
SESSION_SECRET=abc123
"""
        common, _, sections = parse_env_file(legacy)
        assert common == "dev"
        assert "public (dev)" in sections
        assert "APP_DOMAIN=example.com" in sections["public (dev)"]
        assert "secrets (dev)" in sections
        assert "SESSION_SECRET=abc123" in sections["secrets (dev)"]


# ---------------------------------------------------------------------------
# save_config — happy paths (SOPS mocked out)
# ---------------------------------------------------------------------------

def _fake_encrypt(content: str, filepath: Path, sops_config=None) -> bool:
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
        public = config_dir / "dev" / "public.env"
        assert public.exists()
        assert "APP_DOMAIN=example.com" in public.read_text()

    def test_secrets_file_written(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_COMMON_ONLY)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        secrets = config_dir / "dev" / "secrets.env"
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
        assert (config_dir / "dev" / "public.env").read_text().endswith("\n")


class TestSaveConfigWithLocal:
    def test_local_public_file_written(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        local_file = config_dir / "local" / "alice" / "public.env"
        assert local_file.exists()
        assert "DEV_DOCKER_CONTEXT=orbstack" in local_file.read_text()

    def test_empty_secrets_local_not_written(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        # secrets-local section is empty → no file created
        secrets_local = config_dir / "local" / "alice" / "secrets.env"
        assert not secrets_local.exists()

    def test_non_empty_secrets_local_written(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL_SECRETS)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        secrets_local = config_dir / "local" / "alice" / "secrets.env"
        assert secrets_local.exists()
        assert "PERSONAL_TOKEN=pt_secret" in secrets_local.read_text()

    def test_all_expected_files_created(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL_SECRETS)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        assert (config_dir / "dev" / "public.env").exists()
        assert (config_dir / "dev" / "secrets.env").exists()
        assert (config_dir / "local" / "alice" / "public.env").exists()
        assert (config_dir / "local" / "alice" / "secrets.env").exists()


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
        assert "could not encrypt" in captured.err
        # Public file should still be written
        assert (config_dir / "dev" / "public.env").exists()

    def test_sops_key_extracted_from_env(self, env_file, config_dir, monkeypatch):
        """SOPS_AGE_KEY_FILE inside .env is forwarded to the environment."""
        env_content = SAMPLE_ENV_COMMON_ONLY + "SOPS_AGE_KEY_FILE=/home/alice/.config/sops/keys.txt\n"
        env_file.write_text(env_content)
        monkeypatch.delenv("SOPS_AGE_KEY_FILE", raising=False)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        assert os.environ.get("SOPS_AGE_KEY_FILE") == "/home/alice/.config/sops/keys.txt"


# ---------------------------------------------------------------------------
# save_config — override common/local (save to different location)
# ---------------------------------------------------------------------------

class TestSaveConfigOverride:
    def test_override_common_writes_to_different_env(self, env_file, config_dir):
        """Saving with override_common='prod' writes to prod/public.env, not dev/public.env."""
        env_file.write_text(SAMPLE_ENV_COMMON_ONLY)  # CONFIG_COMMON=dev
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir, override_common="prod")
        assert (config_dir / "prod" / "public.env").exists()
        assert not (config_dir / "dev" / "public.env").exists()

    def test_override_common_writes_correct_content(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_COMMON_ONLY)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir, override_common="staging")
        staging = config_dir / "staging" / "public.env"
        assert staging.exists()
        assert "APP_DOMAIN=example.com" in staging.read_text()

    def test_override_common_writes_secrets_to_new_env(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_COMMON_ONLY)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir, override_common="staging")
        secrets = config_dir / "staging" / "secrets.env"
        assert secrets.exists()
        assert "SESSION_SECRET=abc123" in secrets.read_text()

    def test_override_local_writes_to_different_user(self, env_file, config_dir):
        """Saving with override_local='bob' writes to local/bob/public.env, not local/alice/public.env."""
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL)  # CONFIG_LOCAL=alice
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir, override_local="bob")
        assert (config_dir / "local" / "bob" / "public.env").exists()
        assert not (config_dir / "local" / "alice" / "public.env").exists()

    def test_override_local_writes_correct_content(self, env_file, config_dir):
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir, override_local="bob")
        bob_file = config_dir / "local" / "bob" / "public.env"
        assert "DEV_DOCKER_CONTEXT=orbstack" in bob_file.read_text()

    def test_override_both_common_and_local(self, env_file, config_dir):
        """Can override both common and local simultaneously."""
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL_SECRETS)  # dev + alice
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir, override_common="prod", override_local="stan")
        assert (config_dir / "prod" / "public.env").exists()
        assert (config_dir / "local" / "stan" / "public.env").exists()
        assert (config_dir / "prod" / "secrets.env").exists()
        assert (config_dir / "local" / "stan" / "secrets.env").exists()

    def test_no_override_uses_metadata_names(self, env_file, config_dir):
        """Without overrides, existing behaviour is unchanged."""
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL)
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        assert (config_dir / "dev" / "public.env").exists()
        assert (config_dir / "local" / "alice" / "public.env").exists()

    def test_override_common_rewrites_deployment_variable(self, env_file, config_dir):
        """DEPLOYMENT= is rewritten to match the target deployment."""
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL)  # has DEPLOYMENT=dev
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir, override_common="prod")
        local_file = config_dir / "local" / "alice" / "public.env"
        content = local_file.read_text()
        assert "DEPLOYMENT=prod" in content
        assert "DEPLOYMENT=dev" not in content

    def test_same_deployment_keeps_deployment_variable(self, env_file, config_dir):
        """DEPLOYMENT= is unchanged when saving to the same deployment."""
        env_file.write_text(SAMPLE_ENV_WITH_LOCAL)  # has DEPLOYMENT=dev
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir)
        local_file = config_dir / "local" / "alice" / "public.env"
        content = local_file.read_text()
        assert "DEPLOYMENT=dev" in content

    def test_override_common_no_local_in_env(self, env_file, config_dir):
        """override_local is ignored when .env has no local sections."""
        env_file.write_text(SAMPLE_ENV_COMMON_ONLY)  # no local
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(env_file, config_dir, override_common="prod", override_local="stan")
        # Common files should be created with the override name
        assert (config_dir / "prod" / "public.env").exists()
        assert "APP_DOMAIN=example.com" in (config_dir / "prod" / "public.env").read_text()
        # Local files should NOT be created since there are no local sections
        assert not (config_dir / "local").exists()


# ---------------------------------------------------------------------------
# save_config — sops.yaml --config flag
# ---------------------------------------------------------------------------

class TestSaveConfigSopsConfig:
    def test_sops_config_passed_when_sops_yaml_exists(self, env_file, config_dir):
        """When config/sops.yaml exists, _encrypt_sops is called with its path."""
        sops_yaml = config_dir / "sops.yaml"
        sops_yaml.write_text("creation_rules: []\n")
        env_file.write_text(SAMPLE_ENV_COMMON_ONLY)

        calls = []

        def capture_encrypt(content, filepath, sops_config=None):
            calls.append(sops_config)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content)
            return True

        with patch("dotconfig.save._encrypt_sops", side_effect=capture_encrypt):
            save_config(env_file, config_dir)

        assert calls, "expected _encrypt_sops to be called"
        assert all(sc == sops_yaml for sc in calls)

    def test_sops_config_path_passed_when_sops_yaml_missing(self, env_file, config_dir):
        """When config/sops.yaml does not exist, sops_config path is still passed; --config is NOT used."""
        env_file.write_text(SAMPLE_ENV_COMMON_ONLY)

        calls = []

        def capture_encrypt(content, filepath, sops_config=None):
            calls.append(sops_config)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content)
            return True

        with patch("dotconfig.save._encrypt_sops", side_effect=capture_encrypt):
            save_config(env_file, config_dir)

        assert calls, "expected _encrypt_sops to be called"
        expected = config_dir / "sops.yaml"
        assert not expected.exists(), "sops.yaml should be absent for this test"
        assert all(sc == expected for sc in calls)

    def test_encrypt_sops_includes_config_flag_in_cmd(self, tmp_path):
        """_encrypt_sops passes --config to subprocess when sops_config exists."""
        sops_yaml = tmp_path / "sops.yaml"
        sops_yaml.write_text("creation_rules: []\n")
        target = tmp_path / "secrets.env"
        target.parent.mkdir(parents=True, exist_ok=True)

        import subprocess
        from unittest.mock import MagicMock

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            # Create the target dir so mkstemp works
            _encrypt_sops("SECRET=value\n", target, sops_config=sops_yaml)

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "--config" in cmd
        assert str(sops_yaml) in cmd

    def test_encrypt_sops_no_config_flag_when_sops_yaml_missing(self, tmp_path):
        """_encrypt_sops omits --config from subprocess when sops_config absent."""
        target = tmp_path / "secrets.env"
        target.parent.mkdir(parents=True, exist_ok=True)
        sops_yaml = tmp_path / "sops.yaml"  # does not exist
        assert not sops_yaml.exists()

        import subprocess
        from unittest.mock import MagicMock

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _encrypt_sops("SECRET=value\n", target, sops_config=sops_yaml)

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "--config" not in cmd
