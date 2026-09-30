---
id: '002'
title: Key send subcommand (ssh-copy-id)
status: todo
use-cases: [SUC-002]
depends-on: ['001']
github-issue: ''
todo: key-management-system.md
---

# Key send subcommand (ssh-copy-id)

## Description

Add `dotconfig key send <host>` subcommand that uses `ssh-copy-id` to
install a public key on a remote host. By default the key name matches
the host argument; `--key <name>` overrides which key to send.

## Acceptance Criteria

- [ ] `dotconfig key send <host>` sends key named `<host>` to that host
- [ ] `--key <name>` overrides which key to use
- [ ] Uses `ssh-copy-id -i <pubkey_path> <host>` under the hood
- [ ] Error if key doesn't exist
- [ ] Error if ssh-copy-id not found

## Testing

- **Existing tests to run**: `uv run pytest`
- **New tests to write**: Add send tests to `tests/test_key.py` with mocked ssh-copy-id
- **Verification command**: `uv run pytest`
