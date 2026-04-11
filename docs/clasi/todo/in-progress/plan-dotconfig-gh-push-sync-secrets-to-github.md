---
status: in-progress
sprint: '001'
tickets:
- 001-003
---

# Plan: `dotconfig gh-push` — Sync Secrets to GitHub

## Context

When using `build_strategy: github-actions`, GitHub Actions needs access to deployment secrets (SSH keys, host info) and app secrets (DATABASE_URL, API keys, etc.). Codespaces dev environments also need secrets. Today these live in dotconfig (SOPS-encrypted). The user wants a `dotconfig` command that pushes all secrets for a deployment to GitHub as individual repository secrets.

This is a **dotconfig** command — dotconfig already owns secret management, and GitHub is just another target.

## Design

### New command: `dotconfig gh-push`

```bash
# Push all secrets for a deployment to GitHub Actions + Codespaces
dotconfig gh-push -d prod

# Push to Actions only
dotconfig gh-push -d prod --actions

# Push to Codespaces only
dotconfig gh-push -d prod --codespaces

# Include the age decryption key (explicit opt-in)
dotconfig gh-push -d prod --include-age-key

# Push to a GitHub environment
dotconfig gh-push -d prod --environment prod

# Dry run
dotconfig gh-push -d prod --dry-run

# Specific repo (if not auto-detected)
dotconfig gh-push -d prod --repo owner/repo

# Push only specific keys
dotconfig gh-push -d prod --keys DATABASE_URL,DEPLOY_SSH_KEY
```

### Secret scopes

GitHub has three secret scopes, each with its own `gh` flag:

| Scope | `gh` command | Use case |
|-------|-------------|----------|
| Actions | `gh secret set KEY` (default) | CI/CD workflows |
| Codespaces | `gh secret set KEY --app codespaces` | Dev environments |
| Dependabot | `gh secret set KEY --app dependabot` | Dependency updates |

`dotconfig gh-push` defaults to **both Actions and Codespaces**. Flags narrow the scope:
- No flags → push to both Actions and Codespaces
- `--actions` — push to Actions only
- `--codespaces` — push to Codespaces only

### What it does

1. **Load secrets** from dotconfig for the named deployment:
   ```
   dotconfig load -d prod --json --flat -S
   ```

2. **Detect GitHub repo** from `git remote get-url origin` (or `--repo`).

3. **Push each key** via `gh secret set`:
   ```bash
   # Actions (default)
   gh secret set DATABASE_URL --body "postgresql://..." --repo owner/repo
   
   # Codespaces
   gh secret set DATABASE_URL --body "postgresql://..." --repo owner/repo --app codespaces
   ```

4. **Age key** (only with `--include-age-key`):
   ```bash
   # Read the age key from dotconfig's key store
   gh secret set SOPS_AGE_KEY --body "$(cat config/keys/age.key)" --repo owner/repo
   ```
   The age key is the master decryption key — pushing it is a deliberate choice. Without this flag, it's excluded even if it exists.

5. **Report**:
   ```
   Pushed 8 secrets to github.com/owner/repo (Actions):
     DATABASE_URL
     DB_USER
     DB_PASSWORD
     DEPLOY_HOST
     DEPLOY_USER
     DEPLOY_SSH_KEY
     REDIS_URL
     SECRET_KEY
   
   Pushed 8 secrets to github.com/owner/repo (Codespaces):
     (same keys)
   
   Skipped: SOPS_AGE_KEY (use --include-age-key to push)
   ```

### Key naming

Each dotconfig key maps 1:1 to a GitHub secret — same name, no prefixing. If the user has multiple deployments, they use GitHub environments (`--environment`) to namespace them.

### GitHub Environments

```bash
dotconfig gh-push -d prod --environment prod
```

Uses `gh secret set KEY --env prod` instead of repo-level. Workflows reference the environment:

```yaml
jobs:
  deploy:
    environment: prod
    steps:
      - run: echo ${{ secrets.DATABASE_URL }}  # from prod environment
```

### Prerequisites

- `gh` CLI installed and authenticated
- dotconfig initialized with secrets
- Git remote pointing to GitHub

## Flags summary

| Flag | Purpose |
|------|---------|
| `-d <name>` | Deployment to sync (required) |
| `--actions` | Push to Actions only (default: both Actions + Codespaces) |
| `--codespaces` | Push to Codespaces only (default: both Actions + Codespaces) |
| `--include-age-key` | Include the SOPS age decryption key (opt-in) |
| `--environment <name>` | Push to a GitHub environment instead of repo-level |
| `--repo <owner/repo>` | Override auto-detected repo |
| `--dry-run` | Show what would be pushed |
| `--keys <K1,K2,...>` | Push only specific keys |

## Implementation

The `gh-push` command goes in the dotconfig codebase. For rundbat, the changes are skill/doc references only:

| File (rundbat) | Action |
|------|--------|
| `src/rundbat/content/skills/deploy-setup.md` | Add step: sync secrets with `dotconfig gh-push` |
| `src/rundbat/content/skills/github-deploy.md` | Reference gh-push in setup flow |

## Verification

1. `dotconfig gh-push -d prod --dry-run` → lists keys, notes age key skipped
2. `dotconfig gh-push -d prod` → pushes to both Actions + Codespaces
3. `dotconfig gh-push -d prod --actions` → pushes to Actions only
4. `dotconfig gh-push -d prod --include-age-key` → includes SOPS_AGE_KEY
5. `dotconfig gh-push -d prod --environment prod` → pushes to environment scope
6. `gh secret list` → shows pushed secrets
