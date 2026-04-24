---
status: done
---

# Redesign `dotconfig load -e/--embed` around the `_FILE` variable convention

Replaces the current `-e VAR=FILENAME` syntax with a self-documenting,
config-driven form keyed off the `_FILE` suffix convention common in
Docker / 12-factor apps.

## Summary

Today, embedding a file as a base64 env var requires the user to repeat
both the destination variable name and the source filename on the CLI:

```bash
dotconfig load dev -e CERT_PEM=cert.pem -e SSL_KEY=ssl.key
```

The new design moves the pairing into the config itself. The `.env` source
declares which variables refer to filenames using a `_FILE` suffix:

```
# config/prod/public.env
CERT_FILE=cert.pem
SSL_KEY_FILE=ssl.key
```

A single CLI flag triggers expansion:

```bash
dotconfig load prod -e CERT_FILE        # one var
dotconfig load prod -e CERT_FILE -e SSL_KEY_FILE
dotconfig load prod -e                  # all *_FILE variables
```

For each expanded `<NAME>_FILE`, the file referenced by the variable's
value is read from the config tree, base64-encoded, and emitted as
`<NAME>=<base64>` in the existing `#@dotconfig: files` section. The
original `<NAME>_FILE` is **kept** in its original section so consumers
that read the path-style variable (Docker secrets, etc.) still work; the
base64 form is the parallel for env-var consumers.

This is a **breaking change** to the `-e` flag — `VAR=FILENAME` is
removed.

## CLI shape

`-e` / `--embed` becomes an optional-value, repeatable flag.

| Form | Meaning |
|---|---|
| (omitted) | No embedding. |
| `-e` (alone, no value) | Auto-expand every `*_FILE` variable in the loaded config. |
| `-e CERT_FILE` | Expand only `CERT_FILE`. |
| `-e CERT_FILE -e SSL_KEY_FILE` | Expand the listed variables. |
| `-e CERT_FILE -e` (mixed) | If any occurrence is the no-value form, expand all (broader wins). |

Click implementation: `is_flag=False, flag_value="*", multiple=True`. The
sentinel `"*"` is illegal as a shell variable name and can't collide with
a real `*_FILE` var.

Validations (in addition to existing `--embed cannot be used with
--json/--yaml/--file`):
- A non-sentinel value must end in `_FILE` and match
  `^[A-Z_][A-Z0-9_]*_FILE$`. Otherwise `UsageError("--embed argument
  must be a *_FILE variable name, got: ...")`.
- A value containing `=` raises a UsageError pointing at the new form
  (catches the old `VAR=FILENAME` muscle memory).

## Resolution algorithm (replaces `_embed_files_section()`)

Inputs: list of `_FILE` var names (or sentinel meaning "all"), the
assembled section bodies (all 4 sections), the deploy dirs and local
dirs in stack order, the sops_config path.

1. **Build the effective config dict** by parsing the section bodies in
   load order: `public (deploy_1) → secrets (deploy_1) → ... →
   public-local (local_1) → secrets-local (local_1) → ...`,
   last-write-wins. Reuse `_env_lines_to_dict()`.
2. **Determine the var list:**
   - Sentinel present → `var_names = sorted(k for k in effective if k.endswith("_FILE"))`.
   - Otherwise → `var_names = explicit list`, each validated to end in `_FILE`.
3. **For each var_name:**
   - Look up the value (filename) in the effective dict. Missing →
     `error("--embed: variable {var_name} not found in config")`, exit 1.
   - Resolve filename: search **deploy dirs first**, then **local dirs**,
     in stack order. First match wins. No match → error and exit 1.
   - Auto-decrypt if SOPS-encrypted (existing `_decrypt_sops`).
   - Base64-encode bytes.
   - Emit `<base_name>=<b64>` where `base_name = var_name.removesuffix("_FILE")`.
4. **Return the lines** to be appended under `#@dotconfig: files`. The
   integration into the assembled `.env` (split / non-split / `--no-export`
   / `--add-export`) is unchanged — those paths already do the right thing
   for the files section.

