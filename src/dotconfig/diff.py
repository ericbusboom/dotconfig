"""Compare what ``save`` would write against what is already saved.

This is the read-only comparison core behind ``dotconfig diff``.  It asks
``save`` for a *plan* (see :func:`dotconfig.save.plan_save_config` and
:func:`dotconfig.save.plan_save_file`), reads each planned destination,
normalizes both sides, and renders ``difflib`` unified diffs.

Guarantees:

  - Nothing is written to disk.  Encrypted saved files are decrypted in
    memory only (via ``load._read_file_content``); there are no temp files.
  - A missing saved file is treated as empty (everything shows as added).
  - Every failure is raised as :class:`DiffError`; nothing here calls
    ``sys.exit`` (``SystemExit`` from helper code is converted), so the
    CLI can map every error to exit code 2.

Public API: :func:`compare_env`, :func:`compare_file`, :func:`compare_plan`,
:class:`DiffResult`, :class:`FileDiff`, :class:`DiffError`,
:func:`normalize`.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .load import _read_file_content, _strip_export_prefix
from .save import (
    PlannedWrite,
    SavePlan,
    SavePlanError,
    plan_save_config,
    plan_save_file,
)

_METADATA_PREFIXES = (
    "# CONFIG_DEPLOYS=",
    "# CONFIG_DEPLOY=",
    "# CONFIG_COMMON=",
    "# CONFIG_LOCALS=",
    "# CONFIG_LOCAL=",
    "#@dotconfig:",
    "_VERSION=",
)


class DiffError(Exception):
    """Any failure while planning or comparing (CLI maps this to exit 2)."""


@dataclass
class FileDiff:
    """Comparison result for one planned destination."""

    label: str
    path: Path
    diff: str  # unified diff text; "" when identical
    changed: bool
    saved_exists: bool = True


@dataclass
class DiffResult:
    """Per-file diffs for a whole plan."""

    files: List[FileDiff] = field(default_factory=list)
    notice: str = ""

    @property
    def changed(self) -> bool:
        return any(f.changed for f in self.files)

    @property
    def text(self) -> str:
        """All non-empty diffs, concatenated."""
        return "".join(f.diff for f in self.files if f.changed)


def normalize(text: str) -> List[str]:
    """Normalize text for comparison and return its lines.

    Strips a leading ``export `` from assignments, trailing whitespace on
    each line, dotconfig metadata/marker comments and ``_VERSION=``
    lines, and leading/trailing blank lines.
    """
    lines = []
    for line in _strip_export_prefix(text).splitlines():
        line = line.rstrip()
        if line.startswith(_METADATA_PREFIXES):
            continue
        lines.append(line)
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _read_saved(path: Path, config_dir: Path) -> Optional[str]:
    """Saved text (decrypted in memory if needed), or None if missing."""
    if not path.exists():
        return None
    try:
        return _read_file_content(path, config_dir / "sops.yaml")
    except SystemExit as exc:
        raise DiffError(f"failed to read/decrypt saved file {path}") from exc
    except OSError as exc:
        raise DiffError(f"cannot read {path}: {exc}") from exc


def _compare_one(w: PlannedWrite, config_dir: Path) -> FileDiff:
    saved = _read_saved(w.dest, config_dir)
    old = normalize(saved or "")
    new = normalize(w.content)
    if old == new:
        return FileDiff(w.label, w.dest, "", False, saved is not None)
    text = "\n".join(
        difflib.unified_diff(
            old,
            new,
            fromfile=f"{w.dest} (saved)" if saved is not None else f"{w.dest} (missing)",
            tofile=f"{w.dest} (working)",
            lineterm="",
        )
    )
    return FileDiff(w.label, w.dest, text + "\n", True, saved is not None)


def compare_plan(plan: SavePlan, config_dir: Path) -> DiffResult:
    """Compare every write in *plan* with its saved destination."""
    return DiffResult(
        files=[_compare_one(w, config_dir) for w in plan.writes],
        notice=plan.notice,
    )


def compare_env(
    env_file: Path,
    config_dir: Path,
    override_deploy=None,
    override_local=None,
    add_export: bool = False,
) -> DiffResult:
    """Diff a dotconfig-managed ``.env`` against where ``save`` would write."""
    try:
        plan = plan_save_config(
            env_file, config_dir, override_deploy, override_local,
            "env", add_export,
        )
    except SavePlanError as exc:
        raise DiffError(str(exc)) from exc
    except SystemExit as exc:
        raise DiffError(f"cannot plan save for {env_file}") from exc
    return compare_plan(plan, config_dir)


def compare_file(
    deployment: Optional[str],
    local: Optional[str],
    filename: str,
    config_dir: Path,
    source: Optional[Path] = None,
    encrypt: bool = False,
) -> DiffResult:
    """Diff a single file against where ``save --file`` would write it."""
    try:
        plan = plan_save_file(
            deployment, local, filename, config_dir, source, encrypt
        )
    except SavePlanError as exc:
        raise DiffError(str(exc)) from exc
    except SystemExit as exc:
        raise DiffError(f"cannot plan save for {filename}") from exc
    return compare_plan(plan, config_dir)
