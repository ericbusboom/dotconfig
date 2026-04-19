---
id: '001'
title: Archive gitignore TODO (verify-and-move)
status: done
use-cases:
- SUC-002
depends-on: []
github-issue: ''
todo: plan-init-creates-gitignore-for-env-files.md
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Archive gitignore TODO (verify-and-move)

## Description

The TODO `plan-init-creates-gitignore-for-env-files.md` describes
adding `.env`, `.env.*`, and `!.env.example` patterns to `.gitignore`
during `dotconfig init`. The implementation already shipped in commit
`3d2f36e` ([src/dotconfig/init.py:355-389](src/dotconfig/init.py#L355-L389))
with full test coverage in
[tests/test_init.py:493-554](tests/test_init.py#L493-L554) (class
`TestUpdateGitignore`), but the TODO file was never archived.

This ticket is a verify-and-move only: re-read the implementation
against the TODO spec, confirm parity, and archive the TODO file with
sprint linkage. **No code changes.**

## Acceptance Criteria

- [x] Implementation in `src/dotconfig/init.py` matches all bullets of
      the TODO's "Change" section (patterns present, append-only when
      `.gitignore` exists, idempotent when patterns already present,
      invoked from `init_config`).
- [x] `tests/test_init.py::TestUpdateGitignore` covers the create /
      append / no-op / quiet-mode paths and passes.
- [x] TODO file moved to `docs/clasi/todo/done/` via the
      `move_todo_to_done` MCP tool with `sprint_id="002"` and
      `ticket_ids=["001"]`.
- [x] No code or test changes in this ticket.

## Testing

- **Existing tests to run**: `uv run pytest tests/test_init.py -v`
- **New tests to write**: none (implementation already covered).
- **Verification command**: `uv run pytest`
