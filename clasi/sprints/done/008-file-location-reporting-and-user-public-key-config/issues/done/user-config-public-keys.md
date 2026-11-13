---
status: done
sprint: 008
tickets:
- 008-002
- 008-003
- 008-004
- 008-006
---

# User config file listing public keys to add to every project

## Problem

`dotconfig init` adds one age recipient to `config/sops.yaml`: the public key
derived from the user's own secret key (`init._update_sops_yaml`). Anyone
who manages several keys (a second machine, a CI key, a teammate, a
recovery key) has to add the others to each project's sops.yaml by hand.
Once added, a bare `age1…` string gives no hint of whose key it is.

## Proposed

### User config file

Location: `$XDG_CONFIG_HOME/dotconfig/config.yaml`, falling back to
`~/.config/dotconfig/config.yaml` when `XDG_CONFIG_HOME` is unset.

```yaml
public_keys:
  - key: age1...
    name: eric@laptop
  - key: age1...
    name: ci
  - key: age1...
    name: recovery
```

- Each entry has a `key` (required) and a `name` (the label, optional but
  expected).
- Validate the entries. Skip anything whose `key` isn't an `age1…` key,
  with a warning that gives the config file path.

### `dotconfig init`

- **Create the user config if it's missing.** Seed it with the local
  public key (derived from the discovered secret key). Label it
  `<user>@<hostname>` by default. Tell the user it was created, with the
  path, and suggest they edit the label and add other keys there.
- **Always add every listed key** to the project's `config/sops.yaml`,
  along with the local key. No flag or prompt.
- **Re-running `init` re-adds missing keys.** Merge through
  `_collect_age_keys`: existing recipients are kept, nothing is removed.
- **Report the result:** the config file path and each key added, by
  label (ties into the `report-file-locations.md` issue).

### Labels in `config/sops.yaml`

When a key is copied into the project's sops.yaml and it has a label, the
label goes in the file next to the key, so a reader of sops.yaml can tell
which key is which.

Design note: today `_render_sops_yaml` writes recipients as a folded block
scalar (`age: >-`). A YAML comment inside that scalar would become part of
the key string, so labels need a different layout. Options:

- Use `key_groups` with a list of age keys and a trailing comment on each
  item (`- age1...  # eric@laptop`). Check which sops versions support this.
- Use a YAML list for `age:` if the installed sops accepts it.
- Put comment lines above the `age:` block that map labels to keys.

Whichever layout is chosen:

- `_collect_age_keys` must keep reading every existing form (block scalar,
  inline string, list, key_groups), so old files still upgrade cleanly.
- Labels that are already in the project's sops.yaml for keys missing
  from the user config must survive a re-render.
- Confirm with real `sops` that encrypt and decrypt still work.

### Re-encryption

If the recipient set changes, existing secrets must be re-encrypted for
the new key set (see `reencrypt.py`). Decide whether `init` does this
automatically or tells the user to run the re-encrypt command.
