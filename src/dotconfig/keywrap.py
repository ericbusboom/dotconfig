"""Key wrap operations: write wrapped copies of the age key and prove they open.

Policy layer over :mod:`keystore`. Every wrapped file is written to a pending
name, opened with a human-present round trip, and only renamed into place (and
recorded in the sidecar) when the recovered key's public key equals the
sidecar's ``public_key``. A working wrapped file is never replaced by an
unverified one, and the plain key is never modified.
"""

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from . import keystore
from .keystore import AgeToolError

PASSPHRASE_ID = "pass"
RESERVED_IDS = {"se", "yubikey", PASSPHRASE_ID}
_KINDS = ("se", "yubikey", "identity", "passphrase")


class WrapError(Exception):
    """A precondition for wrapping failed (nothing was written)."""


@dataclass
class MethodSpec:
    """One wrap method to create. ``identity_file`` drives the round trip for
    recipient-based kinds (se, yubikey, identity)."""

    kind: str
    method_id: str
    recipient: Optional[str] = None
    label: Optional[str] = None
    identity_file: Optional[Path] = None
    hint: Optional[str] = None


@dataclass
class WrapResult:
    method_id: str
    ok: bool
    path: Optional[Path] = None
    error: Optional[str] = None


def slugify_label(label: str) -> str:
    """Turn a label into a safe method id (lowercase, ``[a-z0-9-]``)."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    if not slug:
        raise WrapError(f"label {label!r} yields an empty method name")
    if slug in RESERVED_IDS:
        raise WrapError(f"label {label!r} collides with reserved method name {slug!r}")
    return slug


def extract_secret(text: str) -> Optional[str]:
    """First ``AGE-SECRET-KEY-1...`` line in ``text``, or None."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("AGE-SECRET-KEY-"):
            return line
    return None


def read_plain_key() -> str:
    """Read the plain secret key from the key path (read-only)."""
    path = keystore.key_path()
    if not path.exists():
        raise WrapError(
            f"plain key not found at {path}. If the key is locked, run: "
            f"dotconfig unlock"
        )
    secret = extract_secret(path.read_text())
    if secret is None:
        raise WrapError(f"no AGE-SECRET-KEY found in {path}")
    return secret


def build_specs(
    *,
    se: bool = False,
    yubikey: bool = False,
    passphrase: bool = False,
    recipient: Optional[str] = None,
    label: Optional[str] = None,
    identity: Optional[Path] = None,
    se_recipient: Optional[str] = None,
    se_identity: Optional[Path] = None,
    yubikey_recipient: Optional[str] = None,
    yubikey_identity: Optional[Path] = None,
    hint: Optional[str] = None,
) -> list[MethodSpec]:
    """Translate CLI-level options into method specs (validates combinations)."""
    existing = {m.get("kind"): m for m in keystore.load_sidecar()["methods"]}
    specs: list[MethodSpec] = []

    def recipient_method(kind, rec, ident, default_label):
        rec = rec or (existing.get(kind) or {}).get("recipient")
        if not rec:
            raise WrapError(
                f"--{kind} needs the plugin recipient: pass --{kind}-recipient "
                f"age1... (create one with the age plugin first)"
            )
        if ident is None:
            raise WrapError(
                f"--{kind} needs --{kind}-identity FILE so the new file can be "
                f"verified by a round trip"
            )
        specs.append(MethodSpec(kind, kind, rec, default_label, Path(ident)))

    if se:
        recipient_method("se", se_recipient, se_identity, "Secure Enclave")
    if yubikey:
        recipient_method("yubikey", yubikey_recipient, yubikey_identity, "YubiKey")
    if recipient or label:
        if not (recipient and label):
            raise WrapError("--recipient and --label must be given together")
        if identity is None:
            raise WrapError(
                "--recipient needs --identity FILE so the new file can be "
                "verified by a round trip"
            )
        specs.append(
            MethodSpec("identity", slugify_label(label), recipient, label,
                       Path(identity), hint)
        )
    if passphrase:
        specs.append(MethodSpec("passphrase", PASSPHRASE_ID, None, "passphrase"))
    if not specs:
        raise WrapError(
            "nothing to wrap: give --se, --yubikey, --passphrase and/or "
            "--recipient ... --label ..."
        )
    return specs


def _encrypt(spec: MethodSpec, secret: str) -> bytes:
    data = secret.encode() + b"\n"
    if spec.kind == "passphrase":
        return keystore.age_encrypt_passphrase(data)
    assert spec.recipient
    return keystore.age_encrypt_to_recipient(data, spec.recipient)


