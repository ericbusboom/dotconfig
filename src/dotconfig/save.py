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
from .load import _env_lines_to_dict
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


def _content_has_secrets(content: str) -> bool:
    """Return True if raw file content contains secret patterns.

    Scans line by line using detect-secrets pattern-based plugins.
    Catches private keys (``-----BEGIN``), embedded tokens, etc.
    """
    try:
        from detect_secrets.core.scan import scan_line
        from detect_secrets.settings import transient_settings

        with transient_settings(_DETECT_SECRETS_SETTINGS):
            for line in content.splitlines():
                if any(True for _ in scan_line(line)):
                    return True
    except ImportError:
        pass

    # Also check for common private key headers directly
    if "-----BEGIN" in content and "PRIVATE KEY" in content:
        return True

    return False


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


def _extract_age_recipients(sops_config: Optional[Path]) -> Optional[str]:
    """Extract the age recipient public keys from sops.yaml.

    Returns the comma-separated public key string, or None if not found.
    """
    if sops_config is None or not sops_config.exists():
        return None
    try:
        data = yaml.safe_load(sops_config.read_text())
        if not data or "creation_rules" not in data:
            return None
        for rule in data["creation_rules"]:
            age = rule.get("age", "").strip()
            if age:
                return age
        return None
    except Exception:
        return None


def _encrypt_sops(
    content: str, filepath: Path, sops_config: Optional[Path] = None
) -> bool:
    """Encrypt content with SOPS and save to filepath.

    Writes plaintext content to *filepath*, then encrypts it in-place
    with sops.  Returns True on success.

    If *sops_config* is provided and exists, it is passed to sops via
    ``--config`` so that a non-dotfile ``sops.yaml`` inside the config
    directory is found even when it would not be auto-discovered.

    If the creation rules don't match the filename, falls back to
    passing the age recipient key directly via ``--age``.
    """
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content)

        # Use a relative path so sops path_regex matching works correctly.
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
            # If creation rules didn't match, retry with --age directly
            if "no matching creation rules" in result.stderr:
                age_keys = _extract_age_recipients(sops_config)
                if age_keys:
                    # Re-write plaintext (sops may have corrupted it)
                    filepath.write_text(content)
                    cmd_retry = [
                        "sops", "--encrypt", "--in-place",
                        "--age", age_keys,
                        str(sops_filepath),
                    ]
                    retry = subprocess.run(
                        cmd_retry,
                        capture_output=True,
                        text=True,
                    )
                    if retry.returncode == 0:
                        return True
                    warn(f"sops encryption failed for {filepath}: {retry.stderr.strip()}")
                else:
                    warn(f"sops encryption failed for {filepath}: {result.stderr.strip()}")
            else:
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


def _parse_env_layers(
    content: str,
) -> Tuple[List[str], List[str], Dict[str, str]]:
    """Parse a dotconfig-generated .env into multi-layer metadata + sections.

    Recognised metadata keys (in priority order — first match wins per type):

      - ``# CONFIG_DEPLOYS=<csv>``   → list of deployments (new, multi-layer)
      - ``# CONFIG_DEPLOY=<value>``  → single deployment (legacy)
      - ``# CONFIG_COMMON=<value>``  → single deployment (very-legacy alias)
      - ``# CONFIG_LOCALS=<csv>``    → list of locals (new, multi-layer)
      - ``# CONFIG_LOCAL=<value>``   → single local (legacy)

    Returns ``(deployments, locals, sections)`` where the lists are empty
    when no metadata is present.
    """
    deployments: Optional[List[str]] = None
    locals_: Optional[List[str]] = None
    sections: Dict[str, str] = {}
    current_section: Optional[str] = None
    current_lines: List[str] = []

    for line in content.splitlines():
        # ---- Metadata keys (deployments) ----
        if line.startswith("# CONFIG_DEPLOYS="):
            csv = line.split("=", 1)[1].strip()
            deployments = [v.strip() for v in csv.split(",") if v.strip()]
            continue
        if line.startswith("# CONFIG_DEPLOY=") and deployments is None:
            deployments = [line.split("=", 1)[1].strip()]
            continue
        if line.startswith("# CONFIG_COMMON=") and deployments is None:
            deployments = [line.split("=", 1)[1].strip()]
            continue

        # ---- Metadata keys (locals) ----
        if line.startswith("# CONFIG_LOCALS="):
            csv = line.split("=", 1)[1].strip()
            locals_ = [v.strip() for v in csv.split(",") if v.strip()]
            continue
        if line.startswith("# CONFIG_LOCAL=") and locals_ is None:
            locals_ = [line.split("=", 1)[1].strip()]
            continue

        # ---- Section markers ----
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

    return deployments or [], locals_ or [], sections


