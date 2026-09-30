---
status: done
sprint: '007'
tickets:
- 007-001
- 007-002
---

# Add `dotconfig diff`: show what `save` would change, exit non-zero on differences

Requested 2026-09-30. There is no way to see how the working `.env` (or a
file) differs from what is saved in the config directory without saving it.
Add a `dotconfig diff` command that is the read-only mirror of
`dotconfig save`: it compares against exactly where `save` would write, and
prints a unified diff.

## Behavior

- `dotconfig diff` — compare the current `.env` to where `save` would write
  it (deployment/local taken from the `.env` metadata, same resolution as
  `save`). Compare section by section (public, secrets, public-local,
  secrets-local) against the decrypted saved files, and print a unified diff
  per section that differs, labeled with the saved file's path.
- `dotconfig diff devel` — positional deployment (same style as
  `load`/`save` positional args): compare the current `.env` against the
  `devel` deployment instead of the one in the metadata. `-d/--deploy` and
  `-l/--local` work as in `save`.
- `dotconfig diff --file app.yaml` (with `-d` or `-l`, same rules as
  `save --file`) — compare that local file against its saved copy in the
  config directory.
- `--env-file` and `--config-dir` options as in `save`.

## Exit status (like `diff(1)`)

- `0` — no differences.
- `1` — differences found (so scripts can do `dotconfig diff || dotconfig save`).
- `2` — error (no managed `.env`, missing deployment, decrypt failure, …).

## Notes

- Read-only: must not write, re-encrypt, or touch any file.
- Secrets are decrypted in memory for comparison; the diff prints secret
  values to stdout (it's the user's own terminal, and a diff without values
  is not useful). Never write decrypted content to disk.
- A saved file that doesn't exist yet counts as empty (everything shows as
  added). Ignore differences that `save` itself would not produce (e.g.
  `export ` prefixes / metadata comments), so `load` followed immediately by
  `diff` exits 0.
- Document the command in README.md alongside `save`.

## Acceptance

Tests: `load` then `diff` → exit 0, no output; edit a public value and a
secret value → exit 1 with both shown; `diff <other-deploy>` compares to that
deployment; `--file` against saved copy (same → 0, changed → 1); missing
deployment → exit 2.
