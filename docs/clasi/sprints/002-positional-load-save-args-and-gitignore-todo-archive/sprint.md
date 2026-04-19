---
id: "002"
title: "Positional load/save args and gitignore TODO archive"
status: planning
branch: sprint/002-positional-load-save-args-and-gitignore-todo-archive
use-cases:
- SUC-001
- SUC-002
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 002: Positional load/save args and gitignore TODO archive

## Goals

1. Replace mandatory `-d/--deploy` and `-l/--local` flags on
   `dotconfig load` and `dotconfig save` with positional name arguments
   that can stack across both deployments and local overrides.
2. Archive the `plan-init-creates-gitignore-for-env-files.md` TODO
   (the implementation already shipped in commit `3d2f36e` but the
   TODO file was never moved to `done/`).

## Problem

Today, `load` and `save` require explicit flags:

    dotconfig load -d dev -l eric
    dotconfig save -d dev -l eric

For the common case the flags are noise. They also don't extend
naturally to layering more than one deployment or more than one local
override on top of each other — there is no shorthand for
"dev then prod, with eric's overrides then alice's".

Separately, an old TODO (`plan-init-creates-gitignore-for-env-files.md`)
has been complete in code for several commits but is still listed as
`pending` in `docs/clasi/todo/`, polluting the active TODO list.

## Solution

### Positional args (primary work)

Accept positional name arguments on `load` and `save`. The behavior of
the classifier differs by command:

**`load` classifier (strict)**: every positional name must match an
existing directory under `config/`. Each argument is classified by
directory existence:

- `config/<name>/`            → deployment
- `config/local/<name>/`      → local override
- present in both, or absent  → `click.UsageError`
- duplicate name within the same invocation (e.g. `load dev dev`) →
  `click.UsageError`

**`save` classifier (lenient)**: positional names go straight to the
destination — they may name directories that don't yet exist (the
typical "materialize a new deployment" case). The first positional is
the destination deployment, the optional second positional is the
destination local. More than two positionals on `save` → `UsageError`.
This matches today's `save -d <new> -l <new>` behavior, which already
auto-creates directories.

Order on the command line is the layer order *within each type*; the
final assembly applies layers in `[deploys..., locals...]` order with
later layers overriding earlier ones.

    dotconfig load dev eric              # = -d dev -l eric
    dotconfig load dev prod eric alice   # deps:[dev,prod]  locals:[eric,alice]
    dotconfig load eric dev              # type-stacking is order-independent
                                          # ACROSS types but order-significant
                                          # WITHIN each type
    dotconfig save                       # round-trip to whatever was loaded
    dotconfig save dev                   # rewrite the assembled file as
                                          # the single deployment "dev"
                                          # (flattens any stacked layers
                                          # in the loaded .env; equivalent
                                          # to today's `save -d dev`)

The existing `-d/--deploy` and `-l/--local` flags are kept (visible) as
backward-compatible single-value aliases. If both positional and flag
forms are supplied, raise a usage error.

**`.env` metadata format.** The writer prefers the new keys:
`# CONFIG_DEPLOYS=dev,prod`, `# CONFIG_LOCALS=eric,alice`. When there
is exactly one deployment and zero-or-one locals, the writer emits the
*legacy singular* keys instead (`# CONFIG_DEPLOY=dev`,
`# CONFIG_LOCAL=eric`) so single-layer files stay byte-identical to
what previous versions wrote — this preserves test fixtures that grep
for the literal `# CONFIG_DEPLOY=` string.

The reader accepts all four keys, plus the very-legacy
`# CONFIG_COMMON=` (already a fallback in `parse_env_file`):

- `CONFIG_DEPLOYS` (new, list)   — wins when present
- `CONFIG_LOCALS`  (new, list)   — wins when present
- `CONFIG_DEPLOY`  (legacy, single) → `[value]`
- `CONFIG_LOCAL`   (legacy, single) → `[value]`
- `CONFIG_COMMON`  (very-legacy, single, alias for `CONFIG_DEPLOY`) → `[value]`

The `#@dotconfig: <section>` markers already include the
deployment/local name, so per-section round-tripping continues to work
unchanged across all metadata variants.

**`save -d <name>` / `save <name>` and `_rewrite_deployment`.** Today,
`save_config` rewrites the inline `DEPLOYMENT=` variable inside each
section body when the destination differs from the loaded source
([src/dotconfig/save.py:235-241, 806-808](src/dotconfig/save.py)).
For multi-deploy stacks, the rewrite target with `save dev` is
unambiguous: every section's `DEPLOYMENT=` line is rewritten to `dev`,
because the user has explicitly asked to flatten the assembly into
that single deployment. No semantic surprise — the existing rewrite
helper applies once per section against the new single target.

### Gitignore TODO archive (housekeeping)

