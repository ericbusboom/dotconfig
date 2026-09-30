---
id: '001'
title: Extract pure save planners and add diff comparison core
status: done
use-cases:
- SUC-001
- SUC-002
- SUC-003
depends-on: []
github-issue: ''
issue: dotconfig-diff-command.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->


# Extract pure save planners and add diff comparison core

## Description

Extract from `save.py` pure, side-effect-free planners that return a list of planned writes `(label, dest_path, content, encrypted)` for (a) `.env` sections (`save_config` logic: layer metadata, override deploy/local, DEPLOYMENT= rewrite, merge, add_export) and (b) `--file` mode (`save_file` / `_write_with_split` logic: dest resolution, secret splitting into public + `.secrets` companion, whole-file encryption cases). `save_config`/`save_file` then execute the plan with their existing write/encrypt/warn behavior (unchanged). Planner errors are raised (not `sys.exit`) and mapped back to the existing messages/exit in save.

Add `src/dotconfig/diff.py`: given a plan, read each saved dest (missing -> empty; encrypted -> decrypt in memory via `load._read_file_content`; never write to disk), normalize both sides (strip `export ` via `load._strip_export_prefix`, trailing whitespace, leading/trailing blank lines, metadata comments), and return per-file `difflib.unified_diff` text labeled with the saved path, plus a has-diff flag. Decrypt failures raise an error type the CLI maps to exit 2.

## Acceptance Criteria

- [x] Planners perform no writes, no encryption, no directory creation.
- [x] `save` behavior and output unchanged; all existing save/load tests pass untouched.
- [x] `diff.compare_env(...)` / `diff.compare_file(...)` return diff text + changed flag; missing saved file shows everything as added.
- [x] Secrets decrypted only in memory; no temp files written.
- [x] Unit tests for normalization (export prefix, whitespace) and missing-file case.

## Implementation Plan

- Approach: refactor save.py incrementally (env planner first, then file planner), run existing tests after each step; then write diff.py against the planner API.
- Files: modify `src/dotconfig/save.py`; create `src/dotconfig/diff.py`, `tests/test_diff_core.py`.
- Testing: `uv run pytest tests -k "save or load or diff_core"`.
- Docs: docstrings only (README in ticket 002).

## Testing

- **Existing tests to run**: all save/load test modules
- **New tests to write**: tests/test_diff_core.py
- **Verification command**: `uv run pytest`
