---
id: '005'
title: Age unlock identity fixes and review follow-ups
status: ticketing
branch: sprint/005-age-unlock-identity-fixes-and-review-follow-ups
use-cases: []
issues:
- age-unlock-identity-review-findings.md
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 005: Age unlock identity fixes and review follow-ups

## Goals

Fix `dotconfig age unlock --identity FILE` so the emergency path (a
passphrase-protected recovery identity, e.g. from a USB drive) prompts for
the passphrase exactly once and fails with an accurate message, and land
three small review follow-ups (lock warning, derived SE recipient, status
wording).

Source issue: `clasi/issues/age-unlock-identity-review-findings.md`.

## Problem

From a hands-on test of sprint 004's age lock/unlock: `unlock --identity FILE`
without `--with` tries every non-passphrase method in sidecar order, and each
attempt runs `age -d -i FILE`, re-prompting for the identity's passphrase.
The first passphrase is spent on `se`, which can never match, and the final
error ("se: age failed; recovery: age failed") reads as a wrong passphrase.
Smaller gaps: `lock` is silent when `SOPS_AGE_KEY` keeps decryption working,
`wrap --se` needs a redundant `--se-recipient`, and `status` does not say
what to do about an unrecorded hand-made wrapped file.

## Solution

Decrypt an encrypted identity once in memory, derive its public key, and
select the wrapped-file method whose recipient matches; pass the identity to
age via pipe/fd, never a temp file. Skip `se`/`yubikey` for non-plugin
identities. Improve error text. Add the lock warning, recipient derivation
from the identity file, and the status/help wording.

## Success Criteria

- [ ] All eight acceptance criteria below are met.

## Scope

### In Scope

Findings 1-4 of the issue and its acceptance criteria 1-8:

1. `unlock --identity <passphrase-protected file>` (no `--with`) prompts
   exactly once and unlocks via `recovery`; covered by a TTY-harness test.
2. A wrong passphrase yields a message saying the identity's passphrase was
   wrong (or the identity matches no wrapped file), not per-method "age failed".
3. Plain identity files and plugin identities (`AGE-PLUGIN-...`) still work
   (`se`/`yubikey` unlock).
4. `lock` with `SOPS_AGE_KEY` set still locks, exits 0, and prints a warning.
5. `wrap --se --se-identity FILE` works with no sidecar and no
   `--se-recipient` (recipient derived from FILE; same for `--yubikey` if cheap).
6. `status` wording for an unrecorded wrapped file says what to run.
7. `unlock --help` mentions `--with recovery --identity FILE` for the USB case.
8. Tests never touch the real key (existing conftest isolation).

Findings: (1) unlock --identity repeated prompts, (2) lock warning,
(3) derive SE/yubikey recipient, (4) status wording for unrecorded files.

### Out of Scope

- Changes to the `load` "Unlock now? [Y/n]" TTY prompt (issue notes it is
  fine as is; agents run without a TTY and get exit 75).
- Changes to behaviours the issue lists under "What worked".

## Test Strategy

Unit and TTY-harness tests for unlock identity selection (single prompt, wrong
passphrase, plain and plugin identities), lock warning, recipient derivation,
and status/help text. All tests use the existing conftest isolation.

## Architecture

Sizing: Compact — changes stay inside the existing age key-wrap modules
(`keywrap.py` unlock/lock/wrap logic, `keystore.py` age-invocation helpers,
`cli.py` help/output text), with no new cross-module dependency, no change in
dependency direction (cli -> keywrap -> keystore), and no data-model change
(the sidecar schema is unchanged). No diagrams.

### What Changed

- **keystore.py (age invocation seam)**: gains identity-kind detection
  (plugin `AGE-PLUGIN-...`, encrypted `age-encryption.org/v1` or
  `-----BEGIN AGE ENCRYPTED FILE-----`, plain) and two helpers: decrypt an
  encrypted identity file once into memory (`age -d FILE`, age prompts once
  on the TTY), and decrypt a wrapped file with an in-memory identity.
  Existing `age_decrypt_identity` (file path) stays for plain/plugin
  identities. Also a helper to derive a recipient from a plugin identity file
  (`age-plugin-se recipients -i FILE`; `age-plugin-yubikey --list` for
  yubikey, only if cheap) with fallback to the `# public key:` comment.
- **keywrap.py unlock**: with `--identity` and no `--with`, classify the
  identity first. Encrypted: decrypt once, derive its public key
  (`age-keygen -y`), select the wrapped method(s) whose sidecar `recipient`
  equals it, decrypt with the in-memory identity. Plugin: only `se`/`yubikey`
  methods are candidates. Plain: behaves as today (public key match, then
  try). If no method matches, raise an error saying the identity matches no
  wrapped file and listing the methods and recipients checked. A failed
  decrypt of the identity itself reports "identity's passphrase was wrong (or
  file is not a valid age identity)". `se`/`yubikey` are never attempted with
  a non-plugin identity.
