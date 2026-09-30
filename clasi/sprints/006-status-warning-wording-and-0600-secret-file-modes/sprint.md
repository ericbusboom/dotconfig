---
id: '006'
title: Status warning wording and 0600 secret file modes
status: ticketing
branch: sprint/006-status-warning-wording-and-0600-secret-file-modes
use-cases: []
issues:
- age-status-lock-warning-wording.md
- env-file-mode-0600.md
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 006: Status warning wording and 0600 secret file modes

## Goals

Fix two small correctness/safety defects: a misleading warning in
`dotconfig age status`, and world-readable decrypted secret files written
by `dotconfig load` / `key load`.

## Problem

1. `age status` prints "locked, but SOPS_AGE_KEY is set..." while the state
   is unlocked (`cli.py` reuses `keywrap.SOPS_AGE_KEY_LOCK_WARNING`).
2. `load.py` writes `.env`, `.env.secret`, `--public` output with
   `Path.write_text` (umask, typically 0644), and `key.py` writes files under
   `config/files/` the same way; they hold decrypted secrets.

## Solution

1. Add a state-neutral warning constant; `status` uses it when unlocked and
   keeps the "locked, but" text when truly locked; `lock` unchanged.
2. Write secret outputs with mode 0600 via atomic temp file + rename; tighten
   and report an existing more-open `.env`.

## Success Criteria

- Status warning wording correct in both states with `SOPS_AGE_KEY` set.
- `.env`, `.env.secret`, `--public` output and `key load` files are 0600; an
  existing 0644 `.env` becomes 0600 with a notice.

## Scope

### In Scope

- Issues `age-status-lock-warning-wording.md` and `env-file-mode-0600.md`.

### Out of Scope

- Changing modes of files other than those listed; other warning text.

## Test Strategy

pytest: `status` output in locked and unlocked states with `SOPS_AGE_KEY`
set; mode assertions (`stat.S_IMODE == 0o600`) after `load`, `load --split`,
`load --public`, `key load`; pre-existing 0644 `.env` tightened.

## Architecture

Compact - two independent changes each confined to existing modules
(`keywrap`/`cli` wording; `load`/`key` file writing), no new cross-module
dependency beyond reusing an atomic-write helper, no data-model change.

### Architecture Overview

What changed: (a) `keywrap` gains a state-neutral warning constant alongside
`SOPS_AGE_KEY_LOCK_WARNING`; the `status` command in `cli.py` picks the
neutral text when unlocked, the existing text when locked. (b) The atomic
0600 writer currently private to `keystore` (`_atomic_write`) is exposed as
a small shared helper (either made public in `keystore` or moved to a tiny
utility) and used by `load.py` and `key.py` for secret outputs. For `.env`,
the writer compares the existing file's mode first and emits an info message
when it tightens a more-open file.

Why: secrets must not be group/world-readable; warning text must match state.

Impact on existing components: `load` and `key` depend on the atomic-write
helper (one new edge into a low-level leaf module, no cycle). Otherwise none.

### Design Rationale

Reuse the existing atomic-write implementation rather than duplicate it, so
mode and durability semantics stay identical across key material and
decrypted output.

### Migration Concerns

None. Existing 0644 `.env` files are tightened on next `load`.

## Use Cases

### SUC-001: Accurate status warning
- **Actor**: User running `dotconfig age status`
- **Preconditions**: `SOPS_AGE_KEY` set in environment
- **Main Flow**: Run `status` unlocked, then locked
- **Postconditions**: Unlocked shows neutral warning; locked shows "locked, but..."
- **Acceptance Criteria**:
  - [ ] Both states tested; `lock` wording unchanged

### SUC-002: Secret output files are private
- **Actor**: User running `load` / `key load`
- **Preconditions**: Config with decrypted secrets
- **Main Flow**: Run `load`, `load --split`, `load --public`, `key load`
- **Postconditions**: All written files are mode 0600; old 0644 `.env` tightened with a message
- **Acceptance Criteria**:
  - [ ] Mode tests for all four paths plus tighten case

## GitHub Issues

(None.)

## Definition of Ready

- [x] Sprint planning document is complete
- [x] Architecture review passed (compact, scoped)
- [ ] Stakeholder has approved the sprint plan

## Tickets

| # | Title | Depends On |
|---|-------|------------|
| 001 | Use state-neutral warning in age status when unlocked | - |
| 002 | Write decrypted secret files with mode 0600 atomically | - |

Tickets execute serially in the order listed.
