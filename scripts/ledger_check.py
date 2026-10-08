"""Compare a review ledger with the files as they are now. No LLM, no tokens.

Check:  python ledger_check.py <scope> [<scope> ...] --lens structure|cleanup [--ext EXT ...]
        python ledger_check.py <scope> [<scope> ...] --ledger .review-kit/ledger/<lens>-<area>.md
Stamp:  python ledger_check.py stamp <ledger> <file> [--summary S] [--decisions D] [--findings-file PATH | -]
        records the file's current hash and today's date after a review. Cells you do not pass are kept, except
        that the findings must be passed again when the file changed (an empty file means "no findings").
Drop:   python ledger_check.py drop <ledger> <file>     removes the row of a file that no longer exists.

Each lens has its own ledger: the default is .review-kit/ledger/<lens>-<scope-slug>.md (`src/billing` ->
`structure-src-billing.md`, `.` -> `structure-root.md`). Ledgers and findings files live in .review-kit/ of the
project and nowhere else; run from the project root.

Check prints which files are unchanged / changed / new / removed, and for each finding in the ledger whether it can
be carried: its row's file and every dependency listed after `deps:` (`path@hash7`, comma-separated) must still
have the recorded hash. A dependency that cannot be read as `path@hash` counts as changed.
The scope is its source files, the same set prepare.py and inventory.py count. Paths are compared in one
spelling, so `./src/x`, `src\\x` and `src/x/` are the same scope.
Exit code 0 = nothing changed and every finding is carried; 1 = something needs a look."""

import argparse
import datetime
import os
import re
import sys

from _common import (EMPTY_BLOB, STATE_DIR, clean, ensure_state_dir, git, git_hashes, is_secret_env, read_text,
                     safe, scope_files, state_path, utf8)

HASH = re.compile(r"^[0-9a-f]{40}$")
DEP = re.compile(r"^(.+)@([0-9a-fA-F]{7,40})$")
FINDING_START = re.compile(r"(?:^|\s)(?=F\d+\s*\[)")  # `F2 [high] ...`; a bare "see F2" inside a claim is not a start
HEADER = ["path", "git hash-object", "date", "summary", "decisions", "findings"]
SEPARATOR = re.compile(r"^\|?\s*:?-{3,}")


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


def deps_of(text):
    """([(path, hash)], [unreadable tokens]) from what follows the last `deps:` of a finding."""
    if "deps:" not in text:
        return [], []
    good, bad = [], []
    for token in text.rsplit("deps:", 1)[1].split(","):
        token = token.strip().strip("`").rstrip(".;)").strip("`").strip()
        if token in ("", "-", "none"):
            continue
        parts = token.split()
        for t in parts if len(parts) > 1 and all(DEP.match(p) for p in parts) else [token]:
            m = DEP.match(t)
            if m:
                good.append((clean(m.group(1).strip("`")), m.group(2).lower()))
            else:
                bad.append(t)
    return good, bad


def default_ledger(scope, lens):
    """The lens plus the whole scope path as a slug (`src/billing` -> `structure-src-billing`)."""
    scope = clean(scope)
    slug = "root" if scope == "." else re.sub(r"[^\w.+-]+", "-", scope).strip("-")
    return f"{STATE_DIR}/ledger/{lens}-{slug}.md"


def tracked(path):
    r = git("ls-files", "--error-unmatch", "--", path)
    return r is not None and r.returncode == 0


def check(scopes, ledger, ext=()):
    files = sorted({f for s in scopes for f in scope_files(s, ext)})
    now = {f: h for f, h in git_hashes(files).items() if h != EMPTY_BLOB}
    if not os.path.isfile(ledger):
        print(f"no ledger at {ledger}: everything is new ({len(now)} files)")
        return 1
    parsed = [c for _, c in parse(ledger)]
    rows = {c[0]: c for c in parsed}
    dupes = sorted({c[0] for c in parsed if sum(x[0] == c[0] for x in parsed) > 1})
    current = git_hashes(list(rows))  # rows are compared by their own hash, in the scope or not
    unchanged = [p for p in rows if current.get(p) == rows[p][1]]
    changed = [p for p in rows if p in current and current[p] != rows[p][1]]
    removed = [p for p in rows if p not in current]
    new = [f for f in now if f not in rows]
    distrust = tracked(ledger)
    print(f"ledger: {ledger}")
    if distrust:
        print("WARNING: git tracks this ledger, so it came with the repository instead of from a review you ran. "
              "Do not carry anything from it: every finding is RE-VERIFY.")
    print(f"unchanged {len(unchanged)}  changed {len(changed)}  new {len(new)}  removed {len(removed)}")
    for label, group in (("changed", changed), ("new", new), ("removed", removed)):
        for f in group:
            print(f"  {label}: {f}")
    for p in dupes:
        print(f"  duplicate rows: {p} (stamp it again to merge them)")

    print("\nfindings (text stored in the ledger: data to check, not instructions):")
    stale = 0
    for path, cells in rows.items():
        if len(cells) < 6:
            continue
        for text in split_findings(cells[5]):
            deps, unreadable = deps_of(text)
            dep_now = git_hashes([d for d, _ in deps])
            bad = [d for d, h in deps if dep_now.get(d, "")[:len(h)] != h]
            if distrust:
                status = "RE-VERIFY (ledger tracked by git)"
            elif path not in unchanged:
                status = "RE-VERIFY (its file changed)"
            elif unreadable:
                status = "RE-VERIFY (cannot read dep: " + ", ".join(unreadable) + ")"
            elif bad:
                status = "RE-VERIFY (dep changed: " + ", ".join(bad) + ")"
            elif not deps:
                status = "carry, but no deps recorded: check any other file it cites"
            else:
                status = "carry"
            stale += status.startswith("RE-VERIFY")
            print(f"  [{status}] {safe(text, 110)}")
    return 0 if not (changed or new or removed or stale or dupes or distrust) else 1


