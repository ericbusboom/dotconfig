---
id: '002'
title: Write decrypted secret files with mode 0600 atomically
status: done
use-cases:
- SUC-002
depends-on: []
github-issue: ''
issue: env-file-mode-0600.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Write decrypted secret files with mode 0600 atomically

## Description

`dotconfig load` writes `.env` with umask mode (0644) though it holds decrypted secrets. Write `.env`, `.env.secret` (`--split`), `--public` output, and files under `config/files/` from `key load` with mode 0600, atomically (temp file + rename, like `keystore._atomic_write`). When rewriting an existing `.env` that is more open, tighten it and say so.

## Acceptance Criteria

- [x] Mode 0600 after `load`, `load --split` (.env and .env.secret), `load --public`, and `key load`
- [x] Existing 0644 `.env` is 0600 after `load`, with a message saying it was tightened
- [x] Writes are atomic (temp file + rename in same dir)
- [x] Tests for all paths

## Implementation Plan

Expose `keystore._atomic_write` as a shared helper (public name or small utility module). Replace `write_text` calls in `src/dotconfig/load.py` (lines ~364, 770, 775, 822, 894) and `src/dotconfig/key.py` (~186, and the pub-file copy ~196 if under config/files/) with it at mode 0o600. Before writing `.env`, stat existing file; if mode has group/other bits, emit an info message after writing. Update README/docs if they state file modes.

## Testing

- **Existing tests to run**: tests/test_keystore*, load and key tests
- **New tests to write**: `stat.S_IMODE(...) == 0o600` for each path; pre-existing 0644 `.env` tightened
- **Verification command**: `uv run pytest`
