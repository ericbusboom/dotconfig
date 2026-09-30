"""Key store: on-disk layout of the age key, wrapped copies and sidecar.

Single owner of (a) the paths of the plain key file, the wrapped files
(``<keyfile>.<method>.age``) and the secret-free sidecar
(``<keyfile>.lock.yaml``), (b) atomic writes of those files, and (c) every
subprocess call to ``age`` / ``age-keygen`` / age plugins.

This module holds no policy and does no user interaction; it depends only on
``output`` for warnings.
"""

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from .output import warn

#: Exit code used when the age key is locked (distinct from ordinary failure 1).
EXIT_LOCKED = 75

DEFAULT_KEY_PATH = Path("~/.config/sops/age/keys.txt")


class LockedKeyError(Exception):
    """The age key is locked (wrapped at rest); run ``dotconfig unlock``."""

    exit_code = EXIT_LOCKED

    def __init__(self, message: str = "age key is locked — run: dotconfig unlock"):
        super().__init__(message)


class AgeToolError(Exception):
    """An age binary is missing or a call to it failed."""


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def key_path() -> Path:
    """Path of the plain key: ``$SOPS_AGE_KEY_FILE`` or the default."""
    env = os.environ.get("SOPS_AGE_KEY_FILE")
    return (Path(env) if env else DEFAULT_KEY_PATH).expanduser()


def wrapped_path(method_id: str) -> Path:
    """Path of the wrapped copy for a method: ``<keyfile>.<method>.age``."""
    kp = key_path()
    return kp.with_name(f"{kp.name}.{method_id}.age")


