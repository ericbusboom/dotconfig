---
id: '002'
title: dotconfig key wrap with round-trip verification
status: done
use-cases:
- SUC-001
depends-on:
- '001'
github-issue: ''
issue: age-key-lock-unlock.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# dotconfig key wrap with round-trip verification

## Description

`dotconfig key wrap`: reads the plain key and writes `<keyfile>.<method>.age` for `--se`, `--recipient age1... --label ...`, `--yubikey`, `--passphrase`, updates the sidecar, and proves each new file opens (human-present round trip) and yields the sidecar's `public_key`. New logic in `keywrap.py`; thin command in `cli.py` under the `key` group.

## Acceptance Criteria

- [x] Writes one file per requested method and a sidecar entry with kind/recipient/label
- [x] Round trip is performed for each new file; result's public key must equal `public_key`; on success `verified:` is set to today's date
- [x] A failing file is deleted and reported, exit non-zero; other methods are unaffected
- [x] An existing wrapped file is only replaced after the replacement is written to a temp name and verified (never replace a working file with an unverified one)
- [x] Refuses if the plain key is missing (suggests unlock) or sidecar `public_key` differs from the plain key
- [x] Missing plugin reports the install command; plain key is never modified
- [x] Identity round trip uses `--identity FILE` for kind `identity`

## Testing

- **Existing tests to run**: scope to touched modules (e.g. `uv run pytest tests/test_keys.py tests/test_key.py`)
- **New tests to write**: Tests in `tests/test_keywrap.py` with plain age identities standing in for plugins via the runner seam; passphrase via pty harness (or seam stub for the prompt). Cases: success, failed verification deletes file, no overwrite with unverified, mismatched key, add second method preserves first.
- **Constraints**: tests must use a temp `SOPS_AGE_KEY_FILE`, never the real key.
- **Verification command**: `uv run pytest <scoped tests>`
