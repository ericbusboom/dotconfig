"""
Save command: write .env sections back to config/ source files,
or store a specific file into a deployment.

Reads the marked sections in .env and writes each section back to its
corresponding source file in config/, re-encrypting secrets with SOPS.

Structured files (YAML, JSON) are automatically scanned for secrets.
Secret values are replaced with REDACTED in the public file and written
to a SOPS-encrypted companion file (e.g. app.secrets.yaml).
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .audit import _key_looks_secret
from .output import error, heading, info, ok, warn


# ---------------------------------------------------------------------------
# Secret detection & splitting helpers
# ---------------------------------------------------------------------------

REDACTED = "REDACTED"

_YAML_SUFFIXES = {".yaml", ".yml"}
_JSON_SUFFIXES = {".json"}
_ENV_SUFFIXES = {".env"}
_STRUCTURED_SUFFIXES = _YAML_SUFFIXES | _JSON_SUFFIXES


_DETECT_SECRETS_SETTINGS = {
    "plugins_used": [
        {"name": "AWSKeyDetector"},
        {"name": "ArtifactoryDetector"},
        {"name": "AzureStorageKeyDetector"},
        {"name": "BasicAuthDetector"},
        {"name": "CloudantDetector"},
        {"name": "DiscordBotTokenDetector"},
        {"name": "GitHubTokenDetector"},
        {"name": "GitLabTokenDetector"},
        {"name": "IbmCloudIamDetector"},
        {"name": "IbmCosHmacDetector"},
        {"name": "JwtTokenDetector"},
        {"name": "MailchimpDetector"},
        {"name": "NpmDetector"},
        {"name": "OpenAIDetector"},
        {"name": "PrivateKeyDetector"},
        {"name": "PypiTokenDetector"},
        {"name": "SendGridDetector"},
        {"name": "SlackDetector"},
        {"name": "SoftlayerDetector"},
        {"name": "SquareOAuthDetector"},
        {"name": "StripeDetector"},
        {"name": "TelegramBotTokenDetector"},
        {"name": "TwilioKeyDetector"},
    ]
}


def _is_secret_value(value: str) -> bool:
    """Return True if *value* matches known secret patterns via detect-secrets.

    Uses only pattern-based detectors (not entropy-based) to avoid false
    positives on normal config values like ``localhost`` or ``true``.
    """
    try:
        from detect_secrets.core.scan import scan_line
        from detect_secrets.settings import transient_settings

        with transient_settings(_DETECT_SECRETS_SETTINGS):
            return any(True for _ in scan_line(str(value)))
    except ImportError:
        return False


def _secrets_companion(filename: str) -> str:
    """Return the secrets companion filename.

    ``app.yaml`` → ``app.secrets.yaml``,
    ``config.json`` → ``config.secrets.json``.
    """
    p = Path(filename)
    return f"{p.stem}.secrets{p.suffix}"


def _is_leaf_secret(key: str, value: Any) -> bool:
    """Return True if a leaf key/value pair looks like a secret."""
    if isinstance(value, (dict, list)):
        return False
    return bool(_key_looks_secret(key)) or _is_secret_value(str(value))


def _count_leaves(data: dict) -> Tuple[int, int]:
    """Return ``(total_leaves, secret_leaves)`` counts."""
    total, secret = 0, 0
    for key, value in data.items():
        if isinstance(value, dict):
            t, s = _count_leaves(value)
            total += t
            secret += s
        else:
            total += 1
            if _is_leaf_secret(key, value):
                secret += 1
    return total, secret


def _split_secrets(data: dict) -> Tuple[dict, dict]:
    """Split *data* into ``(public, secrets)``.

    Secret leaf values are replaced with :data:`REDACTED` in the public
    dict.  The secrets dict preserves the nesting structure so it can be
    deep-merged back on load.
    """
    public: dict = {}
    secrets: dict = {}
    for key, value in data.items():
        if isinstance(value, dict):
            pub_child, sec_child = _split_secrets(value)
            if pub_child:
                public[key] = pub_child
            if sec_child:
                secrets[key] = sec_child
        elif _is_leaf_secret(key, value):
            public[key] = REDACTED
            secrets[key] = value
        else:
            public[key] = value
    return public, secrets


def _split_env_secrets(content: str) -> Tuple[str, str]:
    """Split ``.env`` content into ``(public_with_redacted, secrets_only)``.

    Comments and blank lines are kept in the public output.  Secret lines
    have their value replaced with ``REDACTED`` in the public output and
    appear with their real value in the secrets output.
    """
    public_lines: List[str] = []
    secret_lines: List[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            public_lines.append(line)
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if _is_leaf_secret(key, value):
            public_lines.append(f"{key}={REDACTED}")
            secret_lines.append(stripped)
        else:
            public_lines.append(line)
    pub = "\n".join(public_lines) + "\n"
    sec = "\n".join(secret_lines) + "\n" if secret_lines else ""
    return pub, sec


def _parse_structured(text: str, suffix: str) -> Dict[str, Any]:
    """Parse *text* as YAML or JSON based on *suffix*."""
    if suffix in _YAML_SUFFIXES:
        return yaml.safe_load(text) or {}
    if suffix in _JSON_SUFFIXES:
        return json.loads(text)
    error(f"unsupported structured format: '{suffix}'")
    sys.exit(1)


def _serialize_structured(data: Dict[str, Any], suffix: str) -> str:
    """Serialize *data* to YAML or JSON."""
    if suffix in _YAML_SUFFIXES:
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
    if suffix in _JSON_SUFFIXES:
        return json.dumps(data, indent=2) + "\n"
    error(f"unsupported structured format: '{suffix}'")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Dict diff helper
# ---------------------------------------------------------------------------


def _dict_diff(base: dict, modified: dict) -> dict:
    """Return only keys in *modified* that differ from *base*.

    Nested dicts are compared recursively.  Lists and scalars use
    equality — a changed list is included in its entirety.
    """
    diff: dict = {}
    for key, value in modified.items():
        if key not in base:
            diff[key] = value
        elif isinstance(value, dict) and isinstance(base[key], dict):
            sub = _dict_diff(base[key], value)
            if sub:
                diff[key] = sub
        elif value != base[key]:
            diff[key] = value
    return diff


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
      - CONFIG_DEPLOY (or legacy CONFIG_COMMON) metadata value
      - CONFIG_LOCAL metadata value (may be None)
      - A dict mapping section labels to their variable content

    Section labels are the strings after ``#@dotconfig:`` markers,
    e.g. ``"public (dev)"``, ``"secrets (dev)"``, ``"public-local (alice)"``.

    Also recognises the legacy ``# --- label ---`` format for backward
    compatibility.
    """
    deployment: Optional[str] = None
    local_name: Optional[str] = None
    sections: Dict[str, str] = {}
    current_section: Optional[str] = None
    current_lines = []

    for line in content.splitlines():
        # New metadata key
        if line.startswith("# CONFIG_DEPLOY="):
            deployment = line.split("=", 1)[1].strip()
            continue
        # Legacy metadata key
        if line.startswith("# CONFIG_COMMON="):
            deployment = line.split("=", 1)[1].strip()
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

    return deployment, local_name, sections


