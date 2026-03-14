"""
Save command: write .env sections back to config/ source files.

Reads the marked sections in .env and writes each section back to its
corresponding source file in config/, re-encrypting secrets with SOPS.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

from .output import error, heading, ok, warn


def _rewrite_deployment(body: str, target_deployment: str) -> str:
    """Replace the value of DEPLOYMENT= with *target_deployment*."""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("DEPLOYMENT="):
            lines[i] = f"DEPLOYMENT={target_deployment}"
    return "\n".join(lines)


def _encrypt_sops(
    content: str, filepath: Path, sops_config: Optional[Path] = None
) -> bool:
    """Encrypt content with SOPS and save to filepath.

    Writes plaintext content to *filepath*, then encrypts it in-place
    with sops.  Returns True on success.

    If *sops_config* is provided and exists, it is passed to sops via
    ``--config`` so that a non-dotfile ``sops.yaml`` inside the config
    directory is found even when it would not be auto-discovered.

    The file path passed to sops is kept relative (to the current working
    directory) so that sops ``path_regex`` creation rules match correctly.
    """
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content)

        # Use a relative path so sops path_regex matching works correctly.
        # Absolute paths can fail to match regex patterns like ".+/secrets\\.env$".
        try:
            sops_filepath = filepath.relative_to(Path.cwd())
        except ValueError:
            sops_filepath = filepath

        cmd = ["sops"]
        if sops_config is not None and sops_config.exists():
            cmd += ["--config", str(sops_config)]
        cmd += ["--encrypt", "--in-place", str(sops_filepath)]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            warn(f"sops encryption failed for {filepath}: {result.stderr.strip()}")
            # Remove the plaintext file on encryption failure
            filepath.unlink(missing_ok=True)
            return False

        return True
    except FileNotFoundError:
        warn(f"sops not found — cannot encrypt {filepath}")
        return False
    except Exception as e:
        warn(f"error encrypting {filepath}: {e}")
        return False


def parse_env_file(
    content: str,
) -> Tuple[Optional[str], Optional[str], Dict[str, str]]:
    """Parse a dotconfig-generated .env file.

    Extracts:
      - CONFIG_COMMON metadata value
      - CONFIG_LOCAL metadata value (may be None)
      - A dict mapping section labels to their variable content

    Section labels are the strings after ``#@dotconfig:`` markers,
    e.g. ``"public (dev)"``, ``"secrets (dev)"``, ``"public-local (alice)"``.

    Also recognises the legacy ``# --- label ---`` format for backward
    compatibility.
    """
    common_name: Optional[str] = None
    local_name: Optional[str] = None
    sections: Dict[str, str] = {}
    current_section: Optional[str] = None
    current_lines = []

    for line in content.splitlines():
        if line.startswith("# CONFIG_COMMON="):
            common_name = line.split("=", 1)[1].strip()
            continue
        if line.startswith("# CONFIG_LOCAL="):
            local_name = line.split("=", 1)[1].strip()
            continue

        # New marker format: #@dotconfig: <label>
        if line.startswith("#@dotconfig: "):
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line[len("#@dotconfig: "):].strip()
            current_lines = []
        # Legacy marker format: # --- <label> ---
        elif line.startswith("# --- ") and line.endswith(" ---"):
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line[6:-4].strip()
            current_lines = []
        elif current_section is not None:
            current_lines.append(line)

    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).strip()

    return common_name, local_name, sections


def save_config(
    env_file: Path,
    config_dir: Path,
    override_common: Optional[str] = None,
    override_local: Optional[str] = None,
) -> None:
    """Save .env sections back to the config/ source files.

    Reads CONFIG_COMMON and CONFIG_LOCAL from the .env metadata comments,
    then writes each section to its corresponding file:

      - public ({common_name})         -> config/{save_common}/public.env
      - secrets ({common_name})        -> config/{save_common}/secrets.env  (SOPS-encrypted)
      - public-local ({local_name})    -> config/local/{save_local}/public.env
      - secrets-local ({local_name})   -> config/local/{save_local}/secrets.env (SOPS-encrypted)

    If *override_common* is given it is used as the destination common name
    (i.e. the files that are written to) instead of CONFIG_COMMON.  Likewise
    *override_local* overrides CONFIG_LOCAL for the destination local name.
    This allows saving a loaded .env to a *different* environment or user,
    e.g. loading ``prod eric`` and saving as ``dev stan``.

    If SOPS_AGE_KEY_FILE is found inside the .env, it is added to the
    current process environment before invoking sops.
    """
    if not env_file.exists():
        error(f"{env_file} does not exist")
        sys.exit(1)

    content = env_file.read_text()

    # Extract SOPS key path from the file itself before any section parsing
    # so that sops can be invoked correctly when the variable is stored there.
    for line in content.splitlines():
        if line.startswith("SOPS_AGE_KEY_FILE="):
            key_file = line.split("=", 1)[1].strip()
            os.environ.setdefault("SOPS_AGE_KEY_FILE", key_file)
            break

    common_name, local_name, sections = parse_env_file(content)

    if not common_name:
        error("CONFIG_COMMON not found in .env — is this a dotconfig-managed file?")
        sys.exit(1)

    # Determine destination names: overrides take precedence over metadata.
    save_common = override_common if override_common is not None else common_name
    save_local = override_local if override_local is not None else local_name

    saved = []

    # When saving to a different deployment, rewrite the DEPLOYMENT variable
    # so it reflects the target environment, not the one that was loaded.
    if save_common != common_name:
        for key in sections:
            sections[key] = _rewrite_deployment(sections[key], save_common)

    # Locate the sops config file so it can be passed explicitly to sops.
    # sops.yaml is a non-dotfile and is not auto-discovered by sops, so we
    # must pass --config when invoking sops.
    sops_config = config_dir / "sops.yaml"

    # --- Public (common) ---
    public_key = f"public ({common_name})"
    if public_key in sections:
        public_file = config_dir / save_common / "public.env"
        public_file.parent.mkdir(parents=True, exist_ok=True)
        body = sections[public_key]
        public_file.write_text(body + "\n" if body else "")
        saved.append(("public config", str(public_file)))

    # --- Secrets (common) ---
    secrets_key = f"secrets ({common_name})"
    if secrets_key in sections:
        secrets_body = sections[secrets_key]
        if secrets_body:
            secrets_file = config_dir / save_common / "secrets.env"
            secrets_file.parent.mkdir(parents=True, exist_ok=True)
            if _encrypt_sops(secrets_body + "\n", secrets_file, sops_config):
                saved.append(("secrets 🔒", str(secrets_file)))
            else:
                warn(f"could not encrypt secrets for {save_common}")

    if local_name:
        # --- Public-local ---
        local_key = f"public-local ({local_name})"
        if local_key in sections:
            local_body = sections[local_key]
            local_file = config_dir / "local" / save_local / "public.env"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_text(local_body + "\n" if local_body else "")
            saved.append(("public-local config", str(local_file)))

        # --- Secrets-local ---
        secrets_local_key = f"secrets-local ({local_name})"
        if secrets_local_key in sections:
            secrets_local_body = sections[secrets_local_key]
            if secrets_local_body:
                secrets_local_file = (
                    config_dir / "local" / save_local / "secrets.env"
                )
                secrets_local_file.parent.mkdir(parents=True, exist_ok=True)
                if _encrypt_sops(secrets_local_body + "\n", secrets_local_file, sops_config):
                    saved.append(("secrets-local 🔒", str(secrets_local_file)))
                else:
                    warn(f"could not encrypt local secrets for {save_local}")

    if saved:
        heading("💾 Saved:")
        for label, path in saved:
            ok(f"{label} → {path}")
    else:
        warn("Nothing saved.")
