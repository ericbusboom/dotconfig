"""Print agent instructions for AI coding assistants."""

from importlib.resources import files


def show_agent_instructions() -> None:
    """Read and print the agent instructions markdown file."""
    text = files("dotconfig").joinpath("agent_instructions.md").read_text(
        encoding="utf-8",
    )
    print(text)
