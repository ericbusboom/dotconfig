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