def parse_env_file(
    content: str,
) -> Tuple[Optional[str], Optional[str], Dict[str, str]]:
    """Parse a dotconfig-generated .env file (back-compat single-layer view).

    Extracts:
      - The first deployment from ``CONFIG_DEPLOYS`` / ``CONFIG_DEPLOY`` /
        legacy ``CONFIG_COMMON`` (whichever is present)
      - The first local from ``CONFIG_LOCALS`` / ``CONFIG_LOCAL``
      - A dict mapping section labels to their variable content

    Section labels are the strings after ``#@dotconfig:`` markers,
    e.g. ``"public (dev)"``, ``"secrets (dev)"``, ``"public-local (alice)"``.

    Also recognises the legacy ``# --- label ---`` format for backward
    compatibility.
    """
    deployments, locals_, sections = _parse_env_layers(content)
    deployment = deployments[0] if deployments else None
    local_name = locals_[0] if locals_ else None
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
                error(f"REFUSED: secrets detected but encryption failed for {companion_path}")
                error("will not write secrets unencrypted — fix SOPS configuration")
                # Remove the public file too — incomplete save is worse than no save
                dest.unlink(missing_ok=True)
                sys.exit(1)
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
                error(f"REFUSED: secrets detected but encryption failed for {companion_path}")
                error("will not write secrets unencrypted — fix SOPS configuration")
                dest.unlink(missing_ok=True)
                sys.exit(1)
            return

    # For unrecognised formats, scan the raw content for secret patterns.
    # This catches things like private key files (-----BEGIN RSA PRIVATE KEY-----).
    if _content_has_secrets(data_content):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if _encrypt_sops(data_content, dest, sops_config):
            ok(f"→ {dest} 🔒 (secret content detected)")
        else:
            error(f"REFUSED: secret content detected but encryption failed for {dest}")
            error("will not write secrets unencrypted — fix SOPS configuration")
            sys.exit(1)
        return

    # No secrets found — write as-is
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


def _dict_to_env_lines(data: Dict[str, Any]) -> str:
    """Convert a flat dict to KEY=VALUE lines."""
    lines = []
    for key, value in data.items():
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n" if lines else ""


