"""Styled output helpers for dotconfig CLI."""

import click


def _s(text: str, **kwargs) -> str:
    """Shorthand for click.style."""
    return click.style(text, **kwargs)


def heading(text: str) -> None:
    """Print a bold section heading."""
    click.echo(_s(f"\n{text}", bold=True))


def ok(text: str) -> None:
    """Print a success/ok line with green checkmark."""
    click.echo(f"  {_s('✓', fg='green')} {text}")


def created(text: str) -> None:
    """Print a 'created' line with blue plus."""
    click.echo(f"  {_s('+', fg='blue', bold=True)} {text}")


def updated(text: str) -> None:
    """Print an 'updated' line with yellow pencil."""
    click.echo(f"  {_s('~', fg='yellow')} {text}")


def info(text: str) -> None:
    """Print an informational line."""
    click.echo(f"  {_s('ℹ', fg='cyan')} {text}")


def warn(text: str) -> None:
    """Print a warning line to stderr."""
    click.echo(f"  {_s('⚠', fg='yellow')} {text}", err=True)


def error(text: str) -> None:
    """Print an error line to stderr."""
    click.echo(f"  {_s('✗', fg='red')} {text}", err=True)


def item(text: str) -> None:
    """Print a plain indented line."""
    click.echo(f"  {text}")
