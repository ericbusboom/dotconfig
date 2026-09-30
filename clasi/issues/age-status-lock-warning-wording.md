---
status: open
---

# `dotconfig age status` says "locked, but SOPS_AGE_KEY is set" while unlocked

Seen 2026-09-30 with dotconfig 1.20260930.5 on gala. `dotconfig age status`
showed `state: unlocked` and then, under "Wrapped methods":

    ⚠ locked, but SOPS_AGE_KEY is set in this environment; this shell and its children can still decrypt. Unset it and use SOPS_AGE_KEY_FILE instead.

That text is right for `dotconfig age lock` (sprint 005) but wrong in
`status` when the key is unlocked. In `status`, use the state-neutral
warning (as in sprint 004): "SOPS_AGE_KEY is set in the environment. It
survives 'dotconfig age lock' and defeats locking; unset it and use
SOPS_AGE_KEY_FILE instead." Keep the "locked, but…" wording for `lock` and
for `status` when the state really is locked.

Acceptance: a test for `status` in both states with `SOPS_AGE_KEY` set.
