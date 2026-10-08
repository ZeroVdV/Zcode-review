# review-kit: rules for working in this repository

This repository is **public**. Everything in it (code, docs, examples, tests, commit messages, branch names, pull request titles and bodies, issue text) must be generic.

- Never write names, paths, modules, tables, services, identifiers, URLs, sizes or measurements that come from a specific private project or repository, and do not mention that such projects exist. When you test the tools on private code, keep what you saw out of the repository and out of the pull request.
- Examples use neutral placeholders: `src/jobs.py`, `src/shared/client.py`, `billing`, `service_a`. Measurements are rounded and described as coming from "a mid-size project".
- Skills and scripts stay language-agnostic and project-agnostic: the project's own rules (its `CLAUDE.md`, `AGENTS.md`, README, lint config) are read at run time, never copied in here.
- A project-specific tag or convention is an option or an argument (like `prepare.py --markers`), never a default.
- Before committing, search the diff for names that do not belong to this project and remove them. Before opening a pull request, read its title and body with the same question.

Technical notes: the scripts need only Python 3 and git; keep them stdlib-only and read-only on the target project. Reports and ledgers are written under `.claude/state/review/` of the project being reviewed, not here.
