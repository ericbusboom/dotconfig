---
id: 008
title: File location reporting and user public-key config
status: done
branch: sprint/008-file-location-reporting-and-user-public-key-config
use-cases:
- SUC-001
- SUC-002
- SUC-003
- SUC-004
issues:
- report-file-locations.md
- user-config-public-keys.md
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 008: File location reporting and user public-key config

## Goals

1. dotconfig tells the user where its files are (`dotconfig where`, resolved paths in command output and error messages).
2. A user-level config (`$XDG_CONFIG_HOME/dotconfig/config.yaml`) lists labeled public age keys that `dotconfig init` adds to every project's `config/sops.yaml`, with labels preserved in that file.

## Problem

Commands do not say which files they used, and adding extra recipients (other machines, CI, recovery) is manual per project, leaving unlabeled `age1...` strings.

## Solution

A shared `paths` module is the single source of truth for locations. A `userconfig` module loads, validates and seeds the user config. sops.yaml is rendered in `key_groups` layout with trailing `# label` comments, and a label-aware parser reads all legacy forms. `init` merges the keys and tells the user to run `dotconfig reencrypt` (it does not re-encrypt itself).

## Success Criteria

- `dotconfig where` lists every location with source and existence.
- `init` creates the user config when missing, adds all listed keys with labels, and is idempotent.
- Real `sops` encrypt/decrypt works with the new layout (tested).
- No test touches the real home directory.

## Scope

### In Scope

Both linked issues; README/AGENTS.md updates.

### Out of Scope

Automatic re-encryption; removing keys from sops.yaml; CLI to edit the user config.

## Test Strategy

pytest with HOME and XDG_CONFIG_HOME monkeypatched to tmp dirs (autouse fixture in tests). Unit tests for paths, userconfig, parsing/rendering; integration tests for init with real sops where available (skip if sops/age missing).

## Architecture Notes

See architecture-update.md: key_groups layout chosen; init reports instead of re-encrypting.

## GitHub Issues

None.

## Definition of Ready

Before tickets can be created, all of the following must be true:

- [x] Sprint planning documents are complete (sprint.md, use cases, architecture)
- [x] Architecture review passed
- [ ] Stakeholder has approved the sprint plan

## Tickets

| # | Title | Depends On |
|---|-------|------------|
| 001 | Shared paths module and dotconfig where command | - |
| 002 | User config module: load, validate, seed | 001 |
| 003 | Label-aware sops.yaml parse and key_groups render | 002 |
| 004 | init integration: user config, merged labeled keys, reencrypt notice | 002, 003 |
| 005 | Print resolved paths in commands and include them in errors | 001, 004 |
| 006 | Document where command and user config in README and AGENTS.md | 004, 005 |

Tickets execute serially in the order listed.
