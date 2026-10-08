---
name: plan
description: >
  Turns an approved review report (from review-kit:structure or review-kit:cleanup,
  or any list of findings) into a refactor plan of small, independently
  verifiable steps. Use when the user says "plan these fixes", "make a refactor
  plan from the review", or "/review-kit:plan". Takes the report path. Plans
  only; never edits code.
---

Input: a review report path (default: the newest `.claude/state/review/review-*.md` (or the ledger's findings, if the user names an area)) and, if given, which findings the user approved. Plan only approved ones; if none were named, ask which.

## Method
1. Re-check each approved finding against the code now; code may have changed since the review. Drop or flag any that no longer holds.
2. Group into steps that each leave the project working: one concern per step, smallest useful size, ordered so earlier steps unblock later ones. Put `organization` steps before `behavior-change` ones.
3. For each step state: goal, files touched, exact change in a few lines, what could break, and how to verify (the project's own check commands, a manual route to try, a log to watch). If nothing can verify it, say so plainly and mark the step as high risk.
4. Flag steps that need a decision from the user (naming, API shape, data migration) instead of choosing silently.
5. Respect declared protections and the project's workflow rules (branches, migrations, docs) from `CLAUDE.md` / `AGENTS.md`.

## Output
Write `.claude/state/review/plan-<topic>.md` (working file, do not commit): numbered steps, dependency order, open decisions, and what is explicitly out of scope. Reply with the path, the step count and the riskiest step. Do not start executing; wait for the user.
