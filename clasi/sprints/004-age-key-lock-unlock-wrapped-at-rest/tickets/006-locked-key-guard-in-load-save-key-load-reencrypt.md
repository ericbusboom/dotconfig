---
id: '006'
title: Locked-key guard in load, save, key load, reencrypt
status: open
use-cases: ["SUC-006"]
depends-on: ["001", "003"]
github-issue: ''
issue: age-key-lock-unlock.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Locked-key guard in load, save, key load, reencrypt

## Description

New leaf module `keyguard.py` with `require_unlocked()`: detects 'plain key missing, wrapped copies present' (and no `SOPS_AGE_KEY` set) before sops is called, prints `age key is locked — run: dotconfig unlock`, exits 75. On an interactive TTY it offers to run unlock inline. Wire into the entry points that invoke sops: `load_config`/`load_file`, `save` paths, `key load`/`get`, `reencrypt_all`. Must run before `_decrypt_sops`/`_encrypt_sops` because those turn sops errors into warnings.

## Acceptance Criteria

- [ ] Locked + non-interactive: exact message, exit code 75, sops never invoked
- [ ] Locked + TTY: prompt to unlock inline; on success the command proceeds, on decline exits 75
- [ ] Unlocked, not wrapped (no sidecar), or `SOPS_AGE_KEY` set: no behavior change
- [ ] `keyguard` imports only `keystore`/`output` (no import cycle with load/save)
- [ ] Guard wired into load, save, key load/get, reencrypt; commands that don't touch sops are unaffected

## Testing

- **Existing tests to run**: scope to touched modules (e.g. `uv run pytest tests/test_keys.py tests/test_key.py`)
- **New tests to write**: `tests/test_keyguard.py` plus additions to `tests/test_load.py`, `test_save.py`, `test_key.py`, `test_reencrypt.py` asserting exit 75 and mocked sops not called, using temp `SOPS_AGE_KEY_FILE`.
- **Constraints**: tests must use a temp `SOPS_AGE_KEY_FILE`, never the real key.
- **Verification command**: `uv run pytest <scoped tests>`
