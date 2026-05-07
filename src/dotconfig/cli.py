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

dotconfig --instructions
    Print full operational instructions for AI agents and humans
    (includes the live --help text of every subcommand).
"""

import click
from pathlib import Path
from typing import List, Optional, Tuple

from .agent import show_agent_instructions
from .audit import run_audit
from .reencrypt import reencrypt_all
from .config import show_config
from .gh_push import gh_push as _gh_push
from .hooks import install_pre_commit_hook
from .init import init_config
from .key import (
    gen_key,
    get_key,
    install_key,
    list_keys,
    load_key,
    pub_key,
    rm_key,
    save_key,
    send_key,
    uninstall_key,
)
from .load import load_config, load_file
from .save import save_config, save_file
from .versioning import read_dotconfig_version, bump_version, seed_version_from_sources, write_dotconfig_version


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


def _print_instructions(ctx: click.Context, param, value: bool) -> None:
    """Eager callback for --instructions: print full instructions and exit."""
    if not value or ctx.resilient_parsing:
        return
    # Pass the live cli group in so the help reference is auto-generated
    # from the current command surface.
    show_agent_instructions(ctx.command if isinstance(ctx.command, click.Group) else cli)
    ctx.exit()


def _resolve_config_dir(ctx: click.Context) -> Optional[Path]:
    """Resolve config dir from the top-level ``-c/--config`` / ``DOTCONFIG_DIR``.

    Returns ``None`` when no config root was given; callers fall back to
    :func:`find_config_dir` discovery or a fixed default.
    """
    root = (ctx.obj or {}).get("config_root") if ctx.obj else None
    if root:
        return Path(root).expanduser()
    return None


@click.group()
@click.version_option()
@click.option(
    "-c", "--config",
    "config_root",
    envvar="DOTCONFIG_DIR",
    default=None,
    metavar="PATH",
    help="Root config directory (env: DOTCONFIG_DIR).",
)
@click.option(
    "--instructions",
    is_flag=True,
    callback=_print_instructions,
    expose_value=False,
    is_eager=True,
    help="Print complete agent / usage instructions (with all subcommand help) and exit.",
)
@click.pass_context
def cli(ctx: click.Context, config_root: Optional[str]) -> None:
    """dotconfig — environment configuration cascade manager.

    Manages layered .env configuration assembled from multiple source
    files (common config, SOPS-encrypted secrets, and developer-local
    overrides) stored under a config/ directory.

    \b
    AI agents and humans wanting the full manual: run
        dotconfig --instructions
    """
    ctx.ensure_object(dict)
    ctx.obj["config_root"] = config_root


@cli.command()
@click.option(
    "--config-dir",
    default=None,
    help="Root config directory to create.  [default: config]",
)
@click.option(
    "-q", "--quiet",
    is_flag=True,
    default=False,
    help="Suppress output and auto-answer prompts (for CI/Codespaces).",
)
@click.pass_context
def init(ctx: click.Context, config_dir: str, quiet: bool) -> None:
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
    cfg = (
        Path(config_dir).expanduser() if config_dir
        else _resolve_config_dir(ctx) or Path("config")
    )
    init_config(config_dir=cfg, quiet=quiet)


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
    is_flag=False,
    flag_value="*",
    metavar="VAR_FILE",
    help="Embed a config file as base64 in a 'files' section of the .env. "
         "Pass a *_FILE variable name to expand only that one (e.g. "
         "-e CERT_FILE); the file referenced by its value is read from the "
         "config tree and emitted as CERT=<base64>. Pass -e with no value "
         "to expand every *_FILE variable in the loaded config. Repeatable.",
)
@click.option(
    "--no-export",
    is_flag=True,
    default=False,
    help="Strip the leading 'export ' prefix from assignment lines in the .env "
         "output. Implied by -S/--stdout (since piped consumers usually don't "
         "want shell-style exports). Use when the consumer (e.g. docker stack "
         "deploy) requires plain KEY=value lines rather than shell-sourceable "
         "exports.",
)
@click.option(
    "--add-export",
    is_flag=True,
    default=False,
    help="Ensure every assignment line in the .env output has an 'export ' "
         "prefix. Use to override the implicit --no-export behavior of "
         "-S/--stdout, or to normalize source files that mix prefixed and "
         "plain assignments.",
)
@click.pass_context
def load(
    ctx: click.Context,
    names: Tuple[str, ...],
    deploy: str,
    local: str,
    output: str,
    filename: str,
    to_stdout: bool,
    use_json: bool,
    use_yaml: bool,
    flat: bool,
    split: bool,
    embed_files: Tuple[str, ...],
    no_export: bool,
    add_export: bool,
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
        dotconfig load -d prod -e CERT_FILE        # one *_FILE var
        dotconfig load -d prod -e                  # all *_FILE vars
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

    import re as _re
    _var_re = _re.compile(r"^[A-Z_][A-Z0-9_]*_FILE$")
    for v in embed_files:
        if v == "*":
            continue
        if "=" in v:
            raise click.UsageError(
                "--embed no longer accepts VAR=FILENAME; declare a "
                "<VAR>_FILE variable in your config and pass -e <VAR>_FILE "
                "(or -e alone to expand every *_FILE variable)"
            )
        if not _var_re.match(v):
            raise click.UsageError(
                f"--embed argument must be an UPPERCASE *_FILE variable name, "
                f"got: {v!r}"
            )
    if no_export and filename:
        raise click.UsageError("--no-export cannot be used with --file")
    # --no-export with --json/--yaml is a silent no-op: structured output
    # doesn't carry the `export ` prefix, so there's nothing to strip.
    if no_export and add_export:
        raise click.UsageError("--no-export and --add-export are mutually exclusive")
    if add_export and filename:
        raise click.UsageError("--add-export cannot be used with --file")
    # --add-export with --json/--yaml is a silent no-op (same reason as
    # --no-export): structured output doesn't carry the `export ` prefix.

    # -S/--stdout implies --no-export unless --add-export is explicitly set.
    # Piped consumers (jq, docker stack deploy, ...) usually reject the
    # shell-style `export ` prefix; the explicit override stays available.
    if to_stdout and not add_export and not no_export:
        no_export = True

    cfg = _resolve_config_dir(ctx) or Path("config")

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
            no_export=no_export,
            add_export=add_export,
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
    "--file", "-f",
    "filename",
    default=None,
    is_flag=False,
    flag_value=".",
    help="Save a specific file (e.g. foobar.yaml) into the config directory.",
)
@click.option(
    "-n", "--name",
    "dest_name",
    default=None,
    help="Destination filename inside the config tree. Defaults to the "
         "basename of --file. Use this when the source path's basename "
         "isn't what you want stored (e.g. saving "
         "/tmp/scratch.credentials as route53-ro.credentials).",
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
@click.option(
    "--add-export",
    is_flag=True,
    default=False,
    help="Prepend 'export ' to assignment lines when writing back to source "
         ".env files. Pairs with load's --no-export for round-trip style "
         "preservation.",
)
@click.pass_context
def save(
    ctx: click.Context,
    names: Tuple[str, ...],
    deploy: str,
    local: str,
    env_file: str,
    filename: str,
    dest_name: Optional[str],
    encrypt: bool,
    use_json: bool,
    use_yaml: bool,
    flat: bool,
    add_export: bool,
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
        dotconfig save --file /tmp/scratch.credentials -n route53-ro.credentials -d aws
    """
    if use_json and use_yaml:
        raise click.UsageError("--json and --yaml are mutually exclusive")
    if flat and not (use_json or use_yaml):
        raise click.UsageError("--flat requires --json or --yaml")

    cfg = _resolve_config_dir(ctx) or Path("config")

    if encrypt and not filename:
        raise click.UsageError("--encrypt can only be used with --file")
    if dest_name and not filename:
        raise click.UsageError("-n/--name can only be used with --file")
    if add_export and filename:
        raise click.UsageError("--add-export cannot be used with --file")
    if add_export and (use_json or use_yaml):
        raise click.UsageError("--add-export cannot be used with --json or --yaml")

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
        # -n/--name overrides the source basename for the destination.
        # When provided as a path, only the basename is used — the
        # destination directory is always config/<deploy>/ (or local/).
        stored_name = Path(dest_name).name if dest_name else file_path.name
        save_file(
            deployment=deploy,
            local=local,
            filename=stored_name,
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
            add_export=add_export,
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
@click.pass_context
def key_gen(ctx: click.Context, name: str, key_type: str, bits: int) -> None:
    """Generate an SSH keypair.

    \b
        dotconfig key gen deploy
        dotconfig key gen deploy --type rsa --bits 4096
    """
    cfg = _resolve_config_dir(ctx)
    gen_key(name, key_type=key_type, bits=bits, config_dir=cfg)


@key.command("save")
@click.argument("file", type=click.Path(exists=True))
@click.option("--name", default=None, help="Override the stored key name.")
@click.pass_context
def key_save(ctx: click.Context, file: str, name: str) -> None:
    """Import an existing key file.

    Encrypts the private key with SOPS and stores it in config/keys/.
    Auto-grabs the .pub companion if it exists.

    \b
        dotconfig key save ~/.ssh/id_ed25519
        dotconfig key save deploy.pem --name deploy
    """
    cfg = _resolve_config_dir(ctx)
    save_key(Path(file), name=name, config_dir=cfg)


@key.command("get")
@click.argument("name")
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Write the decrypted key to this path (mode 0600). Overrides the default config/files/<name>.",
)
@click.option(
    "-S",
    "--stdout",
    "to_stdout",
    is_flag=True,
    default=False,
    help="Print the decrypted key to stdout instead of writing a file.",
)
@click.pass_context
def key_get(
    ctx: click.Context,
    name: str,
    output: Optional[Path],
    to_stdout: bool,
) -> None:
    """Decrypt a private key.

    By default, writes the decrypted keypair into config/files/<name>
    (mode 0600 for the private key, 0644 for the .pub if present).

    \b
        dotconfig key get deploy                  # → config/files/deploy
        dotconfig key get deploy -o ~/.ssh/deploy # → custom path
        dotconfig key get deploy -S               # → stdout
    """
    if output is not None and to_stdout:
        raise click.UsageError("--output and --stdout are mutually exclusive")
    cfg = _resolve_config_dir(ctx)
    get_key(name, config_dir=cfg, output=output, to_stdout=to_stdout)