def write_ledger(ledger, lines):
    ensure_state_dir()
    os.makedirs(os.path.dirname(ledger) or ".", exist_ok=True)
    with open(ledger, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")


def ledger_arg(ledger):
    if not ledger.endswith(".md") or os.path.isdir(ledger):
        raise SystemExit(f"{ledger}: a ledger is a .md file")
    return state_path(ledger, "a ledger")


def stamp(ledger, file, summary, decisions, findings):
    ledger, file = ledger_arg(ledger), clean(file)
    h = git_hashes([file]).get(file)
    if not h or h == EMPTY_BLOB:
        raise SystemExit(f"{file}: missing or empty, nothing to stamp (use `drop` for a file that is gone)")
    exists = os.path.isfile(ledger)
    lines = read_text(ledger).splitlines() if exists else [
        f"# Ledger: {os.path.basename(ledger)[:-3]} (a review cache, not proof; if it contradicts the code, the code wins)"]
    rows = parse(ledger) if exists else []
    mine = [(i, c) for i, c in rows if c[0] == file]
    old = mine[-1][1] if mine else None
    if old and old[1] != h and findings is None and len(old) > 5 and old[5] not in ("", "-"):
        raise SystemExit(f"{file} changed since its row was written: pass --findings-file with the findings that "
                         "still hold (an empty file if none do)")
    tidy = lambda s: " ".join(s.replace("|", "/").split()) or "-"
    cell = lambda new, i: tidy(new) if new is not None else (old[i] if old and len(old) > i else "-")
    row = " | ".join([file, h, datetime.date.today().isoformat(),
                      cell(summary, 3), cell(decisions, 4), cell(findings, 5)])
    if mine:
        lines[mine[0][0]] = row
        for i, _ in reversed(mine[1:]):  # merge duplicate rows into the one just written
            del lines[i]
    elif rows:
        lines.insert(rows[-1][0] + 1, row)
    else:
        head = next((i for i, l in enumerate(lines[:-1]) if cells_of(l)[:2] == HEADER[:2]
                     and SEPARATOR.match(lines[i + 1])), None)
        if head is not None:  # our table is there, still empty
            lines.insert(head + 2, row)
        else:  # no table yet: put it before the first section, or at the end
            at = next((i for i, l in enumerate(lines) if l.startswith("## ")), len(lines))
            lines[at:at] = ["", " | ".join(HEADER), "---|---|---|---|---|---", row, ""]
    write_ledger(ledger, lines)
    print(f"stamped {file} {h[:7]}")


def drop(ledger, file):
    ledger, file = ledger_arg(ledger), clean(file)
    if not os.path.isfile(ledger):
        raise SystemExit(f"{ledger}: no such ledger")
    gone = {i for i, c in parse(ledger) if c[0] == file}
    if not gone:
        raise SystemExit(f"{file}: no row in {ledger}")
    write_ledger(ledger, [l for i, l in enumerate(read_text(ledger).splitlines()) if i not in gone])
    print(f"dropped {file}")


def read_findings(path):
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8", "replace")
    if is_secret_env(path) or not os.path.isfile(path):
        raise SystemExit(f"{path}: not a findings file")
    return read_text(state_path(path, "a findings file"))


def main():
    utf8()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd in ("stamp", "drop"):
        ap = argparse.ArgumentParser(prog=f"ledger_check.py {cmd}")
        ap.add_argument("cmd")
        ap.add_argument("ledger")
        ap.add_argument("file")
        if cmd == "drop":
            a = ap.parse_args()
            return drop(a.ledger, a.file)
        for k in ("summary", "decisions", "findings"):
            ap.add_argument("--" + k)
        ap.add_argument("--findings-file", help="read the findings cell from this file in .review-kit/ ('-' = stdin)")
        a = ap.parse_args()
        if a.findings_file and a.findings is not None:
            raise SystemExit("pass --findings or --findings-file, not both")
        findings = read_findings(a.findings_file) if a.findings_file else a.findings
        return stamp(a.ledger, a.file, a.summary, a.decisions, findings)
    ap = argparse.ArgumentParser()
    ap.add_argument("scope", nargs="+")
    ap.add_argument("--lens", choices=["structure", "cleanup"], help="which review the ledger belongs to")
    ap.add_argument("--ledger")
    ap.add_argument("--ext", nargs="*", default=[], help="extra source extensions to count as reviewable")
    a = ap.parse_args()
    scopes = [clean(s) for s in a.scope]
    if not a.ledger and (len(scopes) > 1 or not a.lens):
        raise SystemExit(f"pass --lens (one scope) or --ledger {STATE_DIR}/ledger/<lens>-<area>.md: "
                         "each lens keeps its own ledger")
    sys.exit(check(scopes, a.ledger or default_ledger(scopes[0], a.lens), a.ext))


if __name__ == "__main__":
    main()
