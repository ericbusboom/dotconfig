---
id: '002'
title: 'User config module: load, validate, seed'
status: open
use-cases:
- SUC-003
depends-on:
- '001'
github-issue: ''
issue: user-config-public-keys.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# User config module: load, validate, seed

## Description

Create src/dotconfig/userconfig.py: load_public_keys(path=None) -> list of (key, label) from the user config (path from paths); validate entries (dict with key starting age1; label optional string) and skip invalid ones with a warning that includes the config file path; tolerate missing file, empty file, malformed YAML (warn, return []). seed_user_config(public_key) writes the file (creating dirs, never overwriting) with one entry labeled <user>@<hostname> and returns True if created.

## Acceptance Criteria

- [ ] Valid file returns ordered (key,label) pairs; missing label yields None
- [ ] Non-age1 or missing-key entries are skipped with a warning naming the file path
- [ ] Malformed YAML or non-list public_keys warns and returns []
- [ ] seed creates parent dirs and the file with the given key and <user>@<hostname> label; a second call does not overwrite and returns False
- [ ] Duplicate keys collapsed, first label wins
- [ ] Respects XDG_CONFIG_HOME via paths
- [ ] Tests use an autouse fixture (tests/conftest.py, added by the first ticket that needs it) that monkeypatches HOME and XDG_CONFIG_HOME (and clears SOPS_AGE_KEY_FILE/SOPS_AGE_KEY unless a test sets them) to tmp dirs. No test touches the real ~/.config.

## Implementation Plan

Files: src/dotconfig/userconfig.py, tests/test_userconfig.py. Use yaml.safe_load; getpass.getuser / socket.gethostname (monkeypatched in tests).

## Testing

- **Existing tests to run**: `uv run pytest` scoped to the touched modules
- **New tests to write**: as listed above
- **Verification command**: `uv run pytest`
