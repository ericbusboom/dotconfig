---
id: '001'
title: Key command group with gen, save, get, pub, list, rm
status: todo
use-cases: [SUC-001]
depends-on: []
github-issue: ''
todo: key-management-system.md
---

# Key command group with gen, save, get, pub, list, rm

## Description

Create `src/dotconfig/key.py` with key management logic and register
`dotconfig key` as a Click command group in cli.py with subcommands:
gen, save, get, pub, list, rm. Replace the existing flat `keys` command.

Keys are stored in `config/keys/` — private keys SOPS-encrypted,
public keys plaintext.

## Acceptance Criteria

- [ ] `dotconfig key gen <name>` generates keypair (ed25519 default, --type for rsa/ecdsa)
- [ ] `dotconfig key save <file>` imports existing key, encrypts, stores; auto-grabs .pub
- [ ] `dotconfig key get <name>` decrypts and prints private key to stdout
- [ ] `dotconfig key pub <name>` prints public key (from .pub or derived)
- [ ] `dotconfig key list` shows all keys with metadata
- [ ] `dotconfig key rm <name>` removes key and .pub
- [ ] Private keys are SOPS-encrypted at rest
- [ ] File permissions set to 600 on private key extraction

## Testing

- **Existing tests to run**: `uv run pytest tests/test_keys.py`
- **New tests to write**: `tests/test_key.py` — unit tests for each subcommand with mocked subprocess
- **Verification command**: `uv run pytest`