@key.command("load")
@click.argument("name")
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Write the decrypted key to this path (mode 0600). Overrides the default config/files/<name>.",
)
@click.pass_context
def key_load(
    ctx: click.Context,
    name: str,
    output: Optional[Path],
) -> None:
    """Decrypt a keypair into config/files/<name>.

    Writes the decrypted private key (mode 0600) and its .pub companion
    (mode 0644, if present) into config/files/, ready for tools that need
    them on disk in plaintext.

    \b
        dotconfig key load deploy
        dotconfig key load deploy -o ~/.ssh/deploy
    """
    cfg = _resolve_config_dir(ctx)
    load_key(name, config_dir=cfg, output=output)


@key.command("pub")
@click.argument("name")
@click.pass_context
def key_pub(ctx: click.Context, name: str) -> None:
    """Print the public key for a named key.

    Uses the .pub file if it exists, otherwise derives from the
    private key via ssh-keygen.

    \b
        dotconfig key pub deploy
    """
    cfg = _resolve_config_dir(ctx)
    pub_key(name, config_dir=cfg)


@key.command("list")
@click.pass_context
def key_list(ctx: click.Context) -> None:
    """List all keys in config/keys/.

    \b
        dotconfig key list
    """
    cfg = _resolve_config_dir(ctx)
    list_keys(config_dir=cfg)


