---
status: pending
---

# Key management system — `dotconfig key`

Add a dedicated subsystem for managing cryptographic keys (SSH, age, GPG, etc.)
independent of deployments. Keys are stored SOPS-encrypted in `config/keys/`.

## Motivation

Users already store SSH keys and other credentials via `dotconfig save --file`,
but keys have different requirements than config files:

- Keys have names and are their own thing, not tied to a deployment
- Private keys must always be encrypted at rest
- Public keys should be derivable from private keys
- Key generation should be built in (not requiring the user to run external tools)
- File permissions matter (SSH requires `chmod 600`)

## Proposed commands

| Command | Description |
|---|---|
| `dotconfig key gen <name>` | Generate a keypair (RSA/ed25519/ecdsa/age), encrypt private key, store both. Options: `--type`, `--bits` |
| `dotconfig key save <file>` | Import an existing key file, encrypt it, store in `config/keys/`. `--name` to override stored name. Auto-grab `.pub` companion if it exists |
| `dotconfig key get <name>` | Decrypt and print private key to stdout |
| `dotconfig key pub <name>` | Print public key (from `.pub` file, or derived from private key via `ssh-keygen -y`) |
| `dotconfig key list` | List all keys with types and public key status |
| `dotconfig key rm <name>` | Remove a key and its `.pub` |

## Storage layout

```
config/
  keys/
    deploy_rsa           # SOPS-encrypted private key
    deploy_rsa.pub       # Public key (plaintext)
    github_ed25519       # SOPS-encrypted
    github_ed25519.pub   # Plaintext
    age-recipients.txt   # Age public keys for the team
```

## Open questions

1. Fold the existing `dotconfig keys` (age key status) into this, or keep separate?
2. Per-deployment scoping (`config/keys/prod/deploy_rsa`) or flat?
3. Handle certs (`.crt`, `.ca-bundle`) alongside keys?
4. Auto `chmod 600` when writing private keys to disk?
5. Should `dotconfig save --file id_rsa` suggest `dotconfig key save` instead when it detects a private key?
6. Key rotation workflows — re-encrypt all keys with updated age recipients?
