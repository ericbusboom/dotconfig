---
status: done
---

# dotconfig bug: JSON output leaks `export ` prefix into keys

Hand this to the dotconfig agent. It's a small but blocking bug.

## Summary

`dotconfig load <deploy> --json --flat -S` emits keys like
`"export PIKE13_BUSINESS_DOMAIN"` instead of `"PIKE13_BUSINESS_DOMAIN"`.
Consumers that parse the JSON to look up a specific variable by its
real name (e.g. `rundbat secret create`) fail with "key not found".

## Reproduction (dotconfig 0.20260423.3)

```bash
$ dotconfig load -d prod --json --flat -S | python3 -c '
import sys, json
d = json.loads(sys.stdin.read())
print([k for k in d.keys()][:3])
'
['export PIKE13_BUSINESS_DOMAIN', 'export LEAGUE_BEFORETIMES', 'export REGISTRATIONS_SHEET_ID']
```

All 18 keys in our test output are prefixed. This is the `.env`
serializer's `export ` prefix leaking into the object-key position,
which makes no sense for JSON/YAML output.

## Concrete impact

`rundbat secret create prod MEETUP_CLIENT_ID` returns
`{"error": "Key 'MEETUP_CLIENT_ID' not found in dotconfig env for 'prod'"}`
— the value IS in dotconfig, but it's stored under the key
`"export MEETUP_CLIENT_ID"`. rundbat reasonably assumes a JSON key
match is by the literal variable name.

The new `--no-export` flag (0.20260423.3) fixes the `.env` output
path. It needs the same treatment in the JSON/YAML output path.

## Proposed fix

In the JSON/YAML emission code, strip the `export ` prefix from each
key before putting it in the dict. Or ideally, never generate the
`export ` prefix in JSON/YAML mode to begin with — the prefix is a
shell concept, not a data concept.

Also fix the `--no-export` / `--json` / `--yaml` compatibility:

```
$ dotconfig load -d prod --no-export --json --flat -S
Error: --no-export cannot be used with --json or --yaml
```

`--no-export` should be a no-op in JSON/YAML mode (or always default
to "no export" in those modes). The current "error on combination"
behavior hides the fact that the output is already corrupt.

## Acceptance criteria

- [ ] `dotconfig load <deploy> --json --flat -S` produces keys without
      the `export ` prefix
- [ ] `dotconfig load <deploy> --yaml --flat -S` same
- [ ] `--no-export` with `--json` / `--yaml` either works silently or
      is a documented no-op
- [ ] `rundbat secret create <env> <KEY>` finds values by their
      canonical name (covered as a side effect of the fix)
- [ ] Add a smoke test: "every key in JSON output must match
      `^[A-Z_][A-Z0-9_]*$` — no spaces, no prefix"

## Priority

Blocks `rundbat secret create` from being usable in our project.
Workaround is `docker/prod-make-secrets.sh` which reads the `.env`
file directly instead of the JSON. Low effort fix, unblocks the
rundbat upgrade path.
