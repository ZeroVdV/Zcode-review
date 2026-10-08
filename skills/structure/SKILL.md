---
name: structure
description: >
  Read-only review of how a codebase is organized: coupling between modules,
  boundaries and layering, consistency of patterns across modules, files or
  modules doing too much. Use when the user asks to review architecture,
  structure, coupling, boundaries or cross-module consistency, or says
  "/review-kit:structure". Takes a path (a module, service or directory; asks
  when missing). Reports and proposes; never edits code. Not for reviewing a
  diff or pull request, hunting bugs or security issues, or applying changes.
argument-hint: "<path>"
disallowed-tools: Edit, NotebookEdit
---

Review structure, not style and not bugs. Read-only: write a report, change no code.

The plugin folder is `${CLAUDE_PLUGIN_ROOT}` (if that shows as literal text, it is the folder two levels above this skill's base directory). First read `references/common.md` in it and follow it: it holds the scripts, finding rules, tracing, ledger and output format shared by every review-kit skill. Your lens is `structure`: pass `--lens structure` to `ledger_check.py`, and the report is `.review-kit/review-structure-<scope-slug>.md`.

Scope: the argument must be a path, module or directory. If it is missing or is not one, ask which scope before reading anything.

## Yardstick
Consistency needs a reference. In order:
1. The project's own rules: `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING`, README, ADRs, lint/arch configs.
2. If none says it, the dominant pattern in the code (what most sibling modules do).
Never impose an outside style the project did not choose. State which yardstick each finding uses.

## What to look for
- **Coupling**: module A importing internals of B (or a sibling) instead of a shared layer; cycles; dependency direction against the layering; one change forcing edits in many places.
- **Boundaries**: transport/router code holding business or data logic; shared code that knows about one caller; leaky abstractions.
- **Consistency**: the same job done two different ways across modules (errors, config, HTTP/DB access, naming, layout), where the yardstick says there should be one.
- **Size and focus**: files or modules with several unrelated responsibilities; say where the seam is.
