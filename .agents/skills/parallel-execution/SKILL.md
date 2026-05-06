---
name: parallel-execution
description: Executes independent sprint tickets in parallel using git worktrees for isolation — opt-in only
---

# Parallel Execution Skill

Enables concurrent execution of independent tickets within a sprint.
Each ticket runs in its own git worktree for full filesystem isolation.

**Opt-in only.** Sequential execution remains the default. The
stakeholder must explicitly choose parallel mode.

Note: With agent teams + Tasks (see `execute-sprint` skill), parallel
execution is handled natively. This skill documents the manual worktree
approach as a fallback.

## Prerequisites

- Active sprint with execution lock acquired
- Multiple tickets in `todo` status with no dependency edges between them

## Process

### 1. Analyze Ticket Independence

Two tickets are independent if:
1. Neither appears in the other's `depends-on` list
2. Their plans don't list overlapping files to modify

### 2. Create Worktrees

```bash
git worktree add ../worktree-ticket-NNN sprint/NNN-slug -b ticket-NNN-slug
```

### 3. Dispatch Implementation

For each worktree, invoke the programmer agent with the ticket context.
All run concurrently.

### 4. Review Results

Check each result: tests pass, acceptance criteria met, clean commits.

### 5. Merge Worktree Branches

Merge one at a time to the sprint branch:
```bash
git merge ticket-NNN-slug --no-ff -m "merge: ticket #NNN into sprint branch"
```

If merge conflicts occur despite independence analysis: abort, log,
fall back to sequential for the conflicting ticket.

### 6. Cleanup

```bash
git worktree remove ../worktree-ticket-NNN
git branch -d ticket-NNN-slug
```

Never leave worktrees dangling.

### 7. Execute Sequential Remainder

Any deferred tickets run sequentially on the sprint branch.

## When NOT to Use

- Single ticket sprints
- All tickets have dependencies
- Tickets modify shared files
- Stakeholder has not opted in
