---
name: project
description: >
  Orchestrates a read-only review of a WHOLE project: measures it, splits it
  into areas, delegates each area to a sub-agent running review-kit:structure
  (and/or cleanup), then consolidates project-wide and cross-area findings.
  Use when the user asks to review the whole project, repository or codebase, or
  says "/review-kit:project". Takes an optional root path and options (lens,
  sub-agent model, max parallel agents). Always shows the plan and cost and asks
  before spawning agents. Never edits code.
---

You are the orchestrator. You plan, delegate and consolidate; sub-agents read the code. Read-only: nothing here edits project code.

First read `../../references/common.md` (relative to this skill's base directory); the sub-agents will follow it too. Scripts are at `../../scripts/`.

## Options (free text after the command; ask only for what is missing)
- **root**: default is the repository root.
- **lens**: `structure` (default), `cleanup`, or `both` (doubles the cost).
- **sub-agent model**: default is one tier below yours (Opus or Fable: `sonnet`; Sonnet: `haiku`). Haiku makes more factual mistakes: if used, say so in the plan and confirm the top findings yourself. The user can pick any model.
- **max parallel agents**: default 3. **cap**: default 3,000 lines per area.

## 1. Measure
Run `inventory.py <root> --cap <cap>`. It prints the totals, the tree, the largest files and a proposal of areas made from sizes only. If `graphify-out/graph.json` is missing or older than the latest code, tell the user to run `graphify update .` (no LLM) before the cross-area step; the review itself can start without it.

## 2. Plan the split (your judgment; the script only knows sizes)
Use the names and types of folders and files to decide:
- Keep a cohesive unit (a service, a package) in one area. Never split a file.
- Split an area above about 1.25 x cap along its subfolders; for an OVERSIZE folder choose a split by files that follows the file names (routers, clients, db access).
- Group small related folders; give each area a meaningful name (the service's name, not `+3`).
- Tests and migrations: review with their code or leave out; say which. Leave out generated code, vendored code and docs.
- Aim for 1,000 to 3,500 lines per area: each agent has a fixed cost of about 60k tokens, so tiny areas waste it, and huge ones lose depth.
Save the result to `.claude/state/review/areas.txt` (`name: path path ...`, the format `inventory.py` prints).

## 3. Confirm before spawning (always)
Show a table: area, paths, lines, lens, model, and an estimate. Estimate from what was measured: roughly 60k to 100k tokens per area per lens on a first run (a Sonnet-class agent); far less for areas whose ledger shows no change (`ledger_check.py`). State the total, the number of waves, and the choices still open. Ask with AskUserQuestion: proceed, change model, fewer or bigger areas, cancel. Do not spawn anything before an explicit yes.

## 4. Run the agents
Spawn them in waves of at most the parallel limit with the Agent tool: `subagent_type: general-purpose`, the chosen `model`, `run_in_background: true`. Do not poll; you are notified when each finishes. Prompt for each area (fill in the brackets):

> Read-only review of one area of the project at [root]. Do NOT edit code, do NOT use the Skill tool, do NOT start other agents. Read `[plugin dir]/references/common.md` and `[plugin dir]/skills/[lens]/SKILL.md` and follow them exactly, with scripts at `[plugin dir]/scripts/`. Scope (all of these paths together): [paths]. Ledger: `.claude/state/review/ledger/[area].md` (pass `--ledger` to `ledger_check.py`). Write the report to `.claude/state/review/review-[lens]-[area].md`. Touch no other area's ledger or report. Do not open the real `.env`. Reply in at most 15 lines: report path, files read and files skipped, number of findings, the top 3 in one line each, and anything you could not verify.

`[plugin dir]` is the folder two levels above this skill's base directory. If an agent fails or returns nothing, rerun it once; if it fails again, list the area as not reviewed. Do not do its work yourself.

## 5. Consolidate (cheap: do not re-read the source)
1. Run `cross_areas.py .claude/state/review/areas.txt --ignore <entry-point area>` (needs the graph). This is what no single area can see: which areas depend on which, which pairs depend on each other, which area everyone imports.
2. From each area report read only the top findings and the **Deferred** and **Needs external check** sections (grep for lines that start with `[needs-` instead of opening whole reports).
3. Merge findings that repeat across areas into one project-wide finding with all the locations; those rank first, then cross-area dependencies, then each area's top 3.
4. Verify the 3 most important cross-area claims yourself by reading the cited lines (at most 3 files). Mark the rest as taken from the sub-agents.
5. Write `.claude/state/review/review-project.md`: the partition and the tokens actually used if known, project-wide findings, the cross-area table from the script, the top 3 per area with the report path, Deferred and Needs external check grouped by tag across areas, what was skipped or failed, and next steps (e.g. `review-kit:plan` on the approved findings).
6. Run `verify_refs.py` on it; fix every BAD citation.

Reply with the report path, the top 5 findings, the number of areas and agents, and what was not covered.
