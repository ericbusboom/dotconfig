---
status: in-progress
sprint: '003'
tickets:
- 003-001
---
# Plan: `dotconfig version` + `dotconfig.yaml` as version source-of-truth

## Context

Today the dotconfig project version lives in `pyproject.toml` and is bumped
manually per the rules in `CLAUDE.md`. The user wants to model versioning the
way CLASI does (see [docs/versioning.md](/Users/eric/proj/code-projects/dotconfig/docs/versioning.md)),
but with three differences from the CLASI scheme:

1. The **source of truth** moves to `config/dotconfig.yaml` (key: `version`).
   `pyproject.toml`, `package.json`, and the active `.env` become *sync
   targets* that `bump` writes to whenever they exist.
2. The first `version` value at `init` time is seeded from `package.json` if
   it exists, else `pyproject.toml`. This bridges existing projects into the
   new scheme without forcing a number from thin air.
3. The user's `.env` carries a `_VERSION=<version>` line at the top whenever
   `dotconfig load` produces it. `dotconfig save` strips any `_VERSION=` line
   before writing back to the source files. The variable is therefore
   *dynamic* — it only exists in materialised `.env` output, never in
   `config/`.

The CLI surface mirrors CLASI: `dotconfig version` prints the current
version; `dotconfig version bump` advances it (with `--major`, `--tag`,
`--push`).

## Design

### 1. New module: `src/dotconfig/versioning.py`

Port [/Users/eric/proj/ai-project/clasi/clasi/versioning.py](/Users/eric/proj/ai-project/clasi/clasi/versioning.py)
verbatim, then make these changes:

- `_VERSION_FILES` becomes the list of *sync targets* (still
  `pyproject.toml` + `package.json`); add a third entry, `(".env",
  "dotenv_var")`, written via a new `update_dotenv_version()` helper.
- The **source-of-truth file** is no longer the first existing entry from
  `_VERSION_FILES`. It is fixed at `<config_dir>/dotconfig.yaml`, key
  `version`. `read_current_version()` and `bump_version()` both go through
  a new `read_dotconfig_version(config_dir)` /
  `write_dotconfig_version(config_dir, version)` pair.
- Drop CLASI-specific bits we don't need now:
  - `should_version()`, `load_version_trigger()`, `VALID_TRIGGERS`,
    `DEFAULT_TRIGGER` (CLASI auto-bump on sprint close — not relevant
    here; keep `version_trigger` field reserved in the yaml schema for
    future use but ignore it at runtime).
  - `load_version_source()` — source is fixed.
- Keep verbatim: `parse_format`, `_classify_token`, `format_has_auto`,
  `_format_segment`, `build_version`, `build_tag_regex`,
  `compute_next_version` (with one tweak: read current version from
  `dotconfig.yaml` instead of pyproject), `_get_existing_tags`,
  `update_pyproject_version`, `update_package_json_version`,
  `create_version_tag`.
- New helper: `update_dotenv_version(version, env_path) -> None` —
  rewrites or inserts a `_VERSION=<version>` line at the top of `.env`,
  preserving the rest. Only called when `env_path.exists()`.
- `bump_version(major, tag, project_root, config_dir)` returns a dict
  with: `version`, `source` (`config/dotconfig.yaml`), `synced` (the list
  of `pyproject.toml`/`package.json`/`.env` paths that were updated),
  `tag`. Sync targets are written best-effort: missing files are skipped.

Settings file path: the dotconfig-equivalent of CLASI's
`docs/clasi/settings.yaml`. Reuse `config/dotconfig.yaml` itself for the
rare optional knobs (`version_format`, `version_sync` if a project wants
extra targets). Default format remains `X+.YYYYMMDD.R+` (matches what
`pyproject.toml` already uses: `0.20260503.7`).

### 2. New helper in `src/dotconfig/init.py`

Add `_init_dotconfig_yaml(config_dir, project_root, quiet)`. Behaviour:

