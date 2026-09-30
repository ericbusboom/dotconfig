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


FALLBACK_NAME = ".config"

# Entries whose presence marks a directory as a dotconfig config root.
_MARKER_FILES = ("sops.yaml", "dotconfig.yaml")
_MARKER_DIRS = ("keys", "local")
_LAYER_FILES = ("public.env", "secrets.env")


def looks_like_config_dir(path: Path) -> bool:
    """Return True if *path* is a directory holding dotconfig files.

    A config root has ``sops.yaml`` or ``dotconfig.yaml``, a ``keys/`` or
    ``local/`` directory, or at least one deployment directory containing
    ``public.env`` / ``secrets.env``.
    """
    if not path.is_dir():
        return False
    if any((path / f).is_file() for f in _MARKER_FILES):
        return True
    if any((path / d).is_dir() for d in _MARKER_DIRS):
        return True
    try:
        children = list(path.iterdir())
    except OSError:
        return False
    return any(
        child.is_dir() and any((child / f).is_file() for f in _LAYER_FILES)
        for child in children
    )


def _search_levels(start: Path) -> list:
    """Directories to search: *start* up to the git root, or *start* alone."""
    ceiling = _git_root(start)
    if ceiling is None:
        return [start]
    levels = []
    current = start
    while True:
        levels.append(current)
        if current == ceiling:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return levels


def find_config_dir(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from *start* looking for the config directory.

    Search rules:
    1. Check *start* (defaults to cwd), then walk up parent directories.
    2. Never walk above the git repository root (the directory containing ``.git``).
    3. If not inside a git repo, only check *start* itself.

    When ``DOTCONFIG_NAME`` is set, the first directory with that name wins.
    Otherwise, at each level ``config/`` is used if it looks like a dotconfig
    directory (see :func:`looks_like_config_dir`); if it is missing or holds
    no dotconfig files, ``.config/`` is used when it does.  If neither
    qualifies anywhere, the nearest existing ``config/`` is returned, so a
    freshly created (still empty) config directory is still found.

    Returns the resolved path to the config directory, or ``None`` if not found.
    """
    if start is None:
        start = Path.cwd()
    start = start.resolve()
    levels = _search_levels(start)

    if os.environ.get(ENV_VAR):
        name = config_dir_name()
        for level in levels:
            candidate = level / name
            if candidate.is_dir():
                return candidate
        return None

    fallback: Optional[Path] = None
    for level in levels:
        primary = level / DEFAULT_NAME
        if looks_like_config_dir(primary):
            return primary
        secondary = level / FALLBACK_NAME
        if looks_like_config_dir(secondary):
            return secondary
        if fallback is None and primary.is_dir():
            fallback = primary
    return fallback
