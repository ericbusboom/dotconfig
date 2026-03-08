"""
Load command: assemble config/ source files into a single .env file.

The generated .env has marked sections that map back to source files
in the config/ directory, enabling round-tripping via the save command.
"""

import subprocess
import sys
from pathlib import Path
from typing import Optional


def _decrypt_sops(filepath: Path) -> Optional[str]:
    """Decrypt a SOPS-encrypted file.

    Returns decrypted content as a string, or None if decryption is
    unavailable (sops not installed, key missing, or file unreadable).
    """
    try:
        result = subprocess.run(
            ["sops", "--decrypt", str(filepath)],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except FileNotFoundError:
        print(
            f"Warning: sops not found — skipping encrypted file {filepath}",
            file=sys.stderr,
        )
        return None
    except subprocess.CalledProcessError as e:
        print(
            f"Warning: sops decryption failed for {filepath}: {e.stderr.strip()}",
            file=sys.stderr,
        )
        return None


def load_config(
    common_name: str,
    local_name: Optional[str],
    config_dir: Path,
    output: Path,
) -> None:
    """Assemble config source files into a single .env file.

    Reads from:
      - config/{common_name}.env            (public common config)
      - config/secrets/{common_name}.env    (SOPS-encrypted secrets)
      - config/local/{local_name}.env       (public local overrides, optional)
      - config/secrets/local/{local_name}.env (encrypted local secrets, optional)

    Writes a .env with marked sections:
      # CONFIG_COMMON={common_name}
      # CONFIG_LOCAL={local_name}   (if local_name is provided)

      # --- public ({common_name}) ---
      ...
      # --- secrets ({common_name}) ---
      ...
      # --- public-local ({local_name}) ---   (if local_name is provided)
      ...
      # --- secrets-local ({local_name}) ---  (if local_name is provided)
      ...

    Later sections override earlier ones (last-write-wins when shell-sourced).
    """
    common_env = config_dir / f"{common_name}.env"
    if not common_env.exists():
        print(
            f"Error: common config file not found: {common_env}",
            file=sys.stderr,
        )
        sys.exit(1)

    parts = []

    # --- Metadata header ---
    parts.append(f"# CONFIG_COMMON={common_name}")
    if local_name:
        parts.append(f"# CONFIG_LOCAL={local_name}")
    parts.append("")

    # --- Public (common) section ---
    parts.append(f"# --- public ({common_name}) ---")
    public_content = common_env.read_text().strip()
    if public_content:
        parts.append(public_content)

    # --- Secrets (common) section ---
    parts.append("")
    parts.append(f"# --- secrets ({common_name}) ---")
    secrets_env = config_dir / "secrets" / f"{common_name}.env"
    if secrets_env.exists():
        decrypted = _decrypt_sops(secrets_env)
        if decrypted and decrypted.strip():
            parts.append(decrypted.strip())
    else:
        print(
            f"Info: secrets file not found: {secrets_env} — secrets section will be empty",
            file=sys.stderr,
        )

    if local_name:
        # --- Public-local section ---
        parts.append("")
        parts.append(f"# --- public-local ({local_name}) ---")
        local_env = config_dir / "local" / f"{local_name}.env"
        if local_env.exists():
            local_content = local_env.read_text().strip()
            if local_content:
                parts.append(local_content)
        else:
            print(
                f"Warning: local config file not found: {local_env} — public-local section will be empty",
                file=sys.stderr,
            )

        # --- Secrets-local section ---
        parts.append("")
        parts.append(f"# --- secrets-local ({local_name}) ---")
        secrets_local = config_dir / "secrets" / "local" / f"{local_name}.env"
        if secrets_local.exists():
            decrypted = _decrypt_sops(secrets_local)
            if decrypted and decrypted.strip():
                parts.append(decrypted.strip())

    # Ensure the file ends with a newline
    output.write_text("\n".join(parts) + "\n")
    print(f"Written to {output}")
