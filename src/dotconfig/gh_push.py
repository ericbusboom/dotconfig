"""
gh-push command: sync deployment secrets to GitHub Actions / Codespaces.

Loads secrets from a dotconfig deployment and pushes each one as a
GitHub repository (or environment) secret via the ``gh`` CLI.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .load import _read_env_layers, _env_lines_to_dict
from .output import error, heading, info, item, ok, warn


def _detect_repo() -> Optional[str]:
    """Detect the GitHub repo from git remote origin."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        )
        url = result.stdout.strip()
        # Parse SSH or HTTPS URLs
        # git@github.com:owner/repo.git
        if url.startswith("git@github.com:"):
            repo = url[len("git@github.com:"):].removesuffix(".git")
            return repo
        # https://github.com/owner/repo.git
        if "github.com/" in url:
            parts = url.split("github.com/", 1)[1].removesuffix(".git")
            return parts
        return None
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _load_secrets_flat(
    deployment: str,
    config_dir: Path,
) -> Dict[str, str]:
    """Load all secrets for a deployment as a flat dict."""
    _, deploy_layers, _ = _read_env_layers([deployment], [], config_dir)
    _, public_text, secrets_text = deploy_layers[0]
    result: Dict[str, str] = {}
    result.update(_env_lines_to_dict(public_text))
    result.update(_env_lines_to_dict(secrets_text))
    return result


def _push_secret(
    key: str,
    value: str,
    repo: str,
    app: Optional[str] = None,
    environment: Optional[str] = None,
) -> bool:
    """Push a single secret via gh secret set."""
    cmd = ["gh", "secret", "set", key, "--body", value, "--repo", repo]
    if environment:
        cmd += ["--env", environment]
    elif app:
        cmd += ["--app", app]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        warn(f"failed to set {key}: {e.stderr.strip()}")
        return False


def gh_push(
    deployment: str,
    config_dir: Path,
    repo: Optional[str] = None,
    actions: bool = False,
    codespaces: bool = False,
    include_age_key: bool = False,
    environment: Optional[str] = None,
    dry_run: bool = False,
    keys_filter: Optional[List[str]] = None,
) -> None:
    """Push deployment secrets to GitHub."""
    if shutil.which("gh") is None:
        error("gh CLI not found — install from https://cli.github.com")
        sys.exit(1)

    # Detect repo
    if not repo:
        repo = _detect_repo()
        if not repo:
            error("could not detect GitHub repo — use --repo owner/repo")
            sys.exit(1)

    # Load secrets
    secrets = _load_secrets_flat(deployment, config_dir)

    if keys_filter:
        secrets = {k: v for k, v in secrets.items() if k in keys_filter}

    if not secrets:
        info("no secrets to push")
        return

    # Handle age key
    age_key_name = "SOPS_AGE_KEY"
    if not include_age_key and age_key_name in secrets:
        del secrets[age_key_name]

    # Determine scopes
    scopes: List[Optional[str]] = []
    if environment:
        scopes = [None]  # environment scope uses --env, not --app
    elif actions and not codespaces:
        scopes = [None]  # Actions is the default (no --app flag)
    elif codespaces and not actions:
        scopes = ["codespaces"]
    else:
        scopes = [None, "codespaces"]  # Both

    if dry_run:
        heading(f"Dry run — would push {len(secrets)} secrets to {repo}:")
        for key in sorted(secrets):
            item(f"  {key}")
        if environment:
            info(f"target: environment '{environment}'")
        else:
            scope_names = ["Actions" if s is None else s.title() for s in scopes]
            info(f"target: {', '.join(scope_names)}")
        if not include_age_key:
            info("skipped: SOPS_AGE_KEY (use --include-age-key to push)")
        return

    # Push to each scope
    for scope in scopes:
        scope_label = "Actions" if scope is None else scope.title()
        if environment:
            scope_label = f"environment '{environment}'"

        pushed = []
        for key, value in sorted(secrets.items()):
            success = _push_secret(
                key, value, repo,
                app=scope,
                environment=environment,
            )
            if success:
                pushed.append(key)

        heading(f"Pushed {len(pushed)} secrets to {repo} ({scope_label}):")
        for key in pushed:
            item(f"  {key}")

    if not include_age_key:
        info("skipped: SOPS_AGE_KEY (use --include-age-key to push)")
