"""Tests for dotconfig.discover"""

from pathlib import Path
from unittest.mock import patch

import pytest

from dotconfig.discover import (
    DEFAULT_NAME,
    ENV_VAR,
    _git_root,
    FALLBACK_NAME,
    config_dir_name,
    find_config_dir,
    looks_like_config_dir,
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


# ---------------------------------------------------------------------------
# .dotconfig fallback
# ---------------------------------------------------------------------------


def _make_config(path: Path) -> Path:
    """Create a minimal dotconfig directory (a deployment with public.env)."""
    (path / "dev").mkdir(parents=True)
    (path / "dev" / "public.env").write_text("A=1\n")
    return path


class TestLooksLikeConfigDir:
    def test_missing_dir(self, tmp_path):
        assert not looks_like_config_dir(tmp_path / "nope")

    def test_empty_dir(self, tmp_path):
        assert not looks_like_config_dir(tmp_path)

    def test_unrelated_files(self, tmp_path):
        (tmp_path / "settings.json").write_text("{}")
        (tmp_path / "nvim").mkdir()
        assert not looks_like_config_dir(tmp_path)

    @pytest.mark.parametrize("marker", ["sops.yaml", "dotconfig.yaml"])
    def test_marker_file(self, tmp_path, marker):
        (tmp_path / marker).write_text("")
        assert looks_like_config_dir(tmp_path)

    @pytest.mark.parametrize("marker", ["keys", "local"])
    def test_marker_dir(self, tmp_path, marker):
        (tmp_path / marker).mkdir()
        assert looks_like_config_dir(tmp_path)

    @pytest.mark.parametrize("layer", ["public.env", "secrets.env"])
    def test_deployment_dir(self, tmp_path, layer):
        (tmp_path / "prod").mkdir()
        (tmp_path / "prod" / layer).write_text("")
        assert looks_like_config_dir(tmp_path)


class TestDotconfigFallback:
    @pytest.fixture(autouse=True)
    def _repo(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        (tmp_path / ".git").mkdir()

    def test_fallback_name(self):
        assert FALLBACK_NAME == ".dotconfig"

    def test_uses_dotconfig_dir_when_config_missing(self, tmp_path):
        _make_config(tmp_path / ".dotconfig")
        assert find_config_dir(tmp_path) == (tmp_path / ".dotconfig").resolve()

    def test_uses_dotconfig_dir_when_config_has_no_dotconfig_files(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "webpack.js").write_text("")
        _make_config(tmp_path / ".dotconfig")
        assert find_config_dir(tmp_path) == (tmp_path / ".dotconfig").resolve()

    def test_prefers_valid_config_over_dotconfig(self, tmp_path):
        _make_config(tmp_path / "config")
        _make_config(tmp_path / ".dotconfig")
        assert find_config_dir(tmp_path) == (tmp_path / "config").resolve()

    def test_ignores_dotconfig_without_dotconfig_files(self, tmp_path):
        (tmp_path / ".dotconfig" / "nvim").mkdir(parents=True)
        assert find_config_dir(tmp_path) is None

    def test_empty_config_still_returned_when_nothing_valid(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / ".dotconfig" / "nvim").mkdir(parents=True)
        assert find_config_dir(tmp_path) == (tmp_path / "config").resolve()

    def test_walks_up_to_dotconfig(self, tmp_path):
        _make_config(tmp_path / ".dotconfig")
        sub = tmp_path / "src" / "app"
        sub.mkdir(parents=True)
        assert find_config_dir(sub) == (tmp_path / ".dotconfig").resolve()

    def test_nearest_valid_level_wins(self, tmp_path):
        _make_config(tmp_path / "config")
        mid = tmp_path / "pkg"
        _make_config(mid / ".dotconfig")
        assert find_config_dir(mid) == (mid / ".dotconfig").resolve()

    def test_env_var_disables_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_VAR, "cfg")
        _make_config(tmp_path / ".dotconfig")
        assert find_config_dir(tmp_path) is None


class TestCliUsesFallback:
    def test_load_finds_dotconfig(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from dotconfig.cli import cli

        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.delenv("DOTCONFIG_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        _make_config(tmp_path / ".dotconfig")
        result = CliRunner().invoke(cli, ["load", "dev", "-S"])
        assert result.exit_code == 0, result.output
        assert "A=1" in result.output

    def test_load_file_default_output_under_dotconfig(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from dotconfig.cli import cli

        monkeypatch.delenv(ENV_VAR, raising=False)
        monkeypatch.delenv("DOTCONFIG_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        cfg = _make_config(tmp_path / ".dotconfig")
        (cfg / "dev" / "app.yaml").write_text("x: 1\n")
        result = CliRunner().invoke(cli, ["load", "dev", "--file", "app.yaml"])
        assert result.exit_code == 0, result.output
        assert (cfg / "files" / "app.yaml").read_text() == "x: 1\n"
        assert not (tmp_path / "config").exists()
