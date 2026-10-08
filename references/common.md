# review-kit: rules shared by every review skill

Read-only. A review skill writes a report and a ledger; it never edits project code.

## Scripts
They live at `../../scripts/` relative to the skill's base directory. Run them as `python <that path>/<script>.py`. They need only Python and git, cost no tokens, and print facts: use those facts as given instead of counting by hand, and confirm them in code before they become findings.
- `prepare.py <scope>`: size of the scope, graph freshness, who depends on the scope from outside and what it depends on, deferral markers, env vars read versus the example env file, repeated long SQL strings.
- `ledger_check.py <scope>` and `ledger_check.py stamp ...`: compare and write the ledger (see Ledger).
- `trace.py <file> --entry <main file> --hops 2`: callers and dependencies from the code graph.
- `verify_refs.py <report>`: checks that every cited `file:line` exists.

Run them from the project root with scope paths relative to it. A scope is its source files: what git does not ignore, with a known source extension. Docs, config, lock and generated files, tool state (`.claude/`, `graphify-out/`) and real env files (`.env`, `.env.local`) are left out and never read; a file named directly is taken as is. If the project's language is not counted, pass `--ext <extension>` to `prepare.py`, `ledger_check.py` and `inventory.py` alike.

## Before reading code
1. Run `prepare.py <scope>`. A STALE graph warning means reach is unreliable: ask the user to run `graphify update .` (no LLM) or fall back to grep.
2. Run `ledger_check.py <scope>` (see Ledger).
3. Run what the project already has that needs no judgment: linters, import/dependency checkers, duplicate finders. What a linter catches belongs to the linter; do not list it.
4. If a code graph is available (`graphify-out/graph.json`), use it to list cross-module edges and big modules. It is a hint, not proof: confirm every edge in the code. If it is missing, continue without it; never install tools yourself (you may tell the user the command).

**How much to read**: measure the scope first. Up to about 3,000 lines, read every changed or new file in full; bodies hide duplication and wrong docs. Above that, read what the cheap checks pointed at plus the largest and most-imported files, and list what you skipped. Never read the whole repo, only the scope.

## Rules for every finding
- Cite `file:line` and show the real snippet. If you did not read it, do not list it.
- Before calling two similar pieces duplicates, open both bodies and say whether the difference is intentional. Same name is not same behavior.
- Give a concrete consequence ("changing X breaks Y"), not "could be cleaner". No concrete consequence: drop it.
- Mark each as `organization` (no behavior change) or `behavior-change`, with risk low/medium/high and how to verify.
- Respect protections the project declares (security, transactions, error contracts, redaction). Never propose removing them.
- Opinion is allowed but must be labeled `opinion`.
- Consistency finding: say what the rest of the repo does (how many other places, which) and whether the outlier is intentional.
- Check that comments and docstrings still match the code; a doc that contradicts a constant is a finding.
- If the code already records the point as a decision or deferral (`TODO`, `FIXME`, an ADR, a "temporary" docstring, or a project-specific tag you pass to `prepare.py --markers`), say so, quote it, and rank the finding low.

## Deferred
Collect every such marker in scope (`prepare.py` lists them) into a **Deferred** section: location, the quoted text, what was postponed, the trigger to do it. That lets the marker be removed from the code while the item still lives in the report.

## Needs external check
Anything you cannot prove from the code (an external API's behavior, a database schema or data, an env value, a third-party limit) is not a finding and not a guess. Put it in a **Needs external check** section, one line each: a tag, `file:line`, the exact question, and what would settle it. Tags: `[needs-db-review]`, `[needs-api-review:<provider>]`, `[needs-env-review]`, `[needs-other-review]`. Use `[needs-env-review]` only for a variable that `prepare.py` reports as NOT in the example env file; if it is documented there, settle it yourself from that file. Never open the real `.env` or print secret values. Different tools settle different tags: one tag per item, and do not settle them yourself.

## Trace the reach
For every finding that proposes moving, merging, renaming or removing something:
- **Upward (who depends on it)**: run `trace.py` when `graphify-out/graph.json` exists (it ignores decorator edges, which the graph resolves by name); otherwise grep on the name, including dynamic use: registries, string lookups, re-exports, entry points. Follow the callers up to an entry point or a shared boundary, at most 2 hops. List them in the finding.
- **Downward (what it depends on)**: read the definitions it relies on, 1 hop, enough to know whether the difference you see is intentional.
- Stop at the hop limit or at about 15 extra files, and say what you did not follow. Do not trace outside the scope unless a finding needs it.
- If it cannot be proven (dynamic dispatch, reflection, external callers), write "unproven" instead of guessing.

## Ledger
One ledger file per area: `.claude/state/review/ledger/<scope-slug>.md` (the same slug as the report: the scope path with `/` as `-`, e.g. `src-billing.md`; `root.md` when the scope is `.`). Row per file: `path | git hash-object | date | one-line summary | decisions (intentional / leave alone) | findings`. The findings cell holds each finding as a self-contained line: id, rank, `file:line`, the claim, the consequence, kind/risk, and `deps:` with `path@hash7` (7-char `git hash-object`) for every other file it cites, including files outside the scope. Example: `F2 [rank 2] src/jobs.py:30-42 release() takes a second pool connection while the first is still open; the pool can stall (behavior-change, medium) deps: src/shared/client.py@a1b2c3d`. Keep Deferred, Needs external check, Minor and Leave alone under their own headings in the same file.
- Before reading anything run `ledger_check.py <scope>`. It lists unchanged, changed, new and removed files (empty files ignored) and marks each stored finding `carry` or `RE-VERIFY`. Exit code 0 means nothing changed and every finding is carried: write the report from the ledger without opening any file.
- Unchanged file: do not re-read. Its findings may be carried into the new report as "carried (hash unchanged since <date>)" with their original `file:line`; they count as verified, and carried findings may omit the snippet. A finding is carried only if its row's file and every `deps:` hash are unchanged; otherwise re-verify it or drop it.
- Changed or new file: read it in full and rewrite its row, dropping findings the new code no longer supports. Rows of files that import or are imported by a changed file are suspect if a finding depends on them.
- Reach goes stale even when a hash does not: always re-run `trace.py` for carried findings that propose moving, merging, renaming or removing. Still run the project's cheap checks when every hash matches.
- After the run record each file you read in full: `ledger_check.py stamp <ledger> <file> --summary ... --decisions ... --findings-file <path>` (writes hash and date; cells you do not pass are kept). Write the findings cell to a file first (for example `.claude/state/review/tmp/<area>-findings.txt`) and pass its path: finding text holds backticks and quotes that a shell would mangle, so never put it on the command line. Let `stamp` write the rows; do not reformat the table by hand. Never edit another area's ledger; parallel reviewers each own one.
- The ledger is a cache. If it contradicts the code, the code wins and the row is corrected.

## Output
Write the report to `.claude/state/review/review-<skill>-<scope-slug>.md` (slug = the scope path with `/` as `-`, e.g. `src-billing`; create the dir; never overwrite another scope's report; working file, do not commit). Sections: scope and yardstick, what was not read, the top 10 findings ranked by value (each: location, evidence, consequence, kind, risk, verification), **Deferred**, **Needs external check**, a short "minor" list (one line each; taste and naming preferences go here at most), a short "leave alone" list of things that look wrong but are intentional.
Before replying run `verify_refs.py <report>`: fix or drop every BAD citation (invented or stale line), and check each WARN against the code. Reply with the report path and the top 3 only.
