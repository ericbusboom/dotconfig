---
status: in-progress
sprint: '004'
tickets:
- 004-001
- 004-002
- 004-003
- 004-004
- 004-005
- 004-006
- 004-007
- 004-008
---

# Lock and unlock the age key file (wrapped at rest, unwrapped per session)

From the busboom-home-network security work (2026-09-30). Eric will review
and refine this with the dotconfig agent before it is planned.

## Summary

Today the age key that decrypts every dotconfig store sits on disk in the
clear (`~/.config/sops/age/keys.txt`) and ends up in backups. Add two
commands, **`dotconfig unlock`** and **`dotconfig lock`**, plus a setup
command, so that:

- at rest, the key exists only **wrapped** (encrypted), in one or more
  files next to it, each openable by a different method (Secure Enclave /
  Touch ID, a key on a USB drive, a YubiKey, a pasted key, a passphrase);
- `unlock` restores the plain key file for a work session, after a human
  proves presence with any one method;
- `lock` removes the plain key file again (end of day, screen lock, a
  security audit's "wipe" trigger).

The key itself does not change. **No store is re-encrypted.** Every repo
keeps its current recipient. This is only about protecting the one key
file.

## Why

- A stolen Mac, a leaked disk image or a Time Machine backup currently
  gives away every secret in every dotconfig repo.
- Eric wants an audit/presence check to be able to wipe the usable key,
  with nothing lost: the wrapped copies stay, and the next unlock restores it.
- It must work when Eric is remote (SSH, no GUI), and when every Mac is
  gone (a recovery key on a USB drive).

## How it should work

### Names are derived from `SOPS_AGE_KEY_FILE`

- The plain key path is `$SOPS_AGE_KEY_FILE`, defaulting to
  `~/.config/sops/age/keys.txt` (the same resolution `keys.py` already uses).
- Wrapped copies live **next to it**, and their names are derived from it:
  `<keyfile>.<method>.age`, e.g.
  - `keys.txt.se.age`: encrypted to this Mac's Secure Enclave key
    (`age-plugin-se`)
  - `keys.txt.recovery.age`: encrypted to an age key kept offline (USB drive)
  - `keys.txt.yubikey-23530911.age`: encrypted to a YubiKey (`age-plugin-yubikey`)
  - `keys.txt.pass.age`: encrypted with a passphrase (age scrypt)
- One file per method, so a method can be added or removed without
  touching the others, and `unlock` knows which method each file needs.
- A **metadata sidecar**, `<keyfile>.lock.yaml`, holds no secrets:

  ```yaml
  public_key: age1v3f2...q0d            # the key being protected; checked on every unlock
  methods:
    - file: keys.txt.se.age
      kind: se                          # se | yubikey | identity | passphrase
      recipient: age1se1q...            # public, so lock/rewrap can re-create it
      label: gala Secure Enclave (Touch ID)
      verified: 2026-10-01              # last successful round-trip unlock
    - file: keys.txt.recovery.age
      kind: identity
      recipient: age10cz4fxrr...
      label: Passwords USB drives (recovery-key.sh)
      hint: /Volumes/PASSWORDS1/busboom-recovery.pass-A.age
    - file: keys.txt.pass.age
      kind: passphrase
      label: remote passphrase
  ```

  `unlock` uses it to offer choices and to pick a sensible default;
  `lock` uses it to know whether it is safe to delete the plain file.

### Commands

**`dotconfig key wrap`** (setup, and to add a method later)

- Reads the plain key, writes `<keyfile>.<method>.age` for the methods
  asked for (`--se`, `--recipient age1… --label …`, `--yubikey`,
  `--passphrase`), and writes or updates the sidecar.
- Immediately **proves each new file opens** (a round trip that needs the
  human: Touch ID, YubiKey touch, passphrase, or the recovery identity) and
  checks that the result's public key equals `public_key`. It records
  `verified:`. A file that fails is deleted and reported. It never
  replaces a working wrapped file with an unverified one.

**`dotconfig unlock [--with METHOD] [--identity FILE] [--paste]`**

- If the plain key already exists and matches `public_key`: say so, exit 0.
- Otherwise pick a method: `--with`, or a default (Secure Enclave when a
  GUI session is available; the passphrase file when in SSH / no GUI),
  and list the others if it fails.
- Methods:
  - `se` / `yubikey`: `age -d` with the plugin identity; the OS / device
    does the prompting.
  - `identity`: `--identity FILE` (e.g. an age identity on a USB drive; if
    that identity is itself passphrase-protected, age prompts).
  - `--paste`: read an `AGE-SECRET-KEY-1…` from the terminal **without
    echo**, use it only in memory.
  - `passphrase`: `age -d` on `keys.txt.pass.age`; age prompts on the TTY.
- Decrypts **to memory**, checks the public key, then writes the plain key
  file atomically (temp file in the same directory, mode 0600, rename).

**`dotconfig lock`**

- Deletes the plain key file (best-effort overwrite, then unlink).
- **Refuses** unless at least one wrapped file exists, its method is in
  the sidecar, and the sidecar's `public_key` matches the plain key being
  removed. `--force` exists but prints what will be unrecoverable.
- Safe to run unattended (cron/launchd, an audit job, an agent). Needs no
  secret and asks no questions. Exit 0 if already locked.

**Status**

- Extend the existing key check (`keys.py`) to report: locked or
  unlocked; which wrapped methods exist and when each was last verified;
  and **warn if `SOPS_AGE_KEY` is set in the environment** (it defeats
  locking; see below).

### Other commands when the key is locked

- `load`, `save`, `key load`, `reencrypt`, etc. must detect "plain key
  missing, wrapped copies present" **before** calling sops, and say
  `age key is locked — run: dotconfig unlock`, rather than showing sops'
  "no identity found" error.
- Interactive (TTY) invocation may offer to run `unlock` inline;
  non-interactive invocation fails with the message and a distinct exit
  code, so agents and scripts can report it.

## Requirements (the important part)

1. **Never lock the user out.** `lock` and `wrap` must make it impossible
   to end up with no working copy: no deleting the plain key without a
   verified wrapped file; no overwriting a wrapped file with an unverified
   one; every unlock checks the public key.
2. **No re-encryption of stores.** Only the key file is wrapped. Repos,
   `config/sops.yaml` and recipients are untouched.
3. **The plain key is written only to `$SOPS_AGE_KEY_FILE`.** No temp
   files elsewhere, no logs, no stdout, no environment variables. Mode
   0600; warn if the directory is group/world readable.
4. **A human must be present to unlock; nobody needs to be present to lock.**
   `unlock` has no non-interactive secret input: no `--passphrase` flag,
   no passphrase environment variable, no reading the key from a pipe
   except `--paste` from a real TTY. Agents can use the key once a human
   has unlocked it, but can't unlock it themselves.
5. **Works over SSH with no GUI.** The passphrase method (and a YubiKey
   plugged into that machine) must work from a TTY alone. The Secure
   Enclave method needs the GUI; detect that and fall back or explain.
6. **Uses `age` and its plugins; doesn't implement crypto.** Methods are
   `age -r/-R` / `age -p` / `age -d -i` with `age-plugin-se` and
   `age-plugin-yubikey`. Missing plugins are reported with the install
   command.
7. **Sidecar and wrapped files are safe to commit and back up.** They
   hold no secret; losing the sidecar must not lose the key (the `.age`
   files open with age alone; document the manual `age -d` for each).
8. **Stop recommending `SOPS_AGE_KEY`.** It copies the key into every
   process's environment and survives `lock`. Status warns about it; docs
   say to use `SOPS_AGE_KEY_FILE` only.
9. **Tests never touch the real key.** All tests use a temp
   `SOPS_AGE_KEY_FILE` and test identities (plain age keys stand in for
   plugins; passphrase via an expect-style TTY harness).

## Out of scope here (separate issues later)

- Wiping `.env` and `config/files/` across repos (the nightly cleanup);
  it will call `dotconfig lock` but is its own feature.
- Re-encrypting every repo to new recipients (a separate, careful tool).
- Moving secrets out of `~/.zshenv` into a personal dotconfig store.
- Keeping the unlocked key on a RAM disk. Possible later by pointing
  `SOPS_AGE_KEY_FILE` at one; `unlock` should just create the directory
  if it's missing.

## Open questions for Eric

- One wrapped file per method (proposed) or one multi-recipient `.age`
  plus a separate passphrase file?
- Default method order for `unlock`: Secure Enclave → YubiKey →
  passphrase? Should a GUI session ever pick the passphrase file?
- Should `lock` also run automatically on screen lock or sleep (a
  launchd hook), or only from the nightly job and by hand?
- Sidecar name and format: `keys.txt.lock.yaml`?

## Context

- busboom-home-network: `docs/key-security/README.md` (inventory of keys
  and where they are), `docs/key-security/plan.md`,
  `issues/2026-09-30-secrets-at-rest-and-key-unlock.md`,
  `security/recovery-drive/` (the USB recovery key and its script, which
  would be the `identity` method's key).
- The key to protect today: `~/.config/sops/age/keys.txt`, public key
  `age1v3f2rncavwjzsvlhdn6v4wxkfsm2da8sl5snl5wa3mw7zqlvhyyqmx8q0d`, used by
  12 repos. `~/.zshenv` currently also exports it as `SOPS_AGE_KEY`.
- Relevant dotconfig code: `keys.py` (key source discovery and status),
  `key.py` (`dotconfig key` group), `save.py` (`SOPS_AGE_KEY_FILE` from `.env`).
