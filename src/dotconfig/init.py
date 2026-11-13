"""
Init command: create the config directory structure and set up age keys.

Creates the standard dotconfig directory layout under config/ and
optionally configures SOPS age encryption by discovering an existing
age private key and updating .sops.yaml.

Also creates empty env files for the ``dev`` and ``prod`` deployments and
for the current OS user.  Running ``init`` more than once is safe: existing
files are left untouched.
"""

import getpass
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Union

import yaml

from .userconfig import KeyEntry
from .output import created, error, heading, info, ok, updated, warn
from .versioning import seed_version_from_sources

# Path regexes used in sops.yaml creation_rules.
# sops resolves paths relative to the sops.yaml's directory, so these
# patterns must NOT include a "config/" prefix. SOPS uses Go's RE2, which
# has no lookahead — so we exclude `public.env` via a separate first rule
# (no age recipients) rather than baking the negation into one regex.
# First rule: matches `public.env` anywhere under the tree. No age keys
# means SOPS won't encrypt these files (and dotconfig never asks it to).
_SOPS_PUBLIC_PATH_REGEX = r"(^|/)public\.env$"
# Second rule: catch-all for everything dotconfig submits to sops.
_SOPS_ENCRYPT_PATH_REGEX = r".+"

# Matches a valid age secret key line.
_AGE_SECRET_KEY_RE = re.compile(r"^AGE-SECRET-KEY-[A-Za-z0-9]+$")

# Default deployment environments created on first init.
_DEFAULT_ENVS = ["dev", "prod"]


def _extract_secret_key(text: str) -> Optional[str]:
    """Return the first valid ``AGE-SECRET-KEY-…`` line from *text*, or None."""
    for line in text.splitlines():
        line = line.strip()
        if _AGE_SECRET_KEY_RE.match(line):
            return line
    return None


def _read_key_from_file(path: Path) -> Optional[str]:
    """Read a key file and return the first age secret key found, or None."""
    try:
        return _extract_secret_key(path.read_text())
    except OSError:
        return None


