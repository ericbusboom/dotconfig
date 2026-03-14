# CLAUDE.md — Project guidelines for AI assistants

## Project overview

**dotconfig** is a Python CLI tool that manages layered `.env` configuration
from multiple source files (public config, SOPS-encrypted secrets, per-developer
local overrides) stored under a `config/` directory.

## Development

```bash
# Run tests
uv run pytest

# Run a specific test file
uv run pytest tests/test_init.py -v

# Install locally for development
uv sync
```

## Versioning

The version lives in `pyproject.toml` and follows the format:

```
<major>.<YYYYMMDD>.<revision>
```

- **major**: major version number (currently `0`)
- **YYYYMMDD**: date of the release (e.g. `20260311`)
- **revision**: incremental revision within that date, starting at `1`

### Version bump rules (applied before pushing)

When asked to push, update the version in `pyproject.toml` before committing:

1. Get today's date as `YYYYMMDD`.
2. Read the current version from `pyproject.toml`.
3. If the date portion matches today: increment the revision by 1.
4. If the date portion is older than today: set the date to today and reset
   the revision to `1`.
5. Update the `version = "..."` line in `pyproject.toml`.
6. Include the version bump in the push commit.

## Code conventions

- Uses `pathlib.Path` throughout (never string paths in implementation code).
- Each CLI command has its own module under `src/dotconfig/` with a public
  entry-point function (e.g. `init_config`, `load_config`, `save_config`).
- Private helpers are prefixed with `_`.
- Styled output goes through `src/dotconfig/output.py` helpers.
- Tests use `pytest` with `tmp_path` fixtures and `unittest.mock.patch` for
  external tool calls.
