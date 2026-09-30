---
id: 008
title: Reorganize age-key CLI into dotconfig age group
status: done
use-cases:
- SUC-001
- SUC-002
- SUC-003
- SUC-004
- SUC-006
depends-on:
- '001'
- '002'
- '003'
- '004'
- '005'
- '006'
- '007'
github-issue: ''
issue: age-key-lock-unlock.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Reorganize age-key CLI into dotconfig age group

## Description

Stakeholder decision (2026-09-30): the `key` command group is overloaded.
Move all age-key commands into a dedicated `dotconfig age` group, with NO
top-level shortcuts, and make `key` SSH-only.

Also fixes a bug: ticket 005 implemented lock state / methods /
SOPS_AGE_KEY warning in `keys.show_keys()` (src/dotconfig/keys.py), but no
CLI command invokes it, so it is unreachable. `age status` must expose it.

Target command surface:

- `dotconfig age status` — NEW; wires `keys.show_keys()`.
- `dotconfig age wrap ...` — moved from `key wrap`, same flags.
- `dotconfig age unlock [--with] [--identity] [--paste]` — moved from top-level `unlock`.
- `dotconfig age lock [--force]` — moved from top-level `lock`.
- Removed: `key wrap`, top-level `unlock`, top-level `lock`.
- `key` group is SSH-only; its docstring "Manage SSH keys stored in
  config/keys/" becomes accurate.

## Acceptance Criteria

- [x] `dotconfig age` group exists with subcommands `status`, `wrap`, `unlock`, `lock`.
- [x] `dotconfig age status` calls `keys.show_keys()` and output includes lock state, wrap methods, and the SOPS_AGE_KEY warning when that env var is set.
- [x] `dotconfig age wrap` accepts exactly the flags `key wrap` accepted and behaves identically.
- [x] `dotconfig age unlock` accepts `--with`, `--identity`, `--paste` and behaves as top-level `unlock` did.
- [x] `dotconfig age lock` accepts `--force` and behaves as top-level `lock` did.
- [x] `dotconfig key wrap`, `dotconfig unlock`, and `dotconfig lock` no longer exist (Click "No such command" / usage error, nonzero exit).
- [x] `key` group contains only SSH-key commands; docstring reads "Manage SSH keys stored in config/keys/".
- [x] No top-level shortcut for any `age` subcommand.
- [x] Every user-facing string naming `dotconfig unlock`, `dotconfig lock`, `dotconfig key wrap`, or `dotconfig keys` uses the new form (`dotconfig age unlock|lock|wrap|status`). Verify with `grep -rnE "dotconfig (unlock|lock|key wrap|keys)\b|run: dotconfig unlock" src README.md` returning nothing stale. Covers: keyguard locked message -> `age key is locked — run: dotconfig age unlock`; keywrap error hints; lock refusal text; keys.py guidance; README "Locking the age key" section; src/dotconfig/agent_instructions.md.
- [x] sprint.md Architecture section updated where it names commands, plus a short `## Revision` note explaining the reorganization and the `age status` bug fix. (sprint.md edit goes through the normal process for planning artifacts.)
- [x] Existing CLI tests updated to the new command paths; new tests added (see Testing); full test suite passes.
- [x] No test touches the real age key (tests/conftest.py isolation in effect; all new tests set a temp `SOPS_AGE_KEY_FILE`).

## Implementation Plan

1. In src/dotconfig/cli.py, add `@cli.group() age`; register `status`, `wrap`, `unlock`, `lock` under it; delete `key wrap`, top-level `unlock`, `lock`. `age status` invokes `keys.show_keys()`.
2. Grep for old command strings across src/, README.md, src/dotconfig/agent_instructions.md, tests; replace with new forms.
3. Update the sprint.md Architecture command names and add `## Revision`.
4. Update/add tests.

## Testing

- **Existing tests to run**: `uv run pytest tests/` — especially CLI, keyguard, keywrap, lock/unlock, and key-status tests from tickets 001-007; update any that invoke `unlock`, `lock`, or `key wrap`.
- **New tests to write** (CliRunner, temp `SOPS_AGE_KEY_FILE`):
  - `age status`, `age wrap`, `age unlock`, `age lock` each exist (`--help` exits 0) and work in a basic happy path.
  - `age status` output shows lock state (locked vs unlocked) for both states.
  - `age status` shows SOPS_AGE_KEY warning when env var set.
  - Old `unlock`, `lock`, `key wrap` invocations fail with nonzero exit / "No such command".
  - `key --help` lists no `wrap`; keyguard locked message text equals `age key is locked — run: dotconfig age unlock`.
  - Regression guard: no stale `dotconfig unlock|lock|key wrap|keys` strings in src/ and README (grep-style test or manual check).
- **Verification command**: `uv run pytest`
