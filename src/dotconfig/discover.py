"""Discover the config directory by walking up the directory tree."""

import os
from pathlib import Path
from typing import Optional


ENV_VAR = "DOTCONFIG_NAME"
DEFAULT_NAME = "config"


def _git_root(start: Path) -> Optional[Path]:
    """Return the root of the git repository containing *start*, or None."""
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def config_dir_name() -> str:
    """Return the config directory name from the environment or the default."""
    return os.environ.get(ENV_VAR, DEFAULT_NAME)


def find_config_dir(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from *start* looking for a directory named :func:`config_dir_name`.

    Search rules:
    1. Check *start* (defaults to cwd) for a child directory matching the name.
    2. Walk up parent directories, checking each one.
    3. Never walk above the git repository root (the directory containing ``.git``).
    4. If not inside a git repo, only check *start* itself.

    Returns the resolved path to the config directory, or ``None`` if not found.
    """
    if start is None:
        start = Path.cwd()
    start = start.resolve()

    name = config_dir_name()
    ceiling = _git_root(start)

    # If not in a git repo, only check the start directory.
    if ceiling is None:
        candidate = start / name
        return candidate if candidate.is_dir() else None

    # Walk from start up to (and including) the git root.
    current = start
    while True:
        candidate = current / name
        if candidate.is_dir():
            return candidate
        if current == ceiling:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None
