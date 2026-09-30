---
id: '005'
title: 'save.py: _VERSION strip and tests'
status: done
use-cases:
- SUC-005
depends-on:
- '001'
github-issue: ''
todo: ''
completes_todo: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# save.py: _VERSION strip and tests

## Description

Modify `_parse_env_layers` in `save.py` to silently drop any line matching
`^_VERSION=` from section content. This prevents `_VERSION` (injected by
`dotconfig load`) from leaking back into config source files on `dotconfig save`.

## Acceptance Criteria

- [x] `_parse_env_layers` drops any line matching `^_VERSION=` in the
      section-content accumulation branch (`elif current_section is not None:`).
- [x] `_VERSION=` in the pre-section region (before the first `#@dotconfig:`
      marker) is also harmless — it is already discarded by the existing
      pre-section ignore logic. No additional filter is needed there.
- [x] Config source files written by `save_config` contain no `_VERSION=` line.
- [x] All other key/value pairs in the `.env` are written correctly.
- [x] No new imports are needed (re` is already imported in `save.py`).
- [x] All updated tests in `tests/test_save.py` pass.
- [x] `uv run pytest tests/test_save.py` exits 0.
- [x] Full suite `uv run pytest` exits 0.

## Implementation Plan

### Approach

The change is a single guard in `_parse_env_layers` (around line 411 of
`save.py`). The current accumulation branch is:

```python
elif current_section is not None:
    current_lines.append(line)
```

Change to:

```python
elif current_section is not None:
    if not line.startswith("_VERSION="):
        current_lines.append(line)
```

That is the complete change to `save.py`. No helper function needed.

**Why this is sufficient for the pre-section region**: `_VERSION=` is injected
by `load.py` before the first `#@dotconfig:` section marker. Lines before the
first section marker are neither captured into `sections` nor parsed as metadata
keys (since `_VERSION=` does not start with `# CONFIG_`). They are silently
discarded by `_parse_env_layers` already.

**Why no change to the structured save path**: `_save_config_structured` parses
JSON/YAML, not `.env` sections. It never sees `_VERSION=` line syntax.

### Files to Modify

- `src/dotconfig/save.py` — one-line change in `_parse_env_layers`.

### Testing Plan

Update `tests/test_save.py`:

- `.env` with `_VERSION=` injected before the first section → after save,
  no `_VERSION` in any output config file.
- `.env` with `_VERSION=` manually placed inside a section body → stripped.
- `.env` with no `_VERSION=` → save works identically to current behavior.
- Round-trip test: `load` output fed to `save` → config files clean, other
  key/values preserved.

### Documentation Updates

None required for this ticket.
