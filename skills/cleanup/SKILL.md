---
name: cleanup
description: >
  Read-only review for code cleanliness at the function and file level: unclear
  names, long or deep functions, duplication that is really the same behavior,
  dead code, unused parameters, needless wrappers. Use when the user asks for a
  clean-code review, "what can be tidied", or says "/review-kit:cleanup".
  Takes an optional path. Reports and proposes; never edits code. For
  module-level coupling use review-kit:structure.
---

Review readability and tidiness, not architecture and not bugs. Read-only: write a report, change no code.
This is the "make it better" counterpart to a "make it shorter" tool: shorter is not the goal, clearer is.

First read `../../references/common.md` (relative to this skill's base directory) and follow it: it holds the scripts, finding rules, tracing, ledger and output format shared by every review-kit skill. The report name is `review-cleanup-<scope-slug>.md`.

Scope: the argument must be a path, module or directory. If it is not (or is empty), ask which scope before reading anything.

Yardstick: the project's own conventions first (`CLAUDE.md`, `AGENTS.md`, lint config), else the dominant local style.

## What to look for
- **Names** that hide intent or lie; the same concept under different names.
- **Functions** doing several things, deep nesting, long parameter lists, flags that switch behavior.
- **Duplication** of behavior (not of shape): the same logic copied, where a single owner would remove a real maintenance risk.
- **Dead code**: unreferenced functions, unused parameters, unreachable branches, stale reexports. Grep every caller before saying "unused", including dynamic use and public APIs.
- **Needless indirection**: wrappers that only delegate, abstractions with one implementation.
- **Comments** that restate code or contradict it.

## Extra rules for this lens
- State what is gained (lines, clarity, risk removed) and what could break.
- Do not trade clarity for fewer lines. If the shorter form is harder to read, drop it.
- Skip taste. A change must help the next reader or remove a real risk; otherwise do not list it.
