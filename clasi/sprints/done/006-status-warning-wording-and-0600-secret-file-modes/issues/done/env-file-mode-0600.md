---
status: done
sprint: '006'
tickets:
- 006-002
---

# `dotconfig load` writes `.env` world-readable (0644); it holds decrypted secrets

Seen 2026-09-30 (dotconfig 1.20260930.5): `dotconfig load home` created
`.env` with mode `-rw-r--r--`. The file holds the decrypted secrets, so
any other account on the machine can read them.

Fix: create `.env` (and `.env.secret` with `--split`, and anything under
`config/files/` from `key load`) with mode **0600**, atomically (temp file
+ rename, like `keystore._atomic_write`). When rewriting an existing
`.env` that is more open, tighten it and say so. `--public` output can
keep 0600 as well, for consistency.

Acceptance: a test asserts mode 0600 after `load`, `load --split`,
`load --public`, and `key load`; an existing 0644 `.env` is 0600 after `load`.
