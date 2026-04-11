"""
Key management: generate, import, retrieve, list, remove, and send SSH keys.

Keys are stored in ``config/keys/`` — private keys SOPS-encrypted,
public keys in plaintext.
"""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .discover import find_config_dir
from .load import _decrypt_sops, _is_sops_encrypted
from .output import created, error, heading, info, item, ok, warn
from .save import _encrypt_sops


_KEY_TYPES = ("ed25519", "rsa", "ecdsa")


def _keys_dir(config_dir: Optional[Path] = None) -> Path:
    """Return the keys directory, creating it if needed."""
    if config_dir is None:
        config_dir = find_config_dir()
        if config_dir is None:
            config_dir = Path("config")
    keys = config_dir / "keys"
    keys.mkdir(parents=True, exist_ok=True)
    return keys


def _sops_config(config_dir: Optional[Path] = None) -> Optional[Path]:
    """Return the sops.yaml path if it exists."""
    if config_dir is None:
        config_dir = find_config_dir()
        if config_dir is None:
            config_dir = Path("config")
    cfg = config_dir / "sops.yaml"
    return cfg if cfg.exists() else None


def _find_key(keys_dir: Path, name: str) -> Optional[Path]:
    """Find a private key file by name (with or without type suffix)."""
    # Exact match
    exact = keys_dir / name
    if exact.exists() and not exact.suffix == ".pub":
        return exact
    # Glob for name_* patterns (e.g. deploy matches deploy_ed25519)
    matches = [
        p for p in keys_dir.iterdir()
        if p.stem.startswith(name) and p.suffix != ".pub" and p.is_file()
        and (p.stem == name or p.stem.startswith(name + "_"))
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        warn(f"ambiguous key name '{name}' — matches: {', '.join(p.name for p in matches)}")
        return None
    return None


def gen_key(
    name: str,
    key_type: str = "ed25519",
    bits: Optional[int] = None,
    config_dir: Optional[Path] = None,
) -> None:
    """Generate an SSH keypair, encrypt the private key, store both."""
    if key_type not in _KEY_TYPES:
        error(f"unsupported key type: {key_type} (choose from {', '.join(_KEY_TYPES)})")
        sys.exit(1)

    keys = _keys_dir(config_dir)
    sops_cfg = _sops_config(config_dir)

    key_name = f"{name}_{key_type}"
    priv_path = keys / key_name
    pub_path = keys / f"{key_name}.pub"

    if priv_path.exists() or pub_path.exists():
        error(f"key '{key_name}' already exists in {keys}")
        sys.exit(1)

    # Generate the keypair to a temp location
    cmd = ["ssh-keygen", "-t", key_type, "-f", str(priv_path), "-N", "", "-C", name]
    if key_type == "rsa" and bits:
        cmd += ["-b", str(bits)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        error("ssh-keygen not found")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        error(f"ssh-keygen failed: {e.stderr.strip()}")
        sys.exit(1)

    # Read the private key content, then encrypt it in place
    priv_content = priv_path.read_text()
    if _encrypt_sops(priv_content, priv_path, sops_cfg):
        created(f"{priv_path.name} (encrypted)")
    else:
        warn("private key saved but SOPS encryption failed — key is plaintext!")
        created(f"{priv_path.name} (plaintext)")

    created(f"{pub_path.name}")
    ok(f"generated {key_type} keypair '{key_name}'")


def save_key(
    file: Path,
    name: Optional[str] = None,
    config_dir: Optional[Path] = None,
) -> None:
    """Import an existing key file, encrypt it, store in config/keys/."""
    if not file.exists():
        error(f"file not found: {file}")
        sys.exit(1)

    keys = _keys_dir(config_dir)
    sops_cfg = _sops_config(config_dir)

    key_name = name if name else file.stem
    dest = keys / key_name

    if dest.exists():
        error(f"key '{key_name}' already exists in {keys}")
        sys.exit(1)

    # Encrypt and store private key
    content = file.read_text()
    if _encrypt_sops(content, dest, sops_cfg):
        created(f"{dest.name} (encrypted)")
    else:
        warn("SOPS encryption failed — key stored as plaintext")
        created(f"{dest.name} (plaintext)")

    # Auto-grab .pub companion if it exists
    pub_source = file.parent / f"{file.name}.pub"
    if not pub_source.exists():
        pub_source = file.parent / f"{file.stem}.pub"
    if pub_source.exists():
        pub_dest = keys / f"{key_name}.pub"
        shutil.copy2(pub_source, pub_dest)
        created(f"{pub_dest.name}")

    ok(f"saved key '{key_name}'")


def get_key(name: str, config_dir: Optional[Path] = None) -> None:
    """Decrypt and print a private key to stdout."""
    keys = _keys_dir(config_dir)
    sops_cfg = _sops_config(config_dir)

    priv = _find_key(keys, name)
    if priv is None:
        error(f"key '{name}' not found in {keys}")
        sys.exit(1)

    if _is_sops_encrypted(priv):
        content = _decrypt_sops(priv, sops_cfg)
        if content is None:
            error(f"failed to decrypt {priv}")
            sys.exit(1)
        print(content, end="")
    else:
        print(priv.read_text(), end="")


def pub_key(name: str, config_dir: Optional[Path] = None) -> None:
    """Print the public key for a named key."""
    keys = _keys_dir(config_dir)
    sops_cfg = _sops_config(config_dir)

    priv = _find_key(keys, name)
    if priv is None:
        error(f"key '{name}' not found in {keys}")
        sys.exit(1)

    pub_path = Path(str(priv) + ".pub")
    if pub_path.exists():
        print(pub_path.read_text(), end="")
        return

    # Derive from private key via ssh-keygen -y
    if _is_sops_encrypted(priv):
        content = _decrypt_sops(priv, sops_cfg)
        if content is None:
            error(f"failed to decrypt {priv}")
            sys.exit(1)
    else:
        content = priv.read_text()

    try:
        result = subprocess.run(
            ["ssh-keygen", "-y", "-f", "/dev/stdin"],
            input=content,
            capture_output=True,
            text=True,
            check=True,
        )
        print(result.stdout, end="")
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        error(f"could not derive public key: {e}")
        sys.exit(1)


def list_keys(config_dir: Optional[Path] = None) -> None:
    """List all keys in config/keys/."""
    keys = _keys_dir(config_dir)

    files = sorted(
        p for p in keys.iterdir()
        if p.is_file() and p.suffix != ".pub" and p.name != ".gitignore"
    )

    if not files:
        info("no keys found")
        return

    heading("Keys:")
    for f in files:
        pub_exists = Path(str(f) + ".pub").exists()
        encrypted = _is_sops_encrypted(f)
        status_parts = []
        if encrypted:
            status_parts.append("encrypted")
        else:
            status_parts.append("plaintext")
        if pub_exists:
            status_parts.append(".pub")
        item(f"  {f.name}  ({', '.join(status_parts)})")


def rm_key(name: str, config_dir: Optional[Path] = None) -> None:
    """Remove a key and its .pub companion."""
    keys = _keys_dir(config_dir)

    priv = _find_key(keys, name)
    if priv is None:
        error(f"key '{name}' not found in {keys}")
        sys.exit(1)

    priv.unlink()
    pub = Path(str(priv) + ".pub")
    if pub.exists():
        pub.unlink()

    ok(f"removed key '{name}'")


def send_key(
    host: str,
    key_name: Optional[str] = None,
    config_dir: Optional[Path] = None,
) -> None:
    """Send a public key to a remote host via ssh-copy-id."""
    name = key_name if key_name else host
    keys = _keys_dir(config_dir)

    priv = _find_key(keys, name)
    if priv is None:
        error(f"key '{name}' not found in {keys}")
        sys.exit(1)

    pub_path = Path(str(priv) + ".pub")
    if not pub_path.exists():
        error(f"public key not found: {pub_path}")
        info("run 'dotconfig key pub <name>' to derive one, or save a .pub file")
        sys.exit(1)

    if shutil.which("ssh-copy-id") is None:
        error("ssh-copy-id not found on PATH")
        sys.exit(1)

    info(f"sending {pub_path.name} to {host}")
    try:
        subprocess.run(
            ["ssh-copy-id", "-i", str(pub_path), host],
            check=True,
        )
        ok(f"key sent to {host}")
    except subprocess.CalledProcessError as e:
        error(f"ssh-copy-id failed (exit {e.returncode})")
        sys.exit(1)
