"""Config command: show how dotconfig is configured."""

from importlib.metadata import version
from pathlib import Path
from typing import Optional

from .discover import ENV_VAR, config_dir_name, find_config_dir
from .output import heading, info, item, warn


DIR_ENV_VAR = "DOTCONFIG_DIR"


def show_config(override: Optional[Path] = None) -> None:
    """Print dotconfig configuration details.

    If *override* is provided (e.g. from -c/--config or DOTCONFIG_DIR),
    it is reported as the resolved config directory instead of running
    name-based discovery.
    """
    heading("dotconfig")

    # Version
    try:
        ver = version("dotconfig")
    except Exception:
        ver = "unknown"
    item(f"version:    {ver}")

    # Config directory name
    name = config_dir_name()
    item(f"config dir: {name}")

    # Resolved location
    if override is not None:
        item(f"resolved:   {override}")
        if not override.is_dir():
            warn(f"override path '{override}' does not exist")
    else:
        found = find_config_dir()
        if found:
            item(f"found at:   {found}")
        else:
            warn(f"no '{name}' directory found")

    # Env var hints
    import os
    if os.environ.get(ENV_VAR):
        info(f"{ENV_VAR}={os.environ[ENV_VAR]}")
    else:
        info(f"{ENV_VAR} is not set (using default '{name}')")
    if os.environ.get(DIR_ENV_VAR):
        info(f"{DIR_ENV_VAR}={os.environ[DIR_ENV_VAR]}")
    else:
        info(f"{DIR_ENV_VAR} is not set")
