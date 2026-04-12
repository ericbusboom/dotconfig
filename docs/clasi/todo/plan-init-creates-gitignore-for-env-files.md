---
status: pending
---

# Plan: `dotconfig init` creates/updates .gitignore for env files

## Context

When `dotconfig init` sets up a project, it creates a `config/` directory
where env files will be assembled by `dotconfig load`. The assembled `.env`
file contains decrypted secrets and must not be committed. Currently
dotconfig does not ensure `.gitignore` covers these files — the user has
to remember to add them manually.

## Change

During `dotconfig init`, create or update `.gitignore` in the project
root to include patterns for assembled env files:

```
# dotconfig — assembled env files contain decrypted secrets
.env
.env.*
!.env.example
```

If `.gitignore` already exists, append only missing patterns. If it
doesn't exist, create it with the patterns above.

This should happen at the end of `dotconfig init`, after the `config/`
directory is created.
