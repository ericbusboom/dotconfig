# dotconfig — Agent Instructions

> **You are an AI agent working in a project that uses `dotconfig` to manage
> environment configuration.**  This document tells you everything you need
> to operate `dotconfig` correctly.  Read it fully before taking action.

---

## What dotconfig does

`dotconfig` is a configuration vault that stores `.env`, YAML, and JSON
files organised by deployment (dev, prod, staging, …) and by individual
developer.  It has two modes:

1. **Layered `.env` assembly** — merges multiple `.env` source files
   (public config, SOPS-encrypted secrets, per-developer local overrides)
   into a single `.env` with marked sections, and can round-trip edits back.

2. **Single-file retrieval** — stores and retrieves individual files
   (YAML, JSON, or anything else) keyed by deployment or developer name.

### Layered `.env` — how the layers work

| Layer | Path | Purpose |
|---|---|---|
| Public deployment config | `config/{deploy}/public.env` | Shared, non-secret variables for a deployment |
| Encrypted deployment secrets | `config/{deploy}/secrets.env` | SOPS-encrypted secrets for a deployment |
| Public local overrides | `config/local/{user}/public.env` | Per-developer machine-specific overrides |
| Encrypted local secrets | `config/local/{user}/secrets.env` | Per-developer encrypted secrets (optional) |

The resulting `.env` is ordered so that **later sections override earlier ones**
when shell-sourced (last-write-wins): local overrides deployment, secrets
override public.

### Single-file mode

Any file can be stored per-deployment or per-developer:

| Location | Path |
|---|---|
| Deployment file | `config/{deploy}/{filename}` |
| Local/developer file | `config/local/{user}/{filename}` |

A file belongs to one location — you specify `-d` or `-l`, not both.

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
dotconfig load -d <deployment> [-l <local>] [--file <name>] [--embed [VAR_FILE]]... [--output <path>] [--stdout]
```

Without `--file`: assembles layered `.env` source files into a single `.env`.
With `--file`: retrieves a single file from the config vault.

- `-d/--deploy` — the deployment name (`dev`, `prod`, `staging`, …)
- `-l/--local` — developer name for local overrides (`.env` mode) or local files (`--file` mode)
- `--file` — retrieve a specific file instead of assembling `.env`; requires `-d` or `-l` (not both)
- `--embed` / `-e` — base64-embed config files into a `#@dotconfig: files` section. Driven by the `_FILE` suffix convention: declare a `<NAME>_FILE=<filename>` variable in the config, then pass `-e <NAME>_FILE` (or `-e` alone to expand every `*_FILE` variable). The file is read from `config/<deploy>/` then `config/local/<user>/` (first-match wins; SOPS-decrypted on the fly), base64-encoded, and emitted as `<NAME>=<base64>`. The original `<NAME>_FILE` is kept in its source section so consumers that read the path-style variable still work. Repeatable. Auto-decrypts SOPS-encrypted sources. Incompatible with `--file`, `--json`, `--yaml`.
- `--no-export` — strip the leading `export ` prefix from assignment lines so the output parses as plain `KEY=value` lines. Implied by `-S/--stdout` (piped consumers usually reject shell-style exports). Metadata comments and section markers are preserved. Incompatible with `--file`. To round-trip source files that use `export ` through a `--no-export` load, pair with `save --add-export` so the prefix is re-added when writing back.
- `--add-export` — ensure every assignment line in the `.env` output has an `export ` prefix (no double-up if the source already has it). Use to override the implicit `--no-export` behavior of `-S/--stdout`, or to normalize source files that mix prefixed and plain assignments. Mutually exclusive with `--no-export`.
- `--stdout` / `-S` — print to stdout instead of writing to a file. **Implies `--no-export`** unless `--add-export` is passed.
- `--output` / `-o` — write to a specific path instead of the default

**Examples:**

