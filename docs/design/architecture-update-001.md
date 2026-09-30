---
sprint: "001"
status: complete
---

# Architecture Update -- Sprint 001: Key Management System and GitHub Secrets Sync

## What Changed

- **New module `src/dotconfig/key.py`**: Key management logic — generate,
  save, get, pub, list, rm, send. Uses subprocess for ssh-keygen,
  ssh-copy-id, and SOPS encrypt/decrypt from existing helpers.
- **New module `src/dotconfig/gh_push.py`**: GitHub secrets sync — loads
  deployment secrets via existing `load_config` internals, pushes each
  via `gh secret set`.
- **Modified `src/dotconfig/cli.py`**: Replace flat `keys` command with
  `key` command group. Add `gh-push` command.
- **New storage**: `config/keys/` directory for SOPS-encrypted private
  keys and plaintext public keys.

## Why

Keys have different lifecycle requirements than config values — generation,
permission management, public key derivation, and distribution to remote
hosts. GitHub secrets sync eliminates manual multi-step `gh secret set`
workflows.

## Impact on Existing Components

- `dotconfig keys` command is replaced by `dotconfig key` group. The
  existing age key status display moves to `dotconfig key list` or is
  shown as part of the key listing.
- Existing SOPS helpers in load.py/save.py are reused for key encryption.
- No changes to config/ layout for non-key files.

## Migration Concerns

- Users who script `dotconfig keys` will need to update to `dotconfig key list`.
  Since this is a pre-1.0 project, this is acceptable.
