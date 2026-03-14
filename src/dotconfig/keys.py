"""
Keys command: inspect age encryption key configuration.

Reports where SOPS will find your age secret key, shows the derived
public key, and prints export statements for setting environment
variables as an alternative to the key file.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional

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

    # --- Export suggestions ---
    heading("📋 Environment variable exports:")
    info("To use env vars instead of the key file, add to your shell profile:")
    print()

    # Show the secret key value (reading from file if needed)
    if found_source == "SOPS_AGE_KEY":
        # Already in env, show current value
        item(f'  export SOPS_AGE_KEY="{secret_key}"')
    elif found_source and found_source.startswith("SOPS_AGE_KEY_FILE"):
        # Point to the file
        file_path = os.environ["SOPS_AGE_KEY_FILE"]
        item(f'  export SOPS_AGE_KEY_FILE="{file_path}"')
        print()
        info("Or inline the key directly:")
        item(f'  export SOPS_AGE_KEY="{secret_key}"')
    else:
        # From default file
        item(f'  export SOPS_AGE_KEY_FILE="{default_key_file}"')
        print()
        info("Or inline the key directly:")
        item(f'  export SOPS_AGE_KEY="{secret_key}"')

    # --- Codespaces / CI secret guidance ---
    heading("☁️  GitHub Codespaces / CI:")
    info("To use your age key in Codespaces, add it as a repository secret:")
    print()
    item("  Secret name:  SOPS_AGE_KEY")
    item(f"  Secret value: {secret_key}")
    print()
    info("Via the GitHub CLI:")
    item(f'  gh secret set SOPS_AGE_KEY --body "{secret_key}"')
    print()
    info("Or set it in repo Settings → Secrets and variables → Codespaces.")
