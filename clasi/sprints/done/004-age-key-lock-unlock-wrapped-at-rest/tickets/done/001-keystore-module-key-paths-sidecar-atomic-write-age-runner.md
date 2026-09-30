---
id: '001'
title: 'keystore module: key paths, sidecar, atomic write, age runner'
status: done
use-cases:
- SUC-001
- SUC-002
- SUC-003
- SUC-005
depends-on: []
github-issue: ''
issue: age-key-lock-unlock.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# keystore module: key paths, sidecar, atomic write, age runner

## Description

New leaf module `src/dotconfig/keystore.py`: the single owner of the on-disk layout of the plain key, wrapped files and sidecar, and of every call to `age`/plugins. Foundation for all other tickets. Never touches the real key in tests.

## Acceptance Criteria

- [x] `key_path()` resolves `$SOPS_AGE_KEY_FILE`, defaulting to `~/.config/sops/age/keys.txt`
- [x] `wrapped_path(method_id)` returns `<keyfile>.<method>.age`; sidecar path is `<keyfile>.lock.yaml`
- [x] Sidecar load/save round-trips the issue's YAML schema (`public_key`, `methods[]` with file, kind, recipient, label, verified, hint); written atomically; contains no secret; missing sidecar loads as empty
- [x] `write_plain_key()` writes via temp file in the same directory (0600) + `os.replace`, creates the directory if missing, never writes elsewhere, never prints the key; warns if the directory is group/world readable
- [x] `public_key_of(secret)` derives via `age-keygen -y`
- [x] Age runner: encrypt to recipient, encrypt with passphrase (age prompts on TTY), decrypt with identity file / plugin identity, all through one subprocess seam that tests can substitute; missing `age`/plugin raises an error with the install command
- [x] Shared `LockedKeyError`/exit-code constant 75 defined here or in a tiny constants spot importable by keyguard

## Testing

- **Existing tests to run**: scope to touched modules (e.g. `uv run pytest tests/test_keys.py tests/test_key.py`)
- **New tests to write**: New `tests/test_keystore.py` using tmp_path and a temp `SOPS_AGE_KEY_FILE`, plain `age-keygen` identities (skip if age absent): path derivation, sidecar round trip, atomic 0600 write (mode, no leftover temp files), dir-permission warning, missing-plugin message.
- **Constraints**: tests must use a temp `SOPS_AGE_KEY_FILE`, never the real key.
- **Verification command**: `uv run pytest <scoped tests>`
