"""Tests for dotconfig.gh_push — GitHub secrets sync."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from dotconfig.gh_push import _detect_repo, _load_secrets_flat, gh_push


@pytest.fixture
def config_with_secrets(tmp_path):
    """Create a config directory with a deployment that has secrets."""
    cfg = tmp_path / "config"
    prod = cfg / "prod"
    prod.mkdir(parents=True)

    (prod / "public.env").write_text("APP_NAME=myapp\nDEBUG=false\n")
    (prod / "secrets.env").write_text("DATABASE_URL=postgresql://...\nSECRET_KEY=abc123\n")

    # sops.yaml (not used in tests with mocked decryption)
    (cfg / "sops.yaml").write_text("creation_rules: []\n")

    return cfg


class TestDetectRepo:
    def test_ssh_url(self):
        with patch("dotconfig.gh_push.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="git@github.com:owner/repo.git\n",
                returncode=0,
            )
            assert _detect_repo() == "owner/repo"

    def test_https_url(self):
        with patch("dotconfig.gh_push.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="https://github.com/owner/repo.git\n",
                returncode=0,
            )
            assert _detect_repo() == "owner/repo"

    def test_no_remote(self):
        with patch("dotconfig.gh_push.subprocess.run",
                    side_effect=FileNotFoundError):
            assert _detect_repo() is None


class TestLoadSecretsFlat:
    def test_loads_public_and_secrets(self, config_with_secrets):
        secrets = _load_secrets_flat("prod", config_with_secrets)
        assert secrets["APP_NAME"] == "myapp"
        assert secrets["DATABASE_URL"] == "postgresql://..."
        assert secrets["SECRET_KEY"] == "abc123"


class TestGhPush:
    def test_dry_run(self, config_with_secrets, capsys):
        gh_push(
            deployment="prod",
            config_dir=config_with_secrets,
            repo="owner/repo",
            dry_run=True,
        )
        out = capsys.readouterr().out
        assert "Dry run" in out
        assert "APP_NAME" in out
        assert "DATABASE_URL" in out

    def test_pushes_to_actions_and_codespaces(self, config_with_secrets, capsys):
        with patch("dotconfig.gh_push.shutil.which", return_value="/usr/bin/gh"), \
             patch("dotconfig.gh_push.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            gh_push(
                deployment="prod",
                config_dir=config_with_secrets,
                repo="owner/repo",
            )

        # Should push each secret twice (Actions + Codespaces)
        # 4 secrets × 2 scopes = 8 calls
        assert mock_run.call_count == 8

    def test_actions_only(self, config_with_secrets, capsys):
        with patch("dotconfig.gh_push.shutil.which", return_value="/usr/bin/gh"), \
             patch("dotconfig.gh_push.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            gh_push(
                deployment="prod",
                config_dir=config_with_secrets,
                repo="owner/repo",
                actions=True,
            )

        # 4 secrets × 1 scope = 4 calls
        assert mock_run.call_count == 4

    def test_codespaces_only(self, config_with_secrets, capsys):
        with patch("dotconfig.gh_push.shutil.which", return_value="/usr/bin/gh"), \
             patch("dotconfig.gh_push.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            gh_push(
                deployment="prod",
                config_dir=config_with_secrets,
                repo="owner/repo",
                codespaces=True,
            )

        # 4 secrets × 1 scope = 4 calls
        assert mock_run.call_count == 4
        # Check --app codespaces is in the calls
        for c in mock_run.call_args_list:
            cmd = c[0][0]
            assert "--app" in cmd
            assert "codespaces" in cmd

    def test_keys_filter(self, config_with_secrets, capsys):
        with patch("dotconfig.gh_push.shutil.which", return_value="/usr/bin/gh"), \
             patch("dotconfig.gh_push.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            gh_push(
                deployment="prod",
                config_dir=config_with_secrets,
                repo="owner/repo",
                actions=True,
                keys_filter=["DATABASE_URL"],
            )

        # Only 1 secret × 1 scope = 1 call
        assert mock_run.call_count == 1

    def test_environment_flag(self, config_with_secrets, capsys):
        with patch("dotconfig.gh_push.shutil.which", return_value="/usr/bin/gh"), \
             patch("dotconfig.gh_push.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            gh_push(
                deployment="prod",
                config_dir=config_with_secrets,
                repo="owner/repo",
                environment="prod",
            )

        # Check --env prod is in the calls
        for c in mock_run.call_args_list:
            cmd = c[0][0]
            assert "--env" in cmd
            assert "prod" in cmd

    def test_no_gh_cli(self, config_with_secrets):
        with patch("dotconfig.gh_push.shutil.which", return_value=None):
            with pytest.raises(SystemExit):
                gh_push(
                    deployment="prod",
                    config_dir=config_with_secrets,
                    repo="owner/repo",
                )

    def test_no_repo_detected(self, config_with_secrets):
        with patch("dotconfig.gh_push.shutil.which", return_value="/usr/bin/gh"), \
             patch("dotconfig.gh_push._detect_repo", return_value=None):
            with pytest.raises(SystemExit):
                gh_push(
                    deployment="prod",
                    config_dir=config_with_secrets,
                )

    def test_excludes_age_key_by_default(self, config_with_secrets, capsys):
        # Add SOPS_AGE_KEY to secrets
        secrets_file = config_with_secrets / "prod" / "secrets.env"
        secrets_file.write_text(
            "DATABASE_URL=postgresql://...\nSOPS_AGE_KEY=AGE-SECRET-KEY-1XXX\n"
        )

        with patch("dotconfig.gh_push.shutil.which", return_value="/usr/bin/gh"), \
             patch("dotconfig.gh_push.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            gh_push(
                deployment="prod",
                config_dir=config_with_secrets,
                repo="owner/repo",
                actions=True,
            )

        # SOPS_AGE_KEY should not be in any call
        for c in mock_run.call_args_list:
            cmd = c[0][0]
            assert "SOPS_AGE_KEY" not in cmd
