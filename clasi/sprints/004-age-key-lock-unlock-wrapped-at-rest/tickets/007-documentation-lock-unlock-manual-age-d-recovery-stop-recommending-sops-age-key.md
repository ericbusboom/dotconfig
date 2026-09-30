---
id: '007'
title: 'Documentation: lock/unlock, manual age -d recovery, stop recommending SOPS_AGE_KEY'
status: open
use-cases: ["SUC-005", "SUC-004"]
depends-on: ["003", "004", "005", "006"]
github-issue: ''
issue: age-key-lock-unlock.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Documentation: lock/unlock, manual age -d recovery, stop recommending SOPS_AGE_KEY

## Description

Document the feature in README.md and `src/dotconfig/agent_instructions.md`: setup with `key wrap`, daily `unlock`/`lock`, exit code 75, unattended lock usage, methods, and the manual `age -d` command for each wrapped-file kind so losing the sidecar does not lose the key. Stop recommending `SOPS_AGE_KEY`; use `SOPS_AGE_KEY_FILE` only (README lines ~368-372 currently list `SOPS_AGE_KEY`).

## Acceptance Criteria

- [ ] README has a lock/unlock section with setup, daily use and recovery commands per method (se, yubikey, identity, passphrase)
- [ ] README and agent_instructions state `SOPS_AGE_KEY` is discouraged and why
- [ ] Exit code 75 and 'safe to run unattended' for lock are documented; launchd screen-lock hook noted as a possible follow-up
- [ ] Agent instructions note agents cannot unlock and should report exit 75
- [ ] `dotconfig --instructions` output still renders (existing test passes)

## Testing

- **Existing tests to run**: scope to touched modules (e.g. `uv run pytest tests/test_keys.py tests/test_key.py`)
- **New tests to write**: Run `tests/test_cli.py`; no new code tests beyond checking instructions text contains the new section if an instructions test exists.
- **Constraints**: tests must use a temp `SOPS_AGE_KEY_FILE`, never the real key.
- **Verification command**: `uv run pytest <scoped tests>`
