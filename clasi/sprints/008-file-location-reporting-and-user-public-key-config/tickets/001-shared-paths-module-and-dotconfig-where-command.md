---
id: '001'
title: Shared paths module and dotconfig where command
status: open
use-cases:
- SUC-001
depends-on: []
github-issue: ''
issue: report-file-locations.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Shared paths module and dotconfig where command

## Description

Create src/dotconfig/paths.py as the single source of truth for locations: age key file ($SOPS_AGE_KEY_FILE or ~/.config/sops/age/keys.txt; SOPS_AGE_KEY inline noted), wrapped copies, lock sidecar, ~/.ssh/config, user config path (XDG_CONFIG_HOME or ~/.config/dotconfig/config.yaml), config root (via discover), and project files (sops.yaml, dotconfig.yaml, deploy/local env files, keys/, files/, AGENTS.md, .env*, .gitignore, .gitattributes). Each entry reports path, source (env var / default / discovered) and exists. keystore imports key-path logic from paths (no import cycle). Add the `dotconfig where` command in cli.py.

## Acceptance Criteria

- [ ] paths module returns path, source and exists for every location listed in report-file-locations.md plus the user config
- [ ] XDG_CONFIG_HOME set -> user config path under it; unset or empty -> ~/.config/dotconfig/config.yaml
- [ ] SOPS_AGE_KEY_FILE overrides the default key path and is reported as source env
- [ ] keystore.key_path/wrapped_path/sidecar_path keep their public behavior; no circular import
- [ ] `dotconfig where` prints all entries, works outside a project (says no config root found), and follows output.py conventions
- [ ] Tests use an autouse fixture (tests/conftest.py, added by the first ticket that needs it) that monkeypatches HOME and XDG_CONFIG_HOME (and clears SOPS_AGE_KEY_FILE/SOPS_AGE_KEY unless a test sets them) to tmp dirs. No test touches the real ~/.config.

## Implementation Plan

Files: src/dotconfig/paths.py (new), keystore.py, cli.py, tests/conftest.py, tests/test_paths.py, tests/test_where_cli.py. Tests: parametrize env combinations with monkeypatch; CliRunner for where.

## Testing

- **Existing tests to run**: `uv run pytest` scoped to the touched modules
- **New tests to write**: as listed above
- **Verification command**: `uv run pytest`