```bash
# Assemble layered .env
dotconfig load -d dev -l alice          # dev deployment + Alice's local overrides
dotconfig load -d prod                  # prod only, no local overrides
dotconfig load -d dev --stdout          # print assembled .env to stdout

# Retrieve a single file
dotconfig load -d dev --file app.yaml              # write to ./app.yaml
dotconfig load -d dev --file app.yaml --stdout      # print to stdout
dotconfig load -l alice --file settings.json        # from Alice's local dir

# Embed deployment files as base64 inside the .env (Docker/env-var workflows).
# The convention: declare a *_FILE variable in your config, e.g.
#   CERT_FILE=server.pem
# then pass the *_FILE name to -e (suffix is stripped → CERT=<base64>).
dotconfig load -d dev -e CERT_FILE                # one file
dotconfig load -d dev -e CERT_FILE -e KEY_FILE    # several
dotconfig load -d dev -e                          # every *_FILE variable

# Strip `export` prefix for parsers that reject shell-style assignments
# (e.g. `docker stack deploy`).
dotconfig load -d prod --no-export -o .env

# -S/--stdout already implies --no-export — pipe-friendly by default
dotconfig load -d prod -S | jq .

# Override the stdout default to keep the export prefix
dotconfig load -d prod -S --add-export
```

### `dotconfig save`

```
dotconfig save [-d <deployment>] [-l <local>] [--file <name>] [--env-file .env]
```

Without `--file`: reads the `.env` file (must have been produced by
`dotconfig load`) and writes each marked section back to its source file,
re-encrypting secrets via SOPS.  With `--file`: stores a single file into
the config vault.

- `-d`/`-l` without `--file` — override the destination deployment or
  developer (useful for cloning a deployment)
- `-d`/`-l` with `--file` — specify where the file goes; requires one
  or the other (not both)
- `--add-export` — prepend `export ` to assignment lines when writing
  back to source `.env` files. Pairs with `load --no-export` to
  preserve shell-style sources across a round-trip. Lines already
  prefixed with `export `, comments, and blank lines are left alone.
  Incompatible with `--file`, `--json`, `--yaml`.
- The `.env` **must** contain `# CONFIG_DEPLOY=` metadata for save to work.

**Examples:**

```bash
# Round-trip .env back to source files
dotconfig save                                  # save to original locations
dotconfig save -d staging                       # redirect to staging deployment

# Re-add `export` prefix when writing back (pairs with load --no-export)
dotconfig save --add-export

# Store a single file
dotconfig save -d dev --file app.yaml           # store into config/dev/
dotconfig save -l alice --file settings.json    # store into config/local/alice/
```

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
directory was found.  Useful for verifying your setup.

### `dotconfig agent`

```
dotconfig agent
```

Prints this document.  If you are reading this, you have already run it
or are reading the source file directly.

---

## Generated `.env` format

The `.env` file produced by `dotconfig load` (without `--file`) contains
metadata comments and marked sections:

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

#@dotconfig: files
CERT=LS0tLS1CRUdJTi...        # base64-encoded file content (from --embed CERT_FILE)
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
- The `#@dotconfig: files` section (only present when `--embed`/`-e` was used)
  holds base64-encoded file content. It is **not** written back to any source
  file by `dotconfig save` — it is regenerated on each `load`. Do not hand-edit
  these values; change the source file in `config/<deploy>/` and reload.

---

## Directory layout

```
config/
  sops.yaml                     # SOPS encryption rules
  dev/                          # One directory per deployment
    public.env                  #   layered .env source
    secrets.env                 #   SOPS-encrypted .env source
    app.yaml                    #   any other config files
    docker-compose.override.yml #   stored via --file
  prod/
    public.env
    secrets.env
  local/
    alice/                      # One directory per developer
      public.env                #   layered .env source
      secrets.env               #   optional, SOPS-encrypted
      settings.json             #   any other config files
    bob/
      public.env
```

Deployment names are open-ended — any valid directory name works.

---

## SOPS encryption

