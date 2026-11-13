---
id: '003'
title: Label-aware sops.yaml parse and key_groups render
status: open
use-cases:
- SUC-004
depends-on:
- '002'
github-issue: ''
issue: user-config-public-keys.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Label-aware sops.yaml parse and key_groups render

## Description

In init.py add _parse_sops_keys(content) -> list of (key,label) reading every legacy form (folded block scalar, inline string, list, key_groups) plus trailing '# label' comments via a line scanner; _collect_age_keys delegates and now also reads key_groups. _render_sops_yaml accepts labeled keys and renders the catch-all rule with key_groups: [{age: [- age1... # label]}] (architecture-update D1). Labels already in an existing file survive a re-render.

## Acceptance Criteria

- [ ] Parse returns keys (and labels where present) for block scalar, inline, list and key_groups sources
- [ ] Render->parse round trip preserves keys, order and labels; unlabeled keys render without a comment
- [ ] Existing label kept for a key absent from supplied labels; a supplied label overrides
- [ ] Rendered file works with real sops: encrypt and decrypt round trip with 2 recipients, decryptable by either key (skip if sops/age missing)
- [ ] Existing init tests updated for the new layout and pass
- [ ] public.env no-op rule unchanged
- [ ] Tests use an autouse fixture (tests/conftest.py, added by the first ticket that needs it) that monkeypatches HOME and XDG_CONFIG_HOME (and clears SOPS_AGE_KEY_FILE/SOPS_AGE_KEY unless a test sets them) to tmp dirs. No test touches the real ~/.config.

## Implementation Plan

Files: src/dotconfig/init.py, tests/test_init*.py, new tests/test_sops_labels.py. Use temp keys via age-keygen for the sops round trip.

## Testing

- **Existing tests to run**: `uv run pytest` scoped to the touched modules
- **New tests to write**: as listed above
- **Verification command**: `uv run pytest`
