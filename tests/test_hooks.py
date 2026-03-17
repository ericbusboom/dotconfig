"""Tests for dotconfig.hooks"""

import stat
from pathlib import Path

import pytest

from dotconfig.hooks import _HOOK_MARKER, install_pre_commit_hook


class TestInstallPreCommitHook:
    def test_creates_hook_file(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assert install_pre_commit_hook(tmp_path) is True
        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        assert hook.exists()

    def test_hook_is_executable(self, tmp_path):
        (tmp_path / ".git").mkdir()
        install_pre_commit_hook(tmp_path)
        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        assert hook.stat().st_mode & stat.S_IEXEC

    def test_hook_contains_audit(self, tmp_path):
        (tmp_path / ".git").mkdir()
        install_pre_commit_hook(tmp_path)
        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        content = hook.read_text()
        assert "dotconfig audit" in content
        assert _HOOK_MARKER in content

    def test_hook_has_shebang(self, tmp_path):
        (tmp_path / ".git").mkdir()
        install_pre_commit_hook(tmp_path)
        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        assert hook.read_text().startswith("#!/usr/bin/env bash")

    def test_idempotent(self, tmp_path):
        (tmp_path / ".git").mkdir()
        install_pre_commit_hook(tmp_path)
        install_pre_commit_hook(tmp_path)
        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        content = hook.read_text()
        assert content.count("dotconfig audit") == 1

    def test_appends_to_existing_hook(self, tmp_path):
        (tmp_path / ".git" / "hooks").mkdir(parents=True)
        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/bash\necho 'existing hook'\n")
        install_pre_commit_hook(tmp_path)
        content = hook.read_text()
        assert "existing hook" in content
        assert "dotconfig audit" in content

    def test_not_git_repo_returns_false(self, tmp_path):
        assert install_pre_commit_hook(tmp_path) is False

    def test_creates_hooks_dir(self, tmp_path):
        (tmp_path / ".git").mkdir()
        # No hooks/ dir yet
        assert install_pre_commit_hook(tmp_path) is True
        assert (tmp_path / ".git" / "hooks" / "pre-commit").exists()
