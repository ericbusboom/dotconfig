"""Tests for the agent / --instructions output."""

from click.testing import CliRunner

from dotconfig.agent import _format_help_reference, show_agent_instructions
from dotconfig.cli import cli


def test_show_agent_instructions_plain(capsys):
    """Without a cli_group, prints just the bundled markdown file."""
    show_agent_instructions()
    out = capsys.readouterr().out
    assert "# dotconfig — Agent Instructions" in out
    assert "dotconfig load" in out
    assert "dotconfig save" in out
    assert "Rules for agents" in out
    # Without cli_group, no auto-generated reference appended.
    assert "Command-line help reference" not in out


def test_show_agent_instructions_with_cli_group(capsys):
    """With cli_group passed, an auto-generated help reference is appended."""
    show_agent_instructions(cli)
    out = capsys.readouterr().out
    assert "Command-line help reference" in out
    # Every top-level subcommand should be present.
    for cmd_name in ("init", "load", "save", "audit", "config", "gh-push", "key"):
        assert f"`dotconfig {cmd_name}`" in out
    # Nested key subcommands should be present.
    for sub in ("gen", "save", "get", "pub", "list", "rm", "send"):
        assert f"`dotconfig key {sub}`" in out


def test_instructions_flag_prints_full_manual():
    """`dotconfig --instructions` prints the manual + auto-generated reference."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--instructions"])
    assert result.exit_code == 0
    assert "# dotconfig — Agent Instructions" in result.output
    assert "Rules for agents" in result.output
    assert "Command-line help reference" in result.output
    assert "`dotconfig load`" in result.output


def test_agent_subcommand_removed():
    """The old `dotconfig agent` subcommand is gone."""
    runner = CliRunner()
    result = runner.invoke(cli, ["agent"])
    # Click reports unknown command with non-zero exit.
    assert result.exit_code != 0


def test_cli_help_mentions_instructions():
    """The top-level help points users at --instructions."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "--instructions" in result.output


def test_format_help_reference_renders_subcommands():
    """The reference includes sections for top-level and nested subcommands."""
    text = _format_help_reference(cli)
    assert "## Command-line help reference" in text
    assert "### `dotconfig load`" in text
    assert "### `dotconfig key`" in text
    # Nested subcommands are one heading level deeper.
    assert "#### `dotconfig key gen`" in text