def sidecar_path() -> Path:
    """Path of the metadata sidecar: ``<keyfile>.lock.yaml``."""
    kp = key_path()
    return kp.with_name(f"{kp.name}.lock.yaml")


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    """Write ``data`` to ``path`` via a same-directory temp file + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            # fdopen may not have taken ownership if fchmod failed
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def check_dir_permissions(directory: Path) -> bool:
    """Warn (and return False) if ``directory`` is group/world accessible."""
    try:
        mode = stat.S_IMODE(directory.stat().st_mode)
    except OSError:
        return True
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        warn(
            f"{directory} is group/world accessible (mode {mode:04o}); "
            f"consider: chmod 700 {directory}"
        )
        return False
    return True


def write_plain_key(secret: str) -> Path:
    """Atomically write the plain key (mode 0600) to the key path only."""
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    check_dir_permissions(path.parent)
    text = secret if secret.endswith("\n") else secret + "\n"
    _atomic_write(path, text.encode(), 0o600)
    return path


def write_wrapped(method_id: str, ciphertext: bytes) -> Path:
    """Atomically write a wrapped file for ``method_id``."""
    path = wrapped_path(method_id)
    _atomic_write(path, ciphertext, 0o600)
    return path


# ---------------------------------------------------------------------------
# Sidecar
# ---------------------------------------------------------------------------


def load_sidecar() -> dict[str, Any]:
    """Load the sidecar; a missing sidecar is empty (no public key, no methods)."""
    path = sidecar_path()
    if not path.exists():
        return {"public_key": None, "methods": []}
    data = yaml.safe_load(path.read_text()) or {}
    return {
        "public_key": data.get("public_key"),
        "methods": list(data.get("methods") or []),
    }


def save_sidecar(sidecar: dict[str, Any]) -> Path:
    """Atomically write the sidecar (no secrets; 0644 is fine, use 0600)."""
    out: dict[str, Any] = {
        "public_key": sidecar.get("public_key"),
        "methods": [
            {k: v for k, v in m.items() if v is not None}
            for m in sidecar.get("methods", [])
        ],
    }
    text = yaml.safe_dump(out, sort_keys=False, default_flow_style=False)
    path = sidecar_path()
    _atomic_write(path, text.encode(), 0o600)
    return path


# ---------------------------------------------------------------------------
# Age runner (single subprocess seam)
# ---------------------------------------------------------------------------

_PLUGINS = {
    "age1se1": ("age-plugin-se", "brew install remko/age-plugin-se/age-plugin-se"),
    "age1yubikey1": ("age-plugin-yubikey", "brew install age-plugin-yubikey"),
}
_AGE_INSTALL = "brew install age"


def _default_runner(
    cmd: list[str], input: Optional[bytes] = None, interactive: bool = False
) -> "subprocess.CompletedProcess[bytes]":
    """Run ``cmd``. ``interactive`` leaves stderr on the terminal so age can
    prompt (age reads passphrases from /dev/tty)."""
    return subprocess.run(
        cmd,
        input=input,
        stdout=subprocess.PIPE,
        stderr=None if interactive else subprocess.PIPE,
        check=False,
    )


#: The one seam every age/age-keygen subprocess call goes through. Tests
#: substitute it (``keystore.runner = fake``) or use real age with plain keys.
runner: Callable[..., "subprocess.CompletedProcess[bytes]"] = _default_runner


def _require(binary: str, install: str) -> None:
    if shutil.which(binary) is None:
        raise AgeToolError(f"{binary} not found. Install it with: {install}")


def _require_plugin_for(identity_or_recipient: str) -> None:
    for prefix, (binary, install) in _PLUGINS.items():
        if identity_or_recipient.startswith(prefix):
            _require(binary, install)


def _run(
    cmd: list[str], input: Optional[bytes] = None, interactive: bool = False
) -> bytes:
    _require(cmd[0], _AGE_INSTALL)
    try:
        proc = runner(cmd, input=input, interactive=interactive)
    except FileNotFoundError as e:
        raise AgeToolError(f"{cmd[0]} not found. Install it with: {_AGE_INSTALL}") from e
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode(errors="replace").strip()
        if "plugin" in detail.lower() and "not found" in detail.lower():
            detail += " (install the age plugin; e.g. brew install age-plugin-yubikey)"
        raise AgeToolError(f"{cmd[0]} failed (exit {proc.returncode})"
                           + (f": {detail}" if detail else ""))
    return proc.stdout or b""


def public_key_of(secret: str) -> str:
    """Derive the public key from an ``AGE-SECRET-KEY-1...`` via ``age-keygen -y``."""
    out = _run(["age-keygen", "-y"], input=secret.encode())
    pub = out.decode().strip()
    if not pub:
        raise AgeToolError("age-keygen -y produced no public key")
    return pub


def age_encrypt_to_recipient(plaintext: bytes, recipient: str) -> bytes:
    """Encrypt ``plaintext`` to an age recipient (native or plugin)."""
    _require_plugin_for(recipient)
    return _run(["age", "-r", recipient], input=plaintext)


def age_encrypt_passphrase(plaintext: bytes) -> bytes:
    """Encrypt with a passphrase; age prompts on the TTY."""
    return _run(["age", "-p"], input=plaintext, interactive=True)


def age_decrypt_identity(wrapped: Path, identity_file: Path) -> bytes:
    """Decrypt ``wrapped`` with an identity file (plain key, plugin identity
    file, or passphrase-protected identity; age prompts itself if needed)."""
    try:
        text = Path(identity_file).read_text()
    except OSError:
        text = ""
    for prefix, (binary, install) in _PLUGINS.items():
        marker = "AGE-PLUGIN-" + {"age1se1": "SE", "age1yubikey1": "YUBIKEY"}[prefix]
        if marker in text.upper():
            _require(binary, install)
    return _run(
        ["age", "-d", "-i", str(identity_file), str(wrapped)], interactive=True
    )


def age_decrypt_passphrase(wrapped: Path) -> bytes:
    """Decrypt a passphrase-wrapped file; age prompts on the TTY."""
    return _run(["age", "-d", str(wrapped)], interactive=True)
