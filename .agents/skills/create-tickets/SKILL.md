---
name: create-tickets
description: Breaks a sprint architecture into sequenced, numbered implementation tickets with dependency ordering
---

# Create Tickets Skill

This skill breaks a sprint's architecture document into actionable
implementation tickets. It is typically invoked by the sprint-planner
agent during planning, but can also be used standalone.

## Inputs

- Sprint's `architecture-update.md` (must exist)
- Sprint's `usecases.md` (must exist)

## Process

1. **Read artifacts**: Read the sprint's architecture document and use cases.
2. **Identify work units**: Break the Sprint Changes into coherent
   implementation units. Each unit should be completable in one focused
   session.
3. **Order by dependency**: Number tickets so foundation work comes
   before features. Record dependencies in each ticket's `depends-on` field.
4. **Create ticket files**: Use the `create_ticket` MCP tool. Each ticket
   gets `tickets/NNN-slug.md` with:
   - YAML frontmatter: id, title, status (todo), use-cases, depends-on
   - Description and acceptance criteria (checkboxes)
   - Implementation plan: approach, files to create/modify, testing plan,
     documentation updates
5. **Propagate references**: Copy TODO and GitHub issue references to
   ticket frontmatter. List GitHub issues in the sprint doc's
   `## GitHub Issues` section.
6. **Verify coverage**: Every use case covered by at least one ticket.
   Every ticket traces to at least one use case.
7. **Verify sequencing**: No circular dependencies. Foundation before
   features.

## Ticket Format

File: `<sprint-dir>/tickets/NNN-slug.md`

```yaml
---
id: "NNN"
title: Short title
status: todo
use-cases: [SUC-001, SUC-002]
depends-on: [NNN]
---
```

Followed by: description, acceptance criteria, and implementation plan.

## Output

Numbered ticket files in the sprint's `tickets/` directory, ready for
implementation.
