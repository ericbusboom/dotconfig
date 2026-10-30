---
status: open
---

# Plan: `dotconfig audit` reports open plaintext files; `dotconfig close` puts them away

## Context

`dotconfig load` writes plaintext secrets to disk (`.env`, `.env.json`,
`.env.yaml`, `.env.secret`, files under `config/files/`). They stay until
someone deletes them. On 2026-10-22 gala had **23** such `.env` files across
dotconfig repos, some from June; crispin had 17, pippin 6. Six of gala's
differed from their store, so deleting them blindly could lose a secret that
was never saved. The other direction is also a trap: saving a *stale* `.env`
overwrites newer secrets in the store (this once lost
`TORTURE_OPENWRT_ROOT_PASSWORD` in busboom-home-network).

The user wants:

1. One command that shows, across all project directories, which plaintext
   files are open, and for each one whether it can just be deleted or must be
   saved first.
2. A nightly job (busboom-home-network, `services/cron`) that saves what
   needs saving, deletes the rest, and runs `dotconfig age lock`, so each
   day starts locked and needs a real unlock.

Doing the classification and the save/delete in dotconfig (tested here)
keeps the cron job a one-liner instead of a shell script that reimplements
dotconfig's rules.

## What counts as an open file

In a dotconfig repo (has `config/dotconfig.yaml`):

- `.env`, `.env.json`, `.env.yaml`, `.env.secret` (and `--env-file` /
  `-o` names when we can know them; see open questions) **that carry a
  dotconfig header** (`# CONFIG_DEPLOY[S]=` or `#@dotconfig:`), and
- every file in `config/files/` except `.gitkeep`.

A file is **deletable** only if it is git-ignored (`git check-ignore`). A
generated file that is *not* ignored is reported as a problem and never
deleted. Hand-written `.env.example` and similar files with no dotconfig
header are not touched.

A `.env` loaded with `--public` (all secret values blank) is reported as
`public` and left in place: it holds no secrets, and the home-directory
store relies on it existing.

## Change 1: record fingerprints at load time

Today the header records only which layers were loaded, so "this `.env`
differs from the store" can't say *which side* moved. Add to the header:

    # CONFIG_STORE_SHA=<sha256 of the source files' bytes, per layer, as loaded>
    # CONFIG_ENV_SHA=<sha256 of the generated body, excluding these lines>

Hash the encrypted source files' bytes, not plaintext, so audit can check
"has the store moved since load" **without decrypting**, which means it works
while the age key is locked. `CONFIG_ENV_SHA` tells whether anyone edited
the `.env` after it was written, again without decrypting.

## Change 2: `dotconfig audit` reports open files

Keep today's behavior (plaintext secrets inside `config/`) and add an
"Open files" section. New options:

    dotconfig audit                 # this repo: config/ scan + open files
    dotconfig audit --open ROOT...  # open files only, every repo under ROOTs
    dotconfig audit --open --json   # same, machine-readable

Roots default to `$DOTCONFIG_ROOTS` (colon-separated), else the current
repo. The walk skips `.git`, `node_modules`, `.venv`, `.tmp` and stops
descending into a dotconfig repo once found (except nested repos the user
lists explicitly).

Per file it prints a **state** and the **action** that follows:

| State | Meaning (from the fingerprints) | Action |
|---|---|---|
| `clean` | `.env` unedited, store unchanged since load | delete |
| `edited` | `.env` edited since load, store unchanged | save, then delete |
| `stale` | `.env` unedited, store changed since load | delete (saving would lose the newer store values) |
| `conflict` | both changed | resolve by hand; never touched automatically |
| `public` | loaded with `--public` | keep |
| `legacy` | no fingerprints (written by an older dotconfig) | if the key is unlocked: decrypt and compare; equal means `clean`, otherwise `legacy-differs` (resolve by hand). If locked: `legacy-unknown` |
| `not-ignored` | generated file git does not ignore | warn; never deleted |

Example:

    🔑 age key: unlocked (/Users/eric/.config/sops/age/keys.txt)

    Repo                                     File         State      Action          Age
    home-projects/busboom-home-network       .env         edited     save + delete   18 d
    home-projects/busboom-home-network       config/files/garage-ansible  clean  delete  18 d
    robot-projects/frc-code-scout            .env         clean      delete          29 d
    league-projects/.../student-accounts     .env         conflict   BY HAND         4 d

    4 open files in 3 repos: 2 delete, 1 save + delete, 1 by hand.

For `edited` and `legacy-differs`, it also lists the **key names** that
differ, with which side changed each one, but **never values**. (`dotconfig diff`
prints values; audit must be safe to run in a log or an agent transcript.)

Exit status: `0` nothing open (or only `public`); `1` open files, all
resolvable automatically; `3` at least one needs a human (`conflict`,
`legacy-*`, `not-ignored`); `2` error. Keep the existing exit 1 for
`config/` findings when run without `--open`.

## Change 3: `dotconfig close`

Acts on what `audit --open` reports, with the same roots:

    dotconfig close [--dry-run] [--lock] ROOT...

- `clean`, `stale`: delete (zero-fill then unlink, like `age lock`; same
  caveat about APFS).
- `edited`: `dotconfig save` (round-trip to loaded layers), re-check the
  fingerprints, then delete. Commit **only** the store files it wrote, with
  a fixed message (`dotconfig close: save <host> <date>`), and only if the
  repo has no other staged changes. Never push.
- `conflict`, `legacy-*`, `not-ignored`: skip and report.
- Per-repo mode in `config/dotconfig.yaml`, `close: remove | public`
  (default `remove`). `public` ends with `dotconfig load --public`
  instead of deleting (for the home-directory store, so shells don't break).
- `--lock`: after the sweep, run `dotconfig age lock`, even if some repos
  were skipped. A skipped file stays put either way, and locking is what
  matters most.
- Never prompts and never reads stdin. If saving needs the key and the key
  is locked (or would prompt, e.g. Secure Enclave), treat `edited` as
  "needs a human" instead of hanging.
- Writes a one-line-per-file log (state, action, result; no values) to
  stdout.

## Open questions

- Should `load` record custom output names (`--env-file`, `-o`) somewhere
  (e.g. `config/.open`) so audit can find files not named `.env*`? A small
  registry would also make the sweep cheaper than a disk walk.
- `stale` + delete loses nothing from the store, but it does throw away a
  `.env` someone may still be running a process against. Acceptable at night?
- Repos where `.env` is generated by dotconfig but whose nightly save should
  be skipped entirely (e.g. test fixtures like `tests/proj`): a
  `close: skip` mode?

## Tests

- Fingerprints written for single and stacked loads; `--public` marked.
- Each state reached from a fixture repo (edit `.env`, re-encrypt a store
  file, both, neither, legacy header).
- Audit output and `--json` contain no secret values (assert on a
  sentinel value).
- `close --dry-run` changes nothing; `close` never deletes a `conflict` or
  non-ignored file; `close` with a locked key does not prompt.
