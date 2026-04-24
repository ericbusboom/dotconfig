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
from typing import List, Optional, Tuple

from .agent import show_agent_instructions
from .audit import run_audit
from .config import show_config
from .gh_push import gh_push as _gh_push
from .hooks import install_pre_commit_hook
from .init import init_config
from .key import gen_key, get_key, list_keys, pub_key, rm_key, save_key, send_key
from .load import load_config, load_file
from .save import save_config, save_file


def _classify_load_args(
    names: Tuple[str, ...], config_dir: Path
) -> Tuple[List[str], List[str]]:
    """Classify positional names against the config directory layout.

    A name is a *deployment* if ``config/<name>/`` exists, a *local* if
    ``config/local/<name>/`` exists. Within each type, the order of names
    on the command line is preserved (it determines the layer order
    last-write-wins).

    Raises ``click.UsageError`` for:
      - a name that doesn't exist as either a deployment or a local
      - a name that exists as both (ambiguous)
      - a duplicate name within the same invocation
    """
    deployments: List[str] = []
    locals_: List[str] = []
    seen: set = set()
    for name in names:
        if name in seen:
            raise click.UsageError(f"duplicate name in positional args: '{name}'")
        seen.add(name)
        deploy_dir = config_dir / name
        local_dir = config_dir / "local" / name
        deploy_exists = deploy_dir.is_dir()
        local_exists = local_dir.is_dir()
        if deploy_exists and local_exists:
            raise click.UsageError(
                f"name '{name}' is ambiguous: matches both a deployment "
                f"({deploy_dir}) and a local ({local_dir}). "
                f"Use -d/--deploy or -l/--local to disambiguate."
            )
        if deploy_exists:
            deployments.append(name)
        elif local_exists:
            locals_.append(name)
        else:
            raise click.UsageError(
                f"unknown deployment or local: '{name}' "
                f"(no {deploy_dir} or {local_dir} exists)"
            )
    return deployments, locals_


def _classify_save_args(
    names: Tuple[str, ...],
) -> Tuple[Optional[str], Optional[str]]:
    """Lenient positional classifier for ``dotconfig save``.

    Save accepts up to two names: the first is the destination
    deployment, the optional second is the destination local. Names need
    not exist yet (save typically materializes a new directory).

    Returns ``(deploy_name_or_None, local_name_or_None)``.

    Raises ``click.UsageError`` for >2 names or duplicates.
    """
    if len(names) > 2:
        raise click.UsageError(
            "save accepts at most two positional names: <deploy> [<local>]"
        )
    if len(names) == 2 and names[0] == names[1]:
        raise click.UsageError(f"duplicate name in positional args: '{names[0]}'")
    deploy = names[0] if len(names) >= 1 else None
    local = names[1] if len(names) >= 2 else None
    return deploy, local


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
@click.argument("names", nargs=-1)
@click.option(
    "-d", "--deploy",
    required=False,
    default=None,
    is_flag=False,
    flag_value=".",
    help="Deployment / environment name (e.g. dev, prod, staging). "
         "Legacy single-value alias for the positional form.",
)
@click.option(
    "-l", "--local",
    required=False,
    default=None,
    is_flag=False,
    flag_value=".",
    help="Local / developer name for personal overrides. "
         "Legacy single-value alias for the positional form.",
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
@click.option(
    "--split",
    is_flag=True,
    default=False,
    help="Write public and secret values to separate files (.env + .env.secret).",
)
@click.option(
    "--embed", "-e",
    "embed_files",
    multiple=True,
    metavar="VAR=FILENAME",
    help="Embed a deployment file as base64 in a 'files' section of the .env. "
         "Format: VAR=filename. Repeatable.",
)
def load(
    names: Tuple[str, ...],
    deploy: str,
    local: str,
    config_dir: str,
    output: str,
    filename: str,
    to_stdout: bool,
    use_json: bool,
    use_yaml: bool,
    flat: bool,
    split: bool,
    embed_files: Tuple[str, ...],
) -> None:
    """Assemble config files into .env, or load a specific file.

    \b
    Pass deployment and local-override names as positional arguments;
    each name is classified by which directory exists under config/.
    Multiple names of the same type stack last-write-wins (within type;
    order across types is irrelevant).
    The legacy -d/--deploy and -l/--local flags remain as single-value
    aliases for back-compat. Mixing positional names with the flags
    raises a usage error.

    Use --file to retrieve a single file from the config directory
    instead of assembling a full .env (specify -d or -l, not both).
    Use -S/--stdout to print to stdout instead of writing to disk
    (useful for piping or agents).

    Use --json or --yaml to output as a structured file with deployment
    sections and public/secrets sub-keys.  Use -F/--flat to merge all
    layers into a single flat dict (last-write-wins). Multi-layer
    stacks are not supported with --json/--yaml in this release.

    Use --split to write public values to the main file and secret
    values to a companion .secret file (e.g. .env + .env.secret).

    Example:

    \b
        dotconfig load dev yourname        # positional shorthand
        dotconfig load dev prod alice bob  # stacked deploys + locals
        dotconfig load -d dev -l yourname  # legacy flag form
        dotconfig load -d prod
        dotconfig load -d dev --json
        dotconfig load -d dev -l alice --yaml --flat
        dotconfig load -d dev --json -S
        dotconfig load -d dev --file app.yaml --stdout
        dotconfig load -l alice --file settings.json -o out.json
        dotconfig load -d prod --split
    """
    if use_json and use_yaml:
        raise click.UsageError("--json and --yaml are mutually exclusive")
    if flat and not (use_json or use_yaml):
        raise click.UsageError("--flat requires --json or --yaml")
    if split and to_stdout:
        raise click.UsageError("--split cannot be used with --stdout")
    if split and filename:
        raise click.UsageError("--split cannot be used with --file")
    if embed_files and (use_json or use_yaml):
        raise click.UsageError("--embed cannot be used with --json or --yaml")
    if embed_files and filename:
        raise click.UsageError("--embed cannot be used with --file")

    cfg = Path(config_dir)

    # ---- Resolve positional names vs legacy -d/-l flags ----
    if names and (deploy or local):
        raise click.UsageError(
            "cannot mix positional names with -d/--deploy or -l/--local; "
            "use one form or the other"
        )

    if names:
        if filename:
            # --file takes a single deployment OR a single local;
            # the lenient classifier preserves that one-or-the-other shape.
            file_deploy, file_local = _classify_save_args(names)
            # Verify that the names actually exist for load_file
            if file_deploy and not (cfg / file_deploy).is_dir():
                # Maybe it's actually a local
                if (cfg / "local" / file_deploy).is_dir():
                    file_deploy, file_local = None, file_deploy
            deploys: List[str] = [file_deploy] if file_deploy else []
            locals_: List[str] = [file_local] if file_local else []
        else:
            deploys, locals_ = _classify_load_args(names, cfg)
    else:
        deploys = [deploy] if deploy else []
        locals_ = [local] if local else []

    if (use_json or use_yaml) and (len(deploys) > 1 or len(locals_) > 1):
        raise click.UsageError(
            "--json/--yaml only support a single deployment and a single local "
            "in this release (multi-layer stacks coming in a future sprint)"
        )

    fmt = "json" if use_json else ("yaml" if use_yaml else "env")

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
            deployment=deploys[0] if deploys else None,
            local=locals_[0] if locals_ else None,
            filename=file_path.name,
            config_dir=cfg,
            output=out,
            to_stdout=to_stdout,
        )
    else:
        if not deploys:
            raise click.UsageError(
                "at least one deployment is required when assembling .env "
                "(pass it as a positional name or via -d/--deploy)"
            )
        load_config(
            deployment=deploys,
            local=locals_,
            config_dir=cfg,
            output=out,
            to_stdout=to_stdout,
            fmt=fmt,
            flat=flat,
            split=split,
            embed_files=embed_files,
        )


