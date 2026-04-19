---
sprint: "002"
status: complete
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Architecture Update -- Sprint 002: Positional load/save args and gitignore TODO archive

## What Changed

- **`src/dotconfig/cli.py`**: `load` and `save` Click commands gain
  variadic positional `nargs=-1` arguments. The existing `-d/--deploy`
  and `-l/--local` flags remain as single-value back-compat shims.
- **`src/dotconfig/load.py`**:
  - `load_config(deployment: str, local: Optional[str], …)` becomes
    `load_config(deployments: list[str], locals: list[str], …)`.
  - `_read_env_layers` is generalised to iterate over the layer lists
    and return a list of `(label, text)` pairs instead of a fixed
    4-tuple.
  - The classic `.env` writer emits one block of section markers per
    deployment / local layer.
  - The metadata header writes `# CONFIG_DEPLOYS=<csv>` and
    `# CONFIG_LOCALS=<csv>` (single-value cases still write the legacy
    keys for human friendliness).
- **`src/dotconfig/save.py`**:
  - `save_config(override_deploy, override_local, …)` becomes
    `save_config(override_deploys: list[str], override_locals: list[str], …)`.
  - `parse_env_file` reads `CONFIG_DEPLOYS` / `CONFIG_LOCALS` first,
    falling back to legacy single keys.
  - The section-write loop iterates over the parsed layer lists.
- **New helper** (likely in `src/dotconfig/cli.py` as a private
  function, or a small `src/dotconfig/_args.py` module):
  `_classify_positional_args(names, config_dir) -> (deploys, locals)`
  inspects directory existence to assign each name to a type, raising a
  `click.UsageError` for unknown or ambiguous names.
- **No new modules**, no new external dependencies.
- **TODO archive**: file move only (no code change), recorded via the
  `move_todo_to_done` MCP tool.

## Why

The `-d`/`-l` flags are noise for the common case and can't express
multi-layer composition. Positional args + type classification give a
shorter form for everyday use and a natural extension point for
stacking. The TODO archive cleans up state drift between
`docs/clasi/todo/` and the actual code on disk.

## Impact on Existing Components

- **CLI surface**: `load` / `save` accept new positional args; the
  legacy flag form continues to work. Scripts that use `-d dev -l eric`
  are unaffected. Help text and the embedded examples in
  `cli.py` / `load.py` / `save.py` docstrings need updating to show
  the new shorthand alongside the legacy form.
- **`.env` metadata format**: writer prefers `CONFIG_DEPLOYS`/
  `CONFIG_LOCALS` for stacked layers but emits the legacy singular
  `CONFIG_DEPLOY`/`CONFIG_LOCAL` for the single-layer case (preserves
  byte-for-byte output for existing tests/fixtures). Reader accepts
  all four keys plus the very-legacy `CONFIG_COMMON` alias already
  present in `parse_env_file`. Previously generated `.env` files
  round-trip without modification.
- **Internal call sites**: `cli.py` is the only caller of
  `load_config` / `save_config`; signature changes are isolated.
- **Structured output (`--json` / `--yaml`)**: the structured branch
  currently builds a fixed
  `{_dotconfig: {deploy, local}, deploy: {…}, local: {…}}` shape that
  assumes one of each. For this sprint, passing more than one
  deployment or more than one local with `--json`/`--yaml` raises a
  `click.UsageError`. Single-layer structured output is unchanged.
- **`--file`, `--split`, `--flat`, `--stdout` flags**: unchanged. They
  remain compatible with single-deployment / single-local invocation.

## Migration Concerns

- Pre-existing `.env` files use `CONFIG_DEPLOY` / `CONFIG_LOCAL` (singular).
  `parse_env_file` reads those as single-element lists, so old files
  round-trip cleanly.
- Down-stream code that imports `load_config` / `save_config`
  directly will see signature changes. Inside this repo there is only
  one caller (`cli.py`); external callers are out of scope (pre-1.0).
- The `-d` / `-l` flag deprecation is *not* part of this sprint.
  A future sprint may emit a deprecation warning and eventually
  remove the flags.
