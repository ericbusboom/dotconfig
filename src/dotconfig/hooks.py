"""Install git hooks for dotconfig."""

import stat
import subprocess
from pathlib import Path
from typing import Optional

from .discover import _git_root
from .output import created, error, info, ok


_HOOK_MARKER = "# dotconfig: audit for unencrypted secrets"

_HOOK_SCRIPT = f"""\
#!/usr/bin/env bash
{_HOOK_MARKER}
dotconfig audit
"""


def install_pre_commit_hook(start: Optional[Path] = None) -> bool:
    """Install a git pre-commit hook that runs ``dotconfig audit``.

    Finds the git root from *start* (defaults to cwd), then writes or
    appends to ``.git/hooks/pre-commit``.

    Returns True on success, False on failure.
    """
    if start is None:
        start = Path.cwd()

    root = _git_root(start)
    if root is None:
        error("not inside a git repository")
        return False

    # Use `git rev-parse --git-dir` so submodule checkouts (where .git is a
    # file, not a directory) resolve to the real git object store path.
    try:
        git_dir = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--git-dir"],
                cwd=str(start),
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        )
        if not git_dir.is_absolute():
            git_dir = (start / git_dir).resolve()
    except subprocess.CalledProcessError:
        git_dir = root / ".git"

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_file = hooks_dir / "pre-commit"

    if hook_file.exists():
        existing = hook_file.read_text()
        if _HOOK_MARKER in existing:
            ok("pre-commit hook already installed")
            return True
        # Append to existing hook
        hook_file.write_text(existing.rstrip("\n") + "\n\n" + _HOOK_SCRIPT)
        info("appended dotconfig audit to existing pre-commit hook")
    else:
        hook_file.write_text(_HOOK_SCRIPT)
        created(str(hook_file))

    # Make executable
    hook_file.chmod(hook_file.stat().st_mode | stat.S_IEXEC)
    ok("pre-commit hook installed — commits will be blocked if unencrypted secrets are found")
    return True
