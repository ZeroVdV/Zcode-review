"""Who depends on a file (up) and what it depends on (down), from a graphify graph.json. No LLM, no tokens.

Usage: python trace.py <file> [--hops 2] [--dir up|down|both] [--graph graphify-out/graph.json]
                       [--entry main.py ...] [--max 40] [--extracted-only]

Works at file level: an edge between two nodes in different files becomes a file->file edge.
Files given in --entry are entry points: the walk reaches them and stops there.
Edges the graph only inferred by name are tagged [inferred]: a call can be matched to a same-named function
in an unrelated file. --extracted-only leaves them out. Confirm any edge you act on in the code.
Static only: dynamic dispatch, string lookups and reflection are invisible, so "no callers"
means "no callers in the graph", not "dead". Confirm in the code before removing anything.
Known blind spots: the graph keeps one edge per pair of nodes, so of two files that import each other only one
direction may show; a module imported as a whole (`import pkg` then `pkg.run()`), Go packages without go.mod,
Rust `mod`/`use crate::` and Ruby `require_relative` may have no edge at all. Use grep when the answer matters."""

import argparse
import json
import os
import sys
from collections import defaultdict, deque

from _common import clean, safe, utf8

REL = {"calls", "imports", "imports_from", "references", "uses", "inherits", "indirect_call",
       "implements", "extends", "mixes_in", "re_exports", "dynamic_import"}


def norm(p):
    p = (p or "").replace("\\", "/")
    return p[2:] if p.startswith("./") else p


def build(path, extracted_only=False):
    """(up, down, files): file -> {other file: example edge}, and every file the graph knows."""
    try:
        with open(path, encoding="utf-8") as f:
            g = json.load(f)
        nodes = {n["id"]: n for n in g["nodes"]}
        links = g.get("links") or g.get("edges") or []
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as e:
        raise ValueError(f"cannot read the graph at {path} ({type(e).__name__}): run `graphify update .` again")
    files = {norm(n.get("source_file")) for n in nodes.values() if isinstance(n, dict)} - {""}
    up, down, guessed = defaultdict(dict), defaultdict(dict), set()
    for e in links:
        # decorator edges resolve `@router.post` to any function named post() by name: pure noise
        if not isinstance(e, dict) or e.get("relation") not in REL or e.get("context") == "decorator":
            continue
        inferred = str(e.get("confidence", "")).upper() == "INFERRED"
        if inferred and extracted_only:
            continue
        a, b = nodes.get(e.get("source")), nodes.get(e.get("target"))
        if not a or not b:
            continue
        fa, fb = norm(a.get("source_file")), norm(b.get("source_file"))
        if not fa or not fb or fa == fb:
            continue
        if fb in down[fa] and not ((fa, fb) in guessed and not inferred):
            continue  # keep the first example, unless a real edge can replace a guessed one
        where = str(e.get("source_location") or "").lstrip("L")
        ex = safe(f'{e["relation"]} {b.get("label", "?")} @ {fa}:{where}', 120) + (" [inferred]" if inferred else "")
        down[fa][fb] = up[fb][fa] = ex
        (guessed.add if inferred else guessed.discard)((fa, fb))
    return up, down, files


def walk(start, adj, hops, entries, cap):
    seen, out, q = {start}, [], deque([(start, 0)])
    while q and len(out) < cap:
        cur, d = q.popleft()
        if d == hops:
            continue
        for nxt, ex in sorted(adj.get(cur, {}).items()):
            if nxt in seen:
                continue
            seen.add(nxt)
            tag = "  [entrypoint]" if nxt in entries else ""
            out.append(f"  hop{d + 1}  {nxt}{tag}   ({ex})")
            if nxt not in entries:
                q.append((nxt, d + 1))
            if len(out) >= cap:
                break
    return out, len(out) >= cap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--hops", type=int, default=2)
    ap.add_argument("--dir", choices=["up", "down", "both"], default="both")
    ap.add_argument("--graph", default="graphify-out/graph.json")
    ap.add_argument("--entry", nargs="*", default=[])
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--extracted-only", action="store_true", help="leave out edges the graph inferred by name")
    a = ap.parse_args()
    utf8()
    if a.hops < 1 or a.max < 1:
        sys.exit("--hops and --max must be at least 1")
    if not os.path.isfile(a.graph):
        sys.exit(f"no graph at {a.graph}: run `graphify update .` first, or trace with grep")
    try:
        up, down, files = build(a.graph, a.extracted_only)
    except ValueError as e:
        sys.exit(str(e))
    f, entries = clean(a.file), {clean(e) for e in a.entry}
    if f not in files:
        sys.exit(f"{f}: not in the graph (wrong path, or a file the graph did not parse). Paths are relative to "
                 "the repo root. Use grep instead.")
    for name, adj in (("UP (who depends on it)", up), ("DOWN (what it depends on)", down)):
        if a.dir in ("both", name.split()[0].lower()):
            rows, cut = walk(f, adj, a.hops, entries, a.max)
            print(f"{name} - {f}, up to {a.hops} hops")
            print("\n".join(rows) if rows else "  none in the graph (static only: not proof of dead code)")
            if cut:
                print(f"  ... cut at {a.max}; narrow with --hops 1 or a deeper file")


if __name__ == "__main__":
    main()
