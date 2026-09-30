---
status: in-progress
sprint: '005'
tickets:
- 005-001
- 005-002
- 005-003
---

# `dotconfig age` review: `unlock --identity` asks for the passphrase repeatedly, and small follow-ups

From a hands-on test of dotconfig 1.20260930.2 (sprint 004) in
busboom-home-network, 2026-09-30. Everything was run in a sandbox
(`SOPS_AGE_KEY_FILE` pointing to a throwaway key in a temp dir,
`SOPS_AGE_KEY` unset); the real key was not touched.

## What worked

- `wrap --se` (Touch ID round trip), `wrap --passphrase`, and
  `wrap --recipient … --label recovery --identity <passphrase-protected
  age identity>`: all wrote, verified and recorded. The sidecar is as
  specified (`identity_file` recorded for `se`, `hint` for recovery).
- `status` lists methods with verified dates, and warns about
  `SOPS_AGE_KEY` and a 0755 key directory.
- `lock`: removes the key, lists the methods it can unlock with, and is
  idempotent (exit 0).
- `load` while locked, non-interactive: "age key is locked — run: dotconfig
  age unlock", nothing written. While unlocked: normal.
- `unlock --with pass`: a wrong passphrase fails cleanly, writes nothing,
  and lists the other methods; the right one restores the key (0600).
- `unlock` default order on macOS picks `se` → Touch ID → restored.
- `unlock --with recovery --identity <file>`: restored with one passphrase.
- `unlock` when already unlocked: "already unlocked", exit 0.

## 1. `unlock --identity FILE` without `--with` prompts once per wrapped file (fix)

With `--identity`, `unlock` tries every non-passphrase method in sidecar
order (`se`, then `recovery`, …). When FILE is a **passphrase-protected**
identity (the recovery key on the Passwords USB drive:
`busboom-recovery.pass-A.age`), every attempt runs `age -d -i FILE`, and
age asks for the identity's passphrase **again**. The first passphrase is
spent on the `se` file, which can never match, so the user is asked a
second time for `recovery`. With one attempt the unlock fails with
"identity opened no wrapped file. se: age failed (exit 1); recovery: age
failed (exit 1)", which reads as if the passphrase were wrong.

This is the emergency path ("my Mac is gone, here is the USB drive"), so it
has to work the first time and be obvious.

Suggested fix, any of:

- With `--identity`, try `kind: identity` methods first; never try
  `se`/`yubikey` with an `--identity` that isn't a plugin identity (a
  plugin identity file starts `AGE-PLUGIN-…`; an encrypted one starts
  `age-encryption.org/v1` or `-----BEGIN AGE ENCRYPTED FILE-----`).
- Better: if FILE is an encrypted identity, decrypt it **once** in memory
  (`age -d FILE`, age prompts once), derive its public key, and pick the
  method whose `recipient` equals it; then decrypt that wrapped file with
  the in-memory identity (pass it through a pipe/fd, never a temp file).
- Error text: say which methods were tried, and that a passphrase-protected
  identity is prompted for per attempt.

The workaround until then (`--with recovery --identity FILE`) works; put it
in `unlock --help`.

## 2. `lock` while `SOPS_AGE_KEY` is set should warn loudly (small)

`keyguard.is_locked()` is false whenever `SOPS_AGE_KEY` is set, so after
`lock` every process that already has the variable keeps working, silently.
`status` warns, `lock` doesn't. Have `lock` print the same warning (it still
exits 0), e.g. "locked, but SOPS_AGE_KEY is set in this environment; this
shell and its children can still decrypt".

## 3. `wrap --se` on first use needs `--se-recipient` (nice to have)

With no sidecar yet, `--se` needs both `--se-recipient` and
`--se-identity`. The recipient can be derived from the identity file
(`age-plugin-se recipients -i FILE`; the file also has a `# public key:`
comment). Same for `--yubikey` (`age-plugin-yubikey --list`).

## 4. Existing hand-made wrapped files (note, no change needed)

A `keys.txt.se.age` made by hand before any sidecar existed shows in
`status` as "se — never verified". `wrap --se` replaces it only after the
new one verifies, which is right. Maybe say so in `status`: "not recorded;
run dotconfig age wrap --se to verify and record it".

## Acceptance criteria

1. With a sidecar holding `se`, `pass` and `recovery` (an `identity`
   method whose recipient matches a passphrase-protected identity file),
   `dotconfig age unlock --identity <that file>` (no `--with`) asks for the
   passphrase **exactly once** and unlocks via `recovery`. A test covers
   it with a TTY harness.
2. A wrong passphrase in that case fails with a message that says the
   identity's passphrase was wrong (or the identity matches no wrapped
   file), not "se: age failed; recovery: age failed".
3. `--identity` with a plain (unencrypted) identity file still works, and
   `--identity` with a plugin identity (`AGE-PLUGIN-…`) still unlocks
   `se`/`yubikey`.
4. `dotconfig age lock` with `SOPS_AGE_KEY` set: still locks, exit 0, and
   prints the warning.
5. `dotconfig age wrap --se --se-identity FILE` with no sidecar and no
   `--se-recipient` works, using the recipient derived from FILE (same
   for `--yubikey` if cheap).
6. `status` wording for an unrecorded wrapped file tells the user what to run.
7. `unlock --help` mentions `--with recovery --identity FILE` for the
   USB-drive case.
8. Tests never touch the real key (existing conftest isolation).

## Test harness note

`load` on a TTY asks `Unlock now? [Y/n]`. A default-yes prompt that
triggers Touch ID/passphrase is fine for humans. Just make sure agents
never see it: they run without a TTY, and they get exit 75 and the message,
which is what happened in the test.
