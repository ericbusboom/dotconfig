"""Single source of truth for where dotconfig reads and writes files.

Pure path resolution: no I/O beyond ``exists()`` checks, no user interaction.
Depends only on the stdlib and ``discover`` (a leaf), so ``keystore`` can
import from here without an import cycle.
"""

import getpass
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

SOURCE_ENV = "env"
SOURCE_DEFAULT = "default"
SOURCE_DISCOVERED = "discovered"
SOURCE_DERIVED = "derived"

DEFAULT_KEY_PATH = Path("~/.config/sops/age/keys.txt")


@dataclass(frozen=True)
class Location:
    """One resolved location: what it is, where, where it came from, existence."""

    name: str
    path: Optional[Path]
    source: str
    exists: bool
    note: str = ""


def _loc(name: str, path: Path, source: str, note: str = "") -> Location:
    return Location(name, path, source, path.exists(), note)


# ---------------------------------------------------------------------------
# User-level paths
# ---------------------------------------------------------------------------


def key_path() -> Path:
    """Path of the plain age key: ``$SOPS_AGE_KEY_FILE`` or the default."""
    env = os.environ.get("SOPS_AGE_KEY_FILE")
    return (Path(env) if env else DEFAULT_KEY_PATH).expanduser()


def key_path_source() -> str:
    return SOURCE_ENV if os.environ.get("SOPS_AGE_KEY_FILE") else SOURCE_DEFAULT


def wrapped_path(method_id: str) -> Path:
    """Path of the wrapped copy for a method: ``<keyfile>.<method>.age``."""
    kp = key_path()
    return kp.with_name(f"{kp.name}.{method_id}.age")


def sidecar_path() -> Path:
    """Path of the metadata sidecar: ``<keyfile>.lock.yaml``."""
    kp = key_path()
    return kp.with_name(f"{kp.name}.lock.yaml")


def wrapped_paths() -> List[Path]:
    """Existing wrapped copies next to the key file."""
    kp = key_path()
    if not kp.parent.is_dir():
        return []
    return sorted(kp.parent.glob(f"{kp.name}.*.age"))


def user_config_path() -> Path:
    """``$XDG_CONFIG_HOME/dotconfig/config.yaml`` or ``~/.config/dotconfig/config.yaml``."""
    return user_config_path_and_source()[0]


def user_config_path_and_source():
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / "dotconfig" / "config.yaml", SOURCE_ENV
    return Path("~/.config/dotconfig/config.yaml").expanduser(), SOURCE_DEFAULT


def ssh_config_path() -> Path:
    return Path("~/.ssh/config").expanduser()


# ---------------------------------------------------------------------------
# Project-level paths
# ---------------------------------------------------------------------------


def config_root(explicit: Optional[Path] = None) -> "tuple[Optional[Path], str]":
    """Return ``(root, source)``; root is None when none is found."""
    if explicit:
        src = SOURCE_ENV if os.environ.get("DOTCONFIG_DIR") else "option"
        return Path(explicit).expanduser(), src
    from .discover import find_config_dir

    found = find_config_dir()
    return (found, SOURCE_DISCOVERED) if found else (None, SOURCE_DISCOVERED)


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "user"


def user_locations() -> List[Location]:
    """User-level locations (independent of any project)."""
    kp = key_path()
    locs = [_loc("age key file", kp, key_path_source())]
    if os.environ.get("SOPS_AGE_KEY"):
        locs.append(Location(
            "age key (inline)", None, SOURCE_ENV, True,
            "SOPS_AGE_KEY is set; takes priority over the key file",
        ))
    wrapped = wrapped_paths()
    if wrapped:
        for w in wrapped:
            locs.append(_loc("wrapped key", w, SOURCE_DERIVED))
    else:
        locs.append(Location(
            "wrapped key", kp.with_name(f"{kp.name}.<method>.age"),
            SOURCE_DERIVED, False,
        ))
    locs.append(_loc("lock sidecar", sidecar_path(), SOURCE_DERIVED))
    ucp, usrc = user_config_path_and_source()
    locs.append(_loc("user config", ucp, usrc))
    locs.append(_loc("ssh config", ssh_config_path(), SOURCE_DEFAULT))
    return locs


def project_locations(root: Path) -> List[Location]:
    """Project-level locations under a config root."""
    project_root = root.resolve().parent
    user = _current_user()
    d = SOURCE_DERIVED
    locs = [
        _loc("config root", root, SOURCE_DISCOVERED),
        _loc("sops.yaml", root / "sops.yaml", d),
        _loc("dotconfig.yaml", root / "dotconfig.yaml", d),
        _loc("deploy public.env", root / "<deploy>" / "public.env", d),
        _loc("deploy secrets.env", root / "<deploy>" / "secrets.env", d),
        _loc("local public.env", root / "local" / user / "public.env", d),
        _loc("local secrets.env", root / "local" / user / "secrets.env", d),
        _loc("keys/", root / "keys", d),
        _loc("files/", root / "files", d),
        _loc("AGENTS.md", root / "AGENTS.md", d),
    ]
    for n in (".env", ".env.json", ".env.yaml", ".env.secret",
              ".gitignore", ".gitattributes"):
        locs.append(_loc(n, project_root / n, d))
    return locs


def all_locations(explicit: Optional[Path] = None) -> List[Location]:
    """Every location; project entries omitted when no config root exists."""
    locs = user_locations()
    root, src = config_root(explicit)
    if root is not None:
        pl = project_locations(root)
        pl[0] = _loc("config root", root, src)
        locs += pl
    return locs