- Path: `config_dir / "dotconfig.yaml"`.
- If it already exists, leave it untouched (mirror `_create_env_if_missing`
  pattern, [init.py:398-410](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/init.py#L398)).
- If absent, seed the `version` value:
  1. From `<project_root>/package.json` `version` field, if present.
  2. Else from `<project_root>/pyproject.toml` `[project] version`, if
     present.
  3. Else `"0.0.0"` (no auto-format magic at init time — `bump` is the
     only place that computes formatted values).
- Write a minimal yaml file:
  ```yaml
  # dotconfig project metadata.
  # Edit `version` only via `dotconfig version bump`.
  version: <seed>
  ```
- `project_root` is `config_dir.parent` for the standard layout.

Hook the call into `init_config` between `_init_env_files` (init.py:494)
and `_write_agents_md` (init.py:499), under a `heading("📌 Project
metadata:")` line — gated on `not quiet`.

### 3. CLI wiring: `src/dotconfig/cli.py`

Add a top-level `version` group modelled on the existing `key` group
([cli.py:704-715](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/cli.py#L704)):

```python
@cli.group(invoke_without_command=True)
@click.pass_context
def version(ctx):
    """Show the project version (or run a subcommand)."""
    if ctx.invoked_subcommand is None:
        v = read_dotconfig_version(_resolve_config_dir(ctx) or Path("config"))
        if v is None:
            click.echo("No version set. Run: dotconfig init", err=True)
            sys.exit(1)
        click.echo(v)


@version.command("bump")
@click.option("--major", type=int, default=0)
@click.option("--tag", is_flag=True)
@click.option("-p", "--push", is_flag=True)
@click.pass_context
def version_bump(ctx, major, tag, push):
    ...
```

`bump` semantics (mirrors CLASI):

- Compute next version using `compute_next_version(major, config_dir)`.
- Write `config/dotconfig.yaml`.
- Write `pyproject.toml`, `package.json`, `.env` if any of them exist.
- With `--tag`: create lightweight `v<version>` tag.
- With `--push`: pre-flight clean-master check; bump + commit
  (`pyproject.toml`, `package.json`, `config/dotconfig.yaml` — every
  file we wrote, not `.env`); tag; `git push --tags`. We do *not* commit
  the materialised `.env` because it's gitignored.
- `_resolve_config_dir(ctx)` provides the config dir; `Path.cwd()` is
  the project root.

### 4. `dotconfig load` — inject `_VERSION`

In `src/dotconfig/load.py` `load_config()`, after
`_build_metadata_header()` builds its list of `# CONFIG_*=` comment
lines ([load.py:766-768](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/load.py#L766)),
read `config_dir / "dotconfig.yaml"`. If it has a `version:` field,
prepend `_VERSION=<version>` to `parts` (after the metadata header,
before the first `#@dotconfig:` section).

Scope: only the classic `.env` text output path
([load.py:766-830](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/load.py#L766)).
The structured (JSON/YAML) and split paths are untouched — `_VERSION` is
an env-var convention, not a structured-data convention.

`load_dotconfig_yaml(config_dir) -> dict | None` becomes a small helper
in `versioning.py` reused by both load and the new `read_dotconfig_version`.

### 5. `dotconfig save` — strip `_VERSION`

In `src/dotconfig/save.py`, modify `_parse_env_layers`
([save.py:355-417](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/save.py#L355))
to skip any line matching `^_VERSION=` regardless of which section it's
in. Add the filter in the `current_section is not None` branch
(line 411-412) so even malformed input where the user moved `_VERSION`
into a section gets the line dropped.

Also handle the path that doesn't go through `_parse_env_layers` — the
single-deployment legacy path that just dumps a flat `.env` into one
file. Search for the analogous parse/write site and apply the same
filter, or factor the strip into a top-level helper applied to the raw
`.env` content as the very first thing `save_config()` does. Defer the
exact placement decision to implementation time after re-reading
`save_config` end-to-end.

### 6. `dotconfig.yaml` schema (initial)

```yaml
# version of record. Bump with `dotconfig version bump`.
version: 0.20260503.7

# Optional. Default: "X+.YYYYMMDD.R+"
# version_format: X+.YYYYMMDD.R+

# Optional. Extra files to receive the version on bump.
# version_sync:
#   - frontend/package.json
```

Init writes only the `version` line; the others are documented in
comments but absent unless the user adds them.

## Critical files

| Action | Path |
|---|---|
| New | [src/dotconfig/versioning.py](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/versioning.py) |
| Modify | [src/dotconfig/init.py](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/init.py) — add `_init_dotconfig_yaml`, call it from `init_config` |
| Modify | [src/dotconfig/cli.py](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/cli.py) — add `version` group + `bump` subcommand; import `read_dotconfig_version`, `bump_version` |
| Modify | [src/dotconfig/load.py](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/load.py) — inject `_VERSION=…` into classic `.env` output |
| Modify | [src/dotconfig/save.py](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/save.py) — strip `_VERSION=…` lines in `_parse_env_layers` |
| New tests | tests/test_versioning.py |
| Update tests | [tests/test_init.py](/Users/eric/proj/code-projects/dotconfig/tests/test_init.py) — assert `dotconfig.yaml` is created with seeded version |
| Update tests | [tests/test_load.py](/Users/eric/proj/code-projects/dotconfig/tests/test_load.py) — `_VERSION` appears in classic env output |
| Update tests | [tests/test_save.py](/Users/eric/proj/code-projects/dotconfig/tests/test_save.py) — `_VERSION` is stripped on save |

## Reused functions

- `_resolve_config_dir(ctx)` — [cli.py:136-145](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/cli.py#L136). Already used by every subcommand; reuse for both `version` and `version bump`.
- `_build_metadata_header()` — [load.py:833](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/load.py#L833). Insertion point sits right after this call.
- `_parse_env_layers()` — [save.py:355](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/save.py#L355). Skip-`_VERSION` filter goes here.
- `_create_env_if_missing()` pattern — [init.py:398-410](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/init.py#L398). Mirror for `_init_dotconfig_yaml`.
- `import yaml` is already used in init.py, save.py, load.py — no new dependency.
- The `key` command group at [cli.py:704-715](/Users/eric/proj/code-projects/dotconfig/src/dotconfig/cli.py#L704) is the structural model for the new `version` group.

## Verification

End-to-end smoke test in `tests/proj`:

```sh
# 1. init seeds version from pyproject.toml when no package.json exists
cd /tmp && rm -rf dctest && mkdir dctest && cd dctest
echo '[project]\nversion = "0.20260503.7"' > pyproject.toml
dotconfig init -q
cat config/dotconfig.yaml      # expect: version: 0.20260503.7

# 2. version subcommand prints it
dotconfig version              # expect: 0.20260503.7

# 3. bump advances revision
dotconfig version bump         # expect: 0.20260503.8 (or today's date)
grep '^version' pyproject.toml # expect: same string
grep '^version' config/dotconfig.yaml  # same

# 4. load injects _VERSION
dotconfig load dev             # produces .env
head -5 .env                   # expect: _VERSION=0.20260503.8 near top
grep '^_VERSION' .env          # exits 0

# 5. save strips it
echo '_VERSION=manual-edit-should-vanish' >> .env
dotconfig save dev
grep -r '_VERSION' config/     # expect: no matches

# 6. bump --tag creates a tag
git init && git add . && git commit -m initial
dotconfig version bump --tag
git tag -l                     # expect: v<new-version>

# 7. seeding from package.json takes priority
cd /tmp && rm -rf dctest2 && mkdir dctest2 && cd dctest2
echo '{"version":"1.2.3"}' > package.json
echo '[project]\nversion = "9.9.9"' > pyproject.toml
dotconfig init -q
grep '^version' config/dotconfig.yaml   # expect: 1.2.3
```

Plus pytest:

```sh
uv run pytest tests/test_versioning.py tests/test_init.py \
              tests/test_load.py tests/test_save.py -v
uv run pytest                  # full suite — should be green
```

## Out of scope

- CLASI's `version_trigger` auto-bump-on-event mechanism. Reserved as a
  yaml field but not wired.
- Cargo / setup.cfg / other version-file types. Easy to add later via
  the same `_file_type_for` dispatch.
- A `--no-tag-push` flag on `--push`. CLASI's `--push` always pushes
  tags; we do the same for parity.
- Changing the existing manual versioning convention in `CLAUDE.md`.
  After this lands, that doc should be updated to say "use
  `dotconfig version bump`" — but that's a docs-only follow-up.
