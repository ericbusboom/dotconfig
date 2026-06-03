"""Tests for src/dotconfig/event_hooks.py."""

import stat
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from dotconfig.event_hooks import _hook_path, run_hook


def _make_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


def _make_hook(config_dir: Path, event: str, content: str = "#!/bin/sh\nexit 0\n") -> Path:
    bin_dir = config_dir / "hooks"
    bin_dir.mkdir(exist_ok=True)
    hook = bin_dir / event
    hook.write_text(content)
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    return hook


class TestHookPath:
    def test_returns_none_whenhooks_dir_absent(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        assert _hook_path(config_dir, "version_bump") is None

    def test_returns_none_when_script_absent(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        (config_dir / "hooks").mkdir()
        assert _hook_path(config_dir, "version_bump") is None

    def test_returns_path_when_script_exists(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        hook = _make_hook(config_dir, "version_bump")
        assert _hook_path(config_dir, "version_bump") == hook

    def test_returns_none_for_directory_not_file(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        (config_dir / "hooks").mkdir()
        (config_dir / "hooks" / "version_bump").mkdir()
        assert _hook_path(config_dir, "version_bump") is None


class TestRunHook:
    def test_silently_skips_when_no_hook(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        # Should not raise
        run_hook(config_dir, "version_bump", ["1.0.0", "1.0.1"])

    def test_calls_script_with_project_dir_and_args(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        _make_hook(config_dir, "version_bump")
        with patch("dotconfig.event_hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            run_hook(config_dir, "version_bump", ["1.0.0", "1.0.1"])
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            # cmd[0] is the hook script, cmd[1] is project_dir, cmd[2:] are args
            assert cmd[1] == str(config_dir.parent.resolve())
            assert cmd[2] == "1.0.0"
            assert cmd[3] == "1.0.1"

    def test_warns_on_nonzero_exit(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        _make_hook(config_dir, "version_bump")
        with patch("dotconfig.event_hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            with patch("dotconfig.event_hooks.warn") as mock_warn:
                run_hook(config_dir, "version_bump", [])
                mock_warn.assert_called_once()
                assert "version_bump" in mock_warn.call_args[0][0]

    def test_warns_on_oserror(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        _make_hook(config_dir, "init")
        with patch("dotconfig.event_hooks.subprocess.run", side_effect=OSError("no exec")):
            with patch("dotconfig.event_hooks.warn") as mock_warn:
                run_hook(config_dir, "init", [])
                mock_warn.assert_called_once()
                assert "init" in mock_warn.call_args[0][0]

    def test_init_hook_receives_config_dir(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        _make_hook(config_dir, "init")
        with patch("dotconfig.event_hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            run_hook(config_dir, "init", [str(config_dir.resolve())])
            cmd = mock_run.call_args[0][0]
            assert cmd[2] == str(config_dir.resolve())

    def test_save_hook_receives_deploy_and_local(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        _make_hook(config_dir, "save")
        with patch("dotconfig.event_hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            run_hook(config_dir, "save", [str(config_dir.resolve()), "dev", "alice"])
            cmd = mock_run.call_args[0][0]
            assert cmd[2] == str(config_dir.resolve())
            assert cmd[3] == "dev"
            assert cmd[4] == "alice"
