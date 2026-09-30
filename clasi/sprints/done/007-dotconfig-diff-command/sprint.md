---
id: '007'
title: dotconfig diff command
status: done
branch: sprint/007-dotconfig-diff-command
use-cases:
- SUC-001
- SUC-002
- SUC-003
issues:
- dotconfig-diff-command.md
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 007: dotconfig diff command

## Goals

Add a read-only `dotconfig diff` command that mirrors `dotconfig save`: it compares the current `.env` (or a `--file`) against exactly where `save` would write, prints a unified diff per differing file, and exits 0 (no diff) / 1 (diff) / 2 (error).

## Problem

There is no way to see how a working `.env` or file differs from the saved config directory without actually saving (see issue `dotconfig-diff-command.md`).

## Solution

Extract the "what would save write, and where" logic out of `save.py` into pure planning functions that return `(label, dest_path, content, encrypted)` tuples without touching disk. `save` executes the plan (writes/encrypts); the new `diff` reads the saved side (decrypting in memory via load's `_read_file_content`/`_decrypt_sops`), normalizes both sides, and emits `difflib.unified_diff`. Sharing the planner guarantees diff cannot drift from save.

## Success Criteria

- `load` followed by `diff` exits 0 with no output.
- Edited public and secret values produce exit 1 with both diffs shown.
- `diff <deploy>`, `-d/-l`, `--file`, `--env-file`, `--config-dir` work as in `save`.
- Missing deployment / no managed `.env` / decrypt failure exit 2.
- No file is written and no decrypted content touches disk.
- Existing save tests pass unchanged.

## Scope

### In Scope

- Planner extraction in `save.py` (env sections and `--file` modes).
- New `diff.py` and `diff` CLI command; README docs; tests.

### Out of Scope

- `--json/--yaml/--flat` input formats for diff (exit 2 "unsupported" if passed; not registered).
- Multi-layer flatten diffs beyond what the shared planner gives for free.
- Color output, `--stat`, or a `--quiet` flag.

## Test Strategy

pytest with click's CliRunner against temp config dirs using the project's existing SOPS/age test fixtures (as used by save/load tests). Cases per the issue's Acceptance section, plus a read-only assertion (config dir mtimes/contents unchanged) and regression of the existing save tests after the planner extraction.

## Architecture

**Sizing: Substantial (lightweight) — touches 3 modules (save, diff, cli) and adds one new cross-module dependency (diff -> save/load); no data-model change, so no ERD, and the diagram below is the only one warranted.**

### Architecture Overview

```mermaid
graph LR
  CLI[cli.py: save / diff commands] --> SAVE[save.py: plan + execute]
  CLI --> DIFF[diff.py: compare + render]
  DIFF -->|plan_* (pure)| SAVE
  DIFF -->|_read_file_content| LOAD[load.py: decrypt]
  SAVE --> LOAD
```

What changed:
- `save.py`: `save_config` / `save_file` split into a pure planner (resolves deployment/local, section bodies, DEPLOYMENT= rewrite, secret/public splitting, destination paths, encrypted flag) and an executor that performs the existing writes. Behavior of `save` is unchanged.
- `diff.py` (new): purpose is to report differences between a save plan and the saved files. Reads saved files (decrypting secrets in memory), normalizes (strip `export ` prefix, trailing whitespace/blank edges, ignore metadata comments and `_VERSION=` which the parser already drops), treats a missing file as empty, renders unified diffs labeled with the saved path, returns an exit code.
- `cli.py`: new `diff` command with positional names, `-d/-l`, `--env-file`, `--file/-f`, `-n/--name`; uses the same `_classify_save_args` and `_config_dir`. Does not run hooks.

Impact on existing components: `save.py` refactor is behavior-preserving; `load.py` unchanged. Dependency direction stays cli -> save/diff -> load (no cycles).

### Design Rationale

Decision: share a planner with save rather than re-implementing resolution in diff. Alternative: copy the logic into diff.py (fast, but two implementations drift; the issue explicitly wants diff to mirror save). Alternative: run save against a temp dir and diff trees (would write decrypted/encrypted content to disk, violating the read-only / never-on-disk requirement and requiring a key-unlocked encrypt). Consequence: a modest refactor of save.py guarded by its existing tests.

Decision: exit codes via a dedicated path (`ctx.exit(n)`); all errors in diff map to 2 (save's `sys.exit(1)` helpers must not leak exit 1, which means "differences"). The planner raises/returns errors instead of calling `sys.exit(1)`, or diff catches `SystemExit` and remaps non-zero to 2.

### Migration Concerns

None. Additive command; no on-disk format changes.

### Open Questions

- For `--file` of unstructured content that save encrypts whole-file (secret content detected), diff compares the decrypted saved file to the source; confirm this is acceptable (assumed yes).
- Multi-layer `.env` (stacked load) with no override: diff compares each layer's section to its own file, as save would write it.

### Architecture Self-Review (verdict: APPROVE WITH CHANGES)

Consistency and codebase alignment: ok; save.py is currently a monolithic function, planner extraction is feasible. Cohesion: diff.py has one reason to change (comparison/rendering); planning stays in save. Coupling: one new edge diff -> save, no cycles. Anti-patterns: risk of shotgun coupling if diff reaches into save privates; mitigated by exposing named plan functions. Risk: exit-code remapping of `sys.exit(1)` (handled in design). Change: ensure the planner performs no `require_unlocked`/write side effects beyond decrypt needed by diff itself.

## Use Cases

### SUC-001: Check .env against saved config
Parent: N/A

- **Actor**: Developer
- **Preconditions**: A dotconfig-managed `.env` exists.
- **Main Flow**:
  1. Run `dotconfig diff [deploy] [local]`.
  2. Tool prints a unified diff per differing section, labeled with the saved file path.
- **Postconditions**: Nothing on disk changed; exit 0 if identical, 1 if different.
- **Acceptance Criteria**:
  - [ ] load then diff exits 0 with no output
  - [ ] changed public and secret values both shown, exit 1
  - [ ] `diff <other-deploy>` compares against that deployment

### SUC-002: Check a file against its saved copy
Parent: N/A

- **Actor**: Developer
- **Preconditions**: A local file and a saved copy (possibly not yet existing).
- **Main Flow**:
  1. Run `dotconfig diff --file app.yaml -d dev`.
- **Postconditions**: Exit 0 same / 1 changed (missing saved file counts as empty).
- **Acceptance Criteria**:
  - [ ] same -> 0, changed -> 1

### SUC-003: Error reporting
Parent: N/A

- **Actor**: Developer / script
- **Main Flow**: Run diff with a missing deployment, no managed `.env`, or undecryptable file.
- **Postconditions**: Message on stderr, exit 2, so `diff || save` scripting is safe.
- **Acceptance Criteria**:
  - [ ] each error class exits 2

## GitHub Issues

(None.)

## Definition of Ready

Before tickets can be created, all of the following must be true:

- [ ] Sprint planning document is complete (sprint.md, including its
      Architecture and Use Cases sections)
- [ ] Architecture review passed (or skipped, for changes with no
      architectural impact)
- [ ] Stakeholder has approved the sprint plan

## Tickets

| # | Title | Depends On |
|---|-------|------------|
| 001 | Extract pure save planners and add diff comparison core | none |
| 002 | dotconfig diff CLI command, exit codes, tests and README | 001 |

Tickets execute serially in the order listed.
