---
id: '006'
title: End-to-end smoke verification
status: done
use-cases:
- SUC-001
- SUC-002
- SUC-003
- SUC-004
- SUC-005
- SUC-006
depends-on:
- '002'
- '003'
- '004'
- '005'
github-issue: ''
todo: ''
completes_todo: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# End-to-end smoke verification

## Description

Run the full end-to-end smoke scenarios from the TODO's Verification section to
confirm all sprint work integrates correctly. This ticket contains no new
implementation — it is the integration gate that validates tickets 001–005 work
together.

Reference smoke script:
`docs/clasi/todo/dotconfig-version-and-yaml-source-of-truth.md` §Verification.

## Acceptance Criteria

- [x] Smoke scenario 1: `dotconfig init` in a project with `pyproject.toml`
      creates `config/dotconfig.yaml` seeded from `pyproject.toml` version.
- [x] Smoke scenario 2: `dotconfig version` prints the seeded version.
- [x] Smoke scenario 3: `dotconfig version bump` advances revision; `pyproject.toml`
      and `config/dotconfig.yaml` both show the new version.
- [x] Smoke scenario 4: `dotconfig load dev` produces `.env` with
      `_VERSION=<new-version>` near the top (after metadata header).
- [x] Smoke scenario 5: appending `_VERSION=manual-edit-should-vanish` to `.env`
      and running `dotconfig save dev` results in no `_VERSION=` in `config/`.
- [x] Smoke scenario 6: `dotconfig version bump --tag` creates a `v<version>`
      git tag confirmed by `git tag -l`.
- [x] Smoke scenario 7: `dotconfig init` in a project with both `package.json`
      and `pyproject.toml` seeds from `package.json` (package.json wins).
- [x] `uv run pytest tests/test_versioning.py tests/test_init.py tests/test_load.py tests/test_save.py -v` passes.
- [x] `uv run pytest` (full suite) exits 0.

## Implementation Plan

### Approach

This ticket requires no code changes. The implementer:

1. Verifies all previous tickets are complete and tests are green.
2. Runs the smoke script from the TODO verbatim in a temp directory.
3. Records any failures as bugs to fix in the relevant ticket before marking
   this ticket done.

### Smoke script (from TODO §Verification)

```sh
# Scenario 1 & 2 & 3
cd /tmp && rm -rf dctest && mkdir dctest && cd dctest
printf '[project]\nversion = "0.20260503.7"\n' > pyproject.toml
dotconfig init -q
cat config/dotconfig.yaml      # expect: version: 0.20260503.7
dotconfig version              # expect: 0.20260503.7
dotconfig version bump
grep '^version' pyproject.toml
grep '^version' config/dotconfig.yaml

# Scenario 4
dotconfig load dev
head -5 .env                   # expect: _VERSION= near top
grep '^_VERSION' .env          # exits 0

# Scenario 5
echo '_VERSION=manual-edit-should-vanish' >> .env
dotconfig save dev
grep -r '_VERSION' config/     # expect: no matches

# Scenario 6
git init && git add . && git commit -m initial
dotconfig version bump --tag
git tag -l                     # expect: v<new-version>

# Scenario 7
cd /tmp && rm -rf dctest2 && mkdir dctest2 && cd dctest2
printf '{"version":"1.2.3"}\n' > package.json
printf '[project]\nversion = "9.9.9"\n' > pyproject.toml
dotconfig init -q
grep '^version' config/dotconfig.yaml   # expect: 1.2.3
```

### Files to Modify

None. This is a verification-only ticket.

### Testing Plan

- Run the smoke script above and confirm each `expect:` comment matches actual
  output.
- Run `uv run pytest` (full suite) and confirm it exits 0.
- If any scenario fails, fix the root cause in the appropriate ticket (001–005)
  before marking this ticket done.

### Documentation Updates

None required for this ticket.
