---
id: '002'
title: 'init.py: _init_dotconfig_yaml and tests'
status: done
use-cases:
- SUC-001
depends-on:
- '001'
github-issue: ''
todo: ''
completes_todo: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# init.py: _init_dotconfig_yaml and tests

## Description

Add `_init_dotconfig_yaml(config_dir, project_root, quiet)` to `init.py` and
hook it into `init_config()`. This creates `config/dotconfig.yaml` with a
seeded version when a project first runs `dotconfig init`, bridging existing
projects into the new versioning scheme.

## Acceptance Criteria

- [x] `_init_dotconfig_yaml(config_dir, project_root, quiet)` is implemented in
      `src/dotconfig/init.py`.
- [x] If `config/dotconfig.yaml` already exists, the function does nothing and
      prints `ok(...)` (idempotent — mirrors `_create_env_if_missing` pattern).
- [x] Version seed priority: `package.json` `.version` > `pyproject.toml`
      `[project] version` > `"0.0.0"`.
- [x] Written file contains exactly:
      ```
      # dotconfig project metadata.
      # Edit `version` only via `dotconfig version bump`.
      version: <seed>
      ```
- [x] `init_config()` calls `_init_dotconfig_yaml` between `_init_env_files`
      and `_write_agents_md`, under a `heading("📌 Project metadata:")` block
      (suppressed when `quiet=True`).
- [x] All updated tests in `tests/test_init.py` pass.
- [x] `uv run pytest tests/test_init.py` exits 0.
- [x] Full suite `uv run pytest` exits 0.

## Implementation Plan

### Approach

1. Read `init.py` lines 398–410 (`_create_env_if_missing`) as the pattern to
   mirror.
2. Implement `_init_dotconfig_yaml(config_dir, project_root, quiet)`:
   - Check `config_dir / "dotconfig.yaml"` exists — if so, print `ok(str(path))`
     and return.
   - Determine seed:
     - Try `project_root / "package.json"` — parse JSON, read `["version"]`.
     - Else try `project_root / "pyproject.toml"` — regex for
       `^version\s*=\s*"([^"]+)"` under `[project]` section.
     - Else use `"0.0.0"`.
   - Write the minimal YAML file with header comment.
   - Print `created(str(path))` unless `quiet`.
3. In `init_config()`, insert between the `_init_env_files` call and the
   `heading("📄 Agent documentation:")` block:
   ```python
   if not quiet:
       heading("📌 Project metadata:")
   _init_dotconfig_yaml(config_dir, config_dir.parent, quiet=quiet)
   ```

### Files to Modify

- `src/dotconfig/init.py` — add `_init_dotconfig_yaml`, update `init_config`.

### Testing Plan

Update `tests/test_init.py`:

- `package.json` present with `version` → `dotconfig.yaml` seeded from it.
- Only `pyproject.toml` present with `[project] version` → seeded from it.
- Neither present → seeded with `"0.0.0"`.
- Both present → `package.json` wins.
- `dotconfig.yaml` already exists → file left unchanged after `init`.
- `quiet=True` → no output, file still created.
- `heading("📌 Project metadata:")` appears in output when `quiet=False`.

### Documentation Updates

None required for this ticket.
