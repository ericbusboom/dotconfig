"""Tests for dotconfig.init"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from dotconfig.init import (
    _add_key_to_sops_yaml,
    _create_file_from_template,
    _create_template_if_missing,
    _derive_public_key,
    _discover_age_key,
    _extract_secret_key,
    _get_current_user,
    _harmonize_env_file,
    _init_templates,
    _parse_env_keys,
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


# ---------------------------------------------------------------------------
# _update_sops_yaml
# ---------------------------------------------------------------------------

class TestUpdateSopsYaml:
    def test_creates_sops_yaml_when_missing(self, tmp_path):
        _update_sops_yaml(tmp_path, FAKE_PUBLIC_KEY)
        sops_yaml = tmp_path / ".sops.yaml"
        assert sops_yaml.exists()
        content = sops_yaml.read_text()
        assert FAKE_PUBLIC_KEY in content
        assert "creation_rules" in content

    def test_created_file_contains_path_regex(self, tmp_path):
        _update_sops_yaml(tmp_path, FAKE_PUBLIC_KEY)
        content = (tmp_path / ".sops.yaml").read_text()
        assert "config/secrets/" in content

    def test_does_not_overwrite_when_key_already_listed(self, tmp_path):
        existing = (
            "creation_rules:\n"
            "  - path_regex: config/secrets/.+\\.env$\n"
            "    age: >-\n"
            f"      {FAKE_PUBLIC_KEY}\n"
        )
        sops_yaml = tmp_path / ".sops.yaml"
        sops_yaml.write_text(existing)
        original_mtime = sops_yaml.stat().st_mtime_ns

        _update_sops_yaml(tmp_path, FAKE_PUBLIC_KEY)
        assert sops_yaml.stat().st_mtime_ns == original_mtime

    def test_adds_key_to_existing_file(self, tmp_path):
        existing = (
            "creation_rules:\n"
            "  - path_regex: config/secrets/.+\\.env$\n"
            "    age: >-\n"
            "      age1otherkey,\n"
        )
        (tmp_path / ".sops.yaml").write_text(existing)
        _update_sops_yaml(tmp_path, FAKE_PUBLIC_KEY)
        content = (tmp_path / ".sops.yaml").read_text()
        assert "age1otherkey" in content
        assert FAKE_PUBLIC_KEY in content


# ---------------------------------------------------------------------------
# init_config — directory creation
# ---------------------------------------------------------------------------

class TestInitConfigDirectories:
    def test_creates_all_four_directories(self, tmp_path):
        config_dir = tmp_path / "config"
        with patch("dotconfig.init._discover_age_key", return_value=None):
            init_config(config_dir)
        assert (config_dir).is_dir()
        assert (config_dir / "secrets").is_dir()
        assert (config_dir / "local").is_dir()
        assert (config_dir / "secrets" / "local").is_dir()

    def test_existing_directories_not_overwritten(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        marker = config_dir / "marker.txt"
        marker.write_text("do not delete")
        with patch("dotconfig.init._discover_age_key", return_value=None):
            init_config(config_dir)
        # marker file should still be present
        assert marker.exists()

    def test_all_subdirs_created_idempotently(self, tmp_path):
        config_dir = tmp_path / "config"
        with patch("dotconfig.init._discover_age_key", return_value=None):
            init_config(config_dir)
            # Running a second time should not raise
            init_config(config_dir)

    def test_output_reports_created(self, tmp_path, capsys):
        config_dir = tmp_path / "config"
        with patch("dotconfig.init._discover_age_key", return_value=None):
            init_config(config_dir)
        out = capsys.readouterr().out
        assert "created" in out

    def test_output_reports_ok_for_existing(self, tmp_path, capsys):
        config_dir = tmp_path / "config"
        with patch("dotconfig.init._discover_age_key", return_value=None):
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
        with patch("dotconfig.init._discover_age_key", return_value=None):
            init_config(config_dir)
        out = capsys.readouterr().out
        assert "age-keygen" in out

    def test_key_found_updates_sops_yaml(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=FAKE_SECRET_KEY),
            patch("dotconfig.init._derive_public_key", side_effect=_fake_derive),
        ):
            init_config(config_dir)
        sops_yaml = tmp_path / ".sops.yaml"
        assert sops_yaml.exists()
        assert FAKE_PUBLIC_KEY in sops_yaml.read_text()

    def test_derive_failure_does_not_crash(self, tmp_path, capsys):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=FAKE_SECRET_KEY),
            patch("dotconfig.init._derive_public_key", return_value=None),
        ):
            init_config(config_dir)  # should not raise
        assert (config_dir).is_dir()

    def test_sops_yaml_created_in_project_root(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=FAKE_SECRET_KEY),
            patch("dotconfig.init._derive_public_key", side_effect=_fake_derive),
        ):
            init_config(config_dir)
        # .sops.yaml should be at tmp_path, not inside config/
        assert (tmp_path / ".sops.yaml").exists()
        assert not (config_dir / ".sops.yaml").exists()


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
# _parse_env_keys
# ---------------------------------------------------------------------------

class TestParseEnvKeys:
    def test_extracts_keys(self):
        assert _parse_env_keys("FOO=bar\nBAZ=qux\n") == ["FOO", "BAZ"]

    def test_ignores_comments(self):
        assert _parse_env_keys("# comment\nFOO=bar\n") == ["FOO"]

    def test_ignores_blank_lines(self):
        assert _parse_env_keys("\nFOO=bar\n\nBAZ=qux\n") == ["FOO", "BAZ"]

    def test_empty_value_included(self):
        assert _parse_env_keys("FOO=\nBAR=value\n") == ["FOO", "BAR"]

    def test_empty_content_returns_empty(self):
        assert _parse_env_keys("") == []

    def test_comment_only_returns_empty(self):
        assert _parse_env_keys("# comment 1\n# comment 2\n") == []

    def test_preserves_order(self):
        assert _parse_env_keys("ZEBRA=1\nAPPLE=2\nMIDDLE=3\n") == [
            "ZEBRA",
            "APPLE",
            "MIDDLE",
        ]


# ---------------------------------------------------------------------------
# _create_template_if_missing
# ---------------------------------------------------------------------------

class TestCreateTemplateIfMissing:
    def test_creates_file_when_missing(self, tmp_path):
        path = tmp_path / "public.env"
        _create_template_if_missing(path, "# header\n")
        assert path.exists()

    def test_created_file_has_header(self, tmp_path):
        path = tmp_path / "public.env"
        _create_template_if_missing(path, "# header\n")
        assert "# header" in path.read_text()

    def test_does_not_overwrite_existing_file(self, tmp_path):
        path = tmp_path / "public.env"
        path.write_text("MY_VAR=myvalue\n")
        _create_template_if_missing(path, "# header\n")
        assert "MY_VAR=myvalue" in path.read_text()

    def test_reports_created_for_new_file(self, tmp_path, capsys):
        path = tmp_path / "public.env"
        _create_template_if_missing(path, "# header\n")
        assert "created" in capsys.readouterr().out

    def test_reports_ok_for_existing_file(self, tmp_path, capsys):
        path = tmp_path / "public.env"
        path.write_text("# existing\n")
        _create_template_if_missing(path, "# header\n")
        assert "ok" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _harmonize_env_file
# ---------------------------------------------------------------------------

class TestHarmonizeEnvFile:
    def test_adds_missing_keys(self, tmp_path):
        template = tmp_path / "template.env"
        template.write_text("FOO=\nBAR=\n")
        target = tmp_path / "target.env"
        target.write_text("FOO=somevalue\n")

        _harmonize_env_file(template, target)

        content = target.read_text()
        assert "FOO=somevalue" in content
        assert "BAR=" in content

    def test_does_not_duplicate_existing_keys(self, tmp_path):
        template = tmp_path / "template.env"
        template.write_text("FOO=\nBAR=\n")
        target = tmp_path / "target.env"
        target.write_text("FOO=v1\nBAR=v2\n")

        _harmonize_env_file(template, target)

        content = target.read_text()
        assert content.count("FOO=") == 1
        assert content.count("BAR=") == 1

    def test_no_changes_when_all_keys_present(self, tmp_path):
        template = tmp_path / "template.env"
        template.write_text("FOO=\n")
        target = tmp_path / "target.env"
        target.write_text("FOO=value\n")
        original = target.read_text()

        _harmonize_env_file(template, target)

        assert target.read_text() == original

    def test_empty_template_no_changes(self, tmp_path):
        template = tmp_path / "template.env"
        template.write_text("# just comments\n")
        target = tmp_path / "target.env"
        target.write_text("MY_VAR=value\n")
        original = target.read_text()

        _harmonize_env_file(template, target)

        assert target.read_text() == original

    def test_reports_harmonized_when_keys_added(self, tmp_path, capsys):
        template = tmp_path / "template.env"
        template.write_text("FOO=\nBAR=\n")
        target = tmp_path / "target.env"
        target.write_text("FOO=value\n")

        _harmonize_env_file(template, target)

        assert "harmonized" in capsys.readouterr().out

    def test_no_output_when_nothing_added(self, tmp_path, capsys):
        template = tmp_path / "template.env"
        template.write_text("FOO=\n")
        target = tmp_path / "target.env"
        target.write_text("FOO=value\n")

        _harmonize_env_file(template, target)

        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# _create_file_from_template
# ---------------------------------------------------------------------------

class TestCreateFileFromTemplate:
    def test_creates_target_when_missing(self, tmp_path):
        template = tmp_path / "template.env"
        template.write_text("# header\nFOO=\n")
        target = tmp_path / "dev.env"

        _create_file_from_template(template, target)

        assert target.exists()

    def test_created_target_has_template_content(self, tmp_path):
        template = tmp_path / "template.env"
        template.write_text("# header\nFOO=\n")
        target = tmp_path / "dev.env"

        _create_file_from_template(template, target)

        assert "FOO=" in target.read_text()

    def test_does_not_overwrite_existing_target(self, tmp_path):
        template = tmp_path / "template.env"
        template.write_text("FOO=\n")
        target = tmp_path / "dev.env"
        target.write_text("FOO=devvalue\n")

        _create_file_from_template(template, target)

        assert "FOO=devvalue" in target.read_text()

    def test_harmonizes_new_template_vars_into_existing_target(self, tmp_path):
        template = tmp_path / "template.env"
        template.write_text("FOO=\nNEW_VAR=\n")
        target = tmp_path / "dev.env"
        target.write_text("FOO=devvalue\n")

        _create_file_from_template(template, target)

        content = target.read_text()
        assert "FOO=devvalue" in content
        assert "NEW_VAR=" in content

    def test_reports_created_for_new_file(self, tmp_path, capsys):
        template = tmp_path / "template.env"
        template.write_text("FOO=\n")
        target = tmp_path / "dev.env"

        _create_file_from_template(template, target)

        assert "created" in capsys.readouterr().out

    def test_reports_ok_for_existing_file(self, tmp_path, capsys):
        template = tmp_path / "template.env"
        template.write_text("FOO=\n")
        target = tmp_path / "dev.env"
        target.write_text("FOO=value\n")

        _create_file_from_template(template, target)

        assert "ok" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _init_templates
# ---------------------------------------------------------------------------

def _make_config_dirs(tmp_path: Path) -> Path:
    """Create the standard config directory layout under tmp_path."""
    config_dir = tmp_path / "config"
    (config_dir / "secrets" / "local").mkdir(parents=True)
    (config_dir / "local").mkdir(parents=True)
    return config_dir


class TestInitTemplates:
    def test_creates_public_template(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_templates(config_dir, "testuser")
        assert (config_dir / "public.env").exists()

    def test_creates_secret_template(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_templates(config_dir, "testuser")
        assert (config_dir / "secrets" / "secret.env").exists()

    def test_creates_dev_public_file(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_templates(config_dir, "testuser")
        assert (config_dir / "dev.env").exists()

    def test_creates_prod_public_file(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_templates(config_dir, "testuser")
        assert (config_dir / "prod.env").exists()

    def test_creates_user_local_public_file(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_templates(config_dir, "alice")
        assert (config_dir / "local" / "alice.env").exists()

    def test_creates_dev_secret_file(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_templates(config_dir, "testuser")
        assert (config_dir / "secrets" / "dev.env").exists()

    def test_creates_prod_secret_file(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_templates(config_dir, "testuser")
        assert (config_dir / "secrets" / "prod.env").exists()

    def test_creates_user_secret_local_file(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_templates(config_dir, "alice")
        assert (config_dir / "secrets" / "local" / "alice.env").exists()

    def test_idempotent_second_run(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)
        _init_templates(config_dir, "testuser")
        # A second run should not raise and files should remain intact
        _init_templates(config_dir, "testuser")
        assert (config_dir / "dev.env").exists()

    def test_harmonizes_new_template_variable_on_second_run(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)

        # First run: creates template and all env files
        _init_templates(config_dir, "testuser")

        # Add a new variable to the public template
        (config_dir / "public.env").write_text("# template\nNEW_VAR=\n")

        # Second run: should propagate NEW_VAR to all public env files
        _init_templates(config_dir, "testuser")

        assert "NEW_VAR=" in (config_dir / "dev.env").read_text()
        assert "NEW_VAR=" in (config_dir / "prod.env").read_text()
        assert "NEW_VAR=" in (config_dir / "local" / "testuser.env").read_text()

    def test_existing_values_preserved_during_harmonize(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)

        # Pre-populate dev.env with a value
        (config_dir / "public.env").write_text("MY_VAR=\n")
        (config_dir / "dev.env").write_text("MY_VAR=devvalue\n")
        (config_dir / "prod.env").write_text("")
        (config_dir / "local" / "testuser.env").write_text("")
        (config_dir / "secrets" / "secret.env").write_text("")
        (config_dir / "secrets" / "dev.env").write_text("")
        (config_dir / "secrets" / "prod.env").write_text("")
        (config_dir / "secrets" / "local" / "testuser.env").write_text("")

        _init_templates(config_dir, "testuser")

        # MY_VAR=devvalue must not be overwritten
        assert "MY_VAR=devvalue" in (config_dir / "dev.env").read_text()

    def test_secret_template_harmonizes_secret_files(self, tmp_path):
        config_dir = _make_config_dirs(tmp_path)

        # First run
        _init_templates(config_dir, "testuser")

        # Add a variable to the secret template
        (config_dir / "secrets" / "secret.env").write_text("# template\nDB_PASS=\n")

        # Second run
        _init_templates(config_dir, "testuser")

        assert "DB_PASS=" in (config_dir / "secrets" / "dev.env").read_text()
        assert "DB_PASS=" in (config_dir / "secrets" / "prod.env").read_text()
        assert "DB_PASS=" in (
            config_dir / "secrets" / "local" / "testuser.env"
        ).read_text()


# ---------------------------------------------------------------------------
# init_config — template integration
# ---------------------------------------------------------------------------

class TestInitConfigTemplates:
    def test_creates_public_template(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        assert (config_dir / "public.env").exists()

    def test_creates_secret_template(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        assert (config_dir / "secrets" / "secret.env").exists()

    def test_creates_all_default_env_files(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        assert (config_dir / "dev.env").exists()
        assert (config_dir / "prod.env").exists()
        assert (config_dir / "local" / "testuser.env").exists()
        assert (config_dir / "secrets" / "dev.env").exists()
        assert (config_dir / "secrets" / "prod.env").exists()
        assert (config_dir / "secrets" / "local" / "testuser.env").exists()

    def test_templates_created_even_without_age_key(self, tmp_path):
        """Template/file creation must happen even when no age key is found."""
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)
        assert (config_dir / "dev.env").exists()
        assert (config_dir / "secrets" / "dev.env").exists()

    def test_harmonizes_on_second_init_run(self, tmp_path):
        config_dir = tmp_path / "config"
        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)

        # Add variable to template
        (config_dir / "public.env").write_text("# template\nAPP_ENV=\n")

        with (
            patch("dotconfig.init._discover_age_key", return_value=None),
            patch("dotconfig.init._get_current_user", return_value="testuser"),
        ):
            init_config(config_dir)

        assert "APP_ENV=" in (config_dir / "dev.env").read_text()
        assert "APP_ENV=" in (config_dir / "prod.env").read_text()
        assert "APP_ENV=" in (config_dir / "local" / "testuser.env").read_text()
