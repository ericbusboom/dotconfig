"""Tests for dotconfig.init"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from dotconfig.init import (
    _add_key_to_sops_yaml,
    _create_env_if_missing,
    _derive_public_key,
    _discover_age_key,
    _extract_secret_key,
    _get_current_user,
    _init_env_files,
    _read_key_from_file,
    _update_sops_yaml,
    init_config,
)

# ---------------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------------

FAKE_SECRET_KEY = "AGE-SECRET-KEY-1QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ"
FAKE_PUBLIC_KEY = "age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq0"


def _fake_derive(secret_key: str):
    """Simulates successful age-keygen -y output."""
    return FAKE_PUBLIC_KEY


# ---------------------------------------------------------------------------
# _extract_secret_key
# ---------------------------------------------------------------------------

class TestExtractSecretKey:
    def test_valid_key_extracted(self):
        text = f"# comment\n{FAKE_SECRET_KEY}\n# another comment\n"
        assert _extract_secret_key(text) == FAKE_SECRET_KEY

    def test_inline_key_extracted(self):
        assert _extract_secret_key(FAKE_SECRET_KEY) == FAKE_SECRET_KEY

    def test_no_key_returns_none(self):
        assert _extract_secret_key("just text\nno key here") is None

    def test_invalid_format_ignored(self):
        assert _extract_secret_key("AGE-SECRET-KEY-") is None

    def test_whitespace_stripped(self):
        assert _extract_secret_key(f"  {FAKE_SECRET_KEY}  ") == FAKE_SECRET_KEY


# ---------------------------------------------------------------------------
# _read_key_from_file
# ---------------------------------------------------------------------------

class TestReadKeyFromFile:
    def test_reads_valid_key_from_file(self, tmp_path):
        key_file = tmp_path / "keys.txt"
        key_file.write_text(f"# public key: age1...\n{FAKE_SECRET_KEY}\n")
        assert _read_key_from_file(key_file) == FAKE_SECRET_KEY

    def test_missing_file_returns_none(self, tmp_path):
        assert _read_key_from_file(tmp_path / "nonexistent.txt") is None

    def test_file_without_key_returns_none(self, tmp_path):
        key_file = tmp_path / "keys.txt"
        key_file.write_text("# no key here\n")
        assert _read_key_from_file(key_file) is None


# ---------------------------------------------------------------------------
# _discover_age_key
# ---------------------------------------------------------------------------

class TestDiscoverAgeKey:
    def test_sops_age_key_env_var_has_priority(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SOPS_AGE_KEY", FAKE_SECRET_KEY)
        # Even if a key file also exists, env var wins
        key_file = tmp_path / "keys.txt"
        key_file.write_text("AGE-SECRET-KEY-OTHERKEY\n")
        monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(key_file))
        assert _discover_age_key() == FAKE_SECRET_KEY

    def test_sops_age_key_file_env_var_used(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SOPS_AGE_KEY", raising=False)
        key_file = tmp_path / "keys.txt"
        key_file.write_text(f"{FAKE_SECRET_KEY}\n")
        monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(key_file))
        assert _discover_age_key() == FAKE_SECRET_KEY

    def test_default_location_used_when_no_env_vars(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SOPS_AGE_KEY", raising=False)
        monkeypatch.delenv("SOPS_AGE_KEY_FILE", raising=False)
        default_dir = tmp_path / ".config" / "sops" / "age"
        default_dir.mkdir(parents=True)
        default_file = default_dir / "keys.txt"
        default_file.write_text(f"{FAKE_SECRET_KEY}\n")
        with patch("dotconfig.init.Path.home", return_value=tmp_path):
            result = _discover_age_key()
        assert result == FAKE_SECRET_KEY

    def test_returns_none_when_nothing_found(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SOPS_AGE_KEY", raising=False)
        monkeypatch.delenv("SOPS_AGE_KEY_FILE", raising=False)
        # Point home to an empty directory so the default key file is missing
        with patch("dotconfig.init.Path.home", return_value=tmp_path):
            result = _discover_age_key()
        assert result is None


# ---------------------------------------------------------------------------
# _derive_public_key
# ---------------------------------------------------------------------------

class TestDerivePublicKey:
    def test_returns_public_key_on_success(self):
        with patch("dotconfig.init.subprocess.run") as mock_run:
            mock_run.return_value.stdout = FAKE_PUBLIC_KEY + "\n"
            mock_run.return_value.returncode = 0
            result = _derive_public_key(FAKE_SECRET_KEY)
        assert result == FAKE_PUBLIC_KEY

    def test_returns_none_when_age_keygen_missing(self):
        import subprocess
        with patch(
            "dotconfig.init.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = _derive_public_key(FAKE_SECRET_KEY)
        assert result is None

    def test_returns_none_on_subprocess_error(self):
        import subprocess
        with patch(
            "dotconfig.init.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "age-keygen", stderr="bad key"),
        ):
            result = _derive_public_key(FAKE_SECRET_KEY)
        assert result is None


# ---------------------------------------------------------------------------
# _add_key_to_sops_yaml
# ---------------------------------------------------------------------------

class TestAddKeyToSopsYaml:
    BLOCK_SCALAR_CONTENT = (
        "creation_rules:\n"
        "  - path_regex: config/secrets/.+\\.env$\n"
        "    age: >-\n"
        "      age1existing1234,\n"
    )

    INLINE_CONTENT = (
        "creation_rules:\n"
        "  - path_regex: config/secrets/.+\\.env$\n"
        "    age: age1existing1234\n"
    )

    def test_key_appended_to_block_scalar(self):
        result = _add_key_to_sops_yaml(self.BLOCK_SCALAR_CONTENT, FAKE_PUBLIC_KEY)
        assert FAKE_PUBLIC_KEY in result

    def test_existing_key_gets_trailing_comma_in_block_scalar(self):
        content = (
            "creation_rules:\n"
            "  - path_regex: config/secrets/.+\\.env$\n"
            "    age: >-\n"
            "      age1existing1234\n"
        )
        result = _add_key_to_sops_yaml(content, FAKE_PUBLIC_KEY)
        assert "age1existing1234," in result
        assert FAKE_PUBLIC_KEY in result

    def test_key_appended_to_inline_value(self):
        result = _add_key_to_sops_yaml(self.INLINE_CONTENT, FAKE_PUBLIC_KEY)
        assert FAKE_PUBLIC_KEY in result

    def test_new_key_appears_after_existing_key(self):
        result = _add_key_to_sops_yaml(self.BLOCK_SCALAR_CONTENT, FAKE_PUBLIC_KEY)
        idx_existing = result.index("age1existing1234")
        idx_new = result.index(FAKE_PUBLIC_KEY)
        assert idx_existing < idx_new

    def test_key_inserted_when_age_field_empty(self):
        content = (
            "creation_rules:\n"
            "  - path_regex: .+/secrets\\.env$\n"
            "    age:\n"
        )
        result = _add_key_to_sops_yaml(content, FAKE_PUBLIC_KEY)
        assert FAKE_PUBLIC_KEY in result
        assert "age: >-" in result

    def test_key_inserted_when_age_field_empty_with_trailing_space(self):
        content = (
            "creation_rules:\n"
            "  - path_regex: .+/secrets\\.env$\n"
            "    age: \n"
        )
        result = _add_key_to_sops_yaml(content, FAKE_PUBLIC_KEY)
        assert FAKE_PUBLIC_KEY in result
        assert "age: >-" in result


# ---------------------------------------------------------------------------
# _update_sops_yaml
# ---------------------------------------------------------------------------

class TestUpdateSopsYaml:
    def test_creates_sops_yaml_when_missing(self, tmp_path):
        _update_sops_yaml(tmp_path, FAKE_PUBLIC_KEY)
        sops_yaml = tmp_path / "sops.yaml"
        assert sops_yaml.exists()
        content = sops_yaml.read_text()
        assert FAKE_PUBLIC_KEY in content
        assert "creation_rules" in content

    def test_created_file_contains_path_regex(self, tmp_path):
        _update_sops_yaml(tmp_path, FAKE_PUBLIC_KEY)
        content = (tmp_path / "sops.yaml").read_text()
        assert ".+/secrets" in content

    def test_does_not_overwrite_when_key_already_listed(self, tmp_path):
        existing = (
            "creation_rules:\n"
            "  - path_regex: config/.+/secrets\\.env$\n"
            "    age: >-\n"
            f"      {FAKE_PUBLIC_KEY}\n"
        )
        sops_yaml = tmp_path / "sops.yaml"
        sops_yaml.write_text(existing)
        original_mtime = sops_yaml.stat().st_mtime_ns

        _update_sops_yaml(tmp_path, FAKE_PUBLIC_KEY)
        assert sops_yaml.stat().st_mtime_ns == original_mtime

    def test_adds_key_to_existing_file(self, tmp_path):
        existing = (
            "creation_rules:\n"
            "  - path_regex: config/.+/secrets\\.env$\n"
            "    age: >-\n"
            "      age1otherkey,\n"
        )
        (tmp_path / "sops.yaml").write_text(existing)
        _update_sops_yaml(tmp_path, FAKE_PUBLIC_KEY)
        content = (tmp_path / "sops.yaml").read_text()
        assert "age1otherkey" in content
        assert FAKE_PUBLIC_KEY in content


# ---------------------------------------------------------------------------
# init_config — directory creation
# ---------------------------------------------------------------------------

class TestInitConfigDirectories:
    def test_creates_required_directories(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        assert (config_dir).is_dir()
        assert (config_dir / "local").is_dir()
        assert (config_dir / "dev").is_dir()
        assert (config_dir / "prod").is_dir()
        assert (config_dir / "local" / "testuser").is_dir()

    def test_existing_directories_not_overwritten(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        marker = config_dir / "marker.txt"
        marker.write_text("do not delete")
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        # marker file should still be present
        assert marker.exists()

    def test_all_subdirs_created_idempotently(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
            # Running a second time should not raise
            init_config(config_dir)

    def test_output_reports_created(self, tmp_path, capsys):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        out = capsys.readouterr().out
        assert "created" in out

    def test_output_reports_ok_for_existing(self, tmp_path, capsys):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
            capsys.readouterr()  # discard first run output
            init_config(config_dir)
        out = capsys.readouterr().out
        assert "ok" in out


# ---------------------------------------------------------------------------
# init_config — key setup
# ---------------------------------------------------------------------------

class TestInitConfigKeySetup:
    def test_no_key_found_prints_guidance(self, tmp_path, capsys):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        out = capsys.readouterr().out
        assert "age-keygen" in out

    def test_key_found_updates_sops_yaml(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=FAKE_SECRET_KEY),
            patch("dotconfig.init._derive_public_key", side_effect=_fake_derive),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        sops_yaml = config_dir / "sops.yaml"
        assert sops_yaml.exists()
        assert FAKE_PUBLIC_KEY in sops_yaml.read_text()

    def test_derive_failure_does_not_crash(self, tmp_path, capsys):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=FAKE_SECRET_KEY),
            patch("dotconfig.init._derive_public_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)  # should not raise
        assert (config_dir).is_dir()

    def test_sops_yaml_created_in_config_dir(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=FAKE_SECRET_KEY),
            patch("dotconfig.init._derive_public_key", side_effect=_fake_derive),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        # sops.yaml should be inside config/, not at project root
        assert (config_dir / "sops.yaml").exists()
        assert not (tmp_path / "sops.yaml").exists()


# ---------------------------------------------------------------------------
# _get_current_user
# ---------------------------------------------------------------------------

class TestGetCurrentUser:
    def test_returns_non_empty_string(self):
        result = _get_current_user()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_matches_getpass(self):
        import getpass
        assert _get_current_user() == getpass.getuser()


# ---------------------------------------------------------------------------
# _create_env_if_missing
# ---------------------------------------------------------------------------

class TestCreateEnvIfMissing:
    def test_creates_file_when_missing(self, tmp_path):
        path = tmp_path / "dev.env"
        _create_env_if_missing(path)
        assert path.exists()

    def test_created_file_is_empty(self, tmp_path):
        path = tmp_path / "dev.env"
        _create_env_if_missing(path)
        assert path.read_text() == ""

    def test_does_not_overwrite_existing_file(self, tmp_path):
        path = tmp_path / "dev.env"
        path.write_text("MY_VAR=myvalue\n")
        _create_env_if_missing(path)
        assert "MY_VAR=myvalue" in path.read_text()

    def test_reports_created_for_new_file(self, tmp_path, capsys):
        path = tmp_path / "dev.env"
        _create_env_if_missing(path)
        assert "created" in capsys.readouterr().out

    def test_reports_ok_for_existing_file(self, tmp_path, capsys):
        path = tmp_path / "dev.env"
        path.write_text("# existing\n")
        _create_env_if_missing(path)
        assert "ok" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _init_env_files
# ---------------------------------------------------------------------------

def _make_config_dirs(tmp_path: Path) -> Path:
    """Create the config directory under tmp_path."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    return config_dir


