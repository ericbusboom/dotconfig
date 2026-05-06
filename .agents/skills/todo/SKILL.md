---
name: todo
description: Create a TODO file from user input and place it in docs/clasi/todo/
---

# TODO Skill

This skill captures an idea or task as a TODO file in the project's
TODO directory.

## Process

1. Take the user's input (everything after `/todo` or `/se todo`).
2. Create a markdown file in `docs/clasi/todo/` with:
   - YAML frontmatter: `status: pending`
   - A `# ` heading summarizing the idea
   - A description section expanding on the idea
3. Filename: slugified version of the heading (e.g., `my-idea.md`).
4. If `docs/clasi/todo/` doesn't exist, create it.

## Output

Confirm the file was created and show its path.

## When to use this skill vs plan mode

This skill is for **quick capture** — the user has a clear idea and
wants it recorded as a TODO. If the user wants to discuss, explore
options, or refine an idea before capturing it, use plan mode
(`EnterPlanMode`) instead. The plan-to-todo hook will create the
TODO automatically when plan mode exits.