def _round_trip(spec: MethodSpec, wrapped: Path) -> str:
    """Open ``wrapped`` the way a real unlock would; return the public key."""
    if spec.kind == "passphrase":
        plain = keystore.age_decrypt_passphrase(wrapped)
    else:
        if spec.identity_file is None:
            raise AgeToolError(f"no identity file to verify {spec.method_id}")
        plain = keystore.age_decrypt_identity(wrapped, spec.identity_file)
    secret = extract_secret(plain.decode(errors="replace"))
    if secret is None:
        raise AgeToolError("round trip produced no AGE-SECRET-KEY")
    return keystore.public_key_of(secret)


def _record(sidecar: dict, spec: MethodSpec, filename: str, verified: str) -> None:
    entry = {
        "file": filename,
        "kind": spec.kind,
        "recipient": spec.recipient,
        "label": spec.label,
        "verified": verified,
        "hint": spec.hint,
    }
    # Plugin identity files are non-secret stubs, so record where they live
    # to let `unlock` find them. The recovery (identity) key stays a hint only.
    if spec.kind in ("se", "yubikey") and spec.identity_file is not None:
        entry["identity_file"] = str(Path(spec.identity_file).expanduser().resolve())
    methods = [m for m in sidecar["methods"] if m.get("file") != filename]
    methods.append(entry)
    sidecar["methods"] = methods


def wrap_method(spec: MethodSpec, secret: str, public_key: str,
                sidecar: dict, today: str) -> WrapResult:
    """Write, verify and record one method. Never leaves an unverified file
    in place and never touches an existing file until the new one verified."""
    final = keystore.wrapped_path(spec.method_id)
    pending = None
    try:
        ciphertext = _encrypt(spec, secret)
        pending = keystore.write_wrapped(f"{spec.method_id}.pending", ciphertext)
        got = _round_trip(spec, pending)
        if got != public_key:
            raise AgeToolError(
                f"round trip returned a different public key ({got}); expected "
                f"{public_key}"
            )
        os.replace(pending, final)
        pending = None
    except (AgeToolError, OSError) as e:
        if pending is not None:
            try:
                pending.unlink()
            except FileNotFoundError:
                pass
        return WrapResult(spec.method_id, False, error=str(e))
    _record(sidecar, spec, final.name, today)
    keystore.save_sidecar(sidecar)
    return WrapResult(spec.method_id, True, path=final)


def wrap(specs: list[MethodSpec], today: Optional[str] = None) -> list[WrapResult]:
    """Wrap the plain key with each spec. Raises :class:`WrapError` before
    writing anything when the key is missing or does not match the sidecar;
    otherwise returns one result per spec (failures do not stop the rest)."""
    secret = read_plain_key()
    try:
        public_key = keystore.public_key_of(secret)
    except AgeToolError as e:
        raise WrapError(str(e)) from e
    sidecar = keystore.load_sidecar()
    recorded = sidecar.get("public_key")
    if recorded and recorded != public_key:
        raise WrapError(
            f"plain key's public key ({public_key}) differs from the sidecar's "
            f"({recorded}); refusing to wrap a different key"
        )
    sidecar["public_key"] = public_key
    today = today or date.today().isoformat()
    return [wrap_method(s, secret, public_key, sidecar, today) for s in specs]


# ---------------------------------------------------------------------------
# Unlock
# ---------------------------------------------------------------------------
#
# Human presence is the point: there is no flag, environment variable or piped
# stdin that supplies a secret. age prompts for passphrases on /dev/tty itself,
# plugins prompt via the OS / device, and --paste reads from a real TTY only.


class UnlockError(Exception):
    """Unlock failed; nothing was written."""


@dataclass
class UnlockResult:
    status: str  # "already-unlocked" | "unlocked"
    method: Optional[str] = None
    path: Optional[Path] = None
    degraded: bool = False


@dataclass
class WrappedMethod:
    method_id: str
    kind: str
    path: Path
    label: Optional[str] = None
    hint: Optional[str] = None
    identity_file: Optional[str] = None


def is_gui_session() -> bool:
    """True when a desktop session can show Touch ID / pinentry-style prompts."""
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    import sys

    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def device_present(kind: str) -> bool:
    """Is the plugin for ``kind`` installed and (for yubikey) a device attached?"""
    import shutil

    if kind == "se":
        return shutil.which("age-plugin-se") is not None
    if kind == "yubikey":
        if shutil.which("age-plugin-yubikey") is None:
            return False
        try:
            proc = keystore.runner(["age-plugin-yubikey", "--list"])
        except OSError:
            return False
        return proc.returncode == 0 and bool((proc.stdout or b"").strip())
    return True


