"""Event hook dispatch for dotconfig lifecycle events.

Hooks are executable scripts placed in ``config/_bin/`` named after the
event.  Each script is called with event-specific arguments and the
project directory as the first arg.  Missing scripts are silently skipped.
Non-zero exit codes are reported as warnings (hooks are advisory).

Supported events and their argv:

  version_bump  <project_dir> <old_version> <new_version>
  init          <project_dir> <config_dir>
  save          <project_dir> <config_dir> [<deploy>] [<local>]
  load          <project_dir> <config_dir> [<deploy>] [<local>]
"""

import subprocess
from pathlib import Path
from typing import Optional

from .output import warn


def _hook_path(config_dir: Path, event: str) -> Optional[Path]:
    """Return the path to the hook script for *event*, or None if absent."""
    candidate = config_dir / "_bin" / event
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def run_hook(config_dir: Path, event: str, args: list[str]) -> None:
    """Run the hook script for *event* with *args* if it exists.

    The script receives: <script> <project_dir> [event-specific args...]
    where <project_dir> is the parent of config_dir (the project root).

    Silently skips if no script exists.  Warns on non-zero exit.
    """
    hook = _hook_path(config_dir, event)
    if hook is None:
        return

    project_dir = str(config_dir.parent.resolve())
    cmd = [str(hook), project_dir] + args

    try:
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode != 0:
            warn(f"hook {event} exited with code {result.returncode}")
    except OSError as e:
        warn(f"hook {event} could not be executed: {e}")
