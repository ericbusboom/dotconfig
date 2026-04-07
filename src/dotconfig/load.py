"""
Load command: assemble config/ source files into a single .env file,
or retrieve a specific file from a deployment.

The generated .env has marked sections that map back to source files
in the config/ directory, enabling round-tripping via the save command.

Structured files (YAML, JSON) can be loaded from a deployment and
optionally deep-merged with a local override layer.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import click
import yaml

from .output import error, ok, warn


def _env_lines_to_dict(content: str) -> Dict[str, str]:
    """Parse KEY=VALUE lines into a dict, skipping comments and blanks.

    Surrounding quotes on values are stripped (both single and double).
    """
    result: Dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        result[key] = value
    return result


# ---------------------------------------------------------------------------
# Structured-file helpers (YAML / JSON deep merge)
# ---------------------------------------------------------------------------

_YAML_SUFFIXES = {".yaml", ".yml"}
_JSON_SUFFIXES = {".json"}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *override* into a copy of *base*.

    Override values win at the leaf level.  Nested dicts are merged
    recursively; all other types are replaced outright.
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_file_content(path: Path, sops_config: Optional[Path]) -> str:
    """Read a file, auto-decrypting if SOPS-encrypted."""
    if _is_sops_encrypted(path):
        content = _decrypt_sops(path, sops_config)
        if content is None:
            error(f"failed to decrypt {path}")
            sys.exit(1)
        return content
    return path.read_text()


def _parse_structured(text: str, suffix: str) -> Dict[str, Any]:
    """Parse text as YAML or JSON based on *suffix*."""
    if suffix in _YAML_SUFFIXES:
        return yaml.safe_load(text) or {}
    if suffix in _JSON_SUFFIXES:
        return json.loads(text)
    error(f"cannot merge files with suffix '{suffix}' — only .yaml, .yml, and .json are supported")
    sys.exit(1)


def _serialize_structured(data: Dict[str, Any], suffix: str) -> str:
    """Serialize a dict back to YAML or JSON."""
    if suffix in _YAML_SUFFIXES:
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
    if suffix in _JSON_SUFFIXES:
        return json.dumps(data, indent=2) + "\n"
    error(f"cannot serialize to suffix '{suffix}'")
    sys.exit(1)


def _is_sops_encrypted(filepath: Path) -> bool:
    """Return True if *filepath* appears to be SOPS-encrypted.

    Detection heuristic: SOPS adds a ``sops`` metadata key to JSON and
    YAML files, and a ``sops_`` prefix to dotenv/ini-style files.  We
    check for the presence of these markers in the raw file content.
    """
    try:
        text = filepath.read_text()
    except OSError:
        return False
    # JSON / YAML: top-level "sops" key written by sops
    if '"sops"' in text or "\nsops:\n" in text or text.startswith("sops:\n"):
        return True
    # dotenv / ini: sops stores metadata as sops_version=, sops_mac=, etc.
    if "sops_version=" in text or "sops_mac=" in text:
        return True
    return False


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


def _secrets_companion(filename: str) -> str:
    """Return the secrets companion filename.

    ``app.yaml`` → ``app.secrets.yaml``,
    ``config.json`` → ``config.secrets.json``.
    """
    p = Path(filename)
    return f"{p.stem}.secrets{p.suffix}"


def _load_structured_with_secrets(
    dir_path: Path,
    filename: str,
    suffix: str,
    sops_config: Path,
) -> Optional[Dict[str, Any]]:
    """Load a structured file from *dir_path*, merging its secrets companion.

    Returns the parsed dict with secrets overlaid, or None if the main
    file does not exist.
    """
    main_path = dir_path / filename
    if not main_path.exists():
        return None

    text = _read_file_content(main_path, sops_config)
    data = _parse_structured(text, suffix)

    # Check for secrets companion and merge if present
    companion_name = _secrets_companion(filename)
    companion_path = dir_path / companion_name
    if companion_path.exists():
        sec_text = _read_file_content(companion_path, sops_config)
        sec_data = _parse_structured(sec_text, suffix)
        data = _deep_merge(data, sec_data)

    return data


def load_file(
    deployment: Optional[str],
    local: Optional[str],
    filename: str,
    config_dir: Path,
    output: Optional[Path],
    to_stdout: bool,
) -> None:
    """Load a single file from a deployment or local directory.

    Resolves the file path(s):
      - With only *deployment*: ``config/{deployment}/{filename}``
      - With only *local*: ``config/local/{local}/{filename}``
      - With both: deep-merges the deployment file (base) with the local
        file (override).  Supported for YAML and JSON only.

    Secrets companion files (e.g. ``app.secrets.yaml``) are automatically
    detected, decrypted, and merged on top of the main file.

    For merge mode the layering order is:
      1. Deploy public file (base)
      2. Deploy secrets companion (overlay)
      3. Local override file (overlay)
      4. Local secrets companion (overlay)

    Writes to *output* (defaulting to ``./{filename}``) or prints to
    stdout when *to_stdout* is True.
    """
    if not deployment and not local:
        error("--deploy or --local is required with --file")
        sys.exit(1)

    sops_config = config_dir / "sops.yaml"
    suffix = Path(filename).suffix.lower()

    if deployment and local:
        # Merge mode: deployment base + local override (4-layer)
        if suffix not in _YAML_SUFFIXES and suffix not in _JSON_SUFFIXES:
            error(f"cannot merge '{suffix}' files — only .yaml, .yml, and .json are supported")
            sys.exit(1)

        deploy_dir = config_dir / deployment
        local_dir = config_dir / "local" / local

        deploy_data = _load_structured_with_secrets(deploy_dir, filename, suffix, sops_config)
        if deploy_data is None:
            error(f"deployment file not found: {deploy_dir / filename}")
            sys.exit(1)

        local_data = _load_structured_with_secrets(local_dir, filename, suffix, sops_config)
        if local_data is not None:
            merged = _deep_merge(deploy_data, local_data)
        else:
            warn(f"local file not found: {local_dir / filename} — using deployment file only")
            merged = deploy_data

        content = _serialize_structured(merged, suffix)

    elif suffix in _YAML_SUFFIXES or suffix in _JSON_SUFFIXES:
        # Single structured file — load with secrets companion
        if local:
            dir_path = config_dir / "local" / local
        else:
            dir_path = config_dir / deployment

        data = _load_structured_with_secrets(dir_path, filename, suffix, sops_config)
        if data is None:
            error(f"file not found: {dir_path / filename}")
            sys.exit(1)

        content = _serialize_structured(data, suffix)

    else:
        # Non-structured file — raw load
        if local:
            source = config_dir / "local" / local / filename
        else:
            source = config_dir / deployment / filename

        if not source.exists():
            error(f"file not found: {source}")
            sys.exit(1)

        content = _read_file_content(source, sops_config)

    if to_stdout:
        click.echo(content, nl=False)
    else:
        dest = output if output else Path(filename)
        dest.write_text(content)
        ok(f"Written to {dest}")


def _read_env_layers(
    deployment: str,
    local: Optional[str],
    config_dir: Path,
) -> tuple:
    """Read the four .env layers and return their raw contents.

    Returns ``(sops_config, public_text, secrets_text, local_public_text, local_secrets_text)``.
    Missing layers return empty strings.
    """
    sops_config = config_dir / "sops.yaml"

    deploy_env = config_dir / deployment / "public.env"
    if not deploy_env.exists():
        error(f"deployment config file not found: {deploy_env}")
        sys.exit(1)

    public_text = deploy_env.read_text().strip()

    secrets_text = ""
    secrets_env = config_dir / deployment / "secrets.env"
    if secrets_env.exists():
        decrypted = _decrypt_sops(secrets_env, sops_config)
        if decrypted and decrypted.strip():
            secrets_text = decrypted.strip()
    else:
        warn(f"secrets file not found: {secrets_env} — secrets section will be empty")

    local_public_text = ""
    local_secrets_text = ""
    if local:
        local_env = config_dir / "local" / local / "public.env"
        if local_env.exists():
            local_public_text = local_env.read_text().strip()
        else:
            warn(f"local config file not found: {local_env} — public-local section will be empty")

        secrets_local = config_dir / "local" / local / "secrets.env"
        if secrets_local.exists():
            decrypted = _decrypt_sops(secrets_local, sops_config)
            if decrypted and decrypted.strip():
                local_secrets_text = decrypted.strip()

    return sops_config, public_text, secrets_text, local_public_text, local_secrets_text


def load_config(
    deployment: str,
    local: Optional[str],
    config_dir: Path,
    output: Optional[Path],
    to_stdout: bool = False,
    fmt: str = "env",
    flat: bool = False,
) -> None:
    """Assemble config source files into a single .env, JSON, or YAML file.

    Reads from:
      - config/{deployment}/public.env            (public deployment config)
      - config/{deployment}/secrets.env           (SOPS-encrypted secrets)
      - config/local/{local}/public.env           (public local overrides, optional)
      - config/local/{local}/secrets.env          (encrypted local secrets, optional)

    When *fmt* is ``"env"`` (default), writes a .env with marked sections
    that enable round-tripping via the save command.

    When *fmt* is ``"json"`` or ``"yaml"``, writes a structured file with
    top-level keys for each deployment/local name and ``public``/``secrets``
    sub-keys.  A ``_dotconfig`` metadata key records the deployment and
    local names for round-tripping.

    When *flat* is True (requires ``"json"`` or ``"yaml"``), all layers are
    merged into a single flat dict (last-write-wins).

    Default output filenames: ``.env``, ``.env.json``, or ``.env.yaml``.

    When *to_stdout* is True the assembled content is printed to stdout
    instead of being written to a file.
    """
    _, public_text, secrets_text, local_public_text, local_secrets_text = (
        _read_env_layers(deployment, local, config_dir)
    )

    if fmt in ("json", "yaml"):
        # ---- Structured output ----
        public_dict = _env_lines_to_dict(public_text)
        secrets_dict = _env_lines_to_dict(secrets_text)
        local_public_dict = _env_lines_to_dict(local_public_text)
        local_secrets_dict = _env_lines_to_dict(local_secrets_text)

        if flat:
            result: Any = {}
            result.update(public_dict)
            result.update(secrets_dict)
            result.update(local_public_dict)
            result.update(local_secrets_dict)
        else:
            result = {
                "_dotconfig": {"deploy": deployment},
                deployment: {
                    "public": public_dict,
                    "secrets": secrets_dict,
                },
            }
            if local:
                result["_dotconfig"]["local"] = local
                result[local] = {
                    "public": local_public_dict,
                    "secrets": local_secrets_dict,
                }

        if fmt == "json":
            assembled = json.dumps(result, indent=2) + "\n"
            default_output = Path(".env.json")
        else:
            assembled = yaml.dump(result, default_flow_style=False, sort_keys=False)
            default_output = Path(".env.yaml")
    else:
        # ---- Classic .env output ----
        parts: list = []

        parts.append(f"# CONFIG_DEPLOY={deployment}")
        if local:
            parts.append(f"# CONFIG_LOCAL={local}")
        parts.append("")

        parts.append(f"#@dotconfig: public ({deployment})")
        if public_text:
            parts.append(public_text)

        parts.append("")
        parts.append(f"#@dotconfig: secrets ({deployment})")
        if secrets_text:
            parts.append(secrets_text)

        if local:
            parts.append("")
            parts.append(f"#@dotconfig: public-local ({local})")
            if local_public_text:
                parts.append(local_public_text)

            parts.append("")
            parts.append(f"#@dotconfig: secrets-local ({local})")
            if local_secrets_text:
                parts.append(local_secrets_text)

        assembled = "\n".join(parts) + "\n"
        default_output = Path(".env")

    if to_stdout:
        click.echo(assembled, nl=False)
    else:
        dest = output if output else default_output
        dest.write_text(assembled)
        ok(f"Written to {dest}")
