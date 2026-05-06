---
id: '003'
title: 'cli.py: version group and bump subcommand'
status: done
use-cases:
- SUC-002
- SUC-003
depends-on:
- '001'
github-issue: ''
todo: ''
completes_todo: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# cli.py: version group and bump subcommand

## Description

Add a top-level `version` command group to `cli.py`, modelled on the existing
`key` group (lines 700–715). Invoked without a subcommand it prints the current
version; the `bump` subcommand delegates all logic to `versioning.bump_version`.

## Acceptance Criteria

- [x] `dotconfig version` prints the version string from `config/dotconfig.yaml`
      to stdout and exits 0.
- [x] `dotconfig version` exits 1 with a stderr message if `config/dotconfig.yaml`
      is absent or has no `version` field.
- [x] `dotconfig version bump` computes and writes the next version; prints a
      summary to stdout (version, files updated).
- [x] `dotconfig version bump --major N` sets the major segment to N.
- [x] `dotconfig version bump --tag` additionally creates a `v<version>` git tag.
- [x] `dotconfig version bump --push` / `-p`: pre-flight clean-master check;
      commit all written files (except `.env`); tag; `git push --tags`.
- [x] `dotconfig version bump --push` aborts with an error if the working tree
      is dirty or not on `master`/`main`.
- [x] `cli.py` imports `read_dotconfig_version` and `bump_version` from
      `dotconfig.versioning`.
- [x] `_resolve_config_dir(ctx)` is reused to locate `config/` for both
      `version` and `version bump`.
- [x] Existing CLI commands are unaffected.
- [x] `uv run pytest` exits 0.

## Implementation Plan

### Approach

1. Read `cli.py` lines 700–730 (the `key` group) as the structural model.
2. Read `cli.py` lines 136–145 (`_resolve_config_dir`) to understand config dir
   resolution.
3. Add imports near the top of the imports block:
   ```python
   from .versioning import read_dotconfig_version, bump_version
   ```
4. Add the `version` group after the `key` group (or in alphabetical order with
   other top-level groups):
   ```python
   @cli.group(invoke_without_command=True)
   @click.pass_context
   def version(ctx):
       """Show or manage the project version."""
       if ctx.invoked_subcommand is None:
           cfg = _resolve_config_dir(ctx) or Path("config")
           v = read_dotconfig_version(cfg)
           if v is None:
               click.echo("No version found. Run: dotconfig init", err=True)
               sys.exit(1)
           click.echo(v)
   ```
5. Add the `version bump` subcommand:
   ```python
   @version.command("bump")
   @click.option("--major", type=int, default=0, help="Major version number.")
   @click.option("--tag", is_flag=True, help="Create a git tag.")
   @click.option("-p", "--push", is_flag=True, help="Commit, tag, and push.")
   @click.pass_context
   def version_bump(ctx, major, tag, push):
       """Compute and write the next version."""
       cfg = _resolve_config_dir(ctx) or Path("config")
       result = bump_version(
           major=major, tag=tag or push, project_root=Path.cwd(), config_dir=cfg
       )
       click.echo(f"Version: {result['version']}")
       for p in result.get("synced", []):
           click.echo(f"Updated: {p}")
       if result.get("tag"):
           click.echo(f"Tagged:  {result['tag']}")
       if push:
           # push logic delegated to versioning.bump_version or inline here
           ...
   ```
   Note: the `--push` pre-flight check (clean master/main) and `git push --tags`
   may be implemented inline in this command or in `bump_version` with a
   `push=True` parameter. Decide during implementation; either approach is
   acceptable as long as the pre-flight check happens before any writes.

### Files to Modify

- `src/dotconfig/cli.py` — add `version` group and `version_bump` subcommand,
  new imports.

### Testing Plan

- `dotconfig version` in a temp dir with `config/dotconfig.yaml` → prints version.
- `dotconfig version` with no `dotconfig.yaml` → exits 1, stderr message.
- `dotconfig version bump` → version advances, `dotconfig.yaml` updated.
- `dotconfig version bump --major 1` → major segment = 1.
- `dotconfig version bump --tag` in a git repo → tag created.
- `dotconfig version bump --push` in a dirty tree → aborts.
- Existing CLI smoke tests (`uv run pytest tests/test_cli.py` if it exists) pass.

### Documentation Updates

None required for this ticket (help text is self-documenting via Click).
