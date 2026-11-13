---
status: draft
---

# Sprint 008 Use Cases

## SUC-001: Find where dotconfig keeps its files
Parent: UC-XXX

- **Actor**: Developer
- **Preconditions**: dotconfig installed
- **Main Flow**:
  1. Run `dotconfig where`.
  2. Read each location, its source (env var, default, discovered), and whether it exists.
- **Postconditions**: User knows every path in play.
- **Acceptance Criteria**:
  - [ ] Lists user-level, project-level and user-config paths with source and exists flag
  - [ ] Honors SOPS_AGE_KEY_FILE, SOPS_AGE_KEY, XDG_CONFIG_HOME

## SUC-002: See paths used by commands and in errors
Parent: UC-XXX

- **Actor**: Developer
- **Preconditions**: A project with config/
- **Main Flow**:
  1. Run load/save/init/age/key.
  2. Output names the config root, key file, sops.yaml and output files; suppressed by --quiet.
  3. On decrypt failure the error includes config root and key file.
- **Postconditions**: Failures are diagnosable without reading source.
- **Acceptance Criteria**:
  - [ ] Paths printed by each command; silent under --quiet
  - [ ] Decrypt error messages include config root and key file path

## SUC-003: Maintain a user-level list of labeled public keys
Parent: UC-XXX

- **Actor**: Developer
- **Preconditions**: None
- **Main Flow**:
  1. `dotconfig init` finds no user config and creates it, seeded with the local public key labeled user@hostname.
  2. User is told the path and to edit labels / add keys.
  3. User edits the file adding keys; invalid keys are skipped with a warning naming the file.
- **Postconditions**: User config exists and is valid.
- **Acceptance Criteria**:
  - [ ] File created at XDG or ~/.config location
  - [ ] Invalid entries warned and skipped

## SUC-004: Every project gets all my keys, labeled
Parent: UC-XXX

- **Actor**: Developer
- **Preconditions**: User config lists keys
- **Main Flow**:
  1. Run `dotconfig init` in a project.
  2. All listed keys plus the local key are merged into config/sops.yaml; existing keys kept; labels written beside keys.
  3. init reports each key added by label and tells the user to run `dotconfig reencrypt` if recipients changed and encrypted files exist.
- **Postconditions**: sops.yaml contains all keys with labels; rerun is a no-op.
- **Acceptance Criteria**:
  - [ ] Labels survive re-render; legacy forms still read
  - [ ] Real sops encrypt/decrypt works with the layout