def _save_config_structured(
    env_file: Path,
    config_dir: Path,
    override_deploy: Optional[str],
    override_local: Optional[str],
    fmt: str,
    flat: bool,
) -> None:
    """Save a structured (JSON/YAML) config file back to config/ sources.

    Handles both sectioned format (with ``_dotconfig`` metadata and
    deployment/local top-level keys) and flat format (plain key-value dict
    matched against existing source files).
    """
    content = env_file.read_text()
    if fmt == "json":
        data = json.loads(content)
    else:
        data = yaml.safe_load(content) or {}

    sops_config = config_dir / "sops.yaml"
    saved: List[Tuple[str, str]] = []

    if flat:
        # Flat mode: match each key to the source file that currently owns it.
        deployment = override_deploy
        local_name = override_local

        if not deployment:
            error("-d/--deploy is required when saving flat format")
            sys.exit(1)

        # Read existing layers to find key ownership
        existing: Dict[str, Dict[str, str]] = {}
        layer_order = ["public", "secrets"]
        paths = {
            "public": config_dir / deployment / "public.env",
            "secrets": config_dir / deployment / "secrets.env",
        }

        if local_name:
            layer_order += ["local_public", "local_secrets"]
            paths["local_public"] = config_dir / "local" / local_name / "public.env"
            paths["local_secrets"] = config_dir / "local" / local_name / "secrets.env"

        for layer_name in layer_order:
            p = paths[layer_name]
            if not p.exists():
                existing[layer_name] = {}
                continue
            if "secrets" in layer_name:
                from .load import _decrypt_sops
                decrypted = _decrypt_sops(p, sops_config)
                existing[layer_name] = _env_lines_to_dict(decrypted) if decrypted else {}
            else:
                existing[layer_name] = _env_lines_to_dict(p.read_text())

        # Match keys to most-specific existing layer (reverse order)
        unmatched = []
        for key, value in data.items():
            matched = False
            for layer_name in reversed(layer_order):
                if key in existing[layer_name]:
                    existing[layer_name][key] = str(value)
                    matched = True
                    break
            if not matched:
                unmatched.append(key)

        if unmatched:
            error(f"cannot save new keys in flat mode (no section info): {', '.join(unmatched)}")
            sys.exit(1)

        # Write back modified layers
        for layer_name in layer_order:
            if not existing[layer_name]:
                continue
            p = paths[layer_name]
            env_content = _dict_to_env_lines(existing[layer_name])
            p.parent.mkdir(parents=True, exist_ok=True)

            if "secrets" in layer_name:
                if _encrypt_sops(env_content, p, sops_config):
                    saved.append((f"{layer_name} 🔒", str(p)))
                else:
                    warn(f"could not encrypt {layer_name}")
            else:
                p.write_text(env_content)
                saved.append((layer_name, str(p)))

    else:
        # Sectioned mode: _dotconfig metadata maps sections to source files
        meta = data.get("_dotconfig", {})
        deployment = override_deploy or meta.get("deploy")
        local_name = override_local or meta.get("local")

        if not deployment:
            error(
                "no deployment found — provide -d/--deploy or "
                "include _dotconfig.deploy in the file"
            )
            sys.exit(1)

        save_deploy = override_deploy if override_deploy else deployment
        save_local = override_local if override_local else local_name

        # Deployment sections
        deploy_data = data.get(meta.get("deploy", deployment), {})
        public_dict = deploy_data.get("public", {})
        secrets_dict = deploy_data.get("secrets", {})

        if public_dict:
            p = config_dir / save_deploy / "public.env"
            env_content = _dict_to_env_lines(public_dict)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(env_content)
            saved.append(("public config", str(p)))

        if secrets_dict:
            p = config_dir / save_deploy / "secrets.env"
            env_content = _dict_to_env_lines(secrets_dict)
            p.parent.mkdir(parents=True, exist_ok=True)
            if _encrypt_sops(env_content, p, sops_config):
                saved.append(("secrets 🔒", str(p)))
            else:
                warn(f"could not encrypt secrets for {save_deploy}")

        # Local sections
        source_local = meta.get("local")
        if source_local and source_local in data:
            local_data = data[source_local]
            local_public_dict = local_data.get("public", {})
            local_secrets_dict = local_data.get("secrets", {})

            if local_public_dict:
                p = config_dir / "local" / save_local / "public.env"
                env_content = _dict_to_env_lines(local_public_dict)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(env_content)
                saved.append(("public-local config", str(p)))

            if local_secrets_dict:
                p = config_dir / "local" / save_local / "secrets.env"
                env_content = _dict_to_env_lines(local_secrets_dict)
                p.parent.mkdir(parents=True, exist_ok=True)
                if _encrypt_sops(env_content, p, sops_config):
                    saved.append(("secrets-local 🔒", str(p)))
                else:
                    warn(f"could not encrypt local secrets for {save_local}")

    if saved:
        heading("💾 Saved:")
        for label, path in saved:
            ok(f"{label} → {path}")

        from .audit import run_audit
        run_audit(config_dir)
    else:
        warn("Nothing saved.")


