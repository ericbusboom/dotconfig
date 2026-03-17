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
| Public deployment config | `config/{deploy}/public.env` | Shared, non-secret variables for a deployment |
| Encrypted deployment secrets | `config/{deploy}/secrets.env` | SOPS-encrypted secrets for a deployment |
| Public local overrides | `config/local/{user}/public.env` | Per-developer machine-specific overrides |
| Encrypted local secrets | `config/local/{user}/secrets.env` | Per-developer encrypted secrets (optional) |

The resulting `.env` is ordered so that **later sections override earlier ones**
when shell-sourced (last-write-wins): local overrides deployment, secrets override
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
dotconfig load -d <deployment> [-l <local>] [--file <name>] [--output <path>] [--stdout]
```

Assembles source files into `.env`, or retrieves a specific file.

- `-d/--deploy` — the deployment name (`dev`, `prod`, `staging`, …)
- `-l/--local` — optional developer name for local overrides
- `--file` — load a specific file (e.g. `app.yaml`) instead of assembling `.env`
- `--stdout` — print to stdout instead of writing to a file
- Missing files produce a warning but do not abort

**Examples:**

```bash
dotconfig load -d dev -l alice      # dev deployment + Alice's local overrides
dotconfig load -d prod              # prod only, no local overrides
dotconfig load -d dev --file app.yaml --stdout   # print a file to stdout
```

When using `--file`, specify either `-d` or `-l` (not both) — the file
lives in one location only.

### `dotconfig save`

```
dotconfig save [-d <deployment>] [-l <local>] [--file <name>] [--env-file .env]
```

Reads the `.env` file (which must have been produced by `dotconfig load`) and
writes each marked section back to its source file, re-encrypting secrets via
SOPS.  Or stores a specific file into the config directory.

- If `-d`/`-l` are given without `--file`, sections are written to those
  targets instead of the originals (useful for cloning a deployment).
- The `.env` **must** contain `# CONFIG_DEPLOY=` metadata for save to work.

**Examples:**

```bash
dotconfig save                         # save back to original source files
dotconfig save -d staging              # redirect output to staging
dotconfig save -d dev --file app.yaml  # store app.yaml into config/dev/
dotconfig save -l alice --file settings.json  # store into config/local/alice/
```

When using `--file`, specify either `-d` or `-l` (not both).

### `dotconfig keys`

```
dotconfig keys
```

Reports the status of your age encryption keys: where they are, the derived
public key, and the environment variable exports you need.

### `dotconfig config`

```
dotconfig config
```

Shows the installed version, config directory name, and where the config
directory was found.

---

## Generated `.env` format

The `.env` file produced by `dotconfig load` contains metadata comments and
marked sections:

```bash
# CONFIG_DEPLOY=dev
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

- `# CONFIG_DEPLOY=` and `# CONFIG_LOCAL=` are metadata — do not remove them.
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
  dev/                          # One directory per deployment
    public.env
    secrets.env                 # SOPS-encrypted
    app.yaml                    # Any other config files
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

Deployment names are open-ended — any valid directory name works.

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
# Figure out which deployments exist
ls config/

# Figure out which local overrides exist
ls config/local/

# Load a deployment
dotconfig load -d dev -l alice
```

### Reading a file without writing to disk

```bash
# Print the assembled .env to stdout
dotconfig load -d dev --stdout

# Print a specific config file to stdout
dotconfig load -d dev --file app.yaml --stdout
```

### Editing a variable

1. Run `dotconfig load -d <deploy> [-l <local>]` to produce `.env`.
2. Edit the value in `.env` under the correct section.
3. Run `dotconfig save` to write changes back to source files.

### Storing a config file

```bash
# Save a YAML file into the dev deployment
dotconfig save -d dev --file app.yaml

# Save a JSON file into a local directory
dotconfig save -l alice --file settings.json
```

### Adding a new deployment

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
dotconfig load -d dev -l yourname
```

---

## Rules for agents

1. **Never edit source files under `config/` directly** — use `dotconfig save`
   to round-trip changes so encryption is handled correctly.
2. **Never delete section markers or metadata comments** in `.env`.
3. **Always load before saving** if you are unsure whether `.env` is current.
4. **Do not commit `.env`** — it is a generated file and should be in
   `.gitignore`.
5. **Public config is safe to read directly** from `config/{deploy}/public.env`
   if you only need to inspect values without modifying them.
6. **Secrets files are SOPS-encrypted** — you cannot read them directly.  Use
   `dotconfig load` to decrypt them into `.env`.
7. **Use `--stdout`** to read config into your context without writing files.
8. **Use `--file`** with either `-d` or `-l` (not both) to load/save individual
   files like YAML or JSON configs.
