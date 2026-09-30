---
status: complete
---

# Sprint 001 Use Cases

## SUC-001: Generate and manage SSH keys
Parent: None

- **Actor**: Developer
- **Preconditions**: dotconfig initialized, SOPS configured
- **Main Flow**:
  1. Developer runs `dotconfig key gen deploy_rsa --type rsa`
  2. System generates keypair, encrypts private key with SOPS, stores both in `config/keys/`
  3. Developer runs `dotconfig key list` to see stored keys
  4. Developer runs `dotconfig key get deploy_rsa` to retrieve decrypted private key
  5. Developer runs `dotconfig key pub deploy_rsa` to get public key
- **Postconditions**: Key exists in config/keys/, encrypted at rest
- **Acceptance Criteria**:
  - [ ] Key generation works for ed25519, rsa, ecdsa types
  - [ ] Private keys are SOPS-encrypted
  - [ ] Public keys are stored plaintext
  - [ ] `key list` shows all keys with types
  - [ ] `key get` decrypts and outputs private key
  - [ ] `key pub` outputs public key

## SUC-002: Send SSH key to remote host
Parent: None

- **Actor**: Developer
- **Preconditions**: Key exists in config/keys/, remote host is reachable
- **Main Flow**:
  1. Developer runs `dotconfig key send myhost`
  2. System looks up key named `myhost` in config/keys/
  3. System runs `ssh-copy-id -i <pubkey> myhost` to install key
- **Alternate Flow**:
  1. Developer runs `dotconfig key send myhost --key deploy_rsa`
  2. System uses `deploy_rsa` key instead of `myhost`-named key
- **Postconditions**: Public key installed on remote host
- **Acceptance Criteria**:
  - [ ] Default key name matches host argument
  - [ ] `--key` overrides which key to send
  - [ ] Uses ssh-copy-id under the hood

## SUC-003: Push deployment secrets to GitHub
Parent: None

- **Actor**: Developer
- **Preconditions**: dotconfig initialized with secrets, gh CLI authenticated, git remote set
- **Main Flow**:
  1. Developer runs `dotconfig gh-push -d prod`
  2. System loads secrets for prod deployment
  3. System detects GitHub repo from git remote
  4. System pushes each secret via `gh secret set` to both Actions and Codespaces
  5. System reports what was pushed
- **Postconditions**: Secrets available in GitHub Actions and Codespaces
- **Acceptance Criteria**:
  - [ ] Loads secrets from specified deployment
  - [ ] Auto-detects repo from git remote
  - [ ] Pushes to Actions and Codespaces by default
  - [ ] `--actions` / `--codespaces` narrow scope
  - [ ] `--dry-run` shows plan without pushing
  - [ ] `--include-age-key` opts in to pushing SOPS key
  - [ ] `--environment` pushes to GitHub environment scope
