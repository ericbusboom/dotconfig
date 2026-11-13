---
id: '005'
title: Print resolved paths in commands and include them in errors
status: done
use-cases:
- SUC-002
depends-on:
- '001'
- '004'
github-issue: ''
issue: report-file-locations.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Print resolved paths in commands and include them in errors

## Description

Make load, save, init, age unlock/lock and key print the resolved paths they read and wrote (config root, key file, sops.yaml, output file) using output.py helpers and respecting --quiet. Include the config root and key file path in error messages, especially decryption failures.

## Acceptance Criteria

- [x] Each listed command prints its resolved paths; suppressed under --quiet
- [x] Decrypt failure message includes the config root and key file path
- [x] Paths come from the paths module (no duplicated resolution)
- [x] Existing tests pass; new tests assert path lines with CliRunner
- [x] Tests use an autouse fixture (tests/conftest.py, added by the first ticket that needs it) that monkeypatches HOME and XDG_CONFIG_HOME (and clears SOPS_AGE_KEY_FILE/SOPS_AGE_KEY unless a test sets them) to tmp dirs. No test touches the real ~/.config.

## Implementation Plan

Files: cli.py, load.py, save.py, init.py, key.py, keystore/age commands, tests/test_path_reporting.py.

## Testing

- **Existing tests to run**: `uv run pytest` scoped to the touched modules
- **New tests to write**: as listed above
- **Verification command**: `uv run pytest`