Verify the shipped behavior in `src/dotconfig/init.py:_update_gitignore`
matches the TODO spec, then move
`docs/clasi/todo/plan-init-creates-gitignore-for-env-files.md` to
`docs/clasi/todo/done/` with frontmatter linking it to this sprint.
No code changes.

## Success Criteria

- `dotconfig load dev` and `dotconfig load dev eric` work with no flags.
- `dotconfig load dev prod eric alice` produces an assembled `.env`
  whose layer order matches `dev → prod → eric → alice` (last wins).
- `dotconfig save` round-trips back to all loaded layers.
- `dotconfig save dev` rewrites the entire assembly into `config/dev/`.
- The legacy `dotconfig load -d dev -l eric` invocation still works.
- A name that is neither a deployment nor a local fails with a clear
  error.
- All existing 385 tests still pass; new tests cover stacking, mixed
  ordering, error cases, and round-trip with multi-layer metadata.
- Gitignore TODO is in `docs/clasi/todo/done/` with sprint linkage.

## Scope

### In Scope

- Positional argument support on `load` and `save` Click commands.
- Multi-deployment + multi-local layering in `load_config` /
  `save_config`.
- Backward-compatible `-d` / `-l` single-value flags.
- New `CONFIG_DEPLOYS` / `CONFIG_LOCALS` metadata + reading legacy
  `CONFIG_DEPLOY` / `CONFIG_LOCAL`.
- Tests covering all of the above.
- Archiving the gitignore TODO file with sprint/ticket linkage.

### Out of Scope

- Changing `--file` / `--json` / `--yaml` / `--flat` / `--split`
  behavior or argument shape.
- Changing the structured (JSON/YAML) layout for multi-layer.
  The first iteration writes structured output using only the *first*
  deployment + *first* local; if multiple are stacked, the structured
  format raises a usage error pointing to `--flat` for now. Full
  multi-layer structured output is a follow-up sprint.
- Hiding the `-d` / `-l` flags behind a deprecation warning. (Recommend
  one-release grace period; deprecation noise is a separate change.)
- `dotconfig key`, `gh-push`, `audit`, or `init` arg surfaces.

## Test Strategy

- **Unit tests** for the new argument classifier
  (`_classify_positional_args` or similar) covering: empty input, one
  deployment, one local, mixed order, multiple deployments, multiple
  locals, ambiguous name (exists as both), unknown name, duplicate
  name within one invocation, and (for the lenient `save` variant)
  not-yet-existing names.
- **Unit tests** for `load_config` with stacked layers, asserting that
  the assembled `.env` has the right section markers in the right order
  and that last-wins semantics hold.
- **Unit tests** for `save_config` reading the new `CONFIG_DEPLOYS` /
  `CONFIG_LOCALS` metadata and writing each section back to the right
  file.
- **CLI tests** with `click.testing.CliRunner`:
  - `dotconfig load dev` (no local)
  - `dotconfig load dev eric`
  - `dotconfig load dev prod eric alice`
  - `dotconfig load -d dev -l eric` (legacy)
  - `dotconfig load dev -l eric` (mixed positional + flag → error)
  - `dotconfig load nonexistent` (error path)
  - `dotconfig save` (round-trip multi-layer)
  - `dotconfig save dev` (whole-file rewrite)
- **Backward-compat regression**: existing tests in
  `tests/test_load.py` and `tests/test_save.py` must pass without
  modification (or with only metadata-key updates if they parse the
  comments).
- **Verification command**: `uv run pytest`.

## Architecture Notes

- New private helper in `src/dotconfig/cli.py` (or a small new
  `src/dotconfig/_args.py`) to classify positional names against the
  config directory.
- `load_config` signature changes from `deployment: str, local:
  Optional[str]` to `deployments: list[str], locals: list[str]`. CLI
  shim builds those lists from positional + flag inputs.
- `save_config` `override_deploy` / `override_local` likewise become
  lists; `parse_env_file` parses `CONFIG_DEPLOYS` / `CONFIG_LOCALS`
  with fallback to legacy single-value keys.
- `_read_env_layers` becomes `_read_env_layers_multi` (or is rewritten
  in place) to iterate over the layer lists in order, returning
  `(sops_config, [(label, text), ...])` pairs.
- The classic `.env` writer iterates over the same layer list,
  emitting `#@dotconfig: public ({deploy})`, `secrets ({deploy})`,
  `public-local ({local})`, `secrets-local ({local})` markers per
  layer.

## GitHub Issues

None.

## Definition of Ready

Before tickets can be created, all of the following must be true:

- [x] Sprint planning documents are complete (sprint.md, use cases, architecture)
- [ ] Architecture review passed
- [ ] Stakeholder has approved the sprint plan

## Tickets

| # | Title | Depends On | Group |
|---|-------|------------|-------|
| 1 | Archive gitignore TODO (verify-and-move only) | — | 1 |
| 2 | Positional args + multi-layer load/save | — | 1 |

**Groups**: Tickets in the same group can execute in parallel.
Groups execute sequentially (1 before 2, etc.).
