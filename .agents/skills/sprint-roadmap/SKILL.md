---
name: sprint-roadmap
description: Group assessed TODOs into a sprint roadmap — a sequence of lightweight sprint plans
---

# Sprint Roadmap Skill

Group assessed TODOs into a sprint roadmap — a sequence of lightweight
sprint plans that organize the work into manageable, ordered chunks.

## When to Use

After TODOs have been created and the stakeholder wants to organize
them into sprints.

## Inputs

- `docs/clasi/design/overview.md` (must exist)
- Current architecture (if available)
- TODO files in `docs/clasi/todo/`

## Process

1. **Read TODOs**: Scan `docs/clasi/todo/` for pending TODO files.
   Read each to understand the work requested.

2. **Group into sprints** based on:
   - **Related functionality** — TODOs that touch the same feature
     belong together
   - **Dependency ordering** — TODOs that depend on others must come
     in later sprints
   - **Incremental value delivery** — Each sprint should deliver usable
     progress
   - **Difficulty balancing** — Mix complex and straightforward work

3. **Create sprint directories**: For each sprint, use `create_sprint`
   MCP tool and write a lightweight `sprint.md` with:
   - Sprint goals (what the sprint accomplishes)
   - TODO references (which TODOs are addressed)
   - Rationale for grouping
   - Dependency notes

4. **Update TODOs**: For each TODO claimed by a sprint, set
   `sprint: "NNN"` in the TODO's frontmatter.

## Output

Sprint directories with lightweight `sprint.md` files, ready for
detail planning via the `plan-sprint` skill.
