# dotconfig — Agent Instructions

> **You are an AI agent working in a project that uses `dotconfig` to manage
> environment configuration.**  This document tells you everything you need
> to operate `dotconfig` correctly.  Read it fully before taking action.

---

## What dotconfig does

`dotconfig` assembles a single `.env` file from multiple layered source files
and can round-trip edits back.  The layers are:

| Layer | Path | Purpose |
|---|---|---|
| Public common config | `config/{env}/public.env` | Shared, non-secret variables for an environment |
| Encrypted common secrets | `config/{env}/secrets.env` | SOPS-encrypted secrets for an environment |
| Public local overrides | `config/local/{user}/public.env` | Per-developer machine-specific overrides |
| Encrypted local secrets | `config/local/{user}/secrets.env` | Per-developer encrypted secrets (optional) |

The resulting `.env` is ordered so that **later sections override earlier ones**
when shell-sourced (last-write-wins): local overrides common, secrets override
public.

---

## Commands reference

### `dotconfig init`

```
dotconfig init [--config-dir config]
```

Initialises the `config/` directory structure, discovers or generates an age
encryption keypair, and writes `config/sops.yaml`.  Run this once when setting
up a new project.

### `dotconfig load`

```
dotconfig load <environment> [local_name] [--config-dir config] [--output .env]
```

Assembles source files into `.env`.

- `environment` — the environment directory name (`dev`, `prod`, `staging`, …)
- `local_name` — optional developer name for local overrides
- Missing files produce a warning but do not abort

**Examples:**

```bash
dotconfig load dev alice        # dev environment + Alice's local overrides
dotconfig load prod             # prod only, no local overrides
```

### `dotconfig save`

```
dotconfig save [common_name] [local_name] [--env-file .env] [--config-dir config]
```

Reads the `.env` file (which must have been produced by `dotconfig load`) and
writes each marked section back to its source file, re-encrypting secrets via
SOPS.

- If `common_name` / `local_name` are given, the sections are written to those
  targets instead of the originals (useful for cloning an environment).
- The `.env` **must** contain `# CONFIG_COMMON=` metadata for save to work.

**Examples:**

```bash
dotconfig save                  # save back to original source files
dotconfig save dev stan         # redirect output to dev/stan config files
```

### `dotconfig keys`

```
dotconfig keys
```

Reports the status of your age encryption keys: where they are, the derived
public key, and the environment variable exports you need.

---

## Generated `.env` format

The `.env` file produced by `dotconfig load` contains metadata comments and
marked sections:

```bash
# CONFIG_COMMON=dev
# CONFIG_LOCAL=alice

#@dotconfig: public (dev)
APP_DOMAIN=example.com
PORT=3000

#@dotconfig: secrets (dev)
SESSION_SECRET=abc123

#@dotconfig: public-local (alice)
DEV_DOCKER_CONTEXT=orbstack

#@dotconfig: secrets-local (alice)
```

**Important for agents:**

- `# CONFIG_COMMON=` and `# CONFIG_LOCAL=` are metadata — do not remove them.
- Section markers (`#@dotconfig: public (dev)`, etc.) map sections back to source
  files — do not rename or reorder them.
- The `#@dotconfig:` prefix is reserved for dotconfig — never use it in your
  own comments inside `.env`.
- To change a value, edit it in place within the correct section, then run
  `dotconfig save`.
- To add a new variable, add it under the appropriate section marker.

---

## Directory layout

```
config/
  sops.yaml                     # SOPS encryption rules
  dev/                          # One directory per environment
    public.env
    secrets.env                 # SOPS-encrypted
  prod/
    public.env
    secrets.env
  local/
    alice/                      # One directory per developer
      public.env
      secrets.env               # Optional, SOPS-encrypted
    bob/
      public.env
```

Environment names are open-ended — any valid directory name works.

---

## SOPS encryption

- Secrets files are encrypted with [SOPS](https://github.com/getsops/sops)
  using [age](https://github.com/FiloSottile/age) keys.
- `dotconfig` handles decryption/encryption automatically during load/save.
- If SOPS or keys are not available, secrets sections are skipped with a
  warning — public config still works.
- The SOPS config lives at `config/sops.yaml` (not `.sops.yaml` in the repo
  root), so it is not auto-discovered by SOPS.  When calling SOPS directly:
  ```bash
  SOPS_CONFIG=config/sops.yaml sops --encrypt --in-place config/dev/secrets.env
  ```

---

## Common agent tasks

### Loading environment config

```bash
# Figure out which environments exist
ls config/

# Figure out which local overrides exist
ls config/local/

# Load an environment
dotconfig load dev alice
```

### Editing a variable

1. Run `dotconfig load <env> [local]` to produce `.env`.
2. Edit the value in `.env` under the correct section.
3. Run `dotconfig save` to write changes back to source files.

### Adding a new environment

```bash
mkdir -p config/newenv
echo 'KEY=value' > config/newenv/public.env
touch config/newenv/secrets.env
# Encrypt secrets if needed:
SOPS_CONFIG=config/sops.yaml sops --encrypt --in-place config/newenv/secrets.env
```

### Checking key status

```bash
dotconfig keys
```

### First-time setup

```bash
dotconfig init
dotconfig load dev yourname
```

---

## Rules for agents

1. **Never edit source files under `config/` directly** — use `dotconfig save`
   to round-trip changes so encryption is handled correctly.
2. **Never delete section markers or metadata comments** in `.env`.
3. **Always load before saving** if you are unsure whether `.env` is current.
4. **Do not commit `.env`** — it is a generated file and should be in
   `.gitignore`.
5. **Public config is safe to read directly** from `config/{env}/public.env`
   if you only need to inspect values without modifying them.
6. **Secrets files are SOPS-encrypted** — you cannot read them directly.  Use
   `dotconfig load` to decrypt them into `.env`.
