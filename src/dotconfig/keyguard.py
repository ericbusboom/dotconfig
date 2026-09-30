"""Locked-key guard: fail fast (before sops runs) when the age key is locked.

"Locked" means the plain key file is missing while wrapped copies exist
(sidecar or ``<keyfile>.*.age``) and ``SOPS_AGE_KEY`` is not set. Depends only
on ``keystore`` and ``output``; the inline unlock offer imports ``keywrap``
lazily so load/save can import this module without a cycle.
"""

import os
import sys

from . import keystore
from .output import error, info

LOCKED_MESSAGE = "age key is locked — run: dotconfig age unlock"


def is_locked() -> bool:
    """True if the plain key is absent, wrapped copies exist and no
    ``SOPS_AGE_KEY`` is in the environment."""
    if os.environ.get("SOPS_AGE_KEY"):
        return False
    kp = keystore.key_path()
    if kp.exists():
        return False
    if keystore.sidecar_path().exists():
        return True
    parent = kp.parent
    if not parent.is_dir():
        return False
    return any(
        not p.name.endswith(".pending.age")
        for p in parent.glob(f"{kp.name}.*.age")
    )


def _interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stderr.isatty()
    except (ValueError, AttributeError):
        return False


def require_unlocked() -> None:
    """Return if sops can use the key; otherwise exit 75 (or unlock inline
    on a TTY when the user agrees)."""
    if not is_locked():
        return
    if _interactive():
        error(LOCKED_MESSAGE)
        try:
            answer = input("Unlock now? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer in ("", "y", "yes"):
            from . import keywrap

            try:
                keywrap.unlock()
            except (keywrap.UnlockError, keywrap.WrapError, keystore.AgeToolError) as e:
                error(str(e))
                sys.exit(keystore.EXIT_LOCKED)
            info("unlocked")
            return
        sys.exit(keystore.EXIT_LOCKED)
    error(LOCKED_MESSAGE)
    sys.exit(keystore.EXIT_LOCKED)
