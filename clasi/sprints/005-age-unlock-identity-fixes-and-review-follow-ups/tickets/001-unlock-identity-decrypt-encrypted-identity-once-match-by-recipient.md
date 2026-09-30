---
id: '001'
title: 'unlock --identity: decrypt encrypted identity once, match by recipient'
status: open
use-cases: [SUC-001]
depends-on: []
github-issue: ''
issue: age-unlock-identity-review-findings.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# unlock --identity: decrypt encrypted identity once, match by recipient

## Description

Fix `unlock --identity FILE` (no `--with`) so an encrypted identity prompts once. See sprint.md Architecture.

Plan: in keystore.py add identity-kind detection (plugin `AGE-PLUGIN-`; encrypted `age-encryption.org/v1` or `-----BEGIN AGE ENCRYPTED FILE-----`; plain), `age_decrypt_identity_file(FILE)` (runs `age -d FILE` once, interactive, returns bytes in memory) and `age_decrypt_with_identity_bytes(wrapped, identity_bytes)` which runs `age -d -i /dev/stdin WRAPPED` with identity bytes as stdin (fallback: `/dev/fd/N` via pass_fds). Never write the identity to disk. In keywrap.unlock: encrypted -> decrypt once, `age-keygen -y` for public key, choose methods whose sidecar recipient equals it, decrypt with in-memory identity; plugin -> only se/yubikey candidates; plain -> existing behaviour. Errors: identity decrypt failure -> "identity's passphrase was wrong (or not a valid age identity)"; no match -> "identity matches no wrapped file" plus methods checked. Never try se/yubikey with a non-plugin identity. `--with NAME --identity FILE` with an encrypted FILE also uses the decrypt-once path. Update `unlock --help` (cli.py) to mention `--with recovery --identity FILE` for the USB-drive case. Files: src/dotconfig/keystore.py, keywrap.py, cli.py, tests.

## Acceptance Criteria

- [ ] Sidecar with se, pass, recovery + passphrase-protected identity: `unlock --identity FILE` (no --with) prompts for the passphrase exactly once and unlocks via recovery (TTY-harness test asserts one prompt)
- [ ] Wrong identity passphrase yields a message about the identity's passphrase being wrong / matching no wrapped file, not per-method 'age failed'
- [ ] Plain identity file still unlocks; plugin identity (AGE-PLUGIN-...) still unlocks se/yubikey
- [ ] se/yubikey are never attempted with a non-plugin identity
- [ ] Decrypted identity is never written to disk (test asserts via runner seam that identity goes via stdin/fd and no temp file is created)
- [ ] `unlock --help` mentions `--with recovery --identity FILE`
- [ ] Tests use existing conftest isolation and never touch the real key

## Testing

- **Existing tests to run**: tests/test_unlock.py, test_keywrap.py, test_age_group.py
- **New tests to write**: encrypted-identity single prompt (real `age` with a passphrase-protected identity driven through a pty, or fake runner counting identity-file decrypts); wrong passphrase message; no-match message; plain and plugin identity regression; help text.
- **Verification command**: `uv run pytest tests/test_unlock.py tests/test_lock.py tests/test_keywrap.py tests/test_age_group.py`