@key.command("rm")
@click.argument("name")
@click.pass_context
def key_rm(ctx: click.Context, name: str) -> None:
    """Remove a key and its .pub companion.

    \b
        dotconfig key rm deploy
    """
    cfg = _resolve_config_dir(ctx)
    rm_key(name, config_dir=cfg)


@key.command("send")
@click.argument("name")
@click.argument("host")
@click.pass_context
def key_send(ctx: click.Context, name: str, host: str) -> None:
    """Send a public key to a remote host via ssh-copy-id.

    NAME is the key in config/keys/. HOST is an SSH destination spec
    like user@hostname.

    \b
        dotconfig key send deploy root@web01.example.com
        dotconfig key send apps.example.org deploy@apps.example.org
    """
    cfg = _resolve_config_dir(ctx)
    send_key(name, host, config_dir=cfg)


@key.command("install")
@click.argument("name")
@click.argument("spec")
@click.pass_context
def key_install(ctx: click.Context, name: str, spec: str) -> None:
    """Install a Host entry in ~/.ssh/config for SPEC.

    NAME is the key in config/keys/. SPEC is user@host or just host.
    The keypair is decrypted into config/files/<name> (if not already)
    and IdentityFile points there. If the host already has an entry in
    ~/.ssh/config, this is a no-op.

    \b
        dotconfig key install deploy root@web01.example.com
        dotconfig key install apps.example.org apps.example.org
    """
    cfg = _resolve_config_dir(ctx)
    install_key(name, spec, config_dir=cfg)