def _write_with_split(
    data_content: str,
    dest: Path,
    filename: str,
    config_dir: Path,
    encrypt: bool,
) -> None:
    """Write a file, auto-splitting secrets for structured and .env files.

    For structured files (YAML/JSON): if 100% of leaves are secrets the
    whole file is encrypted.  Otherwise secret values are replaced with
    ``REDACTED`` in the public file and written to a SOPS-encrypted
    companion.

    For .env files: same approach — secret lines get REDACTED values in
    the public file and real values in the companion.

    If *encrypt* is True the main file is also SOPS-encrypted (overrides
    the split — the whole thing is encrypted).
    """
    sops_config = config_dir / "sops.yaml"
    suffix = Path(filename).suffix.lower()
    companion_name = _secrets_companion(filename)
    companion_path = dest.parent / companion_name

    # --encrypt forces whole-file encryption, no split
    if encrypt:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if _encrypt_sops(data_content, dest, sops_config):
            ok(f"→ {dest} 🔒")
        else:
            error(f"encryption failed for {dest}")
            sys.exit(1)
        return

    if suffix in _STRUCTURED_SUFFIXES:
        data = _parse_structured(data_content, suffix)
        total, secret_count = _count_leaves(data)

        if total > 0 and secret_count == total:
            # 100% secrets → encrypt whole file
            dest.parent.mkdir(parents=True, exist_ok=True)
            if _encrypt_sops(data_content, dest, sops_config):
                ok(f"→ {dest} 🔒 (all values are secrets)")
            else:
                error(f"encryption failed for {dest}")
                sys.exit(1)
            return

        if secret_count > 0:
            public_data, secrets_data = _split_secrets(data)
            # Write public file with REDACTED placeholders
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(_serialize_structured(public_data, suffix))
            ok(f"→ {dest}")
            # Write encrypted secrets companion
            sec_content = _serialize_structured(secrets_data, suffix)
            if _encrypt_sops(sec_content, companion_path, sops_config):
                ok(f"→ {companion_path} 🔒")
            else:
                warn(f"could not encrypt {companion_path}")
            return

    elif suffix in _ENV_SUFFIXES:
        pub_content, sec_content = _split_env_secrets(data_content)
        if sec_content:
            # Write public file with REDACTED placeholders
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(pub_content)
            ok(f"→ {dest}")
            # Write encrypted secrets companion
            if _encrypt_sops(sec_content, companion_path, sops_config):
                ok(f"→ {companion_path} 🔒")
            else:
                warn(f"could not encrypt {companion_path}")
            return

    # No secrets found (or unrecognised format) — write as-is
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(data_content)
    ok(f"→ {dest}")


