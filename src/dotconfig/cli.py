"""
CLI entry point for dotconfig.

Commands
--------
dotconfig init
    Create the config/ directory structure and set up age encryption keys.

dotconfig load -d <deployment> [-l <local>] [--file <name>] [--stdout]
    Assemble config/ source files into a single .env file, or retrieve
    a specific file from a deployment.

dotconfig save [-d <deployment>] [-l <local>] [--file <name>]
    Write .env sections back to their config/ source files, or store
    a specific file into a deployment.

dotconfig keys
    Show age encryption key status and configuration.

dotconfig config
    Show dotconfig configuration and discovered paths.

dotconfig agent
    Print full operational instructions for AI agents.
"""

import click
from pathlib import Path

from .agent import show_agent_instructions
from .audit import run_audit
from .config import show_config
from .hooks import install_pre_commit_hook
from .init import init_config
from .keys import show_keys
from .load import load_config, load_file
from .save import save_config, save_file


@click.group()
@click.version_option()
def cli() -> None:
    """dotconfig — environment configuration cascade manager.

    Manages layered .env configuration assembled from multiple source
    files (common config, SOPS-encrypted secrets, and developer-local
    overrides) stored under a config/ directory.

    \b
    AI agents: run "dotconfig agent" for full operational instructions.
    """


@cli.command()
@click.option(
    "--config-dir",
    default="config",
    show_default=True,
    help="Root config directory to create.",
)
def init(config_dir: str) -> None:
    """Initialise the config directory structure and set up age encryption.

    Creates the following directories (skips any that already exist):

    \b
        config/
        config/secrets/
        config/local/
        config/secrets/local/

    Then discovers an existing age private key (checking SOPS_AGE_KEY,
    SOPS_AGE_KEY_FILE, and ~/.config/sops/age/keys.txt in that order),
    derives the public key, and ensures it is listed in .sops.yaml.

    Example:

    \b
        dotconfig init
        dotconfig init --config-dir myconfig
    """
    init_config(config_dir=Path(config_dir))


@cli.command()
@click.option(
    "-d", "--deploy",
    required=False,
    default=None,
    help="Deployment / environment name (e.g. dev, prod, staging).",
)
@click.option(
    "-l", "--local",
    required=False,
    default=None,
    help="Local / developer name for personal overrides.",
)
@click.option(
    "-c", "--config-dir",
    default="config",
    show_default=True,
    help="Root config directory.",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Destination file.  [default: .env, or the filename from --file]",
)
@click.option(
    "--file", "-f",
    "filename",
    default=None,
    help="Load a specific file (e.g. foobar.yaml) instead of assembling .env.",
)
@click.option(
    "--stdout", "to_stdout",
    is_flag=True,
    default=False,
    help="Print to stdout instead of writing to a file.",
)
def load(
    deploy: str,
    local: str,
    config_dir: str,
    output: str,
    filename: str,
    to_stdout: bool,
) -> None:
    """Assemble config files into .env, or load a specific file.

    \b
    Requires -d/--deploy to select the deployment (e.g. dev, prod).
    Optionally add -l/--local for developer-specific overrides.

    Use --file to retrieve a single file from the config directory
    instead of assembling a full .env (specify -d or -l, not both).
    Use --stdout to print to stdout instead of writing to disk
    (useful for piping or agents).

    Example:

    \b
        dotconfig load -d dev -l yourname
        dotconfig load -d prod
        dotconfig load -d dev --file app.yaml --stdout
        dotconfig load -l alice --file settings.json -o out.json
    """
    cfg = Path(config_dir)
    out = Path(output) if output else None

    if filename:
        load_file(
            deployment=deploy,
            local=local,
            filename=filename,
            config_dir=cfg,
            output=out,
            to_stdout=to_stdout,
        )
    else:
        if not deploy:
            raise click.UsageError("-d/--deploy is required when assembling .env")
        load_config(
            deployment=deploy,
            local=local,
            config_dir=cfg,
            output=out,
            to_stdout=to_stdout,
        )


