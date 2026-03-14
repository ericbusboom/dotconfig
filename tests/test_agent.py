"""Tests for the agent instructions command."""

from click.testing import CliRunner

from dotconfig.agent import show_agent_instructions
from dotconfig.cli import cli


def test_show_agent_instructions(capsys):
    """show_agent_instructions prints the markdown file to stdout."""
    show_agent_instructions()
    captured = capsys.readouterr()
    assert "# dotconfig — Agent Instructions" in captured.out
    assert "dotconfig load" in captured.out
    assert "dotconfig save" in captured.out
    assert "Rules for agents" in captured.out


def test_agent_cli_command():
    """The 'agent' subcommand prints agent instructions."""
    runner = CliRunner()
    result = runner.invoke(cli, ["agent"])
    assert result.exit_code == 0
    assert "# dotconfig — Agent Instructions" in result.output
    assert "Rules for agents" in result.output


def test_cli_help_mentions_agent():
    """The top-level help text tells agents where to go."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "dotconfig agent" in result.output
