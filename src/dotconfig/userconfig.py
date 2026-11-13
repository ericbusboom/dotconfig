"""User-level config (``config.yaml``): load, validate and seed public keys.

The file lives at the path resolved by :mod:`dotconfig.paths` and looks like::

    public_keys:
      - key: age1...
        name: alice@laptop
"""

import getpass
import socket
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

from . import paths

KeyEntry = Tuple[str, Optional[str]]  # (age public key, label or None)


def _warn(path: Path, msg: str) -> None:
    print(f"warning: {path}: {msg}", file=sys.stderr)


def load_public_keys(path: Optional[Path] = None) -> List[KeyEntry]:
    """Return ordered, de-duplicated ``(key, label)`` pairs from the user config.

    Missing/empty files return ``[]`` silently. Malformed YAML, a non-list
    ``public_keys`` or invalid entries produce a warning naming the file.
    """
    path = Path(path) if path is not None else paths.user_config_path()
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text())
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
        _warn(path, f"cannot read config: {e}")
        return []
    if data is None:
        return []
    if not isinstance(data, dict):
        _warn(path, "top level must be a mapping; ignoring")
        return []
    entries = data.get("public_keys")
    if entries is None:
        return []
    if not isinstance(entries, list):
        _warn(path, "public_keys must be a list; ignoring")
        return []

    result: List[KeyEntry] = []
    seen = set()
    for i, entry in enumerate(entries):
        key = entry.get("key") if isinstance(entry, dict) else None
        if not isinstance(key, str) or not key.strip().startswith("age1"):
            _warn(path, f"public_keys[{i}] skipped: 'key' must be an age1... public key")
            continue
        key = key.strip()
        label = entry.get("name")
        if label is not None and not isinstance(label, str):
            _warn(path, f"public_keys[{i}]: 'name' must be a string; ignoring name")
            label = None
        label = label.strip() or None if label else None
        if key in seen:
            continue
        seen.add(key)
        result.append((key, label))
    return result


def default_label() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"{user}@{socket.gethostname()}"


def seed_user_config(public_key: str, path: Optional[Path] = None) -> bool:
    """Create the user config with one entry; never overwrite. True if created."""
    path = Path(path) if path is not None else paths.user_config_path()
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(
        {"public_keys": [{"key": public_key, "name": default_label()}]},
        sort_keys=False,
    )
    try:
        with open(path, "x") as f:
            f.write(content)
    except FileExistsError:
        return False
    return True
