# review-kit

Read-only code review skills for [Claude Code](https://claude.com/claude-code) that look at **structure and consistency**, not just at the diff. They write a report and a ledger to a `.review-kit/` folder in your project; they are instructed never to edit your code, and the scripts write nowhere else.

The yardstick is the project's own rules (`CLAUDE.md`, `AGENTS.md`, README, lint config) or, failing that, the dominant pattern in the code. The skills work on any language; the helper scripts know a fixed list of source extensions (add yours with `--ext`).

## Skills

| Command | What it does |
|---|---|
| `/review-kit:structure <path>` | Coupling, boundaries, consistency across modules, files doing too much. |
| `/review-kit:cleanup <path>` | Names, long functions, duplicated behavior, dead code, needless indirection. |
| `/review-kit:plan [report]` | Turns an approved report into small, verifiable refactor steps. Plans only. |
| `/review-kit:project [root]` | Reviews a whole project: measures it, splits it into areas, delegates each to a sub-agent, then merges project-wide and cross-area findings. Shows the plan and the cost and asks before spawning anything. |

The review skills share their rules in [`references/common.md`](references/common.md). The sub-agents of `/review-kit:project` run as the plugin's own `reviewer` agent, which has no edit tool.

## What makes it cheaper and more reliable

Facts a script can get exactly are not left to the model. The scripts need only Python 3.8+ and git, and cost no tokens.

| Script | Purpose |
|---|---|
| `scripts/prepare.py <scope...>` | Size of the scope, graph freshness, who depends on it and what it depends on, `TODO`/`FIXME`/`HACK` markers (plus any you pass), env vars read vs. the example env file, long SQL strings repeated elsewhere. |
| `scripts/ledger_check.py <scope...> --lens <lens>` | Compares the review ledger with the files by `git hash-object`; says which findings can be **carried** unchanged and which must be re-verified. `stamp` writes a ledger row, `drop` removes one. |
| `scripts/trace.py <file>` | Files that depend on a file and files it depends on (hop-limited) from a graphify `graph.json` (`graphify-out/graph.json`). |
| `scripts/verify_refs.py <report>` | Checks that each cited `path:line` exists and is inside the file, and lists citations written in a shape it cannot check. Catches invented or stale references. |
| `scripts/inventory.py [root]` | Reviewable lines per folder, languages, largest files, and a size-based proposal of areas. |
| `scripts/cross_areas.py <areas.txt>` | Dependencies **between** areas from the graph: heaviest pairs, areas that depend on each other, the area everyone imports. |

A scope is its source files: what git does not ignore, with a known source extension. Real env files (`.env`, `.env.local`, `.envrc`), symbolic links and tool folders are skipped by name; a secret kept in a file with an ordinary source name is not recognised, so keep such files out of git or out of the scope.

### The ledger
One file per lens and scope in `.review-kit/ledger/`, a row per file: hash, date, summary, decisions, and its findings with `deps:` (hashes of the other files each finding rests on). On a second run, a file whose hash did not change is not re-read as a whole and its findings are carried over; a changed file is re-read and its row rewritten. The lines behind the top carried findings are re-opened every run, so a wrong finding is not carried forever. It is a cache: if it disagrees with the code, the code wins. A ledger that came with the repository (tracked by git) is not trusted.

### Needs external check
What the code cannot prove (an API's behavior, a database schema, an env value) is not turned into a finding. It goes to a **Needs external check** section with a tag (`[needs-db-review]`, `[needs-api-review:<provider>]`, `[needs-env-review]`, `[needs-other-review]`) so the right tool or person can settle each kind.

## Install

From a terminal `claude` session:

```
/plugin marketplace add ZeroVdV/Zcode-review
/plugin install review-kit@review-kit
```

To update later: `claude plugin marketplace update review-kit`, then `claude plugin update review-kit@review-kit`.

The skills run `python3` (or `python`) scripts and write under `.review-kit/`. Claude Code asks for permission for both unless your settings already allow them; `/review-kit:project` runs sub-agents in the background, and their requests show up in the main session, so stay around for the first wave.

The graph is optional: without `graphify-out/graph.json` the skills fall back to grep and `trace.py` / `cross_areas.py` are unavailable.

## Output

Everything goes to `.review-kit/` at the root of the reviewed project: `review-<lens>-<scope>.md`, `ledger/<lens>-<scope>.md`, `plan-*.md`, `areas.txt`, `yardstick.md`, `review-project.md`, `tmp/`. The folder holds a `.gitignore` of its own, so nothing in it shows up in git; delete it whenever you like.

## What was measured, and what was not

Measurements come from a few runs of an earlier version on one mid-size Python project; treat them as orders of magnitude, not benchmarks.

- A sub-agent that opens **no** file still costs tens of thousands of tokens (reading the rules and the ledger). On a scope of several hundred lines the ledger cut the cost by roughly a third. It should pay off more on bigger scopes; that was not measured.
- On a service of a few dozen files and about 2,000 lines, an early version of the structure skill read under half of the files and reported a handful of findings, while a plain read-everything review reported several times as many items, mixing high and low value. That is why the skill now reads the whole scope when it is small and shows at most 10 ranked findings.
- `/review-kit:project` is built from the pieces above; its end-to-end cost on a large repository has **not** been measured yet.

## Limits

- Static only. The graph resolves some calls by name (shown as `[inferred]`) and cannot see dynamic dispatch or string lookups; it can also miss whole-module imports and some languages' imports. "No callers" means "no callers in the graph", not dead code. Confirm in the code before removing anything.
- A model still writes the findings. `verify_refs.py` catches invented lines, not wrong conclusions. Sub-agents on small models make more factual mistakes: check the top findings.
- "Read-only" is an instruction plus a restricted sub-agent, not a sandbox: the review skills run in your session with your tools.
- The scripts are most exact on Python (repeated SQL detection is Python only). Env var detection knows the common Python, JavaScript, Go, Ruby and Rust call forms and nothing else.
- Outside a git repository the ledger and `verify_refs.py` do not work; the other scripts walk the folder tree instead.

## Layout

```
.claude-plugin/    plugin and marketplace manifests
skills/            structure, cleanup, plan, project
agents/            reviewer (the restricted sub-agent of the project skill)
references/        common.md (rules shared by the review skills)
scripts/           the Python helpers above
tests/             tests for the scripts
```

## Contributing

This repository is public. Keep everything in it generic: see [`CLAUDE.md`](CLAUDE.md).

The scripts have tests that run each one on a throwaway git repository (stdlib only):

```
python -m unittest discover -s tests -v
```

Check the manifests with `claude plugin validate .`, and bump `version` in `.claude-plugin/plugin.json` on every release: installed copies only update when it changes.