@cli.command()
@click.option(
    "-d", "--deploy",
    required=False,
    default=None,
    help="Target deployment name (overrides the .env metadata).",
)
@click.option(
    "-l", "--local",
    required=False,
    default=None,
    help="Target local / developer name (overrides the .env metadata).",
)
@click.option(
    "--env-file",
    default=".env",
    show_default=True,
    help=".env file to read and save.",
)
@click.option(
    "-c", "--config-dir",
    default="config",
    show_default=True,
    help="Root config directory.",
)
@click.option(
    "--file", "-f",
    "filename",
    default=None,
    help="Save a specific file (e.g. foobar.yaml) into the config directory.",
)
@click.option(
    "-e", "--encrypt",
    is_flag=True,
    default=False,
    help="Encrypt the file with SOPS (only with --file).",
)
def save(
    deploy: str,
    local: str,
    env_file: str,
    config_dir: str,
    filename: str,
    encrypt: bool,
) -> None:
    """Save .env sections back to config/ source files, or store a file.

    \b
    Without --file: reads CONFIG_DEPLOY and CONFIG_LOCAL from the .env
    metadata, then writes each section back to its corresponding source
    file, re-encrypting secrets with SOPS.  Optionally provide
    -d/--deploy and -l/--local to redirect the output to a different
    deployment or user.

    With --file: copies the named file into the deployment or local
    config directory.  Add -e/--encrypt to encrypt the file with SOPS.
    Encrypted files are automatically decrypted on load.

    Example:

    \b
        dotconfig save
        dotconfig save -d dev -l stan
        dotconfig save --file app.yaml -d dev
        dotconfig save --file secrets.yaml -d dev --encrypt
        dotconfig save --file settings.json -l alice
    """
    cfg = Path(config_dir)

    if encrypt and not filename:
        raise click.UsageError("--encrypt can only be used with --file")

    if filename:
        save_file(
            deployment=deploy,
            local=local,
            filename=filename,
            config_dir=cfg,
            encrypt=encrypt,
        )
    else:
        save_config(
            env_file=Path(env_file),
            config_dir=cfg,
            override_deploy=deploy,
            override_local=local,
        )


@cli.command()
def keys() -> None:
    """Show age encryption key status and configuration.

    Inspects your environment for age keys, reports where SOPS will
    find your secret key, shows the derived public key, and prints
    export statements for configuring environment variables.

    Example:

    \b
        dotconfig keys
    """
    show_keys()


@cli.command()
@click.option(
    "-c", "--config-dir",
    default=None,
    help="Root config directory.  [default: auto-discovered or 'config']",
)
def audit(config_dir: str) -> None:
    """Scan config/ for unencrypted secrets at rest.

    Walks the config directory looking for files that contain values
    whose key names suggest they are secrets but are stored in plaintext
    rather than SOPS-encrypted.

    Exits with code 0 if clean, code 1 if findings exist (useful for
    CI and git hooks).

    Example:

    \b
        dotconfig audit
        dotconfig audit -c /path/to/config
    """
    import sys
    from .discover import find_config_dir

    if config_dir:
        cfg = Path(config_dir)
    else:
        cfg = find_config_dir()
        if cfg is None:
            cfg = Path("config")

    clean = run_audit(cfg)
    if not clean:
        sys.exit(1)


@cli.command()
def config() -> None:
    """Show dotconfig configuration and discovered paths.

    Reports the installed version, the config directory name (from
    DOTCONFIG_NAME or the default "config"), and where the config
    directory was found by walking up the directory tree.

    Example:

    \b
        dotconfig config
        DOTCONFIG_NAME=.config dotconfig config
    """
    show_config()


@cli.command("install-hooks")
def install_hooks() -> None:
    """Install a git pre-commit hook that runs dotconfig audit.

    The hook blocks commits when unencrypted secrets are detected in
    the config/ directory.  Safe to run multiple times — it will not
    duplicate the hook if already installed.

    Example:

    \b
        dotconfig install-hooks
    """
    import sys
    if not install_pre_commit_hook():
        sys.exit(1)


@cli.command()
def agent() -> None:
    """Print full operational instructions for AI agents.

    Outputs a comprehensive markdown document describing how dotconfig
    works, all available commands, the directory layout, the .env format,
    and rules that agents should follow when operating on configuration.

    Example:

    \b
        dotconfig agent
    """
    show_agent_instructions()
