---
id: '002'
title: dotconfig diff CLI command, exit codes, tests and README
status: done
use-cases:
- SUC-001
- SUC-002
- SUC-003
depends-on:
- '001'
github-issue: ''
issue: dotconfig-diff-command.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->


# dotconfig diff CLI command, exit codes, tests and README

## Description

Add the `diff` click command in `cli.py` mirroring `save`'s options: positional names (via `_classify_save_args`), `-d/--deploy`, `-l/--local`, `--env-file`, `-f/--file`, `-n/--name`, and the global `--config-dir`; usage errors for mixing positionals with flags. Wire to the ticket-001 core, print diffs to stdout, exit 0 (no diff) / 1 (diff) / 2 (any error: no managed .env, missing deployment, decrypt failure, missing source file). Ensure `sys.exit(1)` from shared helpers is remapped to 2 so exit 1 only means "differences". No hooks run; read-only. Document in README next to `save`.

## Acceptance Criteria

- [x] `load` then `diff` exits 0, no output.
- [x] Edited public and secret value -> exit 1, both shown in unified diffs labeled with saved paths.
- [x] `diff <other-deploy>` compares against that deployment; `-d/-l` work.
- [x] `--file app.yaml -d dev`: same -> 0, changed -> 1; missing saved copy -> 1 (all added).
- [x] Missing deployment / no `.env` / decrypt failure -> exit 2.
- [x] Config dir contents unchanged after every diff run (read-only assertion).
- [x] README documents `diff`, exit codes, and the secrets-printed-to-stdout note.

## Implementation Plan

- Approach: add command after `save` in cli.py; wrap core call catching SystemExit/known errors -> `ctx.exit(2)`.
- Files: modify `src/dotconfig/cli.py`, `README.md`; create `tests/test_diff_cli.py`.
- Testing: CliRunner tests reusing existing SOPS/age fixtures; cover each acceptance item.
- Docs: README section; `--help` docstring with examples.

## Testing

- **Existing tests to run**: `uv run pytest` (full CLI suites)
- **New tests to write**: tests/test_diff_cli.py
- **Verification command**: `uv run pytest`
