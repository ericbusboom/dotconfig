"""Tests for dotconfig.discover"""

from pathlib import Path
from unittest.mock import patch

import pytest

from dotconfig.discover import (
    DEFAULT_NAME,
    ENV_VAR,
    _git_root,
    config_dir_name,
    find_config_dir,
)


# ---------------------------------------------------------------------------
# config_dir_name
# ---------------------------------------------------------------------------


class TestConfigDirName:
    def test_default_is_config(self, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        assert config_dir_name() == DEFAULT_NAME

    def test_env_var_overrides_default(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, ".config")
        assert config_dir_name() == ".config"


# ---------------------------------------------------------------------------
# _git_root
# ---------------------------------------------------------------------------


class TestGitRoot:
    def test_finds_git_root(self, tmp_path):
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "a" / "b" / "c"
        sub.mkdir(parents=True)
        assert _git_root(sub) == tmp_path

    def test_returns_none_outside_git(self, tmp_path):
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        assert _git_root(sub) is None

    def test_root_is_start_dir(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assert _git_root(tmp_path) == tmp_path


# ---------------------------------------------------------------------------
# find_config_dir
# ---------------------------------------------------------------------------


class TestFindConfigDir:
    def test_finds_in_current_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        (tmp_path / ".git").mkdir()
        (tmp_path / "config").mkdir()
        result = find_config_dir(tmp_path)
        assert result == (tmp_path / "config").resolve()

    def test_walks_up_to_git_root(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        (tmp_path / ".git").mkdir()
        (tmp_path / "config").mkdir()
        sub = tmp_path / "src" / "app"
        sub.mkdir(parents=True)
        result = find_config_dir(sub)
        assert result == (tmp_path / "config").resolve()

    def test_stops_at_git_root(self, tmp_path, monkeypatch):
        """Config dir above .git root is not found."""
        monkeypatch.delenv(ENV_VAR, raising=False)
        # config/ is one level above the git root
        (tmp_path / "config").mkdir()
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        sub = repo / "src"
        sub.mkdir()
        result = find_config_dir(sub)
        assert result is None

    def test_returns_none_when_not_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        (tmp_path / ".git").mkdir()
        result = find_config_dir(tmp_path)
        assert result is None

    def test_respects_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_VAR, ".config")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".config").mkdir()
        result = find_config_dir(tmp_path)
        assert result == (tmp_path / ".config").resolve()

    def test_env_var_name_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_VAR, ".config")
        (tmp_path / ".git").mkdir()
        (tmp_path / "config").mkdir()  # wrong name
        result = find_config_dir(tmp_path)
        assert result is None

    def test_no_git_repo_checks_start_only(self, tmp_path, monkeypatch):
        """Outside a git repo, only the start directory is checked."""
        monkeypatch.delenv(ENV_VAR, raising=False)
        (tmp_path / "config").mkdir()
        result = find_config_dir(tmp_path)
        assert result == (tmp_path / "config").resolve()

    def test_no_git_repo_does_not_walk_up(self, tmp_path, monkeypatch):
        """Outside a git repo, parent directories are not searched."""
        monkeypatch.delenv(ENV_VAR, raising=False)
        (tmp_path / "config").mkdir()
        sub = tmp_path / "src"
        sub.mkdir()
        result = find_config_dir(sub)
        assert result is None

    def test_finds_in_intermediate_dir(self, tmp_path, monkeypatch):
        """Config dir in an intermediate directory (not root, not start)."""
        monkeypatch.delenv(ENV_VAR, raising=False)
        (tmp_path / ".git").mkdir()
        mid = tmp_path / "packages" / "app"
        mid.mkdir(parents=True)
        (mid / "config").mkdir()
        deep = mid / "src" / "lib"
        deep.mkdir(parents=True)
        result = find_config_dir(deep)
        assert result == (mid / "config").resolve()

    def test_defaults_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        (tmp_path / "config").mkdir()
        result = find_config_dir()
        assert result == (tmp_path / "config").resolve()
