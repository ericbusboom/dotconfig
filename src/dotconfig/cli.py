"""
CLI entry point for dotconfig.

Commands
--------
dotconfig init
    Create the config/ directory structure and set up age encryption keys.

dotconfig load <common_name> [local_name]
    Assemble config/ source files into a single .env file.

dotconfig save
    Write .env sections back to their config/ source files.

dotconfig keys
    Show age encryption key status and configuration.

dotconfig agent
    Print full operational instructions for AI agents.
"""

import click
from pathlib import Path

from .agent import show_agent_instructions
from .init import init_config
from .keys import show_keys
from .load import load_config
from .save import save_config


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
@click.argument("common_name")
@click.argument("local_name", required=False, default=None)
@click.option(
    "--config-dir",
    default="config",
    show_default=True,
    help="Root config directory.",
)
@click.option(
    "--output",
    default=".env",
    show_default=True,
    help="Destination .env file.",
)
def load(
    common_name: str,
    local_name: str,
    config_dir: str,
    output: str,
) -> None:
    """Assemble config files into .env.

    COMMON_NAME selects the environment (e.g. dev, prod, test).
    LOCAL_NAME optionally adds a developer-specific override layer.

    Example:

    \b
        dotconfig load dev yourname      # dev + your local overrides
        dotconfig load prod              # prod only, no local overrides
    """
    load_config(
        common_name=common_name,
        local_name=local_name,
        config_dir=Path(config_dir),
        output=Path(output),
    )


@cli.command()
@click.argument("common_name", required=False, default=None)
@click.argument("local_name", required=False, default=None)
@click.option(
    "--env-file",
    default=".env",
    show_default=True,
    help=".env file to read and save.",
)
@click.option(
    "--config-dir",
    default="config",
    show_default=True,
    help="Root config directory.",
)
def save(common_name: str, local_name: str, env_file: str, config_dir: str) -> None:
    """Save .env sections back to config/ source files.

    Reads CONFIG_COMMON and CONFIG_LOCAL from the .env metadata, then
    writes each section back to its corresponding source file, re-encrypting
    secrets with SOPS.

    Optionally provide COMMON_NAME and LOCAL_NAME to save to a different
    environment or user than what was originally loaded.  For example,
    after loading ``prod eric`` you can run ``dotconfig save dev stan`` to
    write the same content to the dev/stan config files instead.

    Example:

    \b
        dotconfig save
        dotconfig save dev stan
        dotconfig save prod
        dotconfig save --env-file .env.staging --config-dir config
    """
    save_config(
        env_file=Path(env_file),
        config_dir=Path(config_dir),
        override_common=common_name,
        override_local=local_name,
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
