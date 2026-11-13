---
status: pending
---

# User config file listing public keys to add to every project

## Problem

`dotconfig init` adds one age recipient to `config/sops.yaml`: the public key
derived from the user's own secret key (`init._update_sops_yaml`). Anyone
who manages several keys (a second machine, a CI key, a teammate, a
recovery key) has to add the others to each project's sops.yaml by hand.

## Proposed

Add a user-level config file, `~/.config/dotconfig/config.yaml`, that lists
the age public keys to add to every project:

```yaml
public_keys:
  - age1...   # laptop
  - age1...   # CI
  - age1...   # recovery
```

Behavior:

- `dotconfig init` always adds every key in `public_keys` to the project's
  `config/sops.yaml`, along with the key derived from the local secret key.
  No flag or prompt is needed.
- Running `dotconfig init` again in an existing project re-adds any listed
  key that is missing. It merges through the existing `_collect_age_keys`
  logic, so keys already in sops.yaml are kept and nothing is removed.
- If recipients change, existing secrets must be re-encrypted for the new
  key set (see `reencrypt.py`). `init` should do this, or tell the user to
  run the re-encrypt command.
- Validate the entries. Skip anything that isn't an `age1…` key, with a
  warning.
- Report the config file path and which keys were added (ties into
  `report-file-locations.md`).

## Open questions

- Should `dotconfig init` create the user config if it's missing, seeded
  with the local public key?
- Should entries allow a label/comment (e.g. `{key: age1..., name: laptop}`)
  so output can say which key was added?
- Honor `$XDG_CONFIG_HOME` for the path?
