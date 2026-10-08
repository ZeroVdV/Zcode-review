---
name: project
description: >
  Orchestrates a read-only review of a WHOLE project: measures it, splits it
  into areas, delegates each area to a sub-agent running the structure and/or
  cleanup lens, then consolidates project-wide and cross-area findings. Use when
  the user asks for a structure or clean-code review of the whole project,
  repository or codebase, or says "/review-kit:project". Takes an optional root
  path and options (lens, sub-agent model, max parallel agents). Always shows
  the plan and cost and asks before spawning agents. Never edits code. Not for
  reviewing a diff or pull request, or hunting bugs or security issues.
argument-hint: "[root] [lens] [model]"
disallowed-tools: Edit, NotebookEdit
---

You are the orchestrator. You plan, delegate and consolidate; sub-agents read the code. Read-only: nothing here edits project code.

The plugin folder is `${CLAUDE_PLUGIN_ROOT}` (if that shows as literal text, it is the folder two levels above this skill's base directory). First read `references/common.md` in it; the sub-agents follow it too. Run every script as it says: from the project root, `python3` or else `python`.

## Options (free text after the command; ask only for what is missing)
- **root**: the git root of the project. If the user names a subfolder, the root stays the git root and the subfolder is what gets split into areas.
- **lens**: `structure` (default), `cleanup`, or `both` (doubles the cost: one agent per area per lens).
- **sub-agent model**: default is one tier below yours (`sonnet` when you are a larger model, `haiku` when you are Sonnet). A small model makes more factual mistakes: if used, say so in the plan and check its top findings yourself in step 5. The user can pick any model.
- **max parallel agents**: default 3. **cap**: default 3,000 lines per area.
- **extra flags**: `--ext <extension>` when `inventory.py` does not count the project's language, `--markers <tag>` for a project's own deferral tag. Whatever you use, every sub-agent must use too.

## 1. Measure
Run `inventory.py . --cap <cap>`. It prints the totals, the tree, the largest files and a proposal of areas made from sizes only. Check that `graphify-out/graph.json` exists; if not, tell the user that `graphify update .` (no LLM) would add the cross-area step, and go on without it.

## 2. Plan the split (your judgment; the script only knows sizes)
Use the names and types of folders and files to decide:
- Keep a cohesive unit (a service, a package) in one area. Never split a file.
- Split an area above about 1.25 x cap along its subfolders; for an OVERSIZE entry choose a split by files that follows the file names (routers, clients, db access).
- Group small related folders; give each area a meaningful name made of letters, digits and `-` (the service's name, not `src+3`).
- An area is exactly the paths you list: everything under them is reviewed. To leave out tests, migrations, generated or vendored code, list paths that do not contain them, and say in the plan what was left out.
- Aim for 1,000 to 3,500 lines per area: each agent has a fixed cost of tens of thousands of tokens, so tiny areas waste it, and huge ones lose depth.
Save the result to `.review-kit/areas.txt` (`name: path path ...`, a path with spaces in double quotes, the format `inventory.py` prints).

## 3. Skip what has not changed, then confirm (always)
For each area and lens run `ledger_check.py <paths> --ledger .review-kit/ledger/<lens>-<area>.md`. Exit code 0 with the report `.review-kit/review-<lens>-<area>.md` already there means nothing changed: reuse that report and spawn nothing for it.

Write `.review-kit/yardstick.md` once, at most 40 lines: the rules the project states about structure and style, each with its source `path:line`, taken from `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING`, README, ADRs and lint config; or "none stated" so reviewers use the dominant pattern. Sub-agents read this instead of each re-reading those documents. If the project has a linter or type checker with a check-only mode, you may run it once here (never a fixing or formatting mode) and add the lines that concern each area to the yardstick file.

Show a table: area, paths, lines, lens, model, reused or to run, and a rough token estimate (README "What was measured" gives the order of magnitude; say it is rough). State the total, the number of waves, and the choices still open. Ask with AskUserQuestion: proceed, change model, fewer or bigger areas, cancel. Do not spawn anything before an explicit yes.

## 4. Run the agents
Spawn them in waves of at most the parallel limit with the Agent tool: `subagent_type: review-kit:reviewer` (if that agent type is not available, `general-purpose`), the chosen `model`, `run_in_background: true`. Do not poll; you are notified when each finishes. Tell the user once that they may be asked to approve the agents' `python` runs and writes under `.review-kit/`. Prompt for each area (fill in the brackets):

> Read-only review of one area. Plugin folder: `[plugin folder]`. Project root: `[root]` (run every script from there). Lens: `[lens]`. Area: `[area]`. Scope, all of these paths in ONE call of each script: [paths]. Extra flags for `prepare.py` and `ledger_check.py`: [extra flags or "none"]. Ledger: `.review-kit/ledger/[lens]-[area].md` (pass it with `--ledger`). Report: `.review-kit/review-[lens]-[area].md`. Yardstick: read `.review-kit/yardstick.md` instead of the project's rule documents. Read `[plugin folder]/references/common.md` and `[plugin folder]/skills/[lens]/SKILL.md` and follow them exactly. Do not edit project files, do not use skills, do not start agents, do not run the project's own commands, do not open a real `.env`. There is no user: never ask; when unsure take the conservative path and say so. Reply in at most 15 lines: report path, files read and skipped, number of findings, the top 3 in one line each, and anything you could not verify.

After each agent finishes, check that its report exists and run `verify_refs.py` on it. A missing report, or BAD citations, counts as failed: rerun that agent once with the problem stated; if it fails again, list the area as not reviewed. Do not do its work yourself.

## 5. Consolidate (cheap: do not re-read the source beyond the checks below)
1. If the graph exists, run `cross_areas.py .review-kit/areas.txt`. This is what no single area can see: which areas depend on which, which pairs depend on each other, which area everyone imports. Add `--ignore <area>` only for an area that is nothing but wiring (an entry point everything imports from). Without a graph, write "cross-area table unavailable (no graph)" and continue.
2. From each area report read the **Findings** section and grep the whole report for `[needs-` and for the `## Deferred` section; do not open the rest.
3. Merge findings that repeat across areas into one project-wide finding with all the locations; those rank first, then cross-area dependencies, then each area's top 3. Refer to a finding as `<area>:F<n>`.
4. Verify the 3 most important claims yourself by reading the cited lines (at most 3 files; with a small sub-agent model, the top finding of every area). Mark the rest as taken from the sub-agents.
5. Write `.review-kit/review-project.md`: the partition, which areas were reused, project-wide findings, the cross-area table from the script, the top 3 per area with the report path, Deferred, Needs external check grouped by tag across areas, what was skipped or failed, and next steps (e.g. `review-kit:plan` on the approved findings). Token use: write "not measured" unless a notification gave you the number.
6. Run `verify_refs.py` on it; for every BAD citation re-open the file and cite the real lines.

Reply with the report path, the top 5 findings, the number of areas and agents, and what was not covered.
