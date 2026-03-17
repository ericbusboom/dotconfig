"""
Load command: assemble config/ source files into a single .env file,
or retrieve a specific file from a deployment.

The generated .env has marked sections that map back to source files
in the config/ directory, enabling round-tripping via the save command.
"""

import subprocess
import sys
from pathlib import Path
from typing import Optional

import click

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


def load_file(
    deployment: Optional[str],
    local: Optional[str],
    filename: str,
    config_dir: Path,
    output: Optional[Path],
    to_stdout: bool,
) -> None:
    """Load a single file from a deployment or local directory.

    Exactly one of *deployment* or *local* must be provided (not both).

    Resolves the file path:
      - With *deployment*: ``config/{deployment}/{filename}``
      - With *local*: ``config/local/{local}/{filename}``

    Writes to *output* (defaulting to ``./{filename}``) or prints to
    stdout when *to_stdout* is True.
    """
    if deployment and local:
        error("--file requires either --deploy or --local, not both")
        sys.exit(1)
    if local:
        source = config_dir / "local" / local / filename
    elif deployment:
        source = config_dir / deployment / filename
    else:
        error("--deploy or --local is required with --file")
        sys.exit(1)

    if not source.exists():
        error(f"file not found: {source}")
        sys.exit(1)

    content = source.read_text()

    if to_stdout:
        click.echo(content, nl=False)
    else:
        dest = output if output else Path(filename)
        dest.write_text(content)
        ok(f"Written to {dest}")


def load_config(
    deployment: str,
    local: Optional[str],
    config_dir: Path,
    output: Optional[Path],
    to_stdout: bool = False,
) -> None:
    """Assemble config source files into a single .env file.

    Reads from:
      - config/{deployment}/public.env            (public deployment config)
      - config/{deployment}/secrets.env           (SOPS-encrypted secrets)
      - config/local/{local}/public.env           (public local overrides, optional)
      - config/local/{local}/secrets.env          (encrypted local secrets, optional)

    Writes a .env with marked sections:
      # CONFIG_DEPLOY={deployment}
      # CONFIG_LOCAL={local}   (if local is provided)

      #@dotconfig: public ({deployment})
      ...
      #@dotconfig: secrets ({deployment})
      ...
      #@dotconfig: public-local ({local})   (if local is provided)
      ...
      #@dotconfig: secrets-local ({local})  (if local is provided)
      ...

    Later sections override earlier ones (last-write-wins when shell-sourced).

    When *to_stdout* is True the assembled content is printed to stdout
    instead of being written to a file.
    """
    deploy_env = config_dir / deployment / "public.env"
    if not deploy_env.exists():
        error(f"deployment config file not found: {deploy_env}")
        sys.exit(1)

    parts = []

    # Locate the sops config file so it can be passed explicitly to sops.
    # sops.yaml is a non-dotfile and is not auto-discovered by sops, so we
    # must pass --config when invoking sops.
    sops_config = config_dir / "sops.yaml"

    # --- Metadata header ---
    parts.append(f"# CONFIG_DEPLOY={deployment}")
    if local:
        parts.append(f"# CONFIG_LOCAL={local}")
    parts.append("")

    # --- Public (deployment) section ---
    parts.append(f"#@dotconfig: public ({deployment})")
    public_content = deploy_env.read_text().strip()
    if public_content:
        parts.append(public_content)

    # --- Secrets (deployment) section ---
    parts.append("")
    parts.append(f"#@dotconfig: secrets ({deployment})")
    secrets_env = config_dir / deployment / "secrets.env"
    if secrets_env.exists():
        decrypted = _decrypt_sops(secrets_env, sops_config)
        if decrypted and decrypted.strip():
            parts.append(decrypted.strip())
    else:
        warn(f"secrets file not found: {secrets_env} — secrets section will be empty")

    if local:
        # --- Public-local section ---
        parts.append("")
        parts.append(f"#@dotconfig: public-local ({local})")
        local_env = config_dir / "local" / local / "public.env"
        if local_env.exists():
            local_content = local_env.read_text().strip()
            if local_content:
                parts.append(local_content)
        else:
            warn(f"local config file not found: {local_env} — public-local section will be empty")

        # --- Secrets-local section ---
        parts.append("")
        parts.append(f"#@dotconfig: secrets-local ({local})")
        secrets_local = config_dir / "local" / local / "secrets.env"
        if secrets_local.exists():
            decrypted = _decrypt_sops(secrets_local, sops_config)
            if decrypted and decrypted.strip():
                parts.append(decrypted.strip())

    assembled = "\n".join(parts) + "\n"

    if to_stdout:
        click.echo(assembled, nl=False)
    else:
        if output is None:
            output = Path(".env")
        output.write_text(assembled)
        ok(f"Written to {output}")
