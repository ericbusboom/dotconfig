---
id: '005'
title: 'Key status: lock state, methods, SOPS_AGE_KEY warning'
status: open
use-cases: ["SUC-004"]
depends-on: ["001"]
github-issue: ''
issue: age-key-lock-unlock.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Key status: lock state, methods, SOPS_AGE_KEY warning

## Description

Extend `keys.py` `show_keys` to report locked/unlocked, wrapped methods with last-verified dates, and warn when `SOPS_AGE_KEY` is set (it defeats locking). Stop recommending `SOPS_AGE_KEY`: remove the `export SOPS_AGE_KEY=...` and Codespaces secret-value guidance that prints the secret.

## Acceptance Criteria

- [ ] Status shows `locked` when plain key missing and sidecar/wrapped files exist; `unlocked` when plain key present; `not wrapped` when no sidecar
- [ ] Lists each wrapped method with kind, label and `verified` date (or 'never verified')
- [ ] Warns when `SOPS_AGE_KEY` is set in the environment, explaining it survives lock; docs guidance points to `SOPS_AGE_KEY_FILE` only
- [ ] No secret key value is printed anywhere in status output (existing export/Codespaces lines removed or reworded)
- [ ] Existing `tests/test_keys.py` updated accordingly; no regression for no-key and file-key cases

## Testing

- **Existing tests to run**: scope to touched modules (e.g. `uv run pytest tests/test_keys.py tests/test_key.py`)
- **New tests to write**: Update `tests/test_keys.py` and add cases for locked, unlocked, not wrapped, SOPS_AGE_KEY warning, absence of secret in output.
- **Constraints**: tests must use a temp `SOPS_AGE_KEY_FILE`, never the real key.
- **Verification command**: `uv run pytest <scoped tests>`
