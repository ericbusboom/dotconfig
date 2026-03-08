"""
CLI entry point for dotconfig.

Commands
--------
dotconfig load <common_name> [local_name]
    Assemble config/ source files into a single .env file.

dotconfig save
    Write .env sections back to their config/ source files.
"""

import click
from pathlib import Path

from .load import load_config
from .save import save_config


@click.group()
@click.version_option()
def cli() -> None:
    """dotconfig — environment configuration cascade manager.

    Manages layered .env configuration assembled from multiple source
    files (common config, SOPS-encrypted secrets, and developer-local
    overrides) stored under a config/ directory.
    """


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
def save(env_file: str, config_dir: str) -> None:
    """Save .env sections back to config/ source files.

    Reads CONFIG_COMMON and CONFIG_LOCAL from the .env metadata, then
    writes each section back to its corresponding source file, re-encrypting
    secrets with SOPS.

    Example:

    \b
        dotconfig save
        dotconfig save --env-file .env.staging --config-dir config
    """
    save_config(
        env_file=Path(env_file),
        config_dir=Path(config_dir),
    )
