# CLASI Versioning — Reference for Porting

This document describes how `clasi version` and `clasi version bump`
work, in enough detail to port the same scheme into another tool. The
reference implementation lives in [clasi/versioning.py](../clasi/versioning.py)
(self-contained, ~500 lines, only stdlib + `pyyaml`).

The CLI surface is in [clasi/cli.py](/Users/eric/proj/ai-project/clasi/clasi/versioning.py) under the
`version` group.

---

## Default version format

```
X+.YYYYMMDD.R+
```

Three dot-separated segments:

| Segment       | Meaning                                                                                |
|---------------|----------------------------------------------------------------------------------------|
| `X+`          | Manual major number, variable digits. Defaults to `0`. Set with `--major`.             |
| `YYYYMMDD`    | Today's UTC-local date at the moment `bump` runs.                                      |
| `R+`          | Auto-incrementing daily revision. Resets to 1 each new date.                           |

Example progression on a single day:

```
0.20260503.1   ← first bump of the day
0.20260503.2   ← second bump
0.20260503.3
0.20260504.1   ← next day, revision resets
```

The "manual major" segment is for breaking-change bumps the human
controls. The date-and-revision tail is auto-computed and is what
makes successive bumps monotonic without bookkeeping.

The format string is configurable per project (see
[Configuration](#configuration) below). The format engine supports
fully-manual schemes too (e.g. `XX.X.X` for classic semver-shaped
versions), but those don't auto-compute — you pass `--major` and the
caller is responsible for the rest.

---

## Where versions are stored

### Source file (the version of record)

`bump` looks for one of these files in the project root, in priority
order:

1. `pyproject.toml` — Python projects. The `version = "..."` field at
   the top of the `[project]` table.
2. `package.json` — Node projects. The top-level `"version"` field.

The first one that exists is the **source file**. The version stored
there is the canonical version of the project.

The settings file can override priority:

```yaml
# docs/clasi/settings.yaml
version_source: pyproject.toml
```

### Sync files (copies)

Some projects keep the version in more than one place — e.g. a Python
package that also ships a `package.json` for tooling. List those
extra files in settings:

```yaml
# docs/clasi/settings.yaml
version_sync:
  - frontend/package.json
  - api/pyproject.toml
```

`bump` writes the source file first, then writes the same version
string into every sync file. Sync files must be one of the supported
types (`pyproject.toml` or `package.json`); the file extension is
sufficient — the dispatch function in
[clasi/versioning.py](../clasi/versioning.py) is `_file_type_for`.

### Git tags

The other source of truth is the set of git tags matching the version
format. Tags are formatted as `v<version>`:

```
v0.20260503.1
v0.20260503.2
v0.20260503.3
```

The tag set is what `bump` consults to compute the next revision when
the format includes auto-computed segments. **Tags are never assumed
to match the source file** — `bump` reconciles both sources to find
the next revision number.

---

## How `bump` computes the next version

For formats with auto-computed segments (the default
`X+.YYYYMMDD.R+`), the algorithm is:

1. Parse the configured format into typed tokens (manual, date, rev,
   dot). See `parse_format()` in [clasi/versioning.py](../clasi/versioning.py).
2. Build a regex from the format that names each segment as a group
   (`manual_0`, `year`, `month`, `day`, `rev`). See `build_tag_regex()`.
3. Walk every existing git tag. For each tag that matches the regex
   AND has the same manual segments as the requested major AND has
   the same date prefix as today, extract the revision number.
4. Also read the version currently in the source file. Apply the same
   regex; if it matches and the date prefix is today, extract its
   revision number too.
5. The next revision is `max(all_extracted_revisions) + 1`. If no tag
   or current version matches today's date, the next revision is `1`.
6. Build the new version string with today's date and the new
   revision.

For fully-manual formats (no `R` or date tokens), `bump` just emits
the manual values as-is — there is no auto-computation.

The "consider the current version too" step in (4) is what lets
sequential `bump` calls advance even when `--tag` is not used. Without
it, two bumps in a row without intervening tags would both produce
the same revision number.

---

## What `bump` writes

A successful `bump` call performs these writes, in order:

1. **Source file**: writes `version = "<new>"` (TOML) or
   `"version": "<new>"` (JSON) in place. For TOML, a regex replace on
   the first matching `version =` line. For JSON, a parse, mutate,
   re-serialize round-trip with 2-space indent and a trailing newline.
2. **Sync files**: same logic as the source file, dispatched by file
   type, for every path listed in `version_sync`. Missing sync files
   are silently skipped (so it's safe to list a path that only exists
   in some checkouts).
3. **Git tag** (if `--tag` or `--push`): runs `git tag v<new>`. Tag is
   un-annotated (lightweight). Failure (e.g. tag already exists)
   raises a `RuntimeError`.
4. **Commit and push** (if `--push` only): see [push mode](#push-mode)
   below.

`bump` returns a dict with the new version, the source file path, the
list of sync paths actually updated, and the tag name (or `None`).

---

## CLI surface

### `clasi version`

No subcommand — print the current version from the source file.

```sh
$ clasi version
0.20260503.2
```

Exits with code 1 and a stderr message if no version file is found.

### `clasi version bump`

Compute the next version, write source + sync files. **Does not tag
or commit by default.**

```sh
$ clasi version bump
Version: 0.20260503.3
Updated: pyproject.toml
```

#### `--major N`

Override the manual major segment (default: 0).

```sh
$ clasi version bump --major 1
Version: 1.20260503.1
```

When `--major` changes, the revision search filters to tags with that
major value — so changing major resets the daily revision count for
that major.

#### `--tag`

Also create the `v<version>` git tag locally. Does not push.

```sh
$ clasi version bump --tag
Version: 0.20260503.4
Updated: pyproject.toml
Tagged:  v0.20260503.4
```

#### `--push` / `-p`

Pre-flight: must be on `master` or `main` with a clean working tree
(else aborts). Then:

1. `bump` (writes source + sync, no tag yet).
2. `git add pyproject.toml`.
3. `git commit -m "chore: bump version to <new>"`.
4. `git tag v<new>`.
5. `git push --tags`.

This is the "release on master" shortcut. The clean-tree check exists
because pushing tags from a dirty tree leaves the tag pointing at a
commit that doesn't reflect the working state.

`--push` does not push branch commits — only tags. The branch push is
the caller's responsibility (a separate `git push`).

---

## Configuration

All settings live in `docs/clasi/settings.yaml` (with `docs/plans/settings.yaml`
as a fallback path for non-CLASI projects):

```yaml
# Optional. Controls the version format. Default: "X+.YYYYMMDD.R+"
version_format: X+.YYYYMMDD.R+

# Optional. When the version is bumped automatically.
# - manual:        never auto-bump; only `clasi version bump` does anything
# - every_sprint:  bump only at sprint close (CLASI-specific)
# - every_change:  bump after every change (default; integrates with the
#                  commit-check hook)
version_trigger: every_change

# Optional. Force a specific source file, overriding auto-detect priority.
version_source: pyproject.toml

# Optional. Extra files to receive the same version after each bump.
version_sync:
  - frontend/package.json
  - api/pyproject.toml
```

Missing or unparseable `settings.yaml` → all defaults apply. The
`version_trigger` setting is a CLASI-specific concept and only fires
from CLASI's `close_sprint` and hook code; a porter can ignore it if
they don't need automatic bumping.

### Format token reference

| Token   | Meaning                                                       |
|---------|---------------------------------------------------------------|
| `X`     | Manual segment, exactly 1 digit                               |
| `XX`    | Manual segment, exactly 2 digits                              |
| `0XX`   | Manual segment, 2 digits zero-padded                          |
| `0XXX`  | Manual segment, 3 digits zero-padded                          |
| `X+`    | Manual segment, variable digits                               |
| `YYYY`  | 4-digit year                                                  |
| `MM`    | 2-digit month                                                 |
| `DD`    | 2-digit day                                                   |
| `R`     | Auto-incrementing revision, 1 digit                           |
| `RR`    | Revision, 2 digits                                            |
| `0RR`   | Revision, 2 digits zero-padded                                |
| `0RRR`  | Revision, 3 digits zero-padded                                |
| `R+`    | Revision, variable digits                                     |
| `.`     | Literal dot                                                   |

Formats are parsed left-to-right, longest-match-first. Anything that
isn't one of these tokens raises `ValueError`. See `parse_format()`
and `_TOKEN_RE` in [clasi/versioning.py](../clasi/versioning.py).

---

## Synchronizing with GitHub tags

The "tag synchronization" story has two parts: **finding the next
revision** (read) and **publishing the new tag** (write). Each is a
separate `git` subprocess; there is no GitHub API call anywhere.

### Read: finding the next revision

`compute_next_version()` in [clasi/versioning.py](../clasi/versioning.py)
runs:

```sh
git tag -l
```

It does NOT run `git fetch`. The tag set it sees is the local repo's
view. **If you bump on a stale checkout, you can collide with a tag
that exists on the remote but not locally.**

The recommended pre-bump invariant for any porter:

```sh
git fetch --tags origin     # reconcile remote tags
clasi version bump --tag    # now compute against fresh state
```

The `--push` mode does NOT include a fetch; it trusts that the user
has just pulled. The pre-flight clean-tree check helps but does not
fully prevent a stale-tags collision. If `git tag v<new>` fails
because the tag exists on the remote, `bump` raises `RuntimeError`
and leaves the source file already updated — re-run after fetching.

### Write: publishing the tag

Two paths:

1. **`--tag` only** — creates the tag locally. The user pushes it
   later with `git push --tags` or `git push origin v<new>`.
2. **`--push`** — runs `git push --tags` after committing and
   tagging. This pushes ALL local tags that aren't on the remote, not
   just the one just created. That's normally fine; it's only a
   problem if your local repo has stale experimental tags.

The `close_sprint` MCP tool follows the `--push` flow (commit, tag,
`git push --tags`) but as a separate step in its multi-step pipeline.
The actual git invocations are in
[clasi/tools/artifact_tools.py](../clasi/tools/artifact_tools.py)
around the `# ── Step 7: Push tags ──` comment.

### Pushing is per-call

There is no daemon, no background sync, no scheduled re-tagging. Every
tag publish is the result of an explicit user command. If a tag is
missing on the remote, run `git push --tags` manually.

### Annotated vs lightweight

`create_version_tag()` runs `git tag <name>` with no `-a` and no
`-m` — these are **lightweight tags**. If your project policy
requires annotated tags, change the call to:

```python
subprocess.run(["git", "tag", "-a", tag_name, "-m", tag_name], ...)
```

Both lightweight and annotated tags appear in `git tag -l` and both
push the same way, so the read path is unaffected by which kind you
use.

---

## Rules and invariants

These are the guarantees the implementation aims for. A porter should
preserve them.

1. **Successive bumps on the same day always increase the revision.**
   Even without `--tag`, the next bump reads the current source file
   and increments past it.
2. **A new day resets the revision to 1.** No matter how many bumps
   happened yesterday.
3. **Source file is the single write target.** Sync files mirror it;
   they never contribute to the revision search. If a sync file
   diverges from the source, the next bump silently overwrites it.
4. **Tags are read from local git only.** No GitHub API, no remote
   fetch. Caller is responsible for `git fetch --tags` before bump if
   tag freshness matters.
5. **`--push` requires clean master/main.** No exceptions. The check
   is in [clasi/cli.py](../clasi/cli.py) at the top of `version_bump`.
6. **Failure modes leave partial state.** If the source file write
   succeeds but the tag command fails (e.g. tag exists), the source
   file is already updated. Re-running after fixing the underlying
   issue (typically `git fetch --tags`) will roll the revision
   forward and try again.
7. **No version downgrade path.** The math only ever picks
   `max(...) + 1`. If you need to go backwards (rare; usually for
   reverting a bad release), do it manually: edit the file, delete
   the tag, push the deletion.
8. **Lightweight tags by default.** Switch to annotated in
   `create_version_tag()` if you need GPG signing or release notes.

---

## Porting checklist

To replicate this scheme in another tool:

1. Copy [clasi/versioning.py](../clasi/versioning.py) — it depends
   only on stdlib + `pyyaml`. No CLASI-specific imports.
2. Wire a CLI command (`yourtool version` and `yourtool version bump`).
   The CLI in [clasi/cli.py](../clasi/cli.py) under the `version`
   group is ~80 lines and is straight `click` — port directly or
   translate to `argparse`.
3. Decide where settings live. CLASI uses `docs/clasi/settings.yaml`;
   change `_load_settings()` to point at your tool's settings path.
4. Decide your tool's "trigger" semantics. CLASI fires automatic
   bumps from `close_sprint` and from a post-tool-use hook. A simpler
   tool might just trigger on `your-tool release` or never auto-bump
   at all (set default to `manual`).
5. Add additional version-file types if you need them. The dispatch
   in `_file_type_for()` and `update_version_file()` is small;
   `Cargo.toml` or `setup.cfg` would each be ~10 lines.
6. Decide your tag style: lightweight (current default) vs annotated.
   Add a `git push --tags` step somewhere appropriate.
7. Document your invariants for callers — the rules in
   [Rules and invariants](#rules-and-invariants) above are a starting
   template. The "successive bumps advance even without tags" and
   "tags are read locally only" rules in particular surprise people.

---

## File map

| File                                                          | Purpose                                                                                  |
|---------------------------------------------------------------|------------------------------------------------------------------------------------------|
| [clasi/versioning.py](../clasi/versioning.py)                 | All version logic. Self-contained; copy directly.                                        |
| [clasi/cli.py](../clasi/cli.py) (`version` group)             | The `clasi version` and `clasi version bump` CLI commands.                               |
| [clasi/tools/artifact_tools.py](../clasi/tools/artifact_tools.py) | The MCP tools `tag_version` and `close_sprint`. Both call into `versioning.py`. Optional for porters. |
| `docs/clasi/settings.yaml` (per-project)                      | Runtime configuration: format, trigger, source override, sync list. Optional.            |
