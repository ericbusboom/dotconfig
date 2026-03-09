"""
Load command: assemble config/ source files into a single .env file.

The generated .env has marked sections that map back to source files
in the config/ directory, enabling round-tripping via the save command.
"""

import subprocess
import sys
from pathlib import Path
from typing import Optional

from .output import error, ok, warn


def _decrypt_sops(filepath: Path, sops_config: Optional[Path] = None) -> Optional[str]:
    """Decrypt a SOPS-encrypted file.

    Returns decrypted content as a string, or None if decryption is
    unavailable (sops not installed, key missing, or file unreadable).

    If *sops_config* is provided and exists, it is passed to sops via
    ``--config`` so that a non-dotfile ``sops.yaml`` inside the config
    directory is found even when it would not be auto-discovered.
    """
    try:
        cmd = ["sops"]
        if sops_config is not None and sops_config.exists():
            cmd += ["--config", str(sops_config)]
        cmd += ["--decrypt", str(filepath)]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except FileNotFoundError:
        warn(f"sops not found — skipping encrypted file {filepath}")
        return None
    except subprocess.CalledProcessError as e:
        warn(f"sops decryption failed for {filepath}: {e.stderr.strip()}")
        return None


def load_config(
    common_name: str,
    local_name: Optional[str],
    config_dir: Path,
    output: Path,
) -> None:
    """Assemble config source files into a single .env file.

    Reads from:
      - config/{common_name}/public.env            (public common config)
      - config/{common_name}/secrets.env           (SOPS-encrypted secrets)
      - config/local/{local_name}/public.env       (public local overrides, optional)
      - config/local/{local_name}/secrets.env      (encrypted local secrets, optional)

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
    common_env = config_dir / common_name / "public.env"
    if not common_env.exists():
        error(f"common config file not found: {common_env}")
        sys.exit(1)

    parts = []

    # Locate the sops config file so it can be passed explicitly to sops.
    # sops.yaml is a non-dotfile and is not auto-discovered by sops, so we
    # must pass --config when invoking sops.
    sops_config = config_dir / "sops.yaml"

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
    secrets_env = config_dir / common_name / "secrets.env"
    if secrets_env.exists():
        decrypted = _decrypt_sops(secrets_env, sops_config)
        if decrypted and decrypted.strip():
            parts.append(decrypted.strip())
    else:
        warn(f"secrets file not found: {secrets_env} — secrets section will be empty")

    if local_name:
        # --- Public-local section ---
        parts.append("")
        parts.append(f"# --- public-local ({local_name}) ---")
        local_env = config_dir / "local" / local_name / "public.env"
        if local_env.exists():
            local_content = local_env.read_text().strip()
            if local_content:
                parts.append(local_content)
        else:
            warn(f"local config file not found: {local_env} — public-local section will be empty")

        # --- Secrets-local section ---
        parts.append("")
        parts.append(f"# --- secrets-local ({local_name}) ---")
        secrets_local = config_dir / "local" / local_name / "secrets.env"
        if secrets_local.exists():
            decrypted = _decrypt_sops(secrets_local, sops_config)
            if decrypted and decrypted.strip():
                parts.append(decrypted.strip())

    # Ensure the file ends with a newline
    output.write_text("\n".join(parts) + "\n")
    ok(f"Written to {output}")