def _to_layer_list(value) -> list:
    """Normalize a deployment/local arg into an ordered list of names.

    Mirrors ``dotconfig.load._to_layer_list`` so callers can pass either
    a string (legacy single-value form), a list (new multi-layer form),
    or ``None`` (no value).
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _merge_section_bodies(bodies: list) -> str:
    """Merge multiple ``KEY=VAL`` section bodies in last-wins order.

    Single-source bodies (or one non-empty among many) pass through
    verbatim, preserving comments and ordering.  When multiple non-empty
    bodies are present, they are parsed to dicts and merged last-wins,
    losing comments — this is acceptable because multi-layer flatten is
    an explicit user request (``save <name>`` against a stacked load).
    """
    nonempty = [b for b in bodies if b]
    if not nonempty:
        return ""
    if len(nonempty) == 1:
        return nonempty[0]
    merged: Dict[str, str] = {}
    for body in nonempty:
        merged.update(_env_lines_to_dict(body))
    return "\n".join(f"{k}={v}" for k, v in merged.items())


def save_config(
    env_file: Path,
    config_dir: Path,
    override_deploy=None,
    override_local=None,
    fmt: str = "env",
    flat: bool = False,
) -> None:
    """Save .env sections back to the config/ source files.

    Reads layer metadata from the .env header (``CONFIG_DEPLOYS`` /
    ``CONFIG_LOCALS`` for stacked loads, or legacy ``CONFIG_DEPLOY`` /
    ``CONFIG_LOCAL`` / ``CONFIG_COMMON`` singletons), then writes each
    section back to its source file:

      - public ({deployment})         -> config/{deployment}/public.env
      - secrets ({deployment})        -> config/{deployment}/secrets.env  (SOPS-encrypted)
      - public-local ({local})        -> config/local/{local}/public.env
      - secrets-local ({local})       -> config/local/{local}/secrets.env (SOPS-encrypted)

    *override_deploy* and *override_local* may be strings (single dest),
    lists of length 0 or 1, or ``None``.  When supplied, the override is
    a single destination name into which all matching source layers are
    flattened (last-wins merge for multi-layer .env files; pass-through
    for single-layer .env files, preserving comments).  More than one
    override of either type is rejected.

    When the override deploy differs from the loaded layers, the inline
    ``DEPLOYMENT=`` variable in every section body is rewritten to the
    new target — matching the historical single-layer override behavior.

    If SOPS_AGE_KEY_FILE is found inside the .env, it is added to the
    current process environment before invoking sops.
    """
    if not env_file.exists():
        error(f"{env_file} does not exist")
        sys.exit(1)

    override_deploys = _to_layer_list(override_deploy)
    override_locals = _to_layer_list(override_local)

    if len(override_deploys) > 1:
        error("save accepts at most one destination deployment name")
        sys.exit(1)
    if len(override_locals) > 1:
        error("save accepts at most one destination local name")
        sys.exit(1)

    # Auto-detect format from file extension when not explicitly set
    if fmt == "env":
        suffix = env_file.suffix.lower()
        if suffix == ".json":
            fmt = "json"
        elif suffix in (".yaml", ".yml"):
            fmt = "yaml"

    if fmt != "env":
        _save_config_structured(
            env_file,
            config_dir,
            override_deploys[0] if override_deploys else None,
            override_locals[0] if override_locals else None,
            fmt,
            flat,
        )
        return

    content = env_file.read_text()

    # Extract SOPS key path from the file itself before any section parsing
    # so that sops can be invoked correctly when the variable is stored there.
    for line in content.splitlines():
        if line.startswith("SOPS_AGE_KEY_FILE="):
            key_file = line.split("=", 1)[1].strip()
            os.environ.setdefault("SOPS_AGE_KEY_FILE", key_file)
            break

    deployments, locals_, sections = _parse_env_layers(content)

    if not deployments:
        error("CONFIG_DEPLOY not found in .env — is this a dotconfig-managed file?")
        sys.exit(1)

    # Apply DEPLOYMENT= rewrite when the override changes the destination.
    # Matches historical single-layer behavior (rewrites every section,
    # including local ones) — extends naturally to multi-layer flatten.
    if override_deploys and deployments != [override_deploys[0]]:
        target = override_deploys[0]
        for key in sections:
            sections[key] = _rewrite_deployment(sections[key], target)

    sops_config = config_dir / "sops.yaml"
    saved: list = []

    # ---- Deployment sections ----
    if override_deploys:
        save_deploy = override_deploys[0]
        public_body = _merge_section_bodies(
            [sections.get(f"public ({d})", "") for d in deployments]
        )
        secrets_body = _merge_section_bodies(
            [sections.get(f"secrets ({d})", "") for d in deployments]
        )
        any_public = any(f"public ({d})" in sections for d in deployments)
        if any_public:
            public_file = config_dir / save_deploy / "public.env"
            public_file.parent.mkdir(parents=True, exist_ok=True)
            public_file.write_text(public_body + "\n" if public_body else "")
            saved.append(("public config", str(public_file)))
        if secrets_body:
            secrets_file = config_dir / save_deploy / "secrets.env"
            secrets_file.parent.mkdir(parents=True, exist_ok=True)
            if _encrypt_sops(secrets_body + "\n", secrets_file, sops_config):
                saved.append(("secrets 🔒", str(secrets_file)))
            else:
                warn(f"could not encrypt secrets for {save_deploy}")
    else:
        for d in deployments:
            public_key = f"public ({d})"
            if public_key in sections:
                public_file = config_dir / d / "public.env"
                public_file.parent.mkdir(parents=True, exist_ok=True)
                body = sections[public_key]
                public_file.write_text(body + "\n" if body else "")
                saved.append(("public config", str(public_file)))
            secrets_key = f"secrets ({d})"
            if secrets_key in sections:
                body = sections[secrets_key]
                if body:
                    secrets_file = config_dir / d / "secrets.env"
                    secrets_file.parent.mkdir(parents=True, exist_ok=True)
                    if _encrypt_sops(body + "\n", secrets_file, sops_config):
                        saved.append(("secrets 🔒", str(secrets_file)))
                    else:
                        warn(f"could not encrypt secrets for {d}")

    # ---- Local sections ----
    if locals_:
        if override_locals:
            save_local = override_locals[0]
            public_body = _merge_section_bodies(
                [sections.get(f"public-local ({l})", "") for l in locals_]
            )
            secrets_body = _merge_section_bodies(
                [sections.get(f"secrets-local ({l})", "") for l in locals_]
            )
            any_public = any(
                f"public-local ({l})" in sections for l in locals_
            )
            if any_public:
                local_file = config_dir / "local" / save_local / "public.env"
                local_file.parent.mkdir(parents=True, exist_ok=True)
                local_file.write_text(public_body + "\n" if public_body else "")
                saved.append(("public-local config", str(local_file)))
            if secrets_body:
                secrets_local_file = (
                    config_dir / "local" / save_local / "secrets.env"
                )
                secrets_local_file.parent.mkdir(parents=True, exist_ok=True)
                if _encrypt_sops(secrets_body + "\n", secrets_local_file, sops_config):
                    saved.append(("secrets-local 🔒", str(secrets_local_file)))
                else:
                    warn(f"could not encrypt local secrets for {save_local}")
        else:
            for l in locals_:
                local_key = f"public-local ({l})"
                if local_key in sections:
                    body = sections[local_key]
                    local_file = config_dir / "local" / l / "public.env"
                    local_file.parent.mkdir(parents=True, exist_ok=True)
                    local_file.write_text(body + "\n" if body else "")
                    saved.append(("public-local config", str(local_file)))
                secrets_local_key = f"secrets-local ({l})"
                if secrets_local_key in sections:
                    body = sections[secrets_local_key]
                    if body:
                        secrets_local_file = (
                            config_dir / "local" / l / "secrets.env"
                        )
                        secrets_local_file.parent.mkdir(parents=True, exist_ok=True)
                        if _encrypt_sops(body + "\n", secrets_local_file, sops_config):
                            saved.append(("secrets-local 🔒", str(secrets_local_file)))
                        else:
                            warn(f"could not encrypt local secrets for {l}")

    if saved:
        heading("💾 Saved:")
        for label, path in saved:
            ok(f"{label} → {path}")

        # Auto-audit for unencrypted secrets after a successful save.
        from .audit import run_audit
        run_audit(config_dir)
    else:
        warn("Nothing saved.")
