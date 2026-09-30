---
id: '004'
title: 'load.py: _VERSION injection and tests'
status: done
use-cases:
- SUC-004
depends-on:
- '001'
github-issue: ''
todo: ''
completes_todo: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# load.py: _VERSION injection and tests

## Description

Modify the classic `.env` output path in `load.py` to prepend
`_VERSION=<version>` immediately after the metadata header block. This allows
scripts that source `.env` to consume the project version without running
`dotconfig version`.

## Acceptance Criteria

- [x] Classic `.env` output (the `else` branch in `load_config` around
      line 766) includes `_VERSION=<version>` as a line immediately after
      the `_build_metadata_header` block and the blank separator line.
- [x] The `_VERSION=` line is present only when `config/dotconfig.yaml`
      exists and has a non-empty `version` field.
- [x] When `config/dotconfig.yaml` is absent or has no `version` field,
      the line is silently omitted (no error).
- [x] JSON and YAML structured output paths (`--json` / `--yaml`) are
      completely unaffected.
- [x] Split and stdout output paths produce the same injected line as the
      file output path (since they share the `parts` assembly).
- [x] `load.py` imports `load_dotconfig_yaml` from `dotconfig.versioning`.
- [x] All updated tests in `tests/test_load.py` pass.
- [x] `uv run pytest tests/test_load.py` exits 0.
- [x] Full suite `uv run pytest` exits 0.

## Implementation Plan

### Approach

The insertion point is in `load_config()` at the classic `.env` output path
(around line 766–770 of `load.py`). The current code is:

```python
parts: list = []
parts.extend(_build_metadata_header(deployments, locals_))
parts.append("")
```

Change to:

```python
parts: list = []
parts.extend(_build_metadata_header(deployments, locals_))
# Inject _VERSION if config/dotconfig.yaml has a version field.
_dc = load_dotconfig_yaml(config_dir)
if _dc and _dc.get("version"):
    parts.append(f"_VERSION={_dc['version']}")
parts.append("")
```

This places `_VERSION=` between the metadata header and the blank line that
precedes the first `#@dotconfig:` section, so the final `.env` structure is:

```
# CONFIG_DEPLOYS=dev
# CONFIG_LOCALS=eric
_VERSION=0.20260506.3

#@dotconfig: public (dev)
...
```

Add `from .versioning import load_dotconfig_yaml` to the imports in `load.py`.

### Files to Modify

- `src/dotconfig/load.py` — insert `_VERSION` injection; add import.

### Testing Plan

Update `tests/test_load.py`:

- Classic `.env` output with `dotconfig.yaml` present and `version` set →
  `_VERSION=<version>` appears in output after metadata header.
- Classic `.env` output with no `dotconfig.yaml` → `_VERSION` absent, no error.
- Classic `.env` output with `dotconfig.yaml` present but no `version` key →
  `_VERSION` absent.
- `--json` structured output with `dotconfig.yaml` present → `_VERSION` not
  in output.
- `--yaml` structured output → `_VERSION` not in output.
- Verify `_VERSION` line appears before the first `#@dotconfig:` section.

### Documentation Updates

None required for this ticket.
