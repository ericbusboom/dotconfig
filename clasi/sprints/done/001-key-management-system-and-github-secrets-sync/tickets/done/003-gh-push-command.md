---
id: '003'
title: gh-push command
status: todo
use-cases: [SUC-003]
depends-on: []
github-issue: ''
todo: plan-dotconfig-gh-push-sync-secrets-to-github.md
---

# gh-push command

## Description

Add `dotconfig gh-push` command that loads deployment secrets and pushes
them to GitHub as repository/environment secrets via `gh secret set`.

## Acceptance Criteria

- [ ] `dotconfig gh-push -d <deploy>` pushes secrets to Actions + Codespaces
- [ ] `--actions` / `--codespaces` narrow scope
- [ ] `--dry-run` shows plan without pushing
- [ ] `--include-age-key` opts in to pushing the SOPS age key
- [ ] `--environment <name>` pushes to GitHub environment scope
- [ ] `--repo <owner/repo>` overrides auto-detected repo
- [ ] Auto-detects repo from git remote
- [ ] Reports what was pushed

## Testing

- **Existing tests to run**: `uv run pytest`
- **New tests to write**: `tests/test_gh_push.py` — unit tests with mocked gh CLI
- **Integration test**: Push a test secret to dotconfig GitHub accounts repo, verify with `gh secret list`, delete with `gh secret delete`
- **Verification command**: `uv run pytest`
