"""
Keys command: inspect age encryption key configuration.

Reports where SOPS will find your age secret key, shows the derived
public key, and lock state and wrapped methods.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional

from . import keystore, keywrap
from .init import _extract_secret_key, _is_age_installed, _read_key_from_file
from .output import error, heading, info, item, ok, warn


def _derive_public_key_quiet(secret_key: str) -> Optional[str]:
    """Derive the age public key without printing warnings."""
    try:
        result = subprocess.run(
            ["age-keygen", "-y"],
            input=secret_key,
            capture_output=True,
            text=True,
            check=True,
        )
        pub = result.stdout.strip()
        return pub if pub else None
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _show_lock_state() -> None:
    """Report locked/unlocked/not wrapped, wrapped methods and env warnings."""
    kp = keystore.key_path()
    methods, _from_sidecar = keywrap.list_wrapped()
    sidecar_exists = keystore.sidecar_path().exists()
    plain_present = kp.exists()

    heading("🔒 Lock state:")
    if not sidecar_exists and not methods:
        state = "not wrapped"
    elif plain_present:
        state = "unlocked"
    else:
        state = "locked"
    info(f"state: {state} ({kp})")
    if state == "not wrapped":
        info("Run 'dotconfig age wrap' to keep an encrypted copy of the key.")

    if methods:
        verified = {
            m.get("file"): m.get("verified")
            for m in keystore.load_sidecar()["methods"]
        }
        heading("Wrapped methods:")
        for m in methods:
            when = verified.get(m.path.name)
            when_txt = f"verified {when}" if when else "never verified"
            label = f" {m.label}" if m.label else ""
            item(f"  {m.kind}{label} — {when_txt}")

    if os.environ.get("SOPS_AGE_KEY"):
        warn(
            "SOPS_AGE_KEY is set in the environment. It survives 'dotconfig age lock' "
            "and defeats locking; unset it and use SOPS_AGE_KEY_FILE instead."
        )


def show_keys() -> None:
    """Inspect and report age key configuration."""

    heading("🔑 Age encryption key status:")

    # --- Check toolchain ---
    if not _is_age_installed():
        error("age is not installed")
        info("Install it from: https://github.com/FiloSottile/age#installation")
        return

    ok("age is installed")

    # --- Check each source in priority order ---
    default_key_file = Path.home() / ".config" / "sops" / "age" / "keys.txt"

    sources = [
        ("SOPS_AGE_KEY", "environment variable (inline key)"),
        ("SOPS_AGE_KEY_FILE", "environment variable (path to key file)"),
    ]

    secret_key: Optional[str] = None
    found_source: Optional[str] = None

    heading("🔍 Key sources (checked in priority order):")

    # 1. SOPS_AGE_KEY
    val = os.environ.get("SOPS_AGE_KEY", "")
    if val:
        key = _extract_secret_key(val)
        if key:
            ok("SOPS_AGE_KEY — set, contains valid key")
            secret_key = key
            found_source = "SOPS_AGE_KEY"
        else:
            warn("SOPS_AGE_KEY — set, but no valid key found in value")
    else:
        item("  SOPS_AGE_KEY — not set")

    # 2. SOPS_AGE_KEY_FILE
    val = os.environ.get("SOPS_AGE_KEY_FILE", "")
    if val:
        path = Path(val)
        if path.exists():
            key = _read_key_from_file(path)
            if key:
                if not secret_key:
                    secret_key = key
                    found_source = f"SOPS_AGE_KEY_FILE ({val})"
                ok(f"SOPS_AGE_KEY_FILE — {val} (valid key)")
            else:
                warn(f"SOPS_AGE_KEY_FILE — {val} (exists but no valid key)")
        else:
            warn(f"SOPS_AGE_KEY_FILE — {val} (file not found)")
    else:
        item("  SOPS_AGE_KEY_FILE — not set")

    # 3. Default file
    if default_key_file.exists():
        key = _read_key_from_file(default_key_file)
        if key:
            if not secret_key:
                secret_key = key
                found_source = str(default_key_file)
            ok(f"{default_key_file} — exists, valid key")
        else:
            warn(f"{default_key_file} — exists but no valid key")
    else:
        item(f"  {default_key_file} — not found")

    # --- Lock state ---
    _show_lock_state()

    # --- Summary ---
    if secret_key is None:
        heading("❌ No age key found")
        info("Run 'dotconfig init' to generate one, or configure manually.")
        return

    heading("✅ Active key:")
    ok(f"source: {found_source}")

    public_key = _derive_public_key_quiet(secret_key)
    if public_key:
        info(f"public key: {public_key}")
    else:
        warn("could not derive public key")

    # --- Guidance (never prints the secret key) ---
    heading("📋 Using the key:")
    info("Point SOPS at the key file (do not inline the secret in the environment):")
    item(f'  export SOPS_AGE_KEY_FILE="{keystore.key_path()}"')
    info("Protect it at rest with 'dotconfig age wrap' and 'dotconfig age lock'.")
    info("To push the key to GitHub use 'dotconfig gh-push --include-age-key'.")
