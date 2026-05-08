---
id: "003"
title: "dotconfig version command and dotconfig.yaml source-of-truth"
status: planning
branch: sprint/003-dotconfig-version-command-and-dotconfig-yaml-source-of-truth
use-cases: [SUC-001, SUC-002, SUC-003, SUC-004, SUC-005, SUC-006]
todo: docs/clasi/todo/dotconfig-version-and-yaml-source-of-truth.md
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 003: dotconfig version command and dotconfig.yaml source-of-truth

## Goals

Introduce `config/dotconfig.yaml` as the project-level source of truth for the
version number, wire a `dotconfig version` / `dotconfig version bump` CLI
surface modelled on the CLASI scheme, and make `load`/`save` transparently
inject and strip `_VERSION` in the materialised `.env`.

## Problem

Today the dotconfig project version lives only in `pyproject.toml` and is
bumped manually. There is no first-class CLI command for users of dotconfig to
manage *their own project's* version, no single file that owns the canonical
version across `pyproject.toml`, `package.json`, and `.env`, and no mechanism
for the active `.env` to carry a `_VERSION` variable that scripts can consume.

## Solution

Port the CLASI versioning module as `src/dotconfig/versioning.py`, adapting it
so that:
- `config/dotconfig.yaml` (key: `version`) is the fixed source of truth.
- `pyproject.toml`, `package.json`, and the active `.env` are sync targets that
  `bump` writes to when they exist.
- `dotconfig init` seeds `config/dotconfig.yaml` from `package.json` or
  `pyproject.toml` (in that priority order) if present, otherwise `"0.0.0"`.
- `dotconfig load` prepends `_VERSION=<version>` to the classic `.env` output.
- `dotconfig save` strips any `_VERSION=` line before writing back to config.

## Success Criteria

- `dotconfig version` prints the version from `config/dotconfig.yaml`.
- `dotconfig version bump` advances the revision and writes all sync targets.
- `dotconfig version bump --tag` additionally creates a `v<version>` git tag.
- `dotconfig version bump --push` commits + tags + pushes (with clean-master
  pre-flight check).
- `dotconfig init` creates `config/dotconfig.yaml` seeded from existing version
  files, leaving it untouched if it already exists.
- `dotconfig load` produces a `.env` with `_VERSION=<version>` near the top.
- `dotconfig save` never writes `_VERSION=` lines into config files.
- All smoke-test scenarios in the TODO pass end-to-end.
- Existing test suite remains green.

## Scope

### In Scope

- New module `src/dotconfig/versioning.py` with full port + adaptations.
- `init.py`: `_init_dotconfig_yaml()` helper + hook into `init_config`.
- `cli.py`: `version` command group and `version bump` subcommand.
- `load.py`: `_VERSION` injection into the classic `.env` output path.
- `save.py`: `_VERSION` stripping in `_parse_env_layers` and the flat save path.
- New `tests/test_versioning.py`.
- Updates to `tests/test_init.py`, `tests/test_load.py`, `tests/test_save.py`.

### Out of Scope

- `version_trigger` auto-bump-on-event mechanism (field reserved in yaml schema
  but not wired at runtime).
- Cargo / setup.cfg / other version-file types.
- A `--no-tag-push` flag on `--push`.
- `CLAUDE.md` doc updates to describe the new bump command.

## Test Strategy

Unit tests for each changed module:
- `test_versioning.py`: version parsing, format engine, `compute_next_version`,
  `read_dotconfig_version`, `write_dotconfig_version`, `update_dotenv_version`,
  `bump_version` (mock git + file system).
- `test_init.py`: assert `dotconfig.yaml` created with correct seeded version
  for each seed source (package.json, pyproject.toml, fallback `"0.0.0"`);
  assert idempotency (existing file left unchanged).
- `test_load.py`: `_VERSION` line appears in classic `.env` output; absent in
  JSON/YAML structured output.
- `test_save.py`: `_VERSION=` lines stripped regardless of section placement.

End-to-end smoke tests as documented in the TODO's Verification section.

## Architecture Notes

- `versioning.py` is self-contained (stdlib + pyyaml only). No circular deps.
- `load.py` and `init.py` both need `load_dotconfig_yaml(config_dir)`; this
  helper lives in `versioning.py` and is imported by both.
- The classic `.env` injection site is immediately after `_build_metadata_header`
  (load.py ~line 768), before the first `#@dotconfig:` section.
- The `_parse_env_layers` filter (save.py line ~411) drops any line matching
  `^_VERSION=` in the section-content accumulation branch.

## GitHub Issues

None.

## Definition of Ready

Before tickets can be created, all of the following must be true:

- [x] Sprint planning documents are complete (sprint.md, use cases, architecture)
- [x] Architecture review passed
- [x] Stakeholder has approved the sprint plan

## Tickets

| # | Title | Depends On |
|---|-------|------------|
| 001 | versioning.py module and unit tests | — |
| 002 | init.py: _init_dotconfig_yaml and tests | 001 |
| 003 | cli.py: version group and bump subcommand | 001 |
| 004 | load.py: _VERSION injection and tests | 001 |
| 005 | save.py: _VERSION strip and tests | 001 |
| 006 | End-to-end smoke verification | 002, 003, 004, 005 |
| 007 | cli.py: version load subcommand | — |

Tickets execute serially in the order listed. Ticket 007 was added mid-sprint after tickets 001-006 closed; all its prerequisites are already in place.
