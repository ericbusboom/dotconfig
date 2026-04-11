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

dotconfig key <subcommand>
    Manage SSH keys (gen, save, get, pub, list, rm, send).

dotconfig gh-push -d <deployment>
    Push deployment secrets to GitHub Actions / Codespaces.

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
from .gh_push import gh_push as _gh_push
from .hooks import install_pre_commit_hook
from .init import init_config
from .key import gen_key, get_key, list_keys, pub_key, rm_key, save_key, send_key
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
@click.option(
    "-q", "--quiet",
    is_flag=True,
    default=False,
    help="Suppress output and auto-answer prompts (for CI/Codespaces).",
)
def init(config_dir: str, quiet: bool) -> None:
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
        dotconfig init -q
    """
    init_config(config_dir=Path(config_dir), quiet=quiet)


@cli.command()
@click.option(
    "-d", "--deploy",
    required=False,
    default=None,
    is_flag=False,
    flag_value=".",
    help="Deployment / environment name (e.g. dev, prod, staging).",
)
@click.option(
    "-l", "--local",
    required=False,
    default=None,
    is_flag=False,
    flag_value=".",
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
    is_flag=False,
    flag_value=".",
    help="Destination file.  Without a value, writes to CWD.  [default: config/files/]",
)
@click.option(
    "--file", "-f",
    "filename",
    default=None,
    is_flag=False,
    flag_value=".",
    help="Load a specific file (e.g. foobar.yaml) instead of assembling .env.",
)
@click.option(
    "-S", "--stdout", "to_stdout",
    is_flag=True,
    default=False,
    help="Print to stdout instead of writing to a file.",
)
@click.option(
    "--json", "use_json",
    is_flag=True,
    default=False,
    help="Output as JSON (.env.json).",
)
@click.option(
    "--yaml", "use_yaml",
    is_flag=True,
    default=False,
    help="Output as YAML (.env.yaml).",
)
@click.option(
    "-F", "--flat",
    is_flag=True,
    default=False,
    help="Flatten all sections into a single dict (requires --json or --yaml).",
)
def load(
    deploy: str,
    local: str,
    config_dir: str,
    output: str,
    filename: str,
    to_stdout: bool,
    use_json: bool,
    use_yaml: bool,
    flat: bool,
) -> None:
    """Assemble config files into .env, or load a specific file.

    \b
    Requires -d/--deploy to select the deployment (e.g. dev, prod).
    Optionally add -l/--local for developer-specific overrides.

    Use --file to retrieve a single file from the config directory
    instead of assembling a full .env (specify -d or -l, not both).
    Use -S/--stdout to print to stdout instead of writing to disk
    (useful for piping or agents).

    Use --json or --yaml to output as a structured file with deployment
    sections and public/secrets sub-keys.  Use -F/--flat to merge all
    layers into a single flat dict (last-write-wins).

    Example:

    \b
        dotconfig load -d dev -l yourname
        dotconfig load -d prod
        dotconfig load -d dev --json
        dotconfig load -d dev -l alice --yaml --flat
        dotconfig load -d dev --json -S
        dotconfig load -d dev --file app.yaml --stdout
        dotconfig load -l alice --file settings.json -o out.json
    """
    if use_json and use_yaml:
        raise click.UsageError("--json and --yaml are mutually exclusive")
    if flat and not (use_json or use_yaml):
        raise click.UsageError("--flat requires --json or --yaml")

    fmt = "json" if use_json else ("yaml" if use_yaml else "env")

    cfg = Path(config_dir)

    # Resolve -o flag: None = config/files/ (default), "." = CWD, else explicit path
    if output == ".":
        # -o without value: use CWD with source filename
        if filename:
            out = Path(Path(filename).name)
        else:
            fmt_ext = {"env": ".env", "json": ".env.json", "yaml": ".env.yaml"}
            out = Path(fmt_ext.get(fmt, ".env"))
    elif output:
        out = Path(output)
    else:
        out = None

    if filename:
        if fmt != "env":
            raise click.UsageError("--json/--yaml cannot be used with --file")
        file_path = Path(filename).expanduser()
        load_file(
            deployment=deploy,
            local=local,
            filename=file_path.name,
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
            fmt=fmt,
            flat=flat,
        )


@cli.command()
@click.option(
    "-d", "--deploy",
    required=False,
    default=None,
    is_flag=False,
    flag_value=".",
    help="Target deployment name (overrides the .env metadata).",
)
@click.option(
    "-l", "--local",
    required=False,
    default=None,
    is_flag=False,
    flag_value=".",
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
    is_flag=False,
    flag_value=".",
    help="Save a specific file (e.g. foobar.yaml) into the config directory.",
)
@click.option(
    "-e", "--encrypt",
    is_flag=True,
    default=False,
    help="Encrypt the file with SOPS (only with --file).",
)
@click.option(
    "--json", "use_json",
    is_flag=True,
    default=False,
    help="Read from .env.json instead of .env.",
)
@click.option(
    "--yaml", "use_yaml",
    is_flag=True,
    default=False,
    help="Read from .env.yaml instead of .env.",
)
@click.option(
    "-F", "--flat",
    is_flag=True,
    default=False,
    help="Input is a flat dict (requires --json or --yaml; can only update existing keys).",
)
def save(
    deploy: str,
    local: str,
    env_file: str,
    config_dir: str,
    filename: str,
    encrypt: bool,
    use_json: bool,
    use_yaml: bool,
    flat: bool,
) -> None:
    """Save .env sections back to config/ source files, or store a file.

    \b
    Without --file: reads CONFIG_DEPLOY and CONFIG_LOCAL from the .env
    metadata, then writes each section back to its corresponding source
    file, re-encrypting secrets with SOPS.  Optionally provide
    -d/--deploy and -l/--local to redirect the output to a different
    deployment or user.

    Use --json or --yaml to read from a structured file (.env.json or
    .env.yaml) instead of .env.  Use -F/--flat when the input is a flat
    dict with no sections — only existing keys can be updated in flat
    mode (new keys are rejected because there is no section info).

    With --file: copies the named file into the deployment or local
    config directory.  Add -e/--encrypt to encrypt the file with SOPS.
    Encrypted files are automatically decrypted on load.

    Example:

    \b
        dotconfig save
        dotconfig save -d dev -l stan
        dotconfig save --json
        dotconfig save --yaml -d dev -l alice --flat
        dotconfig save --file app.yaml -d dev
        dotconfig save --file secrets.yaml -d dev --encrypt
        dotconfig save --file settings.json -l alice
    """
    if use_json and use_yaml:
        raise click.UsageError("--json and --yaml are mutually exclusive")
    if flat and not (use_json or use_yaml):
        raise click.UsageError("--flat requires --json or --yaml")

    cfg = Path(config_dir)

    if encrypt and not filename:
        raise click.UsageError("--encrypt can only be used with --file")

    # Determine the format and default input file
    fmt = "env"
    if use_json:
        fmt = "json"
        if env_file == ".env":
            env_file = ".env.json"
    elif use_yaml:
        fmt = "yaml"
        if env_file == ".env":
            env_file = ".env.yaml"

    if filename:
        if fmt != "env":
            raise click.UsageError("--json/--yaml cannot be used with --file")
        file_path = Path(filename).expanduser()
        save_file(
            deployment=deploy,
            local=local,
            filename=file_path.name,
            config_dir=cfg,
            source=file_path,
            encrypt=encrypt,
        )
    else:
        save_config(
            env_file=Path(env_file),
            config_dir=cfg,
            override_deploy=deploy,
            override_local=local,
            fmt=fmt,
            flat=flat,
        )


@cli.group()
def key() -> None:
    """Manage SSH keys stored in config/keys/.

    Keys are SOPS-encrypted at rest. Use subcommands to generate,
    import, retrieve, list, remove, or send keys to remote hosts.

    \b
        dotconfig key gen deploy --type ed25519
        dotconfig key list
        dotconfig key send myhost
    """


@key.command("gen")
@click.argument("name")
@click.option("--type", "key_type", default="ed25519", show_default=True,
              type=click.Choice(["ed25519", "rsa", "ecdsa"]),
              help="Key type to generate.")
@click.option("--bits", default=None, type=int,
              help="Key size in bits (RSA only).")
@click.option("-c", "--config-dir", default=None, help="Root config directory.")
def key_gen(name: str, key_type: str, bits: int, config_dir: str) -> None:
    """Generate an SSH keypair.

    \b
        dotconfig key gen deploy
        dotconfig key gen deploy --type rsa --bits 4096
    """
    cfg = Path(config_dir) if config_dir else None
    gen_key(name, key_type=key_type, bits=bits, config_dir=cfg)


@key.command("save")
@click.argument("file", type=click.Path(exists=True))
@click.option("--name", default=None, help="Override the stored key name.")
@click.option("-c", "--config-dir", default=None, help="Root config directory.")
def key_save(file: str, name: str, config_dir: str) -> None:
    """Import an existing key file.

    Encrypts the private key with SOPS and stores it in config/keys/.
    Auto-grabs the .pub companion if it exists.

    \b
        dotconfig key save ~/.ssh/id_ed25519
        dotconfig key save deploy.pem --name deploy
    """
    cfg = Path(config_dir) if config_dir else None
    save_key(Path(file), name=name, config_dir=cfg)


@key.command("get")
@click.argument("name")
@click.option("-c", "--config-dir", default=None, help="Root config directory.")
def key_get(name: str, config_dir: str) -> None:
    """Decrypt and print a private key to stdout.

    \b
        dotconfig key get deploy
    """
    cfg = Path(config_dir) if config_dir else None
    get_key(name, config_dir=cfg)


@key.command("pub")
@click.argument("name")
@click.option("-c", "--config-dir", default=None, help="Root config directory.")
def key_pub(name: str, config_dir: str) -> None:
    """Print the public key for a named key.

    Uses the .pub file if it exists, otherwise derives from the
    private key via ssh-keygen.

    \b
        dotconfig key pub deploy
    """
    cfg = Path(config_dir) if config_dir else None
    pub_key(name, config_dir=cfg)


@key.command("list")
@click.option("-c", "--config-dir", default=None, help="Root config directory.")
def key_list(config_dir: str) -> None:
    """List all keys in config/keys/.

    \b
        dotconfig key list
    """
    cfg = Path(config_dir) if config_dir else None
    list_keys(config_dir=cfg)


@key.command("rm")
@click.argument("name")
@click.option("-c", "--config-dir", default=None, help="Root config directory.")
def key_rm(name: str, config_dir: str) -> None:
    """Remove a key and its .pub companion.

    \b
        dotconfig key rm deploy
    """
    cfg = Path(config_dir) if config_dir else None
    rm_key(name, config_dir=cfg)


@key.command("send")
@click.argument("host")
@click.option("--key", "key_name", default=None,
              help="Key name to send (defaults to host name).")
@click.option("-c", "--config-dir", default=None, help="Root config directory.")
def key_send(host: str, key_name: str, config_dir: str) -> None:
    """Send a public key to a remote host via ssh-copy-id.

    By default the key name matches the host argument.

    \b
        dotconfig key send myhost
        dotconfig key send myhost --key deploy_ed25519
    """
    cfg = Path(config_dir) if config_dir else None
    send_key(host, key_name=key_name, config_dir=cfg)


@cli.command("gh-push")
@click.option("-d", "--deploy", required=True,
              help="Deployment name to sync secrets from.")
@click.option("-c", "--config-dir", default="config", show_default=True,
              help="Root config directory.")
@click.option("--repo", default=None,
              help="GitHub repo (owner/repo). Auto-detected from git remote.")
@click.option("--actions", is_flag=True, default=False,
              help="Push to Actions only (default: both Actions + Codespaces).")
@click.option("--codespaces", is_flag=True, default=False,
              help="Push to Codespaces only (default: both Actions + Codespaces).")
@click.option("--include-age-key", is_flag=True, default=False,
              help="Include the SOPS age decryption key.")
@click.option("--environment", default=None,
              help="Push to a GitHub environment instead of repo-level.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would be pushed without pushing.")
@click.option("--keys", "keys_csv", default=None,
              help="Comma-separated list of specific keys to push.")
def gh_push_cmd(
    deploy: str,
    config_dir: str,
    repo: str,
    actions: bool,
    codespaces: bool,
    include_age_key: bool,
    environment: str,
    dry_run: bool,
    keys_csv: str,
) -> None:
    """Push deployment secrets to GitHub Actions / Codespaces.

    Loads all secrets for the named deployment and pushes each one
    as a GitHub repository secret via the gh CLI.

    \b
        dotconfig gh-push -d prod
        dotconfig gh-push -d prod --dry-run
        dotconfig gh-push -d prod --actions
        dotconfig gh-push -d prod --environment prod
        dotconfig gh-push -d prod --include-age-key
    """
    keys_filter = [k.strip() for k in keys_csv.split(",")] if keys_csv else None
    _gh_push(
        deployment=deploy,
        config_dir=Path(config_dir),
        repo=repo,
        actions=actions,
        codespaces=codespaces,
        include_age_key=include_age_key,
        environment=environment,
        dry_run=dry_run,
        keys_filter=keys_filter,
    )


@cli.command()
@click.option(
    "-c", "--config-dir",
    default=None,
    is_flag=False,
    flag_value=".",
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