@key.command("uninstall")
@click.argument("host")
@click.pass_context
def key_uninstall(ctx: click.Context, host: str) -> None:
    """Remove a Host entry from ~/.ssh/config.

    HOST is the bare hostname (no user@ prefix).

    \b
        dotconfig key uninstall web01.example.com
    """
    uninstall_key(host)


@cli.command("gh-push")
@click.option("-d", "--deploy", required=True,
              help="Deployment name to sync secrets from.")
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
@click.pass_context
def gh_push_cmd(
    ctx: click.Context,
    deploy: str,
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
    cfg = _resolve_config_dir(ctx) or Path("config")
    _gh_push(
        deployment=deploy,
        config_dir=cfg,
        repo=repo,
        actions=actions,
        codespaces=codespaces,
        include_age_key=include_age_key,
        environment=environment,
        dry_run=dry_run,
        keys_filter=keys_filter,
    )


@cli.command()
@click.pass_context
def audit(ctx: click.Context) -> None:
    """Scan config/ for unencrypted secrets at rest.

    Walks the config directory looking for files that contain values
    whose key names suggest they are secrets but are stored in plaintext
    rather than SOPS-encrypted.

    Exits with code 0 if clean, code 1 if findings exist (useful for
    CI and git hooks).

    Example:

    \b
        dotconfig audit
        dotconfig -c /path/to/config audit
    """
    import sys
    from .discover import find_config_dir

    cfg = _resolve_config_dir(ctx)
    if cfg is None:
        cfg = find_config_dir() or Path("config")

    clean = run_audit(cfg)
    if not clean:
        sys.exit(1)


@cli.command()
@click.pass_context
def reencrypt(ctx: click.Context) -> None:
    """Re-encrypt every SOPS-encrypted file under config/ in place.

    Useful after editing sops.yaml — for instance to add or remove an
    age recipient. Existing files keep their old recipient list until
    re-encrypted. Walks the entire config tree; fails fast on the first
    decrypt or encrypt error.

    Example:

    \b
        dotconfig reencrypt
        dotconfig -c /path/to/config reencrypt
    """
    from .discover import find_config_dir

    cfg = _resolve_config_dir(ctx)
    if cfg is None:
        cfg = find_config_dir() or Path("config")

    reencrypt_all(cfg)


@cli.command()
@click.pass_context
def config(ctx: click.Context) -> None:
    """Show dotconfig configuration and discovered paths.

    Reports the installed version, the config directory name (from
    DOTCONFIG_NAME or the default "config"), and where the config
    directory was found by walking up the directory tree.  When
    -c/--config or DOTCONFIG_DIR is set, that path is used directly
    instead of discovery.

    Example:

    \b
        dotconfig config
        DOTCONFIG_NAME=.config dotconfig config
        DOTCONFIG_DIR=/path/to/cfg dotconfig config
    """
    override = _resolve_config_dir(ctx)
    show_config(override=override)


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


# ---------------------------------------------------------------------------
# version group
# ---------------------------------------------------------------------------

@cli.group(invoke_without_command=True)
@click.pass_context
def version(ctx: click.Context) -> None:
    """Show the project version (or run a subcommand).

    When invoked without a subcommand, prints the current version from
    ``config/dotconfig.yaml`` and exits.

    \b
        dotconfig version
        dotconfig version bump
        dotconfig version bump --major 1
        dotconfig version bump --tag
        dotconfig version bump --push
        dotconfig version load
    """
    if ctx.invoked_subcommand is None:
        import sys
        cfg = _resolve_config_dir(ctx) or Path("config")
        v = read_dotconfig_version(cfg)
        if v is None:
            click.echo("No version set. Run: dotconfig init", err=True)
            sys.exit(1)
        click.echo(v)


@version.command("bump")
@click.option("--major", type=int, default=0,
              help="Major version segment (default: 0).")
@click.option("--tag", is_flag=True, default=False,
              help="Create a lightweight v<version> git tag after bumping.")
@click.option("-p", "--push", is_flag=True, default=False,
              help="Commit written files, tag, and push.  Requires clean master/main.")
@click.pass_context
def version_bump(ctx: click.Context, major: int, tag: bool, push: bool) -> None:
    """Compute and write the next version.

    Advances the version in ``config/dotconfig.yaml`` and syncs it to
    ``pyproject.toml`` and ``package.json`` when they exist.

    With ``--tag``, creates a lightweight ``v<version>`` git tag.

    With ``--push`` (or ``-p``): verifies the working tree is clean and on
    ``master``/``main``, commits the written files (excluding ``.env``),
    creates the tag, and runs ``git push --tags``.

    \b
        dotconfig version bump
        dotconfig version bump --major 1
        dotconfig version bump --tag
        dotconfig version bump --push
    """
    import subprocess
    import sys

    cfg = _resolve_config_dir(ctx) or Path("config")
    project_root = Path.cwd()

    if push:
        _preflight_clean_master(project_root)

    result = bump_version(
        major=major,
        tag=tag or push,
        project_root=project_root,
        config_dir=cfg,
    )

    click.echo(f"Version: {result['version']}")
    for p in result.get("synced", []):
        click.echo(f"  Updated: {p}")
    if result.get("tag"):
        click.echo(f"  Tagged:  {result['tag']}")

    if push:
        # Commit all written files except .env (gitignored).
        files_to_commit = [
            str(cfg / "dotconfig.yaml"),
        ]
        for filename in result.get("synced", []):
            if filename not in (".env",):
                files_to_commit.append(filename)

        # Stage files that actually exist
        existing = [f for f in files_to_commit if Path(f).exists()]
        if existing:
            subprocess.run(["git", "add"] + existing, check=True, cwd=project_root)

        commit_result = subprocess.run(
            ["git", "commit", "-m", f"chore: bump version to {result['version']}"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        if commit_result.returncode != 0:
            click.echo(f"git commit failed: {commit_result.stderr.strip()}", err=True)
            sys.exit(1)

        push_result = subprocess.run(
            ["git", "push", "--follow-tags"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        if push_result.returncode != 0:
            click.echo(f"git push failed: {push_result.stderr.strip()}", err=True)
            sys.exit(1)
        click.echo("  Pushed.")


@version.command("load")
@click.pass_context
def version_load(ctx: click.Context) -> None:
    """Seed config/dotconfig.yaml version from package.json or pyproject.toml.

    Reads the version from the first available source (package.json
    takes priority over pyproject.toml) and writes it to
    config/dotconfig.yaml, overwriting any existing value.

    Exits 1 if neither source file contains a version.

    \b
        dotconfig version load
    """
    import sys
    cfg = _resolve_config_dir(ctx) or Path("config")
    project_root = Path.cwd()
    version = seed_version_from_sources(project_root)
    if version is None:
        click.echo(
            "No version source found. "
            "Add a 'version' field to package.json or pyproject.toml.",
            err=True,
        )
        sys.exit(1)
    write_dotconfig_version(cfg, version)
    click.echo(f"Loaded version: {version}")


def _preflight_clean_master(project_root: Path) -> None:
    """Abort with a message if the working tree is dirty or not on master/main."""
    import subprocess
    import sys

    # Check current branch
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        cwd=project_root,
    )
    if branch_result.returncode != 0:
        click.echo("Not a git repository.", err=True)
        sys.exit(1)
    branch = branch_result.stdout.strip()
    if branch not in ("master", "main"):
        click.echo(
            f"--push requires branch master or main; current branch is '{branch}'.",
            err=True,
        )
        sys.exit(1)

    # Check for dirty working tree
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
        cwd=project_root,
    )
    if status_result.returncode != 0:
        click.echo("Could not determine git status.", err=True)
        sys.exit(1)
    if status_result.stdout.strip():
        click.echo(
            "--push requires a clean working tree. Commit or stash your changes first.",
            err=True,
        )
        sys.exit(1)