@cli.command()
@click.argument("names", nargs=-1)
@click.option(
    "-d", "--deploy",
    required=False,
    default=None,
    is_flag=False,
    flag_value=".",
    help="Target deployment name (overrides the .env metadata). "
         "Legacy single-value alias for the positional form.",
)
@click.option(
    "-l", "--local",
    required=False,
    default=None,
    is_flag=False,
    flag_value=".",
    help="Target local / developer name (overrides the .env metadata). "
         "Legacy single-value alias for the positional form.",
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
    names: Tuple[str, ...],
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
    Without --file: reads layer metadata from the .env header, then
    writes each section back to its corresponding source file,
    re-encrypting secrets with SOPS.

    Pass up to two positional names to redirect the output:
      dotconfig save <deploy>          # flatten to config/<deploy>/
      dotconfig save <deploy> <local>  # flatten to deploy + local
    Multi-layer .env files are merged last-wins into the destination.
    The legacy -d/--deploy and -l/--local flags remain as single-value
    aliases. Mixing positional names with the flags raises a usage error.

    Use --json or --yaml to read from a structured file (.env.json or
    .env.yaml) instead of .env.  Use -F/--flat when the input is a flat
    dict with no sections — only existing keys can be updated in flat
    mode (new keys are rejected because there is no section info).

    With --file: copies the named file into the deployment or local
    config directory.  Add -e/--encrypt to encrypt the file with SOPS.
    Encrypted files are automatically decrypted on load.

    Example:

    \b
        dotconfig save                     # round-trip to loaded layers
        dotconfig save dev                 # flatten to config/dev/
        dotconfig save dev stan            # flatten to dev + stan
        dotconfig save -d dev -l stan      # legacy flag form
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

    # ---- Resolve positional names vs legacy -d/-l flags ----
    if names and (deploy or local):
        raise click.UsageError(
            "cannot mix positional names with -d/--deploy or -l/--local; "
            "use one form or the other"
        )

    if names:
        pos_deploy, pos_local = _classify_save_args(names)
        deploy = pos_deploy
        local = pos_local

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