def save_file(
    deployment: Optional[str],
    local: Optional[str],
    filename: str,
    config_dir: Path,
    source: Optional[Path] = None,
    encrypt: bool = False,
) -> None:
    """Save a single file into a deployment or local directory.

    Modes:
      - Only *deployment*: save to ``config/{deployment}/{filename}``
      - Only *local*: save to ``config/local/{local}/{filename}``
      - Both *deployment* and *local* (diff-save): compare the source
        against the existing deployment file and write only the
        changed/added keys to ``config/local/{local}/{filename}``

    Structured files (YAML/JSON) and .env files are automatically scanned
    for secrets.  Secret values are replaced with REDACTED in the public
    file and stored in a SOPS-encrypted companion.

    When *encrypt* is True the entire file is SOPS-encrypted.
    """
    if not deployment and not local:
        error("--deploy or --local is required with --file")
        sys.exit(1)

    src = source if source else Path(filename)
    if not src.exists():
        error(f"source file not found: {src}")
        sys.exit(1)

    content = src.read_text()
    suffix = Path(filename).suffix.lower()

    if deployment and local:
        # Diff-save mode: compare against existing deploy file,
        # write only changed/added keys to local dir.
        if suffix not in _STRUCTURED_SUFFIXES:
            error(f"diff-save requires a structured file (.yaml, .yml, .json), got '{suffix}'")
            sys.exit(1)

        from .load import _read_file_content
        deploy_path = config_dir / deployment / filename
        if not deploy_path.exists():
            error(f"deployment file not found: {deploy_path} — save to deployment first")
            sys.exit(1)

        sops_config = config_dir / "sops.yaml"
        deploy_text = _read_file_content(deploy_path, sops_config)
        deploy_data = _parse_structured(deploy_text, suffix)
        source_data = _parse_structured(content, suffix)

        diff = _dict_diff(deploy_data, source_data)
        if not diff:
            info("no changes relative to deployment file — nothing to save")
            return

        dest = config_dir / "local" / local / filename
        diff_content = _serialize_structured(diff, suffix)
        _write_with_split(diff_content, dest, filename, config_dir, encrypt)
    else:
        # Single-target save
        if local:
            dest = config_dir / "local" / local / filename
        else:
            dest = config_dir / deployment / filename

        _write_with_split(content, dest, filename, config_dir, encrypt)


def save_config(
    env_file: Path,
    config_dir: Path,
    override_deploy: Optional[str] = None,
    override_local: Optional[str] = None,
) -> None:
    """Save .env sections back to the config/ source files.

    Reads CONFIG_DEPLOY (or legacy CONFIG_COMMON) and CONFIG_LOCAL from
    the .env metadata comments, then writes each section to its
    corresponding file:

      - public ({deployment})         -> config/{save_deploy}/public.env
      - secrets ({deployment})        -> config/{save_deploy}/secrets.env  (SOPS-encrypted)
      - public-local ({local})        -> config/local/{save_local}/public.env
      - secrets-local ({local})       -> config/local/{save_local}/secrets.env (SOPS-encrypted)

    If *override_deploy* is given it is used as the destination deployment
    (i.e. the files that are written to) instead of CONFIG_DEPLOY.  Likewise
    *override_local* overrides CONFIG_LOCAL for the destination local name.
    This allows saving a loaded .env to a *different* deployment or user,
    e.g. loading ``-d prod -l eric`` and saving as ``-d dev -l stan``.

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

    deployment, local_name, sections = parse_env_file(content)

    if not deployment:
        error("CONFIG_DEPLOY not found in .env — is this a dotconfig-managed file?")
        sys.exit(1)

    # Determine destination names: overrides take precedence over metadata.
    save_deploy = override_deploy if override_deploy is not None else deployment
    save_local = override_local if override_local is not None else local_name

    saved = []

    # When saving to a different deployment, rewrite the DEPLOYMENT variable
    # so it reflects the target environment, not the one that was loaded.
    if save_deploy != deployment:
        for key in sections:
            sections[key] = _rewrite_deployment(sections[key], save_deploy)

    # Locate the sops config file so it can be passed explicitly to sops.
    # sops.yaml is a non-dotfile and is not auto-discovered by sops, so we
    # must pass --config when invoking sops.
    sops_config = config_dir / "sops.yaml"

    # --- Public (deployment) ---
    public_key = f"public ({deployment})"
    if public_key in sections:
        public_file = config_dir / save_deploy / "public.env"
        public_file.parent.mkdir(parents=True, exist_ok=True)
        body = sections[public_key]
        public_file.write_text(body + "\n" if body else "")
        saved.append(("public config", str(public_file)))

    # --- Secrets (deployment) ---
    secrets_key = f"secrets ({deployment})"
    if secrets_key in sections:
        secrets_body = sections[secrets_key]
        if secrets_body:
            secrets_file = config_dir / save_deploy / "secrets.env"
            secrets_file.parent.mkdir(parents=True, exist_ok=True)
            if _encrypt_sops(secrets_body + "\n", secrets_file, sops_config):
                saved.append(("secrets 🔒", str(secrets_file)))
            else:
                warn(f"could not encrypt secrets for {save_deploy}")

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

        # Auto-audit for unencrypted secrets after a successful save.
        from .audit import run_audit
        run_audit(config_dir)
    else:
        warn("Nothing saved.")
