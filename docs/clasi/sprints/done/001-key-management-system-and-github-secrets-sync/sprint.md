---
id: '001'
title: Key Management System and GitHub Secrets Sync
status: done
branch: sprint/001-key-management-system-and-github-secrets-sync
use-cases:
- SUC-001
- SUC-002
- SUC-003
---

# Sprint 001: Key Management System and GitHub Secrets Sync

## Goals

Add a `dotconfig key` subcommand group for managing SSH/age/GPG keys
(generate, save, get, pub, list, rm, send) and a `dotconfig gh-push`
command to sync deployment secrets to GitHub Actions/Codespaces.

## Problem

Users store SSH keys via `dotconfig save --file`, but keys have different
requirements: they need generation, permission management, public key
derivation, and distribution to remote hosts. Separately, pushing
deployment secrets to GitHub is a manual multi-step process.

## Solution

1. Convert `dotconfig keys` from a flat command to a `key` command group
   with subcommands: gen, save, get, pub, list, rm, send.
2. Keys stored SOPS-encrypted in `config/keys/`.
3. `key send` wraps `ssh-copy-id` — host argument doubles as key name
   unless `--key` overrides.
4. `gh-push` loads deployment secrets and pushes each via `gh secret set`.

## Success Criteria

- All `dotconfig key` subcommands work end-to-end
- `dotconfig gh-push` pushes secrets to GitHub and can be verified with `gh secret list`
- Tests pass for all new functionality

## Scope

### In Scope

- `dotconfig key` command group (gen, save, get, pub, list, rm, send)
- SOPS encryption/decryption of private keys in `config/keys/`
- `ssh-copy-id` integration for `key send`
- `dotconfig gh-push` command with deployment, scope, and environment options
- Unit tests for all commands
- Integration test for gh-push using dotconfig GitHub accounts repo

### Out of Scope

- Certificate management (.crt, .ca-bundle)
- Per-deployment key scoping (config/keys/prod/)
- Key rotation workflows
- Dependabot secret scope

## Test Strategy

- Unit tests: mock subprocess calls (ssh-keygen, ssh-copy-id, sops, gh)
  using `unittest.mock.patch`, test with `tmp_path` fixtures
- Integration test for `gh-push`: use the dotconfig GitHub accounts repo,
  push a test secret via `gh secret set`, verify with `gh secret list`,
  then clean up with `gh secret delete`
- CLI tests: use `click.testing.CliRunner`

## Architecture Notes

- `dotconfig keys` (existing age status command) becomes `dotconfig key status`
  or is folded into `dotconfig key list`
- New module: `src/dotconfig/key.py` for key management logic
- New module: `src/dotconfig/gh_push.py` for GitHub secrets sync
- CLI registration: convert `keys` command to `key` group in cli.py

## GitHub Issues

None.

## Definition of Ready

Before tickets can be created, all of the following must be true:

- [x] Sprint planning documents are complete (sprint.md, use cases, architecture)
- [x] Architecture review passed
- [x] Stakeholder has approved the sprint plan

## Tickets

| # | Title | Depends On | Group |
|---|-------|------------|-------|
| 1 | Key command group with gen, save, get, pub, list, rm | — | 1 |
| 2 | Key send subcommand (ssh-copy-id) | 1 | 2 |
| 3 | gh-push command | — | 1 |
