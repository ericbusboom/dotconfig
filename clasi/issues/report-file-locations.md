---
status: pending
---

# dotconfig should report where its files are

## Problem

dotconfig reads and writes files in several places, but most commands don't
say which paths they used. When something goes wrong (wrong key, stale
`.env`, sops can't decrypt), the user has to read the source to learn where
things live.

## Locations dotconfig uses today

User-level:

- Plain age key: `$SOPS_AGE_KEY_FILE`, or `~/.config/sops/age/keys.txt`
  (`keystore.key_path()`); `SOPS_AGE_KEY` (inline) takes priority when
  discovering the key in `init`
- Wrapped key copies: `<keyfile>.<method>.age` (`keystore.wrapped_path`)
- Lock metadata sidecar: `<keyfile>.lock.yaml` (`keystore.sidecar_path`)
- SSH config written by `dotconfig key`: `~/.ssh/config`

Project-level (config root found by `discover.py`, usually `./config`):

- `config/sops.yaml`: encryption rules and age recipients
- `config/dotconfig.yaml`: project version, etc.
- `config/<deploy>/public.env` and `secrets.env`
- `config/local/<user>/public.env` and `secrets.env`
- `config/keys/`: SOPS-encrypted SSH keys
- `config/files/`: managed files
- `config/AGENTS.md`
- Project root: `.env`, `.env.json`, `.env.yaml`, `.env.secret`,
  `.gitignore`, `.gitattributes`

(The planned user config, see `user-config-public-keys.md`, adds
`~/.config/dotconfig/config.yaml`.)

## Proposed

- Add a `dotconfig where` (or `dotconfig paths`) command that prints each
  location above, the source it was resolved from (env var vs default), and
  whether it exists.
- Make `load`, `save`, `init`, `age unlock/lock` and `key` print the
  resolved paths they read and wrote (config root, key file, sops.yaml,
  output file). Use the existing `output.py` helpers, and respect
  `--quiet`.
- Include the config root and key file path in error messages, e.g. when
  decryption fails.
