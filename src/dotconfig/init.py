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
from typing import Optional

# Path regex used in sops.yaml creation_rules.
# Matches secrets.env (and other extensions) under any subdirectory.
# Because sops.yaml lives inside config/, sops resolves file paths relative
# to the config file's directory — so the regex must NOT include a "config/"
# prefix.
_SOPS_PATH_REGEX = r".+/secrets\.(?:env|json|yaml|yml|txt|conf)$"

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


def _add_key_to_sops_yaml(content: str, public_key: str) -> str:
    """Return *content* with *public_key* appended to the ``age:`` block.

    Handles two common formats:

    Block scalar (most common)::

        age: >-
          age1abc...,
          age1def...

    Inline value::

        age: age1abc...
    """
    lines = content.splitlines()
    result: list[str] = []
    i = 0
    inserted = False

    while i < len(lines):
        line = lines[i]

        # ---- "age: >-" block scalar format --------------------------------
        if re.match(r"^\s+age:\s*>-\s*$", line):
            result.append(line)
            i += 1
            key_lines: list[str] = []
            key_indent: Optional[int] = None

            # Collect all age key value lines that immediately follow
            while i < len(lines):
                peek = lines[i]
                stripped = peek.strip()
                if stripped and re.match(r"age1", stripped.lstrip(",")):
                    if key_indent is None:
                        key_indent = len(peek) - len(peek.lstrip())
                    key_lines.append(peek)
                    i += 1
                else:
                    break

            if key_lines:
                # Ensure the last existing key ends with a comma
                last = key_lines[-1].rstrip()
                if not last.endswith(","):
                    last += ","
                key_lines[-1] = last
                result.extend(key_lines)
                indent = key_indent if key_indent is not None else 6
            else:
                indent = 6

            result.append(" " * indent + public_key)
            inserted = True
            continue

        # ---- "age: age1..." inline format ---------------------------------
        if re.match(r"^\s+age:\s+age1", line):
            stripped = line.rstrip()
            if not stripped.endswith(","):
                stripped += ","
            result.append(stripped + public_key)
            inserted = True
            i += 1
            continue

        result.append(line)
        i += 1

    if not inserted:
        result.append(
            f"# dotconfig init: please add {public_key} to the age: field in sops.yaml"
        )

    return "\n".join(result) + "\n"


def _update_sops_yaml(config_dir: Path, public_key: str) -> None:
    """Create or update ``sops.yaml`` in *config_dir* with *public_key*.

    * If ``sops.yaml`` does not exist, a new file is created with a default
      ``creation_rules`` block covering ``config/secrets/``.
    * If it already exists and the key is already listed, nothing is changed.
    * Otherwise the key is appended to the ``age:`` list.
    """
    sops_yaml = config_dir / "sops.yaml"

    if not sops_yaml.exists():
        content = (
            "creation_rules:\n"
            f"  - path_regex: {_SOPS_PATH_REGEX}\n"
            "    age: >-\n"
            f"      {public_key}\n"
        )
        sops_yaml.write_text(content)
        print(f"  created: {sops_yaml}")
        print(f"           added public key {public_key}")
        return

    existing = sops_yaml.read_text()
    if public_key in existing:
        print(f"  ok:      {sops_yaml} (key already listed)")
        return

    updated = _add_key_to_sops_yaml(existing, public_key)
    sops_yaml.write_text(updated)
    print(f"  updated: {sops_yaml}")
    print(f"           added public key {public_key}")


def _get_current_user() -> str:
    """Return the current OS username."""
    return getpass.getuser()


def _create_env_if_missing(path: Path) -> None:
    """Create an empty .env file at *path* if it does not already exist.

    Prints a ``created`` message on creation or ``ok`` if the file is
    already present.
    """
    if not path.exists():
        path.write_text("")
        print(f"  created: {path}")
    else:
        print(f"  ok:      {path}")


def _init_env_files(config_dir: Path, current_user: str) -> None:
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
    print("\nCreating environment files:")

    for env_name in _DEFAULT_ENVS:
        env_dir = config_dir / env_name
        env_dir.mkdir(parents=True, exist_ok=True)
        _create_env_if_missing(env_dir / "public.env")
        _create_env_if_missing(env_dir / "secrets.env")

    local_user_dir = config_dir / "local" / current_user
    local_user_dir.mkdir(parents=True, exist_ok=True)
    _create_env_if_missing(local_user_dir / "public.env")
    _create_env_if_missing(local_user_dir / "secrets.env")


def init_config(config_dir: Path) -> None:
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
    """
    print("Initialising dotconfig directory structure:")

    dirs = [
        config_dir,
        config_dir / "local",
    ]

    for d in dirs:
        if d.exists():
            if d.is_dir():
                print(f"  ok:      {d}/")
            else:
                print(
                    f"  warning: {d} exists but is not a directory",
                    file=sys.stderr,
                )
        else:
            d.mkdir(parents=True, exist_ok=True)
            print(f"  created: {d}/")

    # ---- Env-file setup ----------------------------------------
    current_user = _get_current_user()
    _init_env_files(config_dir, current_user)

    # ---- Key setup --------------------------------------------------------
    print("\nSetting up age encryption key:")

    secret_key = _discover_age_key()
    if secret_key is None:
        print("  No age key found.")
        print("  To set up encryption, generate a key and re-run init:")
        print("    age-keygen -o ~/.config/sops/age/keys.txt")
        print("    dotconfig init")
        return

    # Report where the key was found
    if os.environ.get("SOPS_AGE_KEY", ""):
        source = "SOPS_AGE_KEY (environment variable)"
    elif os.environ.get("SOPS_AGE_KEY_FILE", ""):
        source = f"SOPS_AGE_KEY_FILE ({os.environ['SOPS_AGE_KEY_FILE']})"
    else:
        source = str(Path.home() / ".config" / "sops" / "age" / "keys.txt")
    print(f"  Found key in: {source}")

    public_key = _derive_public_key(secret_key)
    if public_key is None:
        print(
            "  Warning: could not derive public key — skipping sops.yaml update",
            file=sys.stderr,
        )
        return

    print(f"  Public key:   {public_key}")

    # sops.yaml lives inside config_dir
    print("\nUpdating sops.yaml:")
    _update_sops_yaml(config_dir, public_key)