Edge cases handled by existing code (no new logic needed):
- Stacked deployments: dir lists already passed in order; first-match wins.
- `--split`: `files` section already routed to `.env.secret`.
- `--no-export` / `--add-export`: `files` section is plain `KEY=value`,
  neither helper touches it problematically.

## Resolved design decisions

1. **Old `VAR=FILENAME` syntax:** Dropped entirely. `-e` value containing
   `=` raises a UsageError that points at the new `_FILE` convention.
2. **Variable lookup scope:** All 4 sections (public + secrets +
   public-local + secrets-local), built from the assembled config via
   `_env_lines_to_dict`. Layering applies last-write-wins — a local can
   override a deploy `_FILE` variable.
3. **File search path:** Deploy dirs *then* local dirs. Order: each
   deploy dir in stack order, then each local dir in stack order. First
   match wins. Slight expansion over today's behavior (which only searched
   deploy dirs) — lets developers ship personal cert/key files in
   `config/local/<user>/` without modifying the deployment.

## Files to change

- `src/dotconfig/cli.py` — rewrite the `--embed` option declaration;
  tighten validations; update help text and the `Example:` docstring.
- `src/dotconfig/load.py` — replace `_embed_files_section()` with a new
  helper that takes the effective config dict and the list-or-sentinel.
  Update both call sites (`.env` non-split branch and split branch) to
  build the effective dict and pass deploy + local dirs. The signature
  of `load_config()` keeps `embed_files: tuple` (semantics shift from
  `VAR=FILENAME` strings to `_FILE` var names + optional `*` sentinel).
- `tests/test_load.py` — replace `TestLoadConfigEmbedFiles` against the
  new contract (see Acceptance criteria below for case list).
- `tests/test_cli.py` — add CLI-level tests for the optional-value flag
  parsing.
- `README.md` and `src/dotconfig/agent_instructions.md` — replace the
  `--embed` docs. Show explicit (`-e CERT_FILE`) and bulk (`-e`) forms;
  note that `*_FILE` is kept alongside the base64 form.

## Acceptance criteria

- [ ] `dotconfig load <deploy> -e FOO_FILE` resolves the variable's
      value as a filename, base64-encodes the file, emits `FOO=<b64>`
      under `#@dotconfig: files`.
- [ ] `dotconfig load <deploy> -e` (alone) auto-expands every `*_FILE`
      variable in the loaded config.
- [ ] `-e FOO_FILE -e` (mixed) → all expanded (broader wins).
- [ ] `-e FOO=cert.pem` → UsageError pointing at the new form.
- [ ] `-e foo` (no `_FILE` suffix) → UsageError.
- [ ] `-e MISSING_FILE` (variable not in config) → `SystemExit` with
      a clear error message.
- [ ] `*_FILE` variable's referenced file not found in any deploy or
      local dir → `SystemExit` with a clear error message.
- [ ] SOPS-encrypted source files are decrypted before encoding.
- [ ] Stacked deployments: first-match wins (deploys before locals).
- [ ] `*_FILE` value resolves correctly when defined in `public-local`
      or `secrets-local` (overrides deploy-level definition).
- [ ] `--split`: files section lands in `.env.secret`.
- [ ] `--no-export` / `--add-export`: files section unaffected.
- [ ] Original `*_FILE` variable remains in its source section after
      embedding.

## Verification

1. `uv run pytest`.
2. Manual smoke test:
   ```bash
   mkdir -p /tmp/dctest/config/prod
   printf "CERT_FILE=server.pem\nSSL_KEY_FILE=ssl.key\n" > /tmp/dctest/config/prod/public.env
   echo "test cert" > /tmp/dctest/config/prod/server.pem
   echo "test key" > /tmp/dctest/config/prod/ssl.key
   cd /tmp/dctest

   uv run dotconfig load prod -e -S            # bulk: emits CERT, SSL_KEY (base64)
   uv run dotconfig load prod -e CERT_FILE -S  # explicit: only CERT
   ```
3. Confirm a sourced shell sees both `CERT_FILE=server.pem` and
   `CERT=<base64>`.

## Priority

Quality-of-life improvement; no production blocker. The current
`VAR=FILENAME` form works fine for users who know it. Worth doing before
the embed feature gets wider adoption — the `_FILE` form is dramatically
more discoverable and self-documenting.
