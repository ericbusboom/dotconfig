---
title: Fix dotconfig key name handling and pub derivation
status: pending
---

# Fix `dotconfig key` name handling and pub derivation

Two related bugs in `src/dotconfig/key.py`:

## 1. Name mangling breaks lookups for names containing dots

`gen_key` stores keys as `<name>_<key_type>` (e.g. `apps.jointheleague.org_ed25519`).
`_find_key` then uses `Path.stem` to glob-match, but `Path.stem` only strips
the last dot-extension — so `apps.jointheleague.org_ed25519.stem ==
"apps.jointheleague"`, and `pub`/`rm`/`get`/`send` all fail to resolve the
short name `apps.jointheleague.org`.

**Fix:** stop appending `_<key_type>` at gen time. Store keys under the exact
name the user typed. Rewrite `_find_key` to do an exact `keys_dir / name`
lookup, with a fallback that tries `<name>_<type>` for each known SSH key
type so existing on-disk keys (e.g. `deploy_ed25519`) still resolve.

One key per name. A second `gen` for the same name errors out (current
behavior).

## 2. `pub` cannot derive a public key when `.pub` is missing

`pub_key` decrypts the private key and pipes it to
`ssh-keygen -y -f /dev/stdin`. `ssh-keygen` rejects `/dev/stdin` because its
permissions (0660) are "too open" for a private key.

**Fix:** write the decrypted content to a `tempfile.NamedTemporaryFile` (or
`mkstemp`) with mode `0600`, run `ssh-keygen -y -f <tempfile>`, then unlink.

## Acceptance

- `dotconfig key gen apps.jointheleague.org` creates
  `config/keys/apps.jointheleague.org` (no `_ed25519` suffix).
- `dotconfig key {pub,rm,get,send} apps.jointheleague.org` all work.
- Existing keys named `<name>_ed25519` / `<name>_rsa` still resolve when the
  user passes the short `<name>`.
- `dotconfig key pub <name>` works when the `.pub` file is missing.
- Tests in `tests/test_key.py` updated to match.
- Full `uv run pytest` passes.
