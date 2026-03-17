"""
Audit command: scan config/ for unencrypted secrets at rest.

Walks the config directory looking for files that contain values whose
key names suggest they are secrets (tokens, passwords, API keys, etc.)
but are stored in plaintext rather than SOPS-encrypted.

Uses two detection strategies:
  1. Key-name heuristics for .env files (regex match on the variable name).
  2. detect-secrets library for structured files (YAML, JSON, etc.).
"""

import re
from pathlib import Path
from typing import List, NamedTuple, Optional

from .output import error, heading, info, ok, warn


# ---------------------------------------------------------------------------
# Key-name patterns that indicate a value is a secret
# ---------------------------------------------------------------------------

_SECRET_KEY_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"secret",
        r"password",
        r"passwd",
        r"pwd",
        r"token",
        r"api[_-]?key",
        r"auth[_-]?key",
        r"private[_-]?key",
        r"priv[_-]?key",
        r"access[_-]?key",
        r"client[_-]?secret",
        r"session[_-]?key",
        r"session[_-]?secret",
        r"encryption[_-]?key",
        r"signing[_-]?key",
        r"hmac",
        r"bearer",
        r"credential",
    )
]

# SOPS markers that indicate a value is already encrypted
_SOPS_ENC_PATTERN = re.compile(r"^ENC\[")


class Finding(NamedTuple):
    """A single audit finding — an unencrypted secret at rest."""
    file: Path
    line: int
    key: str
    reason: str


def _key_looks_secret(key: str) -> Optional[str]:
    """Return a reason string if *key* matches a secret-like pattern, else None."""
    for pat in _SECRET_KEY_PATTERNS:
        if pat.search(key):
            return f"key name matches '{pat.pattern}'"
    return None


def _value_is_encrypted(value: str) -> bool:
    """Return True if *value* appears to be SOPS-encrypted."""
    return bool(_SOPS_ENC_PATTERN.match(value.strip()))


# ---------------------------------------------------------------------------
# .env scanner
# ---------------------------------------------------------------------------

def _scan_env_file(path: Path) -> List[Finding]:
    """Scan a .env file for key names that look secret with plaintext values."""
    findings: List[Finding] = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not value:
            continue
        reason = _key_looks_secret(key)
        if reason and not _value_is_encrypted(value):
            findings.append(Finding(file=path, line=lineno, key=key, reason=reason))
    return findings


# ---------------------------------------------------------------------------
# Structured file scanner (YAML, JSON) via detect-secrets
# ---------------------------------------------------------------------------

def _scan_structured_file(path: Path) -> List[Finding]:
    """Scan a YAML or JSON file for secrets using detect-secrets.

    Uses only pattern-based detectors (not entropy) to avoid false positives.
    """
    try:
        from detect_secrets import SecretsCollection
        from detect_secrets.settings import transient_settings
    except ImportError:
        return []

    from .save import _DETECT_SECRETS_SETTINGS

    secrets = SecretsCollection()
    with transient_settings(_DETECT_SECRETS_SETTINGS):
        secrets.scan_file(str(path))

    findings: List[Finding] = []
    for _filename, secret_list in secrets.data.items():
        for s in secret_list:
            findings.append(Finding(
                file=path,
                line=s.line_number,
                key=s.type,
                reason=f"detect-secrets: {s.type}",
            ))
    return findings


# ---------------------------------------------------------------------------
# SOPS-encrypted file detection (skip these entirely)
# ---------------------------------------------------------------------------

def _is_sops_file(path: Path) -> bool:
    """Return True if the file is SOPS-encrypted (whole-file encryption)."""
    try:
        text = path.read_text()
    except OSError:
        return False
    if '"sops"' in text or "\nsops:\n" in text or text.startswith("sops:\n"):
        return True
    if "sops_version=" in text or "sops_mac=" in text:
        return True
    return False


# ---------------------------------------------------------------------------
# Directory walker
# ---------------------------------------------------------------------------

_STRUCTURED_SUFFIXES = {".yaml", ".yml", ".json"}
_ENV_SUFFIXES = {".env"}
_SKIP_NAMES = {"sops.yaml", "AGENTS.md"}


def audit_config_dir(config_dir: Path) -> List[Finding]:
    """Walk *config_dir* and return all audit findings.

    Scans .env files with key-name heuristics and structured files
    (YAML, JSON) with detect-secrets.  Skips files that are already
    SOPS-encrypted at the whole-file level.
    """
    findings: List[Finding] = []

    if not config_dir.is_dir():
        return findings

    for path in sorted(config_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in _SKIP_NAMES:
            continue
        if _is_sops_file(path):
            continue

        suffix = path.suffix.lower()
        if suffix in _ENV_SUFFIXES:
            findings.extend(_scan_env_file(path))
        elif suffix in _STRUCTURED_SUFFIXES:
            findings.extend(_scan_structured_file(path))

    return findings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_audit(config_dir: Path) -> bool:
    """Run the secrets audit and print results.

    Returns True if the audit is clean (no findings), False otherwise.
    """
    findings = audit_config_dir(config_dir)

    if not findings:
        ok("No unencrypted secrets detected")
        return True

    heading("⚠️  UNENCRYPTED SECRETS DETECTED")
    for f in findings:
        try:
            rel = f.file.relative_to(Path.cwd())
        except ValueError:
            rel = f.file
        warn(f"{rel}:{f.line}  {f.key}  ({f.reason})")

    info("")
    info("These values look like secrets but are stored in plaintext.")
    info("Move them to a secrets.env file and use SOPS encryption,")
    info("or save with: dotconfig save -d <deploy> --file <name> --encrypt")

    return False
