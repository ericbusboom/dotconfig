---
id: '002'
title: Positional args + multi-layer load/save
status: todo
use-cases: [SUC-001]
depends-on: []
github-issue: ''
todo: plan-positional-load-save-args.md
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Positional args + multi-layer load/save

## Description

Replace the mandatory `-d/--deploy` and `-l/--local` flags on
`dotconfig load` and `dotconfig save` with positional name arguments
that stack within type. The legacy flags remain as single-value
back-compat aliases. See
[docs/clasi/sprints/002-positional-load-save-args-and-gitignore-todo-archive/sprint.md](docs/clasi/sprints/002-positional-load-save-args-and-gitignore-todo-archive/sprint.md)
for the full design and
[architecture-update.md](docs/clasi/sprints/002-positional-load-save-args-and-gitignore-todo-archive/architecture-update.md)
for the impact analysis.

**Implementation outline** (file-by-file):

1. **New helper** in [src/dotconfig/cli.py](src/dotconfig/cli.py) (or a
   small `src/dotconfig/_args.py` module if it grows):
   `_classify_load_args(names, config_dir) -> (deploys, locals)`
   - inspects `config/<name>/` and `config/local/<name>/`
   - raises `click.UsageError` for unknown, ambiguous (in both), or
     duplicate names
   - returns two ordered lists preserving command-line order within
     each type

2. **`load` command in [src/dotconfig/cli.py:96-256](src/dotconfig/cli.py#L96-L256)**:
   - add `@click.argument("names", nargs=-1)`
   - if `names` and (`-d` or `-l`) both present → `UsageError`
   - if `names`: classify them, build `deploys`/`locals` lists
   - if flags only: `deploys = [-d]` (or `[]`), `locals = [-l]` (or `[]`)
   - require `len(deploys) >= 1` for `.env` assembly mode
   - if `--json`/`--yaml` and (len(deploys) > 1 or len(locals) > 1):
     `UsageError("--json/--yaml only support single-layer for now")`

3. **`save` command in [src/dotconfig/cli.py:259-401](src/dotconfig/cli.py#L259-L401)**:
   - add `@click.argument("names", nargs=-1)`
   - if `names` and (`-d` or `-l`) both present → `UsageError`
   - lenient classifier for save: first positional → deploy, optional
     second → local; ≥3 positionals → `UsageError`. Names need not
     exist yet.
   - if neither names nor flags: round-trip from `.env` metadata
     (current behavior, generalized to lists)

4. **`load_config` in [src/dotconfig/load.py:355-534](src/dotconfig/load.py)**:
   - signature: `(deployments: list[str], locals_: list[str], …)`
     (use `locals_` to avoid shadowing the builtin)
   - `_read_env_layers` returns
     `(sops_config, [(label, text), ...])` pairs in layer order
     (deploys first, then locals; each layer contributes a public
     pair and a secrets pair)
   - classic-`.env` writer iterates the layer pairs, emitting one
     `#@dotconfig: <label>` block per pair
   - metadata header: write
     `# CONFIG_DEPLOYS=<csv>` / `# CONFIG_LOCALS=<csv>` when there is
     more than one of either, else write the legacy
     `# CONFIG_DEPLOY=<value>` / `# CONFIG_LOCAL=<value>` to preserve
     fixture/byte compatibility for single-layer
   - structured (json/yaml) branch: keep current shape; the CLI shim
     guarantees at most one deploy + one local before reaching this
     code

5. **`save_config` in [src/dotconfig/save.py:736-869](src/dotconfig/save.py)**:
   - signature: `override_deploys: list[str], override_locals: list[str]`
   - `parse_env_file` reads new keys first, falls back to legacy
     singular keys (`CONFIG_DEPLOY`, `CONFIG_LOCAL`, `CONFIG_COMMON`)
   - section-write loop iterates over the parsed deploys then locals
   - `_rewrite_deployment` continues to apply per-section against the
     destination deployment name (now possibly renamed to a single
     target via `save dev`)

6. **Help text + docstrings**: update `cli.py` examples on `load` and
   `save` to show the positional shorthand alongside the legacy flag
   form. Update the docstring of `load_config` / `save_config` /
   `parse_env_file` to mention the new lists and metadata keys.

7. **AGENTS.md** ([src/dotconfig/init.py:_AGENTS_MD_CONTENT](src/dotconfig/init.py#L290-L352)):
   update the "Quick reference" section to show the new shorthand
   forms. Existing tests assert on this content
   ([tests/test_init.py:_AGENTS_MD_CONTENT](tests/test_init.py)) so
   they will pick up the new content automatically (the test imports
   the constant).

## Acceptance Criteria

- [ ] `dotconfig load dev` assembles `.env` for the `dev` deployment.
- [ ] `dotconfig load dev eric` works (= `-d dev -l eric`).
- [ ] `dotconfig load eric dev` works (order across types is
      irrelevant; classifier sorts by type).
- [ ] `dotconfig load dev prod eric alice` produces a `.env` whose
      section markers appear in this order: `public (dev)`,
      `secrets (dev)`, `public (prod)`, `secrets (prod)`,
      `public-local (eric)`, `secrets-local (eric)`,
      `public-local (alice)`, `secrets-local (alice)`.
- [ ] `dotconfig load -d dev -l eric` (legacy form) still works.
- [ ] `dotconfig load dev -l eric` raises a usage error (no mixing).
- [ ] `dotconfig load nonexistent` raises a usage error naming the
      offending value.
- [ ] `dotconfig load dev dev` raises a usage error for duplicate.
- [ ] `dotconfig save` (no args) round-trips a multi-layer `.env`
      back to its source files via metadata.
- [ ] `dotconfig save dev` flattens the assembled `.env` into
      `config/dev/`, with `_rewrite_deployment` applied to each
      section.
- [ ] Single-layer load → single-layer save still writes
      `# CONFIG_DEPLOY=<value>` (legacy singular) for fixture parity.
- [ ] Multi-layer load writes `# CONFIG_DEPLOYS=<csv>` /
      `# CONFIG_LOCALS=<csv>`.
- [ ] `parse_env_file` reads `CONFIG_DEPLOYS`, `CONFIG_LOCALS`,
      `CONFIG_DEPLOY`, `CONFIG_LOCAL`, and `CONFIG_COMMON`.
- [ ] All 385 pre-existing tests still pass without modification.
- [ ] New tests cover: classifier behavior (8+ cases), multi-layer
      load assembly, multi-layer save round-trip, mixed positional+flag
      rejection, save-with-positional flatten.

## Testing

- **Existing tests to run**: `uv run pytest` (full suite — 385 tests).
- **New tests to write**:
  - `tests/test_args.py` (or extend `tests/test_cli.py`):
    classifier unit tests covering empty input, single deploy, single
    local, mixed, multi-deploy, multi-local, ambiguous, unknown,
    duplicate, lenient-save (non-existent name).
  - `tests/test_load.py` additions: multi-layer assembly produces
    expected section order; multi-layer metadata uses plural keys;
    single-layer keeps singular keys.
  - `tests/test_save.py` additions: round-trip multi-layer `.env`;
    `save dev` flatten; reader fallback for `CONFIG_COMMON`.
  - `tests/test_cli.py` additions (CliRunner):
    `load dev`, `load dev eric`, `load dev prod eric alice`,
    `load -d dev -l eric`, `load dev -l eric` (error),
    `load nonexistent` (error), `save`, `save dev`.
- **Verification command**: `uv run pytest`
