"""Print agent / usage instructions for AI coding assistants and humans."""

from importlib.resources import files
from typing import List, Optional

import click


def show_agent_instructions(cli_group: Optional[click.Group] = None) -> None:
    """Print the bundled agent_instructions.md.

    When *cli_group* is provided, append an auto-generated
    "Command-line help reference" built from the live ``--help`` text of
    every command and subcommand in the group. That keeps the published
    instructions in sync with the actual CLI surface without relying on
    hand-maintained command tables.
    """
    text = files("dotconfig").joinpath("agent_instructions.md").read_text(
        encoding="utf-8",
    )
    if cli_group is not None:
        text = text.rstrip() + "\n\n" + _format_help_reference(cli_group)
    print(text)


def _format_help_reference(cli_group: click.Group) -> str:
    """Render every subcommand's --help text as a markdown section."""
    parts: List[str] = [
        "---",
        "",
        "## Command-line help reference (auto-generated)",
        "",
        "The following sections are generated on the fly from each subcommand's "
        "`--help` output. They are the authoritative listing of flags and "
        "defaults — if the prose above ever drifts, trust this section.",
        "",
    ]
    for name in sorted(cli_group.commands):
        cmd = cli_group.commands[name]
        parts += _format_command_help(cmd, name, depth=3)
    return "\n".join(parts) + "\n"


def _format_command_help(cmd: click.Command, full_name: str, depth: int) -> List[str]:
    """Render *cmd*'s --help text, recursing into nested groups."""
    parts: List[str] = [f"{'#' * depth} `dotconfig {full_name}`", ""]
    ctx = click.Context(cmd, info_name=cmd.name)
    parts += ["```", cmd.get_help(ctx).strip(), "```", ""]
    if isinstance(cmd, click.Group):
        for sub_name in sorted(cmd.commands):
            sub = cmd.commands[sub_name]
            parts += _format_command_help(sub, f"{full_name} {sub_name}", depth + 1)
    return parts
