---
id: '001'
title: Use state-neutral warning in age status when unlocked
status: open
use-cases: [SUC-001]
depends-on: []
github-issue: ''
issue: age-status-lock-warning-wording.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Use state-neutral warning in age status when unlocked

## Description

`age status` shows the lock-specific warning (`SOPS_AGE_KEY_LOCK_WARNING`) even when unlocked. Use a state-neutral warning in `status` when unlocked: "SOPS_AGE_KEY is set in the environment. It survives 'dotconfig age lock' and defeats locking; unset it and use SOPS_AGE_KEY_FILE instead." Keep the "locked, but..." text for `lock` and for `status` when truly locked.

## Acceptance Criteria

- [ ] `status` unlocked + SOPS_AGE_KEY set shows neutral wording, not "locked, but"
- [ ] `status` locked + SOPS_AGE_KEY set shows "locked, but..."
- [ ] `lock` wording unchanged
- [ ] Tests cover both status states

## Implementation Plan

Add a neutral constant next to `SOPS_AGE_KEY_LOCK_WARNING` in `src/dotconfig/keywrap.py`; in `src/dotconfig/cli.py` (around line 889) choose text by lock state in `status`; `lock` path untouched. Tests in the existing age/keywrap CLI test file.

## Testing

- **Existing tests to run**: tests/test_keyguard.py and other age/keywrap/cli tests
- **New tests to write**: status in both states with SOPS_AGE_KEY set, asserting wording
- **Verification command**: `uv run pytest`
