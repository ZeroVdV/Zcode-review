---
name: cleanup
description: >
  Read-only review for code cleanliness at the function and file level: unclear
  names, long or deep functions, duplication that is really the same behavior,
  dead code, unused parameters, needless wrappers. Use when the user asks for a
  clean-code review or a report of what could be tidied, or says
  "/review-kit:cleanup". Takes a path (asks when missing). Reports and proposes;
  never edits code. Not for reviewing a diff or pull request, hunting bugs, or
  actually tidying or simplifying the code. For module-level coupling use
  review-kit:structure.
argument-hint: "<path>"
disallowed-tools: Edit, NotebookEdit
---

Review readability and tidiness, not architecture and not bugs. Read-only: write a report, change no code.
This is the "make it better" counterpart to a "make it shorter" tool: shorter is not the goal, clearer is.

The plugin folder is `${CLAUDE_PLUGIN_ROOT}` (if that shows as literal text, it is the folder two levels above this skill's base directory). First read `references/common.md` in it and follow it: it holds the scripts, finding rules, tracing, ledger and output format shared by every review-kit skill. Your lens is `cleanup`: pass `--lens cleanup` to `ledger_check.py`, and the report is `.review-kit/review-cleanup-<scope-slug>.md`.

Scope: the argument must be a path, module or directory. If it is missing or is not one, ask which scope before reading anything.

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
