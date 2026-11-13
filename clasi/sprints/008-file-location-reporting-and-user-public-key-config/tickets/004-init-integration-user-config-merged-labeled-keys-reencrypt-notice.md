---
id: '004'
title: 'init integration: user config, merged labeled keys, reencrypt notice'
status: done
use-cases:
- SUC-003
- SUC-004
depends-on:
- '002'
- '003'
github-issue: ''
issue:
- user-config-public-keys.md
- report-file-locations.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# init integration: user config, merged labeled keys, reencrypt notice

## Description

Integrate into init_config/_update_sops_yaml: after deriving the local public key, create the user config if missing (seed with local key; print its path and suggest editing labels and adding keys), load listed keys, and merge local key + all listed keys into config/sops.yaml, keeping existing keys and labels. Print the user config path and each key added by label. If the recipient set changed and encrypted files exist under config/, print a clear notice to run `dotconfig reencrypt` (init does NOT re-encrypt; architecture-update D2). Idempotent on rerun. Also serves report-file-locations (path reporting).

## Acceptance Criteria

- [x] Missing user config is created, seeded with the local key labeled <user>@<hostname>, and init tells the user the path
- [x] All listed keys appear in sops.yaml with labels; the local key is always present
- [x] Rerun is a no-op (file untouched, reports up to date) and re-adds a key that was removed from sops.yaml
- [x] Existing recipients and their labels are never removed
- [x] Invalid user-config entries are skipped with a warning and do not break init
- [x] When recipients changed and encrypted files exist, output tells the user to run `dotconfig reencrypt`; nothing is re-encrypted
- [x] --quiet suppresses messages but still does the work
- [x] Tests use an autouse fixture (tests/conftest.py, added by the first ticket that needs it) that monkeypatches HOME and XDG_CONFIG_HOME (and clears SOPS_AGE_KEY_FILE/SOPS_AGE_KEY unless a test sets them) to tmp dirs. No test touches the real ~/.config.

## Implementation Plan

Files: src/dotconfig/init.py, tests/test_init_userconfig.py. Detect encrypted files with load._is_sops_encrypted.

## Testing

- **Existing tests to run**: `uv run pytest` scoped to the touched modules
- **New tests to write**: as listed above
- **Verification command**: `uv run pytest`
