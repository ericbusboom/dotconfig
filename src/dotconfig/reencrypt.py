"""
Re-encrypt every SOPS-encrypted file under config/ in place.

Useful after editing ``sops.yaml`` (e.g. adding or removing an age
recipient): existing encrypted files keep their old recipient list
until they are re-encrypted against the current config.
"""

import sys
from pathlib import Path
from typing import Optional

from .load import _decrypt_sops, _is_sops_encrypted
from .output import created, error, heading, info, ok
from .save import _encrypt_sops


def reencrypt_all(config_dir: Path) -> None:
    """Walk ``config_dir`` and re-encrypt every SOPS-encrypted file in place.

    Fails fast on the first decrypt or encrypt error.
    """
    if not config_dir.is_dir():
        error(f"config dir not found: {config_dir}")
        sys.exit(1)

    sops_cfg: Optional[Path] = config_dir / "sops.yaml"
    if not sops_cfg.exists():
        sops_cfg = None

    encrypted = sorted(
        p for p in config_dir.rglob("*")
        if p.is_file() and _is_sops_encrypted(p)
    )

    if not encrypted:
        info(f"no SOPS-encrypted files found under {config_dir}")
        return

    heading(f"Re-encrypting {len(encrypted)} file(s) under {config_dir}")
    for path in encrypted:
        rel = path.relative_to(config_dir)
        plaintext = _decrypt_sops(path, sops_cfg)
        if plaintext is None:
            error(f"failed to decrypt {rel}")
            sys.exit(1)
        if not _encrypt_sops(plaintext, path, sops_cfg):
            error(f"failed to re-encrypt {rel}")
            sys.exit(1)
        created(f"{rel} 🔒")

    ok(f"re-encrypted {len(encrypted)} file(s)")