def _is_age_installed() -> bool:
    """Return True if the ``age`` toolchain (age-keygen) is on PATH."""
    try:
        subprocess.run(
            ["age-keygen", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _generate_age_key() -> Optional[str]:
    """Generate a new age keypair and save it to the standard location.

    Creates ``~/.config/sops/age/keys.txt`` with a freshly generated
    keypair.  Returns the secret key string, or ``None`` on failure.
    """
    key_file = Path.home() / ".config" / "sops" / "age" / "keys.txt"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["age-keygen", "-o", str(key_file)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(
                f"  Warning: age-keygen failed: {result.stderr.strip()}",
                file=sys.stderr,
            )
            return None
        # age-keygen prints the public key to stderr; read the secret from file
        return _read_key_from_file(key_file)
    except FileNotFoundError:
        return None


def _discover_age_key() -> Optional[str]:
    """Discover the age secret key following SOPS priority order.

    Priority:
      1. ``SOPS_AGE_KEY`` env var — inline secret key string
      2. ``SOPS_AGE_KEY_FILE`` env var — path to a key file
      3. ``~/.config/sops/age/keys.txt`` — standard default location

    Returns the raw ``AGE-SECRET-KEY-…`` string, or ``None`` if not found.
    """
    # 1. Inline secret key
    inline = os.environ.get("SOPS_AGE_KEY", "")
    if inline:
        key = _extract_secret_key(inline)
        if key:
            return key

    # 2. Key file pointed to by environment variable
    key_file_env = os.environ.get("SOPS_AGE_KEY_FILE", "")
    if key_file_env:
        key = _read_key_from_file(Path(key_file_env))
        if key:
            return key

    # 3. Standard default location
    default_key_file = Path.home() / ".config" / "sops" / "age" / "keys.txt"
    if default_key_file.exists():
        key = _read_key_from_file(default_key_file)
        if key:
            return key

    return None


def _derive_public_key(secret_key: str) -> Optional[str]:
    """Derive the age public key from *secret_key* by running ``age-keygen -y``.

    Returns the ``age1…`` public key string, or ``None`` on failure.
    """
    try:
        result = subprocess.run(
            ["age-keygen", "-y"],
            input=secret_key,
            capture_output=True,
            text=True,
            check=True,
        )
        pub = result.stdout.strip()
        return pub if pub else None
    except FileNotFoundError:
        print(
            "Warning: age-keygen not found — cannot derive public key",
            file=sys.stderr,
        )
        return None
    except subprocess.CalledProcessError as e:
        print(
            f"Warning: age-keygen failed: {e.stderr.strip()}",
            file=sys.stderr,
        )
        return None


def _clean_label(label: Optional[str]) -> Optional[str]:
    """Make *label* safe for a trailing YAML comment.

    Newlines and other whitespace runs collapse to a single space. A ``#``
    is harmless inside a comment (parsing takes everything after the first
    ``#`` that follows the key), so it is kept. Empty results become None.
    """
    if label is None:
        return None
    cleaned = " ".join(str(label).split())
    return cleaned or None


_KEY_COMMENT_RE = re.compile(r"(age1[0-9a-z]+)[\"',\s]*#\s*(.*?)\s*$")


def _rule_age_candidates(rule: dict) -> List[str]:
    """Return raw age strings from one creation rule (all forms)."""
    sources = [rule.get("age")]
    groups = rule.get("key_groups")
    if isinstance(groups, list):
        for g in groups:
            if isinstance(g, dict):
                sources.append(g.get("age"))
    out: List[str] = []
    for age in sources:
        if not age:
            continue
        if isinstance(age, str):
            out.extend(re.split(r"[,\s]+", age.strip()))
        elif isinstance(age, list):
            for item in age:
                if isinstance(item, str):
                    out.extend(re.split(r"[,\s]+", item.strip()))
    return out


def _parse_sops_keys(content: str) -> List[KeyEntry]:
    """Return ``(key, label)`` pairs from sops.yaml *content*, in order.

    Reads block-scalar, inline string, list and ``key_groups`` forms.
    Labels come from a trailing ``# label`` comment on the key's line
    (found with a line scanner, since YAML loaders drop comments).
    Duplicates are dropped, preserving first-seen order.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    rules = data.get("creation_rules") or []
    if not isinstance(rules, list):
        return []

    labels = {}
    for line in content.splitlines():
        m = _KEY_COMMENT_RE.search(line)
        if m and m.group(1) not in labels:
            labels[m.group(1)] = _clean_label(m.group(2))

    entries: List[KeyEntry] = []
    seen: set = set()
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        for c in _rule_age_candidates(rule):
            c = c.strip().rstrip(",")
            if c.startswith("age1") and c not in seen:
                seen.add(c)
                entries.append((c, labels.get(c)))
    return entries


def _collect_age_keys(content: str) -> List[str]:
    """Return all age public keys found in sops.yaml *content*, in order."""
    return [k for k, _ in _parse_sops_keys(content)]


def _merge_key_entries(
    existing: List[KeyEntry], supplied: List[KeyEntry]
) -> List[KeyEntry]:
    """Merge *supplied* entries into *existing*, preserving order.

    Existing keys keep their position; a supplied non-None label overrides,
    otherwise the existing label is kept. New keys are appended.
    """
    merged = {k: lbl for k, lbl in existing}
    order = [k for k, _ in existing]
    for k, lbl in supplied:
        if k not in merged:
            order.append(k)
            merged[k] = _clean_label(lbl)
        elif _clean_label(lbl) is not None:
            merged[k] = _clean_label(lbl)
    return [(k, merged[k]) for k in order]


def _render_sops_yaml(age_keys: List[Union[str, KeyEntry]]) -> str:
    """Render the canonical two-rule sops.yaml in ``key_groups`` form.

    Rule 1 matches ``public.env`` and has no recipients (sops will refuse
    to encrypt files matching it — but dotconfig never asks it to).
    Rule 2 is the catch-all with one key group whose ``age`` list holds
    every recipient, each with an optional trailing ``# label`` comment.
    Items are plain key strings or ``(key, label)`` pairs.
    """
    lines = [
        "creation_rules:",
        f"  - path_regex: '{_SOPS_PUBLIC_PATH_REGEX}'",
        f"  - path_regex: '{_SOPS_ENCRYPT_PATH_REGEX}'",
        "    key_groups:",
        "      - age:",
    ]
    for item in age_keys:
        key, label = (item, None) if isinstance(item, str) else item
        label = _clean_label(label)
        lines.append(f"          - {key}" + (f"  # {label}" if label else ""))
    return "\n".join(lines) + "\n"


def _has_encrypted_files(config_dir: Path) -> bool:
    """Return True if any file under *config_dir* is SOPS-encrypted."""
    from .load import _is_sops_encrypted

    for p in sorted(config_dir.rglob("*")):
        if p.name == "sops.yaml" or not p.is_file():
            continue
        if _is_sops_encrypted(p):
            return True
    return False


def _short(key: str) -> str:
    return key if len(key) <= 20 else f"{key[:12]}...{key[-6:]}"


def _describe(key: str, label: Optional[str]) -> str:
    return f"{label} ({_short(key)})" if label else _short(key)


def _update_sops_yaml(
    config_dir: Path,
    public_key: str,
    quiet: bool = False,
    extra_keys: Optional[List[KeyEntry]] = None,
) -> bool:
    """Create or refresh ``sops.yaml`` in *config_dir*.

    The local *public_key* and every entry in *extra_keys* (the user
    config's labeled keys) are merged into the existing recipients.
    Existing keys and labels are never removed; where both sides carry a
    label the supplied (user config) label wins. The file is always
    rewritten in canonical ``key_groups`` form, but if the canonical
    content is already on disk it is left untouched.

    Returns True if the set of recipient keys changed (a key was added), so
    the caller can tell the user to re-encrypt. Label-only changes return
    False.
    """
    sops_yaml = config_dir / "sops.yaml"
    if sops_yaml.exists():
        existing = sops_yaml.read_text()
        old = _parse_sops_keys(existing)
    else:
        existing = None
        old = []
    old_keys = {k for k, _ in old}

    supplied: List[KeyEntry] = [(public_key, None)] + list(extra_keys or [])
    keys = _merge_key_entries(old, supplied)
    added = [(k, lbl) for k, lbl in keys if k not in old_keys]
    new_content = _render_sops_yaml(keys)

    if existing == new_content:
        if not quiet:
            ok(f"{sops_yaml} (already up to date)")
        return False

    sops_yaml.write_text(new_content)
    if not quiet:
        if existing is None:
            created(f"{sops_yaml}")
        else:
            updated(f"{sops_yaml}")
        for k, lbl in added:
            info(f"added key: {_describe(k, lbl)}")
        if not added:
            info(f"refreshed creation_rules (preserved {len(keys)} key(s))")
    return bool(added)


_AGENTS_MD_CONTENT = """\
# config/ — dotconfig managed environment configuration

This directory is managed by [dotconfig](https://github.com/ericbusboom/dotconfig),
an environment configuration cascade manager for `.env` files.

## Quick reference

```bash
# Initialise (creates this directory structure + age encryption setup)
dotconfig init

# Load config into .env (assembles layers into a single file)
dotconfig load dev yourname         # dev deployment + local overrides
dotconfig load prod                 # prod only, no local overrides
dotconfig load dev prod alice bob   # stacked deploys + locals
dotconfig load -d dev -l yourname   # legacy flag form (still supported)

# Save .env edits back to source files
dotconfig save                      # round-trip to whatever was loaded
dotconfig save dev                  # flatten the assembly into config/dev/

# Load/save a specific file
dotconfig load -d dev --file app.yaml --stdout
dotconfig save -d dev --file app.yaml
```

## Directory layout

```
config/
  sops.yaml                    # SOPS encryption rules
  dev/
    public.env                 # Public config for "dev"
    secrets.env                # SOPS-encrypted secrets for "dev"
  prod/
    public.env                 # Public config for "prod"
    secrets.env                # SOPS-encrypted secrets for "prod"
  local/
    <username>/
      public.env               # Per-developer public overrides
      secrets.env              # Per-developer encrypted secrets (optional)
```

## How it works

`dotconfig load` assembles a single `.env` from four layers in
last-write-wins order:

1. `config/{deploy}/public.env` — shared public config
2. `config/{deploy}/secrets.env` — shared SOPS-encrypted secrets
3. `config/local/{user}/public.env` — personal public overrides
4. `config/local/{user}/secrets.env` — personal encrypted secrets (optional)

The generated `.env` contains marked sections (`#@dotconfig: public (dev)`, etc.)
so `dotconfig save` can round-trip edits back to the correct source files.

## Important notes

- **Do not edit `.env` section markers** — they are used for round-tripping.
- **`.env` is generated** — add it to `.gitignore`. The source of truth is
  this `config/` directory.
- **Secrets files are SOPS-encrypted** — use `dotconfig save` (not manual
  sops commands) to re-encrypt after editing `.env`.
- Deployment names are open-ended: dev, prod, test, staging, ci, etc.
"""


_GITIGNORE_PATTERNS = [
    "# dotconfig — assembled env files contain decrypted secrets",
    ".env",
    ".env.*",
    "!.env.example",
]


def _update_gitignore(config_dir: Path, quiet: bool = False) -> None:
    """Create or update ``.gitignore`` in the project root with env patterns.

    Appends only patterns that are not already present.  The project root
    is assumed to be the parent of *config_dir*.
    """
    gitignore = config_dir.parent / ".gitignore"

    if gitignore.exists():
        existing = gitignore.read_text()
        existing_lines = set(existing.splitlines())
        missing = [p for p in _GITIGNORE_PATTERNS if p not in existing_lines]
        if not missing:
            if not quiet:
                ok(str(gitignore))
            return
        # Ensure we start on a new line
        if existing and not existing.endswith("\n"):
            existing += "\n"
        gitignore.write_text(existing + "\n".join(missing) + "\n")
        if not quiet:
            updated(str(gitignore))
    else:
        gitignore.write_text("\n".join(_GITIGNORE_PATTERNS) + "\n")
        if not quiet:
            created(str(gitignore))


def _update_gitattributes(config_dir: Path, quiet: bool = False) -> None:
    """Pin LF line endings for the config directory in ``.gitattributes``.

    Git on Windows (``core.autocrlf=true``) otherwise checks files out with
    CRLF, which breaks sops decryption of dotenv/ini files.
    """
    gitattributes = config_dir.parent / ".gitattributes"
    line = f"{config_dir.name}/** text eol=lf"
    header = "# dotconfig — sops files must keep LF line endings (Windows checkouts)"

    if gitattributes.exists():
        existing = gitattributes.read_text()
        if line in existing.splitlines():
            if not quiet:
                ok(str(gitattributes))
            return
        if existing and not existing.endswith("\n"):
            existing += "\n"
        gitattributes.write_text(existing + header + "\n" + line + "\n")
        if not quiet:
            updated(str(gitattributes))
    else:
        gitattributes.write_text(header + "\n" + line + "\n")
        if not quiet:
            created(str(gitattributes))


def _write_agents_md(config_dir: Path, quiet: bool = False) -> None:
    """Write an AGENTS.md file into *config_dir* explaining dotconfig usage.

    If the file already exists it is overwritten, since it is generated
    content that should stay in sync with the current version of dotconfig.
    """
    agents_md = config_dir / "AGENTS.md"
    if agents_md.exists():
        existing = agents_md.read_text()
        if existing == _AGENTS_MD_CONTENT:
            if not quiet:
                ok(str(agents_md))
            return
        agents_md.write_text(_AGENTS_MD_CONTENT)
        if not quiet:
            updated(str(agents_md))
    else:
        agents_md.write_text(_AGENTS_MD_CONTENT)
        if not quiet:
            created(str(agents_md))


def _get_current_user() -> str:
    """Return the current OS username."""
    return getpass.getuser()


def _create_env_if_missing(path: Path, quiet: bool = False) -> None:
    """Create an empty .env file at *path* if it does not already exist.

    Prints a ``created`` message on creation or ``ok`` if the file is
    already present.
    """
    if not path.exists():
        path.write_text("")
        if not quiet:
            created(str(path))
    else:
        if not quiet:
            ok(str(path))


def _init_dotconfig_yaml(
    config_dir: Path, project_root: Path, quiet: bool = False
) -> None:
    """Create ``config/dotconfig.yaml`` if it does not already exist.

    Mirrors the ``_create_env_if_missing`` pattern: if the file is already
    present it is left untouched and an ``ok`` message is printed (unless
    *quiet*).  When the file is absent it is created with a seeded version
    drawn from (in priority order):

    1. ``<project_root>/package.json`` — the ``version`` field.
    2. ``<project_root>/pyproject.toml`` — ``version = "..."`` under
       ``[project]``.
    3. ``"0.0.0"`` — fallback when neither file exists.
    """
    path = config_dir / "dotconfig.yaml"
    if path.exists():
        if not quiet:
            ok(str(path))
        return

    # --- Seed version ---
    seed = seed_version_from_sources(project_root) or "0.0.0"

    path.write_text(
        "# dotconfig project metadata.\n"
        "# Edit `version` only via `dotconfig version bump`.\n"
        f"version: {seed}\n",
        encoding="utf-8",
    )
    if not quiet:
        created(str(path))


def _init_env_files(config_dir: Path, current_user: str, quiet: bool = False) -> None:
    """Create empty env files for default deployments and the current user.

    Creates the following files if they do not already exist (empty):

      - ``config/dev/public.env``
      - ``config/dev/secrets.env``
      - ``config/prod/public.env``
      - ``config/prod/secrets.env``
      - ``config/local/<current_user>/public.env``
      - ``config/local/<current_user>/secrets.env``

    Subdirectories are created automatically if they do not already exist.
    On every run, existing files are left completely untouched.
    """
    if not quiet:
        heading("📁 Environment files:")

    for env_name in _DEFAULT_ENVS:
        env_dir = config_dir / env_name
        env_dir.mkdir(parents=True, exist_ok=True)
        _create_env_if_missing(env_dir / "public.env", quiet=quiet)
        _create_env_if_missing(env_dir / "secrets.env", quiet=quiet)

    local_user_dir = config_dir / "local" / current_user
    local_user_dir.mkdir(parents=True, exist_ok=True)
    _create_env_if_missing(local_user_dir / "public.env", quiet=quiet)
    _create_env_if_missing(local_user_dir / "secrets.env", quiet=quiet)


def init_config(config_dir: Path, quiet: bool = False) -> None:
    """Initialise the dotconfig directory structure.

    Creates the two standard top-level directories under *config_dir*:

    * ``config/``
    * ``config/local/``

    Then creates empty env files (and their parent directories) for the
    ``dev`` and ``prod`` deployments and for the current OS user:

    * ``config/dev/public.env``, ``config/dev/secrets.env``
    * ``config/prod/public.env``, ``config/prod/secrets.env``
    * ``config/local/<user>/public.env``, ``config/local/<user>/secrets.env``

    Running ``init`` more than once is safe: existing files are always left
    completely untouched.

    After directory and env-file setup, the command attempts to discover an
    existing age private key (following SOPS key-discovery priority order),
    derives the corresponding public key, and ensures that key is listed in
    ``sops.yaml`` inside *config_dir*.  If no key is found, guidance is
    printed instead.

    When *quiet* is ``True``, all output is suppressed and interactive
    prompts are auto-answered "yes".  On error (age not installed or key
    generation failed) ``sys.exit(1)`` is called.
    """
    if not quiet:
        heading("📦 Initialising dotconfig:")

    dirs = [
        config_dir,
        config_dir / "local",
    ]

    for d in dirs:
        if d.exists():
            if d.is_dir():
                if not quiet:
                    ok(f"{d}/")
            else:
                if not quiet:
                    warn(f"{d} exists but is not a directory")
        else:
            d.mkdir(parents=True, exist_ok=True)
            if not quiet:
                created(f"{d}/")

    # ---- Env-file setup ----------------------------------------
    current_user = _get_current_user()
    _init_env_files(config_dir, current_user, quiet=quiet)

    # ---- Project metadata (dotconfig.yaml) --------------------------------
    if not quiet:
        heading("📌 Project metadata:")
    _init_dotconfig_yaml(config_dir, config_dir.parent, quiet=quiet)

    # ---- AGENTS.md -------------------------------------------------------
    if not quiet:
        heading("📄 Agent documentation:")
    _write_agents_md(config_dir, quiet=quiet)

    # ---- .gitignore ------------------------------------------------------
    if not quiet:
        heading("📝 Updating .gitignore:")
    _update_gitignore(config_dir, quiet=quiet)
    _update_gitattributes(config_dir, quiet=quiet)

    # ---- Key setup --------------------------------------------------------
    if not quiet:
        heading("🔑 Setting up age encryption key:")

    secret_key = _discover_age_key()
    default_key_file = Path.home() / ".config" / "sops" / "age" / "keys.txt"

    if secret_key is None:
        if not _is_age_installed():
            if quiet:
                sys.exit(1)
            error("age is not installed.")
            info("Install it from: https://github.com/FiloSottile/age#installation")
            info("Then re-run: dotconfig init")
            return

        # age is installed but no key was found — explain and ask
        if quiet:
            answer = "y"
        else:
            warn("No age key found. Looked in:")
            info("  1. SOPS_AGE_KEY environment variable")
            info("  2. SOPS_AGE_KEY_FILE environment variable")
            info(f"  3. {default_key_file}")
            print()
            answer = input(
                f"  Generate a new key at {default_key_file}? [Y/n] "
            ).strip().lower()
        if answer and answer not in ("y", "yes"):
            info("Skipping key setup. Re-run dotconfig init after configuring your key.")
            return

        secret_key = _generate_age_key()
        if secret_key is None:
            if quiet:
                sys.exit(1)
            error("Failed to generate age key.")
            return
        if not quiet:
            created(f"key at {default_key_file}")
        source = str(default_key_file)
    else:
        # Report where the existing key was found
        if os.environ.get("SOPS_AGE_KEY", ""):
            source = "SOPS_AGE_KEY (environment variable)"
        elif os.environ.get("SOPS_AGE_KEY_FILE", ""):
            source = f"SOPS_AGE_KEY_FILE ({os.environ['SOPS_AGE_KEY_FILE']})"
        else:
            source = str(default_key_file)
    if not quiet:
        ok(f"key: {source}")

    public_key = _derive_public_key(secret_key)
    if public_key is None:
        if not quiet:
            warn("Could not derive public key — skipping sops.yaml update")
        return

    if not quiet:
        info(f"public key: {public_key}")

    # ---- User config (listed public keys) ---------------------------------
    from . import paths
    from .userconfig import load_public_keys, seed_user_config

    uc_path, uc_source = paths.user_config_path_and_source()
    if seed_user_config(public_key, uc_path):
        if not quiet:
            created(f"user config {uc_path} (seeded with your key)")
            info("edit it to change labels or add teammates' public keys")
    elif not quiet:
        ok(f"user config: {uc_path} ({uc_source})")
    extra_keys = load_public_keys(uc_path)

    if not quiet:
        heading("📝 Updating sops.yaml:")
    changed = _update_sops_yaml(
        config_dir, public_key, quiet=quiet, extra_keys=extra_keys
    )
    if changed and not quiet and _has_encrypted_files(config_dir):
        warn(
            "recipients changed but existing encrypted files were not "
            "re-encrypted; run `dotconfig reencrypt` to apply the new keys"
        )