def read_secret_tty() -> str:
    """Read an ``AGE-SECRET-KEY-1...`` from the terminal with no echo.

    Only from a real TTY: piped/redirected stdin is refused."""
    import getpass
    import sys

    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        raise UnlockError(
            "--paste needs an interactive terminal (stdin is not a TTY); the "
            "key is never read from a pipe or file"
        )
    text = getpass.getpass("Paste AGE-SECRET-KEY (input hidden): ")
    secret = extract_secret(text)
    if secret is None:
        raise UnlockError("input is not an AGE-SECRET-KEY-1... value")
    return secret


def list_wrapped() -> tuple[list[WrappedMethod], bool]:
    """Wrapped files known for this key. Returns (methods, from_sidecar).

    Sidecar entries whose file is missing are dropped. Without a sidecar the
    directory is globbed (``*.pending.age`` leftovers ignored)."""
    kp = keystore.key_path()
    prefix, suffix = f"{kp.name}.", ".age"

    def ident(name: str) -> str:
        return name[len(prefix):-len(suffix)]

    sidecar = keystore.load_sidecar()
    out: list[WrappedMethod] = []
    for m in sidecar["methods"]:
        fname = m.get("file")
        if not fname:
            continue
        p = kp.with_name(fname)
        if p.exists():
            out.append(WrappedMethod(ident(fname), m.get("kind", "identity"), p,
                                     m.get("label"), m.get("hint"),
                                     m.get("identity_file")))
    if sidecar["methods"] or sidecar.get("public_key"):
        return out, True
    for p in sorted(kp.parent.glob(f"{kp.name}.*.age")) if kp.parent.exists() else []:
        if p.name.endswith(".pending.age"):
            continue
        mid = ident(p.name)
        kind = mid if mid in ("se", "yubikey") else (
            "passphrase" if mid == PASSPHRASE_ID else "identity")
        out.append(WrappedMethod(mid, kind, p))
    return out, False


def _select(methods: list[WrappedMethod], name: str) -> list[WrappedMethod]:
    name = "pass" if name == "passphrase" else name
    hit = [m for m in methods if m.method_id == name]
    return hit or [m for m in methods if m.kind == name]


def _decrypt_method(m: WrappedMethod, identity: Optional[Path]) -> str:
    if m.kind == "passphrase":
        plain = keystore.age_decrypt_passphrase(m.path)
    else:
        idf = identity or (Path(m.identity_file).expanduser() if m.identity_file else None)
        if idf is None:
            raise AgeToolError(
                f"{m.method_id} needs its plugin identity file: pass --identity FILE"
            )
        plain = keystore.age_decrypt_identity(m.path, idf)
    secret = extract_secret(plain.decode(errors="replace"))
    if secret is None:
        raise AgeToolError(f"{m.method_id}: decrypted data holds no AGE-SECRET-KEY")
    return secret


def _default_order(methods: list[WrappedMethod]) -> list[WrappedMethod]:
    order: list[WrappedMethod] = []
    if is_gui_session():
        order += [m for m in methods if m.kind == "se"]
    order += [m for m in methods if m.kind == "yubikey" and device_present("yubikey")]
    order += [m for m in methods if m.kind == "passphrase"]
    return order


