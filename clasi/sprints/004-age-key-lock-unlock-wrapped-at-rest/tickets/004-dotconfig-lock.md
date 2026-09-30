---
id: '004'
title: dotconfig lock
status: in-progress
use-cases:
- SUC-003
depends-on:
- '001'
- '002'
github-issue: ''
issue: age-key-lock-unlock.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# dotconfig lock

## Description

`dotconfig lock`: removes the plain key file, only when it is safe. Needs no secret, asks no questions, safe to run unattended. Logic in `keywrap.py`, command in `cli.py`.

## Acceptance Criteria

- [ ] Exits 0 with a message if already locked (plain file absent)
- [ ] Refuses (non-zero) unless at least one wrapped file exists, its method is in the sidecar, and sidecar `public_key` equals the plain key's public key
- [ ] Refusal message explains what is missing and suggests `dotconfig key wrap`
- [ ] `--force` deletes anyway after printing what will be unrecoverable
- [ ] Deletion is best-effort zero-fill then unlink; documented as not guaranteed on APFS/SSD
- [ ] Never prompts; never reads stdin; no secret printed
- [ ] Does not require any wrapped file to have a recent `verified:` date beyond being present and recorded (verified flag is reported, not gating) -- planner choice

## Testing

- **Existing tests to run**: scope to touched modules (e.g. `uv run pytest tests/test_keys.py tests/test_key.py`)
- **New tests to write**: Tests in `tests/test_lock.py`: lock succeeds with valid wrapped+sidecar, refuses with no wrapped file, refuses with sidecar missing/mismatched key, `--force`, already locked exit 0, no stdin use.
- **Constraints**: tests must use a temp `SOPS_AGE_KEY_FILE`, never the real key.
- **Verification command**: `uv run pytest <scoped tests>`
