"""Config command: show how dotconfig is configured."""

from importlib.metadata import version

from .discover import ENV_VAR, config_dir_name, find_config_dir
from .output import heading, info, item, warn


def show_config() -> None:
    """Print dotconfig configuration details."""
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

    # Discovery
    found = find_config_dir()
    if found:
        item(f"found at:   {found}")
    else:
        warn(f"no '{name}' directory found")

    # Env var hint
    import os
    if os.environ.get(ENV_VAR):
        info(f"{ENV_VAR}={os.environ[ENV_VAR]}")
    else:
        info(f"{ENV_VAR} is not set (using default '{name}')")