- **keywrap.py lock**: when `SOPS_AGE_KEY` is set, print the same warning
  `status` prints (still exit 0). Reuse the status warning text rather than
  duplicating it.
- **keywrap.py wrap / build_specs**: for `--se`/`--yubikey` with no sidecar
  recipient and no `--*-recipient`, derive the recipient from the identity
  file via the keystore helper.
- **status wording** (keywrap listing / cli): an unrecorded wrapped file
  reads "not recorded; run: dotconfig age wrap --se to verify and record it"
  (method-specific command).
- **cli.py**: `unlock --help` mentions `--with recovery --identity FILE` for
  the USB-drive case.

### Why

Serves SUC-001 to SUC-003. The emergency path must prompt once and report
accurately; the other items close small review gaps.

### Design Rationale

Decision: pass the decrypted identity to age without touching disk.
Context: `age -i` requires a path, not stdin data. Alternatives: (a) temp
file (rejected: plaintext secret on disk); (b) `-i /dev/stdin` with the
wrapped ciphertext as a file argument and the identity bytes as process stdin
(chosen; nothing is written to disk); (c) inherited pipe fd via
`/dev/fd/N` through `pass_fds` (acceptable fallback if /dev/stdin proves
unreliable on a platform). Consequence: the runner seam already takes `input`,
so tests can fake it; the wrapped file must be passed as a path argument, which
it already is. The identity bytes live only in process memory and are dropped
after use. Note age reads the passphrase for an encrypted identity from
/dev/tty, so the single prompt comes from the one `age -d FILE` call, and the
second call (`age -d -i /dev/stdin wrapped`) uses a plain identity and does
not prompt.

Decision: select by recipient match rather than trying methods in order.
Why: deterministic, one prompt, and lets the error state "matches no wrapped
file".

### Impact on Existing Components

`unlock` with `--with NAME --identity FILE` keeps working (workaround from
the issue); when FILE is encrypted it now also goes through the decrypt-once
path so the prompt count is one there too. No other callers change.

### Migration Concerns

None. No sidecar schema change; existing sidecars work unchanged.

### Architecture Self-Review (compact)

Cohesion: the added keystore helpers each do one thing (classify, decrypt
identity in memory, decrypt with in-memory identity, derive recipient);
boundary unchanged, keystore remains the only module that shells out to age.
No new cross-module dependency, so the compact sizing holds. Verdict:
APPROVE.

### Open Questions

None blocking. If `/dev/stdin` as `-i` fails on a target platform, use the
`/dev/fd/N` fallback (ticket 001 must test on macOS at least).

## Use Cases

### SUC-001: Emergency unlock with a passphrase-protected identity
Parent: sprint 004 unlock

- **Actor**: Developer whose machine key is gone, holding a USB recovery identity
- **Preconditions**: sidecar with `se`, `pass`, `recovery` (identity kind)
- **Main Flow**: run `dotconfig age unlock --identity FILE`; asked for the
  passphrase once; key restored via `recovery`.
- **Postconditions**: key restored (0600); wrong passphrase gives a clear
  message; plain and plugin identities still work.
- **Acceptance Criteria**:
  - [ ] Covered by ticket 001 (issue criteria 1, 2, 3, 7)

### SUC-002: Lock warns about a leaking environment
- **Actor**: Developer
- **Preconditions**: `SOPS_AGE_KEY` set
- **Main Flow**: run `dotconfig age lock`; it locks, warns, exits 0.
- **Acceptance Criteria**:
  - [ ] Covered by ticket 002 (issue criterion 4)

### SUC-003: First-time wrap and status guidance
- **Actor**: Developer
- **Main Flow**: `wrap --se --se-identity FILE` without sidecar or recipient
  derives the recipient; `status` tells how to record a hand-made wrapped file.
- **Acceptance Criteria**:
  - [ ] Covered by tickets 002 and 003 (issue criteria 5, 6)

## GitHub Issues

(GitHub issues linked to this sprint's tickets. Format: `owner/repo#N`.)

## Definition of Ready

Before tickets can be created, all of the following must be true:

- [ ] Sprint planning document is complete (sprint.md, including its
      Architecture and Use Cases sections)
- [ ] Architecture review passed (or skipped, for changes with no
      architectural impact)
- [ ] Stakeholder has approved the sprint plan

## Tickets

| # | Title | Depends On |
|---|-------|------------|
| 001 | unlock --identity: decrypt encrypted identity once, match by recipient | — |
| 002 | lock warns on SOPS_AGE_KEY; status wording for unrecorded wrapped files | — |
| 003 | wrap --se/--yubikey derives recipient from identity file | 001 |

Tickets execute serially in the order listed.
