"""
Save command: write .env sections back to config/ source files.

Reads the marked sections in .env and writes each section back to its
corresponding source file in config/, re-encrypting secrets with SOPS.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple


def _encrypt_sops(content: str, filepath: Path) -> bool:
    """Encrypt content with SOPS and save to filepath.

    Writes content to a temporary file, encrypts it in-place with sops,
    then moves it to the target path.  Returns True on success.
    """
    try:
        # Write plaintext to a temp file in the same directory so sops
        # can infer creation rules from .sops.yaml
        tmp_fd, tmp_path = tempfile.mkstemp(
            suffix=".env", dir=filepath.parent if filepath.parent.exists() else None
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                f.write(content)

            result = subprocess.run(
                ["sops", "--encrypt", "--in-place", tmp_path],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(
                    f"Warning: sops encryption failed for {filepath}: {result.stderr.strip()}",
                    file=sys.stderr,
                )
                return False

            filepath.parent.mkdir(parents=True, exist_ok=True)
            Path(tmp_path).replace(filepath)
            return True
        except Exception:
            # Clean up temp file if anything goes wrong
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
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


def save_config(env_file: Path, config_dir: Path) -> None:
    """Save .env sections back to the config/ source files.

    Reads CONFIG_COMMON and CONFIG_LOCAL from the .env metadata comments,
    then writes each section to its corresponding file:

      - public ({common_name})         -> config/{common_name}.env
      - secrets ({common_name})        -> config/secrets/{common_name}.env  (SOPS-encrypted)
      - public-local ({local_name})    -> config/local/{local_name}.env
      - secrets-local ({local_name})   -> config/secrets/local/{local_name}.env (SOPS-encrypted)

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

    saved = []

    # --- Public (common) ---
    public_key = f"public ({common_name})"
    if public_key in sections:
        public_file = config_dir / f"{common_name}.env"
        public_file.parent.mkdir(parents=True, exist_ok=True)
        body = sections[public_key]
        public_file.write_text(body + "\n" if body else "")
        saved.append(f"  public config       -> {public_file}")

    # --- Secrets (common) ---
    secrets_key = f"secrets ({common_name})"
    if secrets_key in sections:
        secrets_body = sections[secrets_key]
        if secrets_body:
            secrets_file = config_dir / "secrets" / f"{common_name}.env"
            secrets_file.parent.mkdir(parents=True, exist_ok=True)
            if _encrypt_sops(secrets_body + "\n", secrets_file):
                saved.append(f"  secrets (encrypted) -> {secrets_file}")
            else:
                print(
                    f"Warning: could not encrypt secrets for {common_name}",
                    file=sys.stderr,
                )

    if local_name:
        # --- Public-local ---
        local_key = f"public-local ({local_name})"
        if local_key in sections:
            local_body = sections[local_key]
            local_file = config_dir / "local" / f"{local_name}.env"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_text(local_body + "\n" if local_body else "")
            saved.append(f"  public-local config -> {local_file}")

        # --- Secrets-local ---
        secrets_local_key = f"secrets-local ({local_name})"
        if secrets_local_key in sections:
            secrets_local_body = sections[secrets_local_key]
            if secrets_local_body:
                secrets_local_file = (
                    config_dir / "secrets" / "local" / f"{local_name}.env"
                )
                secrets_local_file.parent.mkdir(parents=True, exist_ok=True)
                if _encrypt_sops(secrets_local_body + "\n", secrets_local_file):
                    saved.append(
                        f"  secrets-local (encrypted) -> {secrets_local_file}"
                    )
                else:
                    print(
                        f"Warning: could not encrypt local secrets for {local_name}",
                        file=sys.stderr,
                    )

    if saved:
        print("Saved:")
        for line in saved:
            print(line)
    else:
        print("Nothing saved.")
