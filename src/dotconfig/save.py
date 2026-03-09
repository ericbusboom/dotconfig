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
            print(
                f"Warning: sops encryption failed for {filepath}: {result.stderr.strip()}",
                file=sys.stderr,
            )
            # Remove the plaintext file on encryption failure
            filepath.unlink(missing_ok=True)
            return False

        return True
    except FileNotFoundError:
        print(
            f"Warning: sops not found — cannot encrypt {filepath}",
            file=sys.stderr,
        )
        return False
    except Exception as e:
        print(f"Warning: error encrypting {filepath}: {e}", file=sys.stderr)
        return False


def parse_env_file(
    content: str,
) -> Tuple[Optional[str], Optional[str], Dict[str, str]]:
    """Parse a dotconfig-generated .env file.

    Extracts:
      - CONFIG_COMMON metadata value
      - CONFIG_LOCAL metadata value (may be None)
      - A dict mapping section labels to their variable content

    Section labels are the full strings inside ``# --- ... ---`` markers,
    e.g. ``"public (dev)"``, ``"secrets (dev)"``, ``"public-local (alice)"``.
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

        # Section marker: # --- <label> ---
        if line.startswith("# --- ") and line.endswith(" ---"):
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
        print(f"Error: {env_file} does not exist", file=sys.stderr)
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
        print(
            "Error: CONFIG_COMMON not found in .env — is this a dotconfig-managed file?",
            file=sys.stderr,
        )
        sys.exit(1)

    # Determine destination names: overrides take precedence over metadata.
    save_common = override_common if override_common is not None else common_name
    save_local = override_local if override_local is not None else local_name

    saved = []

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
        saved.append(f"  public config       -> {public_file}")

    # --- Secrets (common) ---
    secrets_key = f"secrets ({common_name})"
    if secrets_key in sections:
        secrets_body = sections[secrets_key]
        if secrets_body:
            secrets_file = config_dir / save_common / "secrets.env"
            secrets_file.parent.mkdir(parents=True, exist_ok=True)
            if _encrypt_sops(secrets_body + "\n", secrets_file, sops_config):
                saved.append(f"  secrets (encrypted) -> {secrets_file}")
            else:
                print(
                    f"Warning: could not encrypt secrets for {save_common}",
                    file=sys.stderr,
                )

    if local_name:
        # --- Public-local ---
        local_key = f"public-local ({local_name})"
        if local_key in sections:
            local_body = sections[local_key]
            local_file = config_dir / "local" / save_local / "public.env"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_text(local_body + "\n" if local_body else "")
            saved.append(f"  public-local config -> {local_file}")

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
                    saved.append(
                        f"  secrets-local (encrypted) -> {secrets_local_file}"
                    )
                else:
                    print(
                        f"Warning: could not encrypt local secrets for {save_local}",
                        file=sys.stderr,
                    )

    if saved:
        print("Saved:")
        for line in saved:
            print(line)
    else:
        print("Nothing saved.")
