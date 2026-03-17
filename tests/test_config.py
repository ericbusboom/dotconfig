"""Tests for the dotconfig config command."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from dotconfig.cli import cli


class TestConfigCommand:
    def test_shows_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["config"])
        assert result.exit_code == 0
        assert "version:" in result.output

    def test_shows_config_dir_name(self, monkeypatch):
        monkeypatch.delenv("DOTCONFIG_NAME", raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["config"])
        assert "config dir: config" in result.output

    def test_shows_custom_dir_name(self, monkeypatch):
        monkeypatch.setenv("DOTCONFIG_NAME", ".config")
        runner = CliRunner()
        result = runner.invoke(cli, ["config"])
        assert "config dir: .config" in result.output

    def test_shows_found_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DOTCONFIG_NAME", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        (tmp_path / "config").mkdir()
        runner = CliRunner()
        result = runner.invoke(cli, ["config"])
        assert "found at:" in result.output

    def test_warns_when_not_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DOTCONFIG_NAME", raising=False)
        monkeypatch.chdir(tmp_path)
        # No config dir, no git
        runner = CliRunner()
        result = runner.invoke(cli, ["config"])
        assert result.exit_code == 0
        assert "no 'config' directory found" in result.output

    def test_shows_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("DOTCONFIG_NAME", "myconf")
        runner = CliRunner()
        result = runner.invoke(cli, ["config"])
        assert "DOTCONFIG_NAME=myconf" in result.output

    def test_shows_env_var_not_set(self, monkeypatch):
        monkeypatch.delenv("DOTCONFIG_NAME", raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["config"])
        assert "DOTCONFIG_NAME is not set" in result.output
