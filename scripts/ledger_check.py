"""Compare a review ledger with the files as they are now. No LLM, no tokens.

Check:  python ledger_check.py <scope> [<scope> ...] [--ledger .claude/state/review/ledger/<last dir of scope>.md]
Stamp:  python ledger_check.py stamp <ledger> <file> [--summary S] [--decisions D] [--findings F]
        records the file's current hash and today's date after a review (keeps cells you do not pass).

Check prints which files are unchanged / changed / new / removed, and for each finding in the ledger whether it can
be carried: its row's file and every `path@hash7` listed after `deps:` must still have the recorded hash.
Exit code 0 = nothing changed and every finding is carried; 1 = something needs a look."""

import argparse
import datetime
import os
import re
import sys

from _common import EMPTY_BLOB, git_hashes, norm, read_text, scope_files, utf8

HASH = re.compile(r"^[0-9a-f]{40}$")
DEP = re.compile(r"([\w./\\-]+)@([0-9a-f]{7,40})")
HEADER = ["path", "git hash-object", "data", "resumo", "decisões", "achados"]


def parse(ledger):
    """[(line index, [cells])] for table rows whose second cell is a git hash."""
    rows = []
    for i, line in enumerate(read_text(ledger).splitlines()):
        cells = [c.strip() for c in line.split(" | ")]
        if len(cells) >= 2 and HASH.match(cells[1]):
            rows.append((i, cells))
    return rows


def split_findings(cell):
    return [t.strip() for t in re.split(r"\s(?=F\d+\b)", cell) if t.strip() and t.strip() != "-"]


def check(scopes, ledger):
    files = sorted({f for s in scopes for f in scope_files(s)})
    now = git_hashes(files)
    now = {f: h for f, h in now.items() if h != EMPTY_BLOB}
    if not os.path.isfile(ledger):
        print(f"no ledger at {ledger}: everything is new ({len(now)} files)")
        return 1
    rows = {c[0]: c for _, c in parse(ledger)}
    unchanged = [f for f in now if f in rows and rows[f][1] == now[f]]
    changed = [f for f in now if f in rows and rows[f][1] != now[f]]
    new = [f for f in now if f not in rows]
    prefixes = [norm(s).rstrip("/") for s in scopes]
    removed = [p for p in rows if any(p == x or p.startswith(x + "/") for x in prefixes) and not os.path.isfile(p)]
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
            deps = DEP.findall(text)
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
    h = git_hashes([norm(file)]).get(norm(file))
    if not h or h == EMPTY_BLOB:
        raise SystemExit(f"{file}: missing or empty, nothing to stamp")
    lines = read_text(ledger).splitlines() if os.path.isfile(ledger) else [
        f"# Ledger: {os.path.basename(ledger)[:-3]} (cache de revisão, não prova; se contradiz o código, o código vence)", "",
        " | ".join(HEADER), "---|---|---|---|---|---"]
    rows = parse(ledger) if os.path.isfile(ledger) else []
    old = next((c for _, c in rows if c[0] == norm(file)), None)
    clean = lambda s: s.replace("|", "/").replace("\n", " ")
    cell = lambda new, i: clean(new) if new is not None else (old[i] if old and len(old) > i else "-")
    row = " | ".join([norm(file), h, datetime.date.today().isoformat(),
                      cell(summary, 3), cell(decisions, 4), cell(findings, 5)])
    if old:
        idx = next(i for i, c in rows if c[0] == norm(file))
        lines[idx] = row
    else:
        last = rows[-1][0] if rows else max(i for i, l in enumerate(lines) if l.startswith("---"))
        lines.insert(last + 1, row)
    os.makedirs(os.path.dirname(ledger) or ".", exist_ok=True)
    open(ledger, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print(f"stamped {norm(file)} {h[:7]}")


def main():
    utf8()
    if len(sys.argv) > 1 and sys.argv[1] == "stamp":
        ap = argparse.ArgumentParser()
        ap.add_argument("cmd")
        ap.add_argument("ledger")
        ap.add_argument("file")
        for k in ("summary", "decisions", "findings"):
            ap.add_argument("--" + k)
        a = ap.parse_args()
        return stamp(a.ledger, a.file, a.summary, a.decisions, a.findings)
    ap = argparse.ArgumentParser()
    ap.add_argument("scope", nargs="+")
    ap.add_argument("--ledger")
    a = ap.parse_args()
    if len(a.scope) > 1 and not a.ledger:
        raise SystemExit("several scopes: pass --ledger .claude/state/review/ledger/<area>.md")
    ledger = a.ledger or f".claude/state/review/ledger/{os.path.basename(norm(a.scope[0]).rstrip('/'))}.md"
    sys.exit(check(a.scope, ledger))


if __name__ == "__main__":
    main()