- Secrets files are encrypted with [SOPS](https://github.com/getsops/sops)
  using [age](https://github.com/FiloSottile/age) keys.
- `dotconfig` handles decryption/encryption automatically during load/save
  of layered `.env` files.
- If SOPS or keys are not available, secrets sections are skipped with a
  warning — public config still works.
- The SOPS config lives at `config/sops.yaml` (not `.sops.yaml` in the repo
  root), so it is not auto-discovered by SOPS.  When calling SOPS directly:
  ```bash
  SOPS_CONFIG=config/sops.yaml sops --encrypt --in-place config/dev/secrets.env
  ```
- Single files loaded/saved via `--file` are **not** automatically
  encrypted — use SOPS directly if you need to encrypt them.

---

## Common agent tasks

### Loading environment config

```bash
# Figure out which deployments exist
ls config/

# Figure out which local overrides exist
ls config/local/

# Load a deployment's .env
dotconfig load -d dev -l alice
```

### Reading config without writing to disk

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

### Storing and retrieving config files

```bash
# Save a YAML file into the dev deployment
dotconfig save -d dev --file app.yaml

# Load it back (or print to stdout)
dotconfig load -d dev --file app.yaml
dotconfig load -d dev --file app.yaml --stdout

# Save a JSON file into a local directory
dotconfig save -l alice --file settings.json
```

### Generating a `.env` for `docker stack deploy` / strict env-file parsers

`docker compose up` tolerates shell-style `export KEY=value` lines, but
`docker stack deploy -c <compose.yml>` and some other env-file parsers
reject them because they read `export KEY` as a key name containing
whitespace. For those consumers, pass `--no-export`:

```bash
# Output is plain KEY=value — compatible with docker stack deploy env_file:
dotconfig load -d prod --no-export -o .env
```

Notes:
- Metadata comments (`# CONFIG_DEPLOY=…`) and section markers
  (`#@dotconfig: …`) are preserved — they aren't assignments.
- Embedded files (`-e`) are already written without the `export` prefix,
  so they're unaffected.
- Round-trip: if your source files use `export KEY=value`, combine
  `load --no-export` with `save --add-export` so the style is restored
  when writing back. Without `--add-export`, save writes section bodies
  verbatim and the `export` prefix is lost from the source files.

### Embedding files as env vars (Docker / PEM / cert use case)

For deployment targets that consume certificates, PEM files, or keys through
environment variables rather than mounted files (common with Docker images and
serverless runtimes), embed the file as a base64-encoded variable directly in
the `.env`. The pairing lives in the config itself via the `_FILE` suffix
convention:

```bash
# config/dev/public.env
CERT_FILE=server.pem
SSL_KEY_FILE=ssl.key
```

```bash
# Expand one
dotconfig load -d dev -e CERT_FILE

# Expand several
dotconfig load -d dev -e CERT_FILE -e SSL_KEY_FILE

# Expand every *_FILE variable in the loaded config
dotconfig load -d dev -e
```

The output adds a `#@dotconfig: files` section, with the `_FILE` suffix
stripped from each destination key:

```bash
#@dotconfig: public (dev)
CERT_FILE=server.pem
SSL_KEY_FILE=ssl.key

#@dotconfig: files
CERT=LS0tLS1CRUdJTi...
SSL_KEY=LS0tLS1CRUdJTi...
```

Notes:
- Source file lookup: `config/<deploy>/<filename>` first, then
  `config/local/<user>/<filename>`. Stacked deployments and locals are
  searched in order; first-match wins.
- A `*_FILE` variable can be defined in any of the four sections (deploy
  public, deploy secrets, local public, local secrets). Locals override
  deploys (last-write-wins).
- SOPS-encrypted source files are auto-decrypted before base64 encoding.
- The original `*_FILE` variable stays in its source section, so consumers
  that read the path-style variable still work. The base64 form is the
  parallel for env-var consumers.
- `dotconfig save` does **not** write the `files` section back to any source
  file. The section is regenerated each time `load` runs with `-e`.
- Incompatible with `--file`, `--json`, and `--yaml`.
- With `--split`: embedded files go into the `.env.secret` companion (treated
  as secrets), not the public `.env`.

### Adding a new deployment

```bash
mkdir -p config/newenv
echo 'KEY=value' > config/newenv/public.env
dotconfig load -d newenv            # generates .env from the new deployment
# Edit .env to add secrets under the secrets section, then:
dotconfig save                      # writes secrets back, encrypted via SOPS
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
