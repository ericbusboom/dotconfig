---
status: complete
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 002 Use Cases

## SUC-001: Load and save with positional names
Parent: None

- **Actor**: Developer
- **Preconditions**: `config/` is initialized; one or more deployment
  directories (`config/<name>/`) and/or local directories
  (`config/local/<name>/`) exist.
- **Main Flow**:
  1. Developer runs `dotconfig load dev` — assembles `dev` deployment
     into `.env` (no local override).
  2. Developer runs `dotconfig load dev eric` — assembles `dev` plus
     local override `eric`.
  3. Developer runs `dotconfig load dev prod eric alice` — assembles
     two deployments stacked (`dev → prod`) and two locals stacked
     (`eric → alice`).
  4. Developer edits `.env`.
  5. Developer runs `dotconfig save` — each section is round-tripped to
     the source file it came from, using the `CONFIG_DEPLOYS` /
     `CONFIG_LOCALS` metadata in the `.env` header.
  6. Developer runs `dotconfig save dev` — entire assembled `.env` is
     written to `config/dev/` as if it were a fresh deployment.
- **Alternate Flow** (back-compat):
  1. Developer runs `dotconfig load -d dev -l eric` — equivalent to
     `dotconfig load dev eric`.
  2. Developer runs `dotconfig load nonexistent` — fails with a usage
     error naming the unknown argument.
  3. Developer runs `dotconfig load dev -l eric` — fails with a usage
     error: don't mix positional and flag forms.
- **Postconditions**: `.env` contains the assembled layers with section
  markers; the metadata header records the layer lists for round-trip.
- **Acceptance Criteria**:
  - [ ] `dotconfig load <deploy>` works with a single positional arg.
  - [ ] `dotconfig load <deploy> <local>` works with two positional args
        in either order.
  - [ ] `dotconfig load <d1> <d2> <l1> <l2>` stacks layers in command-line
        order within each type; the assembled `.env` reflects last-wins
        semantics.
  - [ ] `dotconfig save` with no args round-trips to all loaded layers.
  - [ ] `dotconfig save <deploy>` rewrites the entire assembly into
        `config/<deploy>/`.
  - [ ] `dotconfig load -d dev -l eric` (legacy form) continues to work.
  - [ ] Mixing positional names with `-d`/`-l` raises a usage error.
  - [ ] Unknown names raise a usage error naming the offending value.
  - [ ] `# CONFIG_DEPLOYS=...` / `# CONFIG_LOCALS=...` are written to the
        `.env` header; legacy `CONFIG_DEPLOY` / `CONFIG_LOCAL` are still
        read on save for back-compat with previously generated files.

## SUC-002: Archive completed gitignore TODO
Parent: None

- **Actor**: Maintainer
- **Preconditions**: `_update_gitignore` is shipped in
  `src/dotconfig/init.py`; tests in `tests/test_init.py` cover its
  behavior; `docs/clasi/todo/plan-init-creates-gitignore-for-env-files.md`
  is still in `pending` state.
- **Main Flow**:
  1. Maintainer cross-checks the implementation against the TODO spec
     (patterns, append-only update, idempotent, runs as part of init).
  2. Maintainer moves the TODO file to `docs/clasi/todo/done/` via the
     `move_todo_to_done` MCP tool, recording the sprint and ticket IDs.
- **Postconditions**: TODO file lives under `docs/clasi/todo/done/`
  with `status: done` and sprint linkage in frontmatter.
- **Acceptance Criteria**:
  - [ ] Implementation in `init.py` matches all bullets in the TODO's
        "Change" section (patterns present, append-only, idempotent,
        invoked from `init_config`).
  - [ ] `tests/test_init.py::TestUpdateGitignore` covers create / append
        / no-op / quiet-mode paths.
  - [ ] TODO file is in `docs/clasi/todo/done/` with sprint=`002` and
        ticket linkage.
