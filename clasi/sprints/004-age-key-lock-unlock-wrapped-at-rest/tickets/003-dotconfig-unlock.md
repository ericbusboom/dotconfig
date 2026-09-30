---
id: '003'
title: dotconfig unlock
status: open
use-cases: ["SUC-002", "SUC-005"]
depends-on: ["001", "002"]
github-issue: ''
issue: age-key-lock-unlock.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# dotconfig unlock

## Description

`dotconfig unlock [--with METHOD] [--identity FILE] [--paste]`: restores the plain key for a session after a human proves presence, decrypting to memory, checking the public key, and writing atomically. Command in `cli.py`, logic in `keywrap.py`.

## Acceptance Criteria

- [ ] Already unlocked and matching `public_key`: prints so, exit 0
- [ ] Default order: se (GUI session only) -> yubikey (plugin + device present) -> passphrase; passphrase not auto-picked in a GUI session unless earlier methods unavailable/fail; remaining methods listed on failure
- [ ] `--with` selects a method; `--identity FILE` decrypts an `identity`-kind file; `--paste` reads `AGE-SECRET-KEY-1...` with no echo and only from a real TTY, used in memory only
- [ ] No passphrase flag, env var, or piped secret input exists; `--paste` without a TTY errors
- [ ] Public-key mismatch against sidecar: nothing written, exit non-zero
- [ ] Plain key written only to `$SOPS_AGE_KEY_FILE` via `write_plain_key` (0600, atomic); directory created if missing; nothing on stdout/logs
- [ ] Works with no sidecar if `--identity`/`--paste` supplies a key matching an existing wrapped file's manual `age -d` (degraded mode, warns)

## Testing

- **Existing tests to run**: scope to touched modules (e.g. `uv run pytest tests/test_keys.py tests/test_key.py`)
- **New tests to write**: Tests in `tests/test_unlock.py`: default order with stubbed GUI/device detection, `--with`, mismatch, already-unlocked, paste with pty and non-TTY rejection, 0600 and atomicity, passphrase file via pty harness. Temp key file only.
- **Constraints**: tests must use a temp `SOPS_AGE_KEY_FILE`, never the real key.
- **Verification command**: `uv run pytest <scoped tests>`
