---
id: '007'
title: 'cli.py: version load subcommand'
status: done
use-cases:
- SUC-001
depends-on: []
github-issue: ''
todo: ''
completes_todo: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# cli.py: version load subcommand

## Description

Add a `dotconfig version load` subcommand that seeds or refreshes the
`version` field in `config/dotconfig.yaml` by reading from external
version source files. This exposes the seeding logic already used at
`dotconfig init` time as an explicit CLI command, so users can resync
after directly editing `pyproject.toml` or `package.json`.

The seeding logic currently duplicated inside `_init_dotconfig_yaml`
(in `init.py`) should be extracted into a shared helper
`seed_version_from_sources(project_root)` in `versioning.py`. Both
`_init_dotconfig_yaml` and the new CLI command will call this helper.
Unlike init (which is a no-op if the file already exists), `load`
unconditionally overwrites the `version` field.

Priority order for sources:
1. `<project_root>/package.json` -- `version` field
2. `<project_root>/pyproject.toml` -- `version = "..."` under `[project]`

If neither source exists (or neither contains a version), exit 1 with a
clear, user-facing message. On success, write the value via
`write_dotconfig_version` and print the loaded version to stdout.

This work was requested by the stakeholder mid-sprint after tickets
001-006 closed. No separate TODO file.

## Acceptance Criteria

- [x] `seed_version_from_sources(project_root: Path) -> str | None` is
      added to `src/dotconfig/versioning.py`. It reads `package.json`
      first (if the file exists and contains a `version` field), then
      `pyproject.toml` (if it exists and contains `version = "..."` under
      `[project]`). Returns the first found version string, or `None` if
      neither source yields a value.
- [x] `_init_dotconfig_yaml` in `src/dotconfig/init.py` is refactored
      to call `seed_version_from_sources` instead of duplicating the
      inline parsing logic. Behavior is identical to before: falls back
      to `"0.0.0"` when `seed_version_from_sources` returns `None`.
- [x] `dotconfig version load` is added as a subcommand under the
      existing `version` group in `src/dotconfig/cli.py`.
      - Resolves `config_dir` the same way as other `version` subcommands
        (`_resolve_config_dir(ctx) or Path("config")`).
      - Calls `seed_version_from_sources(project_root)` where
        `project_root = Path.cwd()`.
      - If `seed_version_from_sources` returns `None`, prints a friendly
        error message to stderr and exits with code 1.
      - Otherwise, calls `write_dotconfig_version(cfg, version)` and
        prints the loaded version to stdout (e.g. `Loaded version: 1.2.3`).
- [x] `dotconfig version load` overwrites any existing `version` in
      `config/dotconfig.yaml` (unlike `dotconfig init`, which skips if
      the file already exists).
- [x] `dotconfig version load` creates `config/dotconfig.yaml` if it
      does not exist (handled by `write_dotconfig_version`'s existing
      create-if-absent logic).
- [x] Unit tests for `seed_version_from_sources` in
      `tests/test_versioning.py` (or equivalent):
      - Returns the `package.json` version when both files exist (priority).
      - Returns the `pyproject.toml` version when only `pyproject.toml` exists.
      - Returns `None` when neither file exists.
      - Returns `None` when `package.json` exists but has no `version` field.
      - Returns `None` when `pyproject.toml` exists but has no version under
        `[project]`.
      - Handles malformed JSON / TOML gracefully: returns `None`, does not raise.
- [x] CLI tests for `dotconfig version load` (in an existing or new test file):
      - Exits 0 and prints the version when a valid source exists.
      - Writes the version into `config/dotconfig.yaml`.
      - Exits 1 with a non-empty stderr message when no source file exists.
- [x] All existing tests pass: `uv run pytest`.

## Implementation Plan

### Approach

Pure refactor + additive CLI surface. No data model changes, no new
external dependencies.

### Files to modify

1. **`src/dotconfig/versioning.py`**
   - Add `seed_version_from_sources(project_root: Path) -> str | None`
     after the `write_dotconfig_version` block. Move the `package.json`
     and `pyproject.toml` parsing logic from `_init_dotconfig_yaml` into
     this function. Keep the same error handling (`except Exception: pass`).

2. **`src/dotconfig/init.py`**
   - Add `seed_version_from_sources` to the import from `.versioning`.
   - Replace the inline seed-detection block in `_init_dotconfig_yaml`
     with `seed = seed_version_from_sources(project_root) or "0.0.0"`.
   - Remove the `import json` at the top if it is no longer used
     elsewhere in `init.py` (verify before removing).

3. **`src/dotconfig/cli.py`**
   - Add `seed_version_from_sources` and `write_dotconfig_version` to the
     `from .versioning import ...` line (`write_dotconfig_version` is not
     currently imported in `cli.py`).
   - Add a `version load` subcommand after `version_bump`:

     ```python
     @version.command("load")
     @click.pass_context
     def version_load(ctx: click.Context) -> None:
         """Seed config/dotconfig.yaml version from package.json or pyproject.toml.

         Reads the version from the first available source (package.json
         takes priority over pyproject.toml) and writes it to
         config/dotconfig.yaml, overwriting any existing value.

         Exits 1 if neither source file contains a version.

         \b
             dotconfig version load
         """
         import sys
         cfg = _resolve_config_dir(ctx) or Path("config")
         project_root = Path.cwd()
         version = seed_version_from_sources(project_root)
         if version is None:
             click.echo(
                 "No version source found. "
                 "Add a 'version' field to package.json or pyproject.toml.",
                 err=True,
             )
             sys.exit(1)
         write_dotconfig_version(cfg, version)
         click.echo(f"Loaded version: {version}")
     ```

   - Update the `version` group docstring example block to include
     `dotconfig version load`.

### Testing plan

- Run existing test suite first to confirm baseline: `uv run pytest`.
- Add unit tests for `seed_version_from_sources` using `tmp_path` fixtures
  (write real `package.json` / `pyproject.toml` fragments and assert return
  values). Cover the priority logic, missing-file, missing-field, and
  malformed-content cases.
- Add CLI tests using Click's `CliRunner` (or a `tmp_path`-based fixture)
  for the `version load` command: assert exit code, stdout content, and the
  resulting `config/dotconfig.yaml` content.
- Run full suite again: `uv run pytest`.
