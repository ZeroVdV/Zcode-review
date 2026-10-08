"""Inventory of a project, to split a whole-project review among agents. No LLM, no tokens.

Usage: python inventory.py [root] [--depth 2] [--cap 3000] [--exclude GLOB ...] [--ext EXT ...] [--top 8]

Counts reviewable source lines per directory (docs, config, lock files, generated and binary files are
listed apart, not counted), shows the tree down to --depth, the languages, the largest files, and proposes
areas: a directory that fits under --cap lines is one area; a bigger one is split by its subdirectories;
small neighbours are packed together up to the cap. A directory with no subdirectories that is still over
the cap is flagged OVERSIZE: it needs a split by files, decided by whoever plans the work.

The proposal ends with lines `name: path path ...` (a path is a directory or a file): paste them, edited, into
.claude/state/review/areas.txt, the format cross_areas.py reads. It is a hint made from sizes only; the
planner is expected to adjust it by what the names say (a service stays whole, tests apart, and so on)."""

import argparse
import fnmatch
import os
import re
from collections import Counter, defaultdict

from _common import EXCLUDE_GLOBS, SKIP_EXT, all_files, count_lines, is_source, utf8

TESTS = re.compile(r"(^|/)(tests?|__tests__|spec|specs)(/|$)|(^|/)test_[^/]*$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$", re.I)
MIGRATIONS = re.compile(r"(^|/)(migrations?|alembic)(/|$)", re.I)


def classify(path, extra=()):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if "." + ext in SKIP_EXT:
        return "binary"
    if not is_source(path, extra):
        return "docs" if ext in {"md", "rst", "txt"} else "other"
    if MIGRATIONS.search(path):
        return "migrations"
    return "tests" if TESTS.search(path) else "code"


class Node:
    def __init__(self, path):
        self.path, self.lines, self.files, self.kids, self.own = path, 0, 0, {}, []  # own = (file, lines) directly here


def build_tree(rows):
    root = Node("")
    for f, n in rows:
        node, parts = root, f.split("/")
        node.lines += n; node.files += 1
        for i, p in enumerate(parts[:-1]):
            node = node.kids.setdefault(p, Node("/".join(parts[:i + 1])))
            node.lines += n; node.files += 1
        node.own.append((f, n))
    return root


def split(node, cap, soft=1.25):
    """[(paths, lines, files, oversize)] for this node. A directory up to cap*soft lines stays whole; a bigger one
    is split by its subdirectories; only siblings (same parent) are packed together."""
    if node.lines <= cap * soft or not node.kids:
        return [([node.path or "."], node.lines, node.files, node.lines > cap * soft)]
    small, finals = [], []
    if node.own:
        small.append(([f for f, _ in node.own], sum(n for _, n in node.own), len(node.own), False))
    for name in sorted(node.kids):
        kid = node.kids[name]
        if kid.lines <= cap * soft or not kid.kids:
            small.append(([kid.path], kid.lines, kid.files, kid.lines > cap * soft))
        else:
            finals += split(kid, cap, soft)
    packed, cur = [], None
    for p in small:
        if p[3] or p[1] >= cap * 0.6:
            packed.append(p)
        elif cur and cur[1] + p[1] <= cap:
            cur = (cur[0] + p[0], cur[1] + p[1], cur[2] + p[2], False)
        else:
            if cur:
                packed.append(cur)
            cur = p
    if cur:
        packed.append(cur)
    return packed + finals


def area_name(paths, used):
    parents = {os.path.dirname(p.rstrip("/")) for p in paths}
    files_only = all("." in os.path.basename(p) for p in paths)
    if paths == ["."]:
        base = "root"
    elif len(paths) == 1 and not files_only:
        base = paths[0].strip("/")
    else:
        parent = parents.pop() if len(parents) == 1 else os.path.commonpath([p.rstrip("/") for p in paths] or ["."])
        base = (parent or "root") + ("-files" if files_only and len(parents) == 0 else "") + (f"+{len(paths)}" if not files_only else "")
    base = re.sub(r"[^A-Za-z0-9_+.-]", "-", base.replace("/", "-"))[:40] or "root"
    name, i = base, 2
    while name in used:
        name, i = f"{base}-{i}", i + 1
    used.add(name)
    return name


def main():
    utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--cap", type=int, default=3000)
    ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--ext", nargs="*", default=[], help="extra source extensions to count as reviewable")
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()
    os.chdir(a.root)
    excl = EXCLUDE_GLOBS + a.exclude
    kinds, rows, big = defaultdict(lambda: [0, 0]), [], []
    for f in all_files("."):
        if any(fnmatch.fnmatch(f, p) for p in excl):
            continue
        k = classify(f, a.ext)
        n = count_lines(f)
        kinds[k][0] += 1; kinds[k][1] += n
        if k in ("code", "tests", "migrations"):
            rows.append((f, n))
    root = build_tree(rows)
    print(f"# Inventory: {os.getcwd()}")
    print("\n## Totals")
    for k in ("code", "tests", "migrations", "docs", "other", "binary"):
        if k in kinds:
            print(f"  {k:11s} {kinds[k][0]:5d} files {kinds[k][1]:8d} lines" + ("" if k in ("code", "tests", "migrations") else "  (not reviewed)"))
    langs = Counter()
    for f, n in rows:
        langs[os.path.splitext(f)[1].lower()] += n
    print("  languages: " + ", ".join(f"{e or '(none)'} {n}" for e, n in langs.most_common(8)))

    print(f"\n## Tree (reviewable lines, depth {a.depth})")
    def show(node, depth):
        for name in sorted(node.kids, key=lambda k: -node.kids[k].lines):
            k = node.kids[name]
            print(f"  {'  ' * depth}{name}/  {k.lines} lines, {k.files} files")
            if depth + 1 < a.depth:
                show(k, depth + 1)
    show(root, 0)
    if root.own:
        print(f"  (files at the root: {len(root.own)}, {sum(n for _, n in root.own)} lines)")

    print(f"\n## Largest files")
    for f, n in sorted(rows, key=lambda x: -x[1])[:a.top]:
        print(f"  {n:5d}  {f}")

    print(f"\n## Proposed areas (cap {a.cap} lines per area, sizes only)")
    used, lines_out = set(), []
    for paths, ln, nf, over in split(root, a.cap):
        name = area_name(paths, used)
        flag = "  OVERSIZE: split by files" if over else ""
        print(f"  {name:32s} {ln:6d} lines {nf:4d} files{flag}")
        lines_out.append(f"{name}: " + " ".join(paths))
    print("\n## areas.txt format (edit, then save to .claude/state/review/areas.txt)")
    print("\n".join(lines_out))


if __name__ == "__main__":
    main()
