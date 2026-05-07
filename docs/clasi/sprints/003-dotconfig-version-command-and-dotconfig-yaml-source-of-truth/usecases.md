---
status: ready
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 003 Use Cases

## SUC-001: Developer initialises version tracking in a new project

- **Actor**: Developer running `dotconfig init` in a project directory.
- **Preconditions**: `config/dotconfig.yaml` does not yet exist. The project
  may have a `pyproject.toml` and/or `package.json` with existing version
  values.
- **Main Flow**:
  1. Developer runs `dotconfig init` (or `dotconfig init -q`).
  2. dotconfig reads the version seed: `package.json` version if present, else
     `pyproject.toml` `[project] version` if present, else `"0.0.0"`.
  3. dotconfig creates `config/dotconfig.yaml` with `version: <seed>`.
  4. Output confirms the file was created (unless `--quiet`).
- **Postconditions**: `config/dotconfig.yaml` exists with a `version` field
  equal to the seeded value.
- **Idempotency**: Running `init` again leaves an existing `dotconfig.yaml`
  completely untouched.
- **Acceptance Criteria**:
  - [ ] `config/dotconfig.yaml` is created with the correct seeded version.
  - [ ] Priority: `package.json` > `pyproject.toml` > `"0.0.0"`.
  - [ ] Re-running `init` does not modify an existing `dotconfig.yaml`.
  - [ ] `--quiet` suppresses all output but still creates the file.

## SUC-002: Developer reads the current project version

- **Actor**: Developer or CI script.
- **Preconditions**: `config/dotconfig.yaml` exists with a `version` field.
- **Main Flow**:
  1. Developer runs `dotconfig version`.
  2. dotconfig reads `version` from `config/dotconfig.yaml`.
  3. Prints the version string to stdout.
- **Postconditions**: Version string printed; no files modified.
- **Error case**: If `config/dotconfig.yaml` is absent or has no `version`
  field, prints an error to stderr and exits with code 1.
- **Acceptance Criteria**:
  - [ ] Prints the exact version string from `config/dotconfig.yaml`.
  - [ ] Exits 1 with stderr message when no version is found.

## SUC-003: Developer bumps the project version

- **Actor**: Developer.
- **Preconditions**: `config/dotconfig.yaml` exists. Git repo is present for
  tag discovery.
- **Main Flow**:
  1. Developer runs `dotconfig version bump` (optionally `--major N`,
     `--tag`, `--push`).
  2. dotconfig computes the next version using the `X+.YYYYMMDD.R+` format:
     reads current version from `dotconfig.yaml`, inspects local git tags,
     picks `max(today revisions) + 1`.
  3. Writes new version to `config/dotconfig.yaml`.
  4. Writes same version to `pyproject.toml` and `package.json` if they exist.
  5. With `--tag`: creates a local `v<version>` git tag.
  6. With `--push`: verifies clean master/main, commits changed files (all
     written files except `.env`), creates tag, runs `git push --tags`.
- **Postconditions**: `config/dotconfig.yaml`, `pyproject.toml`, and
  `package.json` (where present) all carry the new version. Tag created if
  requested.
- **Acceptance Criteria**:
  - [ ] New version is strictly greater than the previous one.
  - [ ] All existing sync targets are updated.
  - [ ] `--tag` creates a `v<version>` lightweight git tag.
  - [ ] `--push` aborts if the working tree is not clean or not on master/main.
  - [ ] `--push` commits, tags, and runs `git push --tags`.

## SUC-004: Developer loads config with version injected into .env

- **Actor**: Developer running `dotconfig load`.
- **Preconditions**: `config/dotconfig.yaml` has a `version` field. At least
  one deployment layer exists.
- **Main Flow**:
  1. Developer runs `dotconfig load <deployment>`.
  2. dotconfig builds the classic `.env` output, prepending
     `_VERSION=<version>` immediately after the metadata header lines.
  3. Writes (or prints) the `.env` with `_VERSION` present.
- **Postconditions**: The materialised `.env` contains `_VERSION=<version>`.
  Structured (`--json`/`--yaml`) output is unaffected.
- **Acceptance Criteria**:
  - [ ] `_VERSION=<version>` appears in the classic `.env` output.
  - [ ] The line appears after the `# CONFIG_*` metadata header.
  - [ ] JSON and YAML structured outputs do NOT include `_VERSION`.
  - [ ] If `config/dotconfig.yaml` has no `version`, the line is omitted
        (no error).

## SUC-005: Developer saves config without polluting source files with _VERSION

- **Actor**: Developer running `dotconfig save`.
- **Preconditions**: The active `.env` contains a `_VERSION=` line (injected by
  `load`, or manually added by the user).
- **Main Flow**:
  1. Developer runs `dotconfig save <deployment>`.
  2. dotconfig parses the `.env` layers.
  3. Any line matching `^_VERSION=` is silently dropped before writing back.
  4. Config files in `config/` are written without `_VERSION`.
- **Postconditions**: No `_VERSION=` line appears in any file under `config/`.
- **Acceptance Criteria**:
  - [ ] `_VERSION=` lines are stripped from all sections during save.
  - [ ] `_VERSION=` in any section position (header, body) is dropped.
  - [ ] Remaining config key/value pairs are written correctly.

## SUC-006: End-to-end round-trip: init, bump, load, save

- **Actor**: Developer performing a full workflow.
- **Preconditions**: Clean project directory with a `pyproject.toml`.
- **Main Flow**:
  1. `dotconfig init` seeds version from `pyproject.toml`.
  2. `dotconfig version` prints the seeded version.
  3. `dotconfig version bump` advances to next revision.
  4. `dotconfig load dev` produces `.env` with `_VERSION=<new>`.
  5. `dotconfig save dev` writes config without `_VERSION`.
  6. `dotconfig version bump --tag` creates a git tag.
- **Postconditions**: Version is advanced; `.env` injected; config clean; tag
  exists.
- **Acceptance Criteria**:
  - [ ] All six steps complete without error.
  - [ ] Version in `dotconfig.yaml`, `pyproject.toml`, and `.env` are
        consistent after bump.
  - [ ] No `_VERSION` in `config/` after save.
  - [ ] Git tag `v<version>` exists after `--tag`.