class TestInitEnvFiles:
    def test_creates_dev_public_file(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_env_files(config_dir, "testuser")
        assert (config_dir / "dev" / "public.env").exists()

    def test_creates_prod_public_file(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_env_files(config_dir, "testuser")
        assert (config_dir / "prod" / "public.env").exists()

    def test_creates_user_local_public_file(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_env_files(config_dir, "alice")
        assert (config_dir / "local" / "alice" / "public.env").exists()

    def test_creates_dev_secret_file(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_env_files(config_dir, "testuser")
        assert (config_dir / "dev" / "secrets.env").exists()

    def test_creates_prod_secret_file(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_env_files(config_dir, "testuser")
        assert (config_dir / "prod" / "secrets.env").exists()

    def test_creates_user_secret_local_file(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_env_files(config_dir, "alice")
        assert (config_dir / "local" / "alice" / "secrets.env").exists()

    def test_created_files_are_empty(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_env_files(config_dir, "testuser")
        assert (config_dir / "dev" / "public.env").read_text() == ""
        assert (config_dir / "dev" / "secrets.env").read_text() == ""

    def test_does_not_overwrite_existing_files(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        (config_dir / "dev").mkdir()
        (config_dir / "dev" / "public.env").write_text("MY_VAR=devvalue\n")
        _init_env_files(config_dir, "testuser")
        assert "MY_VAR=devvalue" in (config_dir / "dev" / "public.env").read_text()

    def test_idempotent_second_run(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_env_files(config_dir, "testuser")
        # A second run should not raise and files should remain intact
        _init_env_files(config_dir, "testuser")
        assert (config_dir / "dev" / "public.env").exists()

    def test_no_flat_env_files_created(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_env_files(config_dir, "testuser")
        assert not (config_dir / "dev.env").exists()
        assert not (config_dir / "secrets").exists()


# ---------------------------------------------------------------------------
# init_config — env-file integration
# ---------------------------------------------------------------------------

class TestInitConfigEnvFiles:
    def test_creates_all_default_env_files(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        assert (config_dir / "dev" / "public.env").exists()
        assert (config_dir / "dev" / "secrets.env").exists()
        assert (config_dir / "prod" / "public.env").exists()
        assert (config_dir / "prod" / "secrets.env").exists()
        assert (config_dir / "local" / "testuser" / "public.env").exists()
        assert (config_dir / "local" / "testuser" / "secrets.env").exists()

    def test_no_flat_env_files_created(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        assert not (config_dir / "dev.env").exists()
        assert not (config_dir / "secrets").exists()

    def test_env_files_created_even_without_age_key(self, tmp_path):
        """Env-file creation must happen even when no age key is found."""
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        assert (config_dir / "dev" / "public.env").exists()
        assert (config_dir / "dev" / "secrets.env").exists()

    def test_existing_env_files_not_overwritten(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)

        # Populate dev/public.env with values
        (config_dir / "dev" / "public.env").write_text("APP_ENV=development\n")

        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)

        # Values must be preserved after second run
        assert "APP_ENV=development" in (config_dir / "dev" / "public.env").read_text()
