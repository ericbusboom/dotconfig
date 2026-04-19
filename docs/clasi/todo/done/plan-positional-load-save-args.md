---
status: done
sprint: '002'
tickets:
- '002'
---

# Plan: positional args for `dotconfig load` and `dotconfig save`

## Context

Today, `load` and `save` require explicit flags to name the deployment
and local override:

    dotconfig load -d dev -l eric
    dotconfig save -d dev -l eric

The flags are noisy for the common case and don't extend naturally to
stacking multiple deployments or multiple local overrides on top of
each other.

## Change

Accept positional name arguments on `load` and `save`. Each argument
is classified by looking at what exists under `config/`:

- if `config/<name>/` exists → it's a deployment
- if `config/local/<name>/` exists → it's a local override
- ambiguous or missing → error with a clear message

Order on the command line is the layer order (later overrides earlier),
within each type. Examples:

    dotconfig load dev eric
        # equivalent to: -d dev -l eric

    dotconfig load dev prod eric alice
        # deployments: dev (base), prod (overlay)
        # locals:      eric (overlay), alice (final overlay)

    dotconfig load eric dev
        # same as `dev eric` — type-stacking is order-independent
        # ACROSS types, but order-significant WITHIN each type.

`save` behavior:

    dotconfig save
        # round-trip: writes each section back to whichever
        # deployment/local it was loaded from (read from .env metadata).

    dotconfig save dev
        # write the entire assembled .env to deployment `dev`,
        # ignoring per-section provenance. Equivalent to today's
        # `save -d dev` override behavior, applied to the whole file.

## Implications / open questions

- The `.env` metadata block currently records a single `CONFIG_DEPLOY`
  and `CONFIG_LOCAL`. To round-trip stacked loads, this must become a
  list (e.g. `CONFIG_DEPLOYS=dev,prod`, `CONFIG_LOCALS=eric,alice`)
  and the `#@dotconfig: <section>` markers must be unique per layer
  (already are, since the section label includes the deployment/local
  name).
- Internal `load_config` / `save_config` signatures take `deployment:
  str` and `local: Optional[str]` — they will need to accept lists.
  The existing code paths in `src/dotconfig/load.py` and
  `src/dotconfig/save.py` only iterate over one deployment + one
  local; the layering loop needs to be generalised.
- `-d` and `-l` flags: decide whether to keep them as backward-compatible
  aliases or remove them outright. Recommend keeping them (hidden) for
  one release to avoid breaking existing scripts.
- Name collision: if a name exists as both a deployment and a local,
  fail loudly and require the user to disambiguate with `-d`/`-l`.
- `--file`, `--json`, `--yaml`, `--flat`, `--split`, `--stdout` flags
  remain unchanged.
