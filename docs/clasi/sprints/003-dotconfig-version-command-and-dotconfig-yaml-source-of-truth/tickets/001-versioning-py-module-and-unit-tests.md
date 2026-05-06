---
id: '001'
title: versioning.py module and unit tests
status: done
use-cases:
- SUC-002
- SUC-003
depends-on: []
github-issue: ''
todo: dotconfig-version-and-yaml-source-of-truth.md
completes_todo: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# versioning.py module and unit tests

## Description

Create `src/dotconfig/versioning.py` by porting `clasi/versioning.py` and
adapting it for the dotconfig source-of-truth model. This module is the
foundation all other tickets depend on.

Reference implementation: `/Users/eric/proj/ai-project/clasi/clasi/versioning.py`.
Reference docs: `/Users/eric/proj/code-projects/dotconfig/docs/versioning.md`.

## Acceptance Criteria

- [x] `src/dotconfig/versioning.py` exists and is importable.
- [x] `load_dotconfig_yaml(config_dir) -> dict | None` reads and parses
      `config/dotconfig.yaml`; returns `None` if absent or malformed.
- [x] `read_dotconfig_version(config_dir) -> str | None` returns the `version`
      field from `config/dotconfig.yaml`, or `None` if absent.
- [x] `write_dotconfig_version(config_dir, version)` writes the `version` field
      to `config/dotconfig.yaml` in place (preserving comments and other keys
      where possible; creating the file if absent).
- [x] `update_dotenv_version(version, env_path)` rewrites or inserts
      `_VERSION=<version>` at the top of `.env`, preserving the rest of the
      file. No-ops if `env_path` does not exist.
- [x] `update_pyproject_version(version, path)` and
      `update_package_json_version(version, path)` update the respective files
      (ported verbatim from CLASI; skip silently if file does not exist).
- [x] `compute_next_version(major, config_dir)` reads current version from
      `config/dotconfig.yaml`, reads local git tags, returns the next version
      string under the `X+.YYYYMMDD.R+` format.
- [x] `create_version_tag(version)` creates a lightweight `v<version>` git tag.
- [x] `bump_version(major, tag, project_root, config_dir)` returns
      `{version, source, synced, tag}`. Writes `config/dotconfig.yaml` first,
      then `pyproject.toml`, `package.json`, `.env` (best-effort; missing files
      skipped). Creates tag if `tag=True`.
- [x] CLASI-specific functions dropped: `should_version`, `load_version_trigger`,
      `VALID_TRIGGERS`, `DEFAULT_TRIGGER`, `load_version_source`.
- [x] All unit tests in `tests/test_versioning.py` pass.
- [x] `uv run pytest tests/test_versioning.py` exits 0.

## Implementation Plan

### Approach

Port `clasi/versioning.py` verbatim for the format engine, then make the
following targeted changes:

1. Replace `_load_settings()` / `load_version_source()` with
   `load_dotconfig_yaml(config_dir)` and `read_dotconfig_version(config_dir)`.
2. Replace file-source detection logic with the fixed
   `config_dir / "dotconfig.yaml"` path.
3. Add `write_dotconfig_version(config_dir, version)`.
4. Add `update_dotenv_version(version, env_path)`:
   - Read existing `.env` if present.
   - Strip any existing `_VERSION=` lines.
   - Prepend `_VERSION=<version>\n`.
   - Write back.
5. Adapt `bump_version` signature and return dict.
6. Remove CLASI-specific functions.

### Files to Create

- `src/dotconfig/versioning.py` — new module.
- `tests/test_versioning.py` — new test file.

### Testing Plan

`tests/test_versioning.py` should cover:

- `load_dotconfig_yaml`: file missing → `None`; valid yaml → dict; malformed
  yaml → `None`.
- `read_dotconfig_version`: missing file → `None`; file with `version` key →
  version string; file without `version` key → `None`.
- `write_dotconfig_version`: creates file if absent; updates existing version
  field; does not corrupt other keys.
- `update_dotenv_version`: creates `_VERSION=` at top when `.env` missing;
  replaces existing `_VERSION=` line; preserves other lines.
- `compute_next_version`: mock `_get_existing_tags` and current version → verify
  revision increments correctly for same-day and new-day cases.
- `bump_version`: mock git + temp dir → verify correct files written, return
  dict populated, tag created when requested.
- `update_pyproject_version` and `update_package_json_version`: verify correct
  in-place update (copy tests from CLASI if they exist).

### Documentation Updates

None required for this ticket. The module has internal docstrings.