def unlock(
    with_method: Optional[str] = None,
    identity: Optional[Path] = None,
    paste: bool = False,
) -> UnlockResult:
    """Restore the plain key to ``$SOPS_AGE_KEY_FILE`` after a human proves
    presence. Decrypts to memory, checks the public key, writes atomically."""
    if paste and identity is not None:
        raise UnlockError("--paste and --identity are mutually exclusive")
    kp = keystore.key_path()
    sidecar = keystore.load_sidecar()
    expected = sidecar.get("public_key")

    if kp.exists():
        existing = extract_secret(kp.read_text())
        if existing is not None:
            try:
                have = keystore.public_key_of(existing)
            except AgeToolError as e:
                raise UnlockError(str(e)) from e
            if not expected or have == expected:
                return UnlockResult("already-unlocked", path=kp)
            raise UnlockError(
                f"{kp} holds a different key ({have}) than the sidecar's "
                f"({expected}); refusing to overwrite it"
            )

    methods, from_sidecar = list_wrapped()
    used: str
    secret: Optional[str] = None
    errors: list[str] = []

    if paste:
        secret, used = read_secret_tty(), "paste"
    elif identity is not None:
        cands = _select(methods, with_method) if with_method else [
            m for m in methods if m.kind != "passphrase"]
        if not cands:
            raise UnlockError("no wrapped file to open with --identity")
        used = ""
        for m in cands:
            try:
                secret, used = _decrypt_method(m, Path(identity)), m.method_id
                break
            except AgeToolError as e:
                errors.append(f"{m.method_id}: {e}")
        if secret is None:
            raise UnlockError("identity opened no wrapped file. " + "; ".join(errors))
    else:
        if not methods:
            raise UnlockError(
                "no wrapped key files found next to "
                f"{kp}; use --paste or --identity FILE, or run 'dotconfig key wrap' "
                "while the key is unlocked"
            )
        if with_method:
            order = _select(methods, with_method)
            if not order:
                have = ", ".join(m.method_id for m in methods)
                raise UnlockError(f"no method {with_method!r}; available: {have}")
        else:
            order = _default_order(methods)
        used = ""
        for m in order:
            try:
                secret, used = _decrypt_method(m, None), m.method_id
                break
            except AgeToolError as e:
                errors.append(f"{m.method_id}: {e}")
        if secret is None:
            tried = {m.method_id for m in order}
            rest = [m for m in methods if m.method_id not in tried]
            msg = "unlock failed. " + ("; ".join(errors) if errors
                                       else "no method usable in this session.")
            if rest:
                msg += " Other methods: " + ", ".join(
                    f"--with {m.method_id}" + (f" ({m.hint})" if m.hint else "")
                    for m in rest)
            msg += ". Also: --identity FILE, --paste"
            raise UnlockError(msg)

    try:
        got = keystore.public_key_of(secret)
    except AgeToolError as e:
        raise UnlockError(str(e)) from e
    degraded = not expected
    if expected and got != expected:
        raise UnlockError(
            f"recovered key's public key ({got}) does not match the sidecar's "
            f"({expected}); nothing written"
        )
    if degraded:
        from .output import warn

        warn("no sidecar public key to check against (degraded mode); key "
             "written unverified. Run 'dotconfig key wrap' to record it.")
    path = keystore.write_plain_key(secret)
    return UnlockResult("unlocked", used, path, degraded)


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------
#
# Lock needs no secret and asks nothing: it never prompts and never reads
# stdin, so it is safe to run unattended (cron, hooks, screen-lock).


class LockError(Exception):
    """Lock refused; the plain key file was left in place."""


@dataclass
class LockResult:
    status: str  # "already-locked" | "locked"
    forced: bool = False
    path: Optional[Path] = None
    methods: Optional[list[WrappedMethod]] = None
    verified: Optional[dict] = None  # method_id -> verified date or None


def scrub_file(path: Path) -> None:
    """Best-effort zero-fill then unlink.

    Not guaranteed to destroy the data on APFS / SSDs (copy-on-write and wear
    levelling may keep old blocks); it only raises the bar."""
    try:
        size = path.stat().st_size
        with open(path, "r+b") as f:
            f.write(b"\0" * size)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass  # still unlink below
    path.unlink()


def lock_problems(secret_pub: Optional[str]) -> list[str]:
    """Reasons it is unsafe to delete the plain key (empty list means safe)."""
    problems: list[str] = []
    sidecar = keystore.load_sidecar()
    recorded = sidecar.get("public_key")
    methods, from_sidecar = list_wrapped()
    if not methods:
        problems.append("no wrapped key file exists next to the key")
    elif not from_sidecar:
        problems.append("no sidecar records the wrapped files")
    if not recorded:
        problems.append("sidecar has no public_key to check the key against")
    elif secret_pub is None:
        problems.append("could not derive the plain key's public key")
    elif recorded != secret_pub:
        problems.append(
            f"sidecar public_key ({recorded}) differs from the plain key's "
            f"({secret_pub})"
        )
    return problems


def lock(force: bool = False) -> LockResult:
    """Remove the plain key file when at least one verified-recorded wrapped
    copy exists for the same public key. ``force`` deletes regardless."""
    kp = keystore.key_path()
    if not kp.exists():
        return LockResult("already-locked", path=kp)

    secret_pub: Optional[str] = None
    try:
        secret = extract_secret(kp.read_text())
        if secret is not None:
            secret_pub = keystore.public_key_of(secret)
    except (AgeToolError, OSError):
        secret_pub = None

    problems = lock_problems(secret_pub)
    methods, _ = list_wrapped()
    if problems and not force:
        raise LockError(
            "refusing to lock: " + "; ".join(problems) + ". The plain key at "
            f"{kp} was left in place. Create a wrapped copy first with: "
            "dotconfig key wrap (or pass --force to delete anyway)"
        )
    sidecar = keystore.load_sidecar()
    verified = {m.get("file"): m.get("verified") for m in sidecar["methods"]}
    by_id = {m.method_id: verified.get(m.path.name) for m in methods}
    scrub_file(kp)
    return LockResult("locked", forced=bool(problems), path=kp, methods=methods,
                      verified=by_id)
