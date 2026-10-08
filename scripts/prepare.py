"""Briefing for a review scope, from facts a script can get exactly. No LLM, no tokens.

Usage: python prepare.py <scope> [<scope> ...] [--graph graphify-out/graph.json] [--env-example .env.example]
                         [--markers EXTRA ...]

Prints: size of the scope, graph freshness, who depends on the scope from outside and what it depends
on outside, deferral markers (TODO/FIXME/HACK/XXX plus any --markers you pass), env vars read vs documented in the example
env file, and long SQL strings repeated in more than one place (Python only).
Never reads the real .env. Static only: confirm every item in the code."""

import argparse
import ast
import importlib.util
import os
import re
import subprocess
from collections import defaultdict

from _common import norm, read_text, scope_files, utf8

DEFAULT_MARKERS = ["TODO", "FIXME", "HACK", "XXX"]
ENV_USE = [re.compile(p) for p in (
    r"os\.environ\.get\(\s*[\"']([A-Z][A-Z0-9_]*)", r"os\.environ\[\s*[\"']([A-Z][A-Z0-9_]*)",
    r"os\.getenv\(\s*[\"']([A-Z][A-Z0-9_]*)", r"process\.env\.([A-Z][A-Z0-9_]*)", r"process\.env\[\s*[\"']([A-Z][A-Z0-9_]*)",
)]
ENV_DEF = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=")
SQL_START = re.compile(r"^\s*(select|insert|update|delete|with)\b", re.I)


def load_trace_build():
    """trace.py shadows the stdlib name `trace`, so load it by path."""
    spec = importlib.util.spec_from_file_location("review_kit_trace", os.path.join(os.path.dirname(__file__), "trace.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build


def section(title):
    print(f"\n## {title}")


def show_scope(files):
    section("Scope")
    sizes = {f: read_text(f).count("\n") for f in files}
    print(f"{len(files)} files, {sum(sizes.values())} lines")
    for f, n in sorted(sizes.items(), key=lambda x: -x[1])[:5]:
        print(f"  {n:5d}  {f}")
    empty = [f for f, n in sizes.items() if os.path.getsize(f) == 0]
    if empty:
        print("  empty (ignore): " + ", ".join(empty))


def show_graph(files, graph, scope_set):
    section("Graph")
    if not os.path.isfile(graph):
        print(f"no graph at {graph}: reach via grep only")
        return None
    newest = max(os.path.getmtime(f) for f in files)
    if os.path.getmtime(graph) < newest:
        print(f"STALE: {graph} is older than the newest file in scope. Run `graphify update .` (no LLM) before trusting reach.")
    else:
        print("fresh (newer than every file in scope)")
    up, down = load_trace_build()(graph)
    for name, adj in (("used by (outside the scope)", up), ("depends on (outside the scope)", down)):
        by_dir = defaultdict(set)
        for f in files:
            for other in adj.get(f, {}):
                if other not in scope_set:
                    by_dir[os.path.dirname(other) or "."].add(other)
        print(f"{name}:" + ("" if by_dir else " none in the graph"))
        for d, fs in sorted(by_dir.items(), key=lambda x: -len(x[1]))[:12]:
            print(f"  {d}: {len(fs)} file(s) " + ", ".join(sorted(os.path.basename(x) for x in fs)[:6]))
    return graph


def show_markers(files, extra):
    section("Deferral markers (candidates for the Deferred section)")
    marker = re.compile("(" + "|".join(re.escape(m) for m in DEFAULT_MARKERS + list(extra)) + ")")
    n = 0
    for f in files:
        for i, line in enumerate(read_text(f).splitlines(), 1):
            if marker.search(line):
                print(f"{f}:{i}  {line.strip()[:160]}")
                n += 1
    if not n:
        print("none")


def show_env(files, example):
    section("Env vars read in scope")
    uses = defaultdict(list)
    for f in files:
        for i, line in enumerate(read_text(f).splitlines(), 1):
            for pat in ENV_USE:
                for m in pat.finditer(line):
                    uses[m.group(1)].append(f"{f}:{i}")
    if not uses:
        print("none")
        return
    ex = example if example and os.path.isfile(example) else next(
        (c for c in (".env.example", ".env.sample", "env.example") if os.path.isfile(c)), None)
    documented = {m.group(1) for line in read_text(ex).splitlines() if (m := ENV_DEF.match(line))} if ex else set()
    print(f"example file: {ex or 'none found'}")
    for name, locs in sorted(uses.items()):
        tag = "documented" if name in documented else "NOT in example file -> [needs-env-review]"
        print(f"  {name}  {tag}  ({locs[0]}{' +%d' % (len(locs) - 1) if len(locs) > 1 else ''})")


def show_repeated_sql(files):
    section("Long SQL strings repeated in more than one place (Python files tracked by git)")
    tracked = subprocess.run(["git", "ls-files", "*.py"], capture_output=True, text=True, encoding="utf-8").stdout.split()
    seen = defaultdict(list)
    for f in tracked:
        try:
            tree = ast.parse(read_text(f))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) >= 60 and SQL_START.match(node.value):
                seen[" ".join(node.value.lower().split())].append(f"{norm(f)}:{node.lineno}")
    scope_set = set(files)
    hits = [(k, v) for k, v in seen.items() if len(set(v)) > 1 and any(x.rsplit(":", 1)[0] in scope_set for x in v)]
    if not hits:
        print("none")
    for k, v in hits[:10]:
        print(f"  {k[:90]}...\n    " + "\n    ".join(sorted(set(v))))
    print("(whole-string match only: a similar query with another column or filter will not show up here)")


def main():
    utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("scope", nargs="+", help="one or more directories or files")
    ap.add_argument("--graph", default="graphify-out/graph.json")
    ap.add_argument("--env-example", default="")
    ap.add_argument("--markers", nargs="*", default=[], help="extra literal markers, e.g. a project-specific tag")
    a = ap.parse_args()
    files = sorted({f for s in a.scope for f in scope_files(s)})
    if not files:
        raise SystemExit(f"{a.scope}: no files")
    print(f"# Briefing: {' '.join(norm(s) for s in a.scope)}")
    show_scope(files)
    show_graph(files, a.graph, set(files))
    show_markers(files, a.markers)
    show_env(files, a.env_example)
    show_repeated_sql(files)


if __name__ == "__main__":
    main()
