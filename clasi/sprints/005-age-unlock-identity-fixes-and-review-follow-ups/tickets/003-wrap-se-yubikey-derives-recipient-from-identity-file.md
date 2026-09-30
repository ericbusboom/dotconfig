---
id: '003'
title: wrap --se/--yubikey derives recipient from identity file
status: open
use-cases: [SUC-003]
depends-on: ['001']
github-issue: ''
issue: age-unlock-identity-review-findings.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# wrap --se/--yubikey derives recipient from identity file

## Description

Finding 3. `wrap --se --se-identity FILE` with no sidecar and no `--se-recipient` derives the recipient from FILE (`age-plugin-se recipients -i FILE`, fall back to the `# public key:` comment). Same for `--yubikey` via `age-plugin-yubikey --list` only if cheap; otherwise document as not done. Explicit `--*-recipient` still wins. Put the derive helper in keystore.py (through the runner seam); call it from keywrap.build_specs. Depends on 001 only to serialize edits to keystore.py/keywrap.py.

## Acceptance Criteria

- [ ] `wrap --se --se-identity FILE` works with no sidecar and no --se-recipient, using the derived recipient
- [ ] `--yubikey` equivalent works, or is explicitly recorded as deferred in the ticket
- [ ] Explicit --se-recipient overrides derivation
- [ ] Clear error if recipient cannot be derived
- [ ] Tests use fake runner / conftest isolation; real key untouched

## Testing

- **Existing tests to run**: tests/test_keywrap.py, test_age_group.py
- **New tests to write**: derive from plugin identity via fake runner; fallback to `# public key:` comment; explicit recipient precedence; derivation failure error.
- **Verification command**: `uv run pytest tests/test_unlock.py tests/test_lock.py tests/test_keywrap.py tests/test_age_group.py`
