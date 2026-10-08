# review-kit

Read-only code review skills for [Claude Code](https://claude.com/claude-code) that look at **structure and consistency**, not just at the diff. They write a report and a ledger to disk; they never edit your code.

Language-agnostic. The yardstick is the project's own rules (`CLAUDE.md`, `AGENTS.md`, README, lint config) or, failing that, the dominant pattern in the code.

## Skills

| Command | What it does |
|---|---|
| `/review-kit:structure <path>` | Coupling, boundaries, consistency across modules, files doing too much. |
| `/review-kit:cleanup <path>` | Names, long functions, duplicated behavior, dead code, needless indirection. |
| `/review-kit:plan [report]` | Turns an approved report into small, verifiable refactor steps. Plans only. |
| `/review-kit:project [root]` | Reviews a whole project: measures it, splits it into areas, delegates each to a sub-agent, then merges project-wide and cross-area findings. Shows the plan and the cost and asks before spawning anything. |

The review skills share their rules in [`references/common.md`](references/common.md).

## What makes it cheaper and more reliable

Facts a script can get exactly are not left to the model. The scripts need only Python 3 and git, and cost no tokens.

| Script | Purpose |
|---|---|
| `scripts/prepare.py <scope...>` | Size of the scope, graph freshness, who depends on it and what it depends on, `TODO`/`FIXME`/`HACK` markers (plus any you pass), env vars read vs. the example env file, long SQL strings repeated elsewhere. |
| `scripts/ledger_check.py <scope...>` | Compares the review ledger with the files by `git hash-object`; says which findings can be **carried** unchanged and which must be re-verified. `stamp` writes a ledger row. |
| `scripts/trace.py <file>` | Callers and dependencies (up/down, hop-limited) from a graphify `graph.json` (`graphify-out/graph.json`). |
| `scripts/verify_refs.py <report>` | Checks that every cited `file:line` exists and is inside the file. Catches invented or stale references. |
| `scripts/inventory.py [root]` | Reviewable lines per folder, languages, largest files, and a size-based proposal of areas. |
| `scripts/cross_areas.py <areas.txt>` | Dependencies **between** areas from the graph: heaviest pairs, areas that depend on each other, the area everyone imports. |

### The ledger
One file per area in `.claude/state/review/ledger/`, a row per file: hash, date, summary, decisions, and its findings with `deps:` (hashes of the other files each finding cites). A second run on an unchanged area opens no source file and carries the findings over; a changed file is re-read and its row rewritten. It is a cache: if it disagrees with the code, the code wins.

### Needs external check
What the code cannot prove (an API's behavior, a database schema, an env value) is not turned into a finding. It goes to a **Needs external check** section with a tag (`[needs-db-review]`, `[needs-api-review:<provider>]`, `[needs-env-review]`, `[needs-other-review]`) so the right tool or person can settle each kind.

## Install

From a terminal `claude` session:

```
/plugin marketplace add ZeroVdV/Zcode-review
/plugin install review-kit@review-kit
```

The command names above follow the usual plugin flow; if your version differs, run `/plugin`. The graph is optional: without `graphify-out/graph.json` the skills fall back to grep and `trace.py` / `cross_areas.py` are unavailable.

## Output

Everything goes to `.claude/state/review/` (working files, do not commit): `review-<lens>-<scope>.md`, `ledger/<area>.md`, `areas.txt`, `review-project.md`.

## What was measured, and what was not

Measurements come from a few runs on one mid-size Python project; treat them as orders of magnitude, not benchmarks.

- A sub-agent that opens **no** file still costs about 60k tokens (reading the skill and the ledger). On a scope of about 750 lines the ledger saved about 35k (96k to 61k). It should pay off more on bigger scopes; that was not measured.
- On a service of about 27 files and 2,000 lines, an early version of the structure skill read 10 files and reported 5 findings, while a plain read-everything review reported 29 items mixing high and low value. That is why the skill now reads the whole scope when it is small and caps the report at 10 ranked findings.
- `/review-kit:project` is built from the pieces above; its end-to-end cost on a large repository has **not** been measured yet.

## Limits

- Static only. The graph resolves calls by name and cannot see dynamic dispatch or string lookups; "no callers" means "no callers in the graph", not dead code. Confirm in the code before removing anything.
- A model still writes the findings. `verify_refs.py` catches invented lines, not wrong conclusions. Sub-agents on small models make more factual mistakes: check the top findings.
- Python is where the scripts are most exact (repeated SQL detection is Python only); the rest works on any text files.

## Layout

```
.claude-plugin/    plugin and marketplace manifests
skills/            structure, cleanup, plan, project
references/        common.md (rules shared by the review skills)
scripts/           the Python helpers above
```

## Contributing

This repository is public. Keep everything in it generic: see [`CLAUDE.md`](CLAUDE.md).
