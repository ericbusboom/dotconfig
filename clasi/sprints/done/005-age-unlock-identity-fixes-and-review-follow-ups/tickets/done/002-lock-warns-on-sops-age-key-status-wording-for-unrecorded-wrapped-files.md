---
id: '002'
title: lock warns on SOPS_AGE_KEY; status wording for unrecorded wrapped files
status: done
use-cases:
- SUC-002
- SUC-003
depends-on: []
github-issue: ''
issue: age-unlock-identity-review-findings.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# lock warns on SOPS_AGE_KEY; status wording for unrecorded wrapped files

## Description

Finding 2 and 4. `age lock` prints the same warning as `status` when `SOPS_AGE_KEY` is set ("locked, but SOPS_AGE_KEY is set in this environment; this shell and its children can still decrypt"), still exits 0 and still removes the key. Reuse the status warning text. `status` shows, for a wrapped file not in the sidecar, "not recorded; run: dotconfig age wrap --<kind> to verify and record it". Files: keywrap.py, cli.py, tests/test_lock.py, test_age_group.py.

## Acceptance Criteria

- [x] `lock` with SOPS_AGE_KEY set locks, exits 0, prints the warning
- [x] `lock` without SOPS_AGE_KEY prints no such warning
- [x] `status` wording for an unrecorded wrapped file names the command to run
- [x] Tests use existing conftest isolation

## Testing

- **Existing tests to run**: tests/test_lock.py, test_age_group.py
- **New tests to write**: lock warning present/absent; status wording for a hand-made unrecorded wrapped file.
- **Verification command**: `uv run pytest tests/test_unlock.py tests/test_lock.py tests/test_keywrap.py tests/test_age_group.py`
