"""Compare a review ledger with the files as they are now. No LLM, no tokens.

Check:  python ledger_check.py <scope> [<scope> ...] [--ledger .claude/state/review/ledger/<scope-slug>.md]
                               [--ext EXT ...]
Stamp:  python ledger_check.py stamp <ledger> <file> [--summary S] [--decisions D]
                               [--findings F | --findings-file PATH | --findings-file -]
        records the file's current hash and today's date after a review (keeps cells you do not pass).
        Finding text usually holds backticks and quotes, which a shell mangles: write it to a file (or pipe it
        on stdin with `--findings-file -`) instead of passing it with --findings.

Check prints which files are unchanged / changed / new / removed, and for each finding in the ledger whether it can
be carried: its row's file and every `path@hash7` listed after `deps:` must still have the recorded hash.
The scope is its source files, the same set prepare.py and inventory.py count. Paths are compared in one
spelling, so `./src/x`, `src\\x` and `src/x/` are the same scope.
Exit code 0 = nothing changed and every finding is carried; 1 = something needs a look."""

import argparse
import datetime
import os
import re
import sys

from _common import EMPTY_BLOB, clean, git_hashes, read_text, scope_files, under, utf8

HASH = re.compile(r"^[0-9a-f]{40}$")
DEP = re.compile(r"([\w./\\-]+)@([0-9a-f]{7,40})")
FINDING_START = re.compile(r"(?:^|\s)(?=F\d+\s*\[)")  # `F2 [rank 2] ...`; a bare "see F2" inside a claim is not a start
HEADER = ["path", "git hash-object", "date", "summary", "decisions", "findings"]


def cells_of(line):
    """Cells of a table row, with or without the outer pipes; pipes inside the findings cell are kept."""
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") else s
    return [c.strip() for c in s.split("|", 5)]


def parse(ledger):
    """[(line index, [cells])] for table rows whose second cell is a git hash."""
    rows = []
    for i, line in enumerate(read_text(ledger).splitlines()):
        cells = cells_of(line)
        if len(cells) >= 2 and HASH.match(cells[1].strip("`")):
            cells[0], cells[1] = clean(cells[0].strip("`")), cells[1].strip("`")
            rows.append((i, cells))
    return rows


def split_findings(cell):
    return [t.strip() for t in FINDING_START.split(cell) if t.strip() and t.strip() != "-"]


def default_ledger(scope):
    """The whole scope path as a slug (`src/billing` -> `src-billing`), so same-named folders do not share a ledger."""
    scope = clean(scope)
    slug = "root" if scope == "." else re.sub(r"[^\w.+-]+", "-", scope).strip("-")
    return f".claude/state/review/ledger/{slug}.md"


def check(scopes, ledger, ext=()):
    scopes = [clean(s) for s in scopes]
    files = sorted({f for s in scopes for f in scope_files(s, ext)})
    now = git_hashes(files)
    now = {f: h for f, h in now.items() if h != EMPTY_BLOB}
    if not os.path.isfile(ledger):
        print(f"no ledger at {ledger}: everything is new ({len(now)} files)")
        return 1
    rows = {c[0]: c for _, c in parse(ledger)}
    unchanged = [f for f in now if f in rows and rows[f][1] == now[f]]
    changed = [f for f in now if f in rows and rows[f][1] != now[f]]
    new = [f for f in now if f not in rows]
    removed = [p for p in rows if any(under(p, s) for s in scopes) and not os.path.isfile(p)]
    print(f"ledger: {ledger}")
    print(f"unchanged {len(unchanged)}  changed {len(changed)}  new {len(new)}  removed {len(removed)}")
    for label, group in (("changed", changed), ("new", new), ("removed", removed)):
        for f in group:
            print(f"  {label}: {f}")

    print("\nfindings:")
    stale = 0
    for path, cells in rows.items():
        if len(cells) < 6:
            continue
        for text in split_findings(cells[5]):
            deps = [(clean(d), h) for d, h in DEP.findall(text)]
            dep_now = git_hashes([d for d, _ in deps])
            bad = [d for d, h in deps if dep_now.get(d, "")[:len(h)] != h]
            if path in changed or path in removed or path not in now:
                status = "RE-VERIFY (its file changed)"
            elif bad:
                status = "RE-VERIFY (dep changed: " + ", ".join(bad) + ")"
            elif not deps:
                status = "carry, but no deps recorded: check any other file it cites"
            else:
                status = "carry"
            stale += status.startswith("RE-VERIFY")
            print(f"  [{status}] {text[:110]}")
    return 0 if not (changed or new or removed or stale) else 1


def stamp(ledger, file, summary, decisions, findings):
    file = clean(file)
    h = git_hashes([file]).get(file)
    if not h or h == EMPTY_BLOB:
        raise SystemExit(f"{file}: missing or empty, nothing to stamp")
    exists = os.path.isfile(ledger)
    lines = read_text(ledger).splitlines() if exists else [
        f"# Ledger: {os.path.basename(ledger)[:-3]} (a review cache, not proof; if it contradicts the code, the code wins)"]
    rows = parse(ledger) if exists else []
    old = next((c for _, c in rows if c[0] == file), None)
    tidy = lambda s: " ".join(s.replace("|", "/").split())
    cell = lambda new, i: tidy(new) if new is not None else (old[i] if old and len(old) > i else "-")
    row = " | ".join([file, h, datetime.date.today().isoformat(),
                      cell(summary, 3), cell(decisions, 4), cell(findings, 5)])
    if old:
        lines[next(i for i, c in rows if c[0] == file)] = row
    elif rows:
        lines.insert(rows[-1][0] + 1, row)
    else:
        seps = [i for i, l in enumerate(lines) if re.match(r"^\|?\s*-{3,}\s*\|", l)]
        if seps:  # an empty table is already there
            lines.insert(seps[-1] + 1, row)
        else:  # no table yet: put it before the first section, or at the end
            at = next((i for i, l in enumerate(lines) if l.startswith("## ")), len(lines))
            lines[at:at] = ["", " | ".join(HEADER), "---|---|---|---|---|---", row, ""]
    os.makedirs(os.path.dirname(ledger) or ".", exist_ok=True)
    with open(ledger, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    print(f"stamped {file} {h[:7]}")


def main():
    utf8()
    if len(sys.argv) > 1 and sys.argv[1] == "stamp":
        ap = argparse.ArgumentParser()
        ap.add_argument("cmd")
        ap.add_argument("ledger")
        ap.add_argument("file")
        for k in ("summary", "decisions", "findings"):
            ap.add_argument("--" + k)
        ap.add_argument("--findings-file", help="read the findings cell from this file ('-' = stdin)")
        a = ap.parse_args()
        findings = a.findings
        if a.findings_file:
            if findings is not None:
                raise SystemExit("pass --findings or --findings-file, not both")
            findings = sys.stdin.buffer.read().decode("utf-8", "replace") if a.findings_file == "-" else read_text(a.findings_file)
        return stamp(a.ledger, a.file, a.summary, a.decisions, findings)
    ap = argparse.ArgumentParser()
    ap.add_argument("scope", nargs="+")
    ap.add_argument("--ledger")
    ap.add_argument("--ext", nargs="*", default=[], help="extra source extensions to count as reviewable")
    a = ap.parse_args()
    if len(a.scope) > 1 and not a.ledger:
        raise SystemExit("several scopes: pass --ledger .claude/state/review/ledger/<area>.md")
    sys.exit(check(a.scope, a.ledger or default_ledger(a.scope[0]), a.ext))


if __name__ == "__main__":
    main()
