---
name: se
description: CLASI Software Engineering process dispatcher
---

# /se

Dispatch to the CLASI SE process. Parse the argument after `/se` and
invoke the matching skill from the table below.

If `/se` is called with **no arguments**, display this help listing
to the user and stop — do not execute any skill.

## Available commands

| Command | Description | Action |
|---------|-------------|--------|
| `/se status` | Show project status — sprints, tickets, next actions | Invoke the `project-status` skill |
| `/se todo <text>` | Create a TODO file from the description | Invoke the `todo` skill |
| `/se init` | Start a new project with a guided interview | Invoke the `project-initiation` skill |
| `/se report` | Report a bug with the CLASI tools | Invoke the `report` skill |
| `/se gh-import [repo] [--labels L]` | Import GitHub issues as TODOs | Invoke the `gh-import` skill |
| `/se knowledge <description>` | Capture hard-won technical understanding | Invoke the `project-knowledge` skill |
| `/se oop` | Make a quick out-of-process change | Invoke the `oop` skill |
| `/se plan` | Enter plan mode for a discussed TODO | Enter plan mode via `EnterPlanMode` |

Pass any remaining text after the subcommand as the argument to the
skill (e.g., `/se todo fix the login bug` passes "fix the login bug"
to the todo skill).

## When to use /se todo vs /se plan

- `/se todo <text>`: Quick capture. The user has a clear idea and just
  wants it recorded. One statement → one TODO file.
- `/se plan`: The user wants to discuss, explore, and refine an idea
  before capturing it. Enters plan mode for a conversation. On exit,
  the plan-to-todo hook automatically creates the TODO.
