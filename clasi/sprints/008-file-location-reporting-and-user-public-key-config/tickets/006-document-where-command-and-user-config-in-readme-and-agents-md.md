---
id: '006'
title: Document where command and user config in README and AGENTS.md
status: in-progress
use-cases:
- SUC-001
- SUC-004
depends-on:
- '004'
- '005'
github-issue: ''
issue:
- user-config-public-keys.md
- report-file-locations.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Document where command and user config in README and AGENTS.md

## Description

Document `dotconfig where`, the user config file (location, XDG, format, labels), the labeled sops.yaml layout, and the reencrypt-after-init notice in README.md and the AGENTS.md template (src/dotconfig/agent_instructions.md). Also serves report-file-locations.

## Acceptance Criteria

- [ ] README documents where, user config format/location and the reencrypt step
- [ ] AGENTS.md template mentions where and the user config
- [ ] Doc examples match actual command output
- [ ] Affected tests (any AGENTS.md generation tests) pass
- [ ] Tests use an autouse fixture (tests/conftest.py, added by the first ticket that needs it) that monkeypatches HOME and XDG_CONFIG_HOME (and clears SOPS_AGE_KEY_FILE/SOPS_AGE_KEY unless a test sets them) to tmp dirs. No test touches the real ~/.config.

## Implementation Plan

Files: README.md, src/dotconfig/agent_instructions.md. Doc-only; run tests touching AGENTS.md generation.

## Testing

- **Existing tests to run**: `uv run pytest` scoped to the touched modules
- **New tests to write**: as listed above
- **Verification command**: `uv run pytest`
