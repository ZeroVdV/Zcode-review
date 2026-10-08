"""Who depends on a file (up) and what it depends on (down), from a graphify graph.json. No LLM, no tokens.

Usage: python trace.py <file> [--hops 2] [--dir up|down|both] [--graph graphify-out/graph.json]
                       [--entry main.py ...] [--max 40]

Works at file level: an edge between two nodes in different files becomes a file->file edge.
Files given in --entry are entry points: the walk reaches them and stops there.
Edges are resolved by name, so a call can be matched to a same-named function elsewhere: confirm in the code.
Static only: dynamic dispatch, string lookups and reflection are invisible, so "no callers"
means "no callers in the graph", not "dead". Confirm in the code before removing anything."""

import argparse
import json
import sys
from collections import defaultdict, deque

REL = {"calls", "imports", "imports_from", "references", "uses", "inherits", "indirect_call"}


def norm(p):
    p = (p or "").replace("\\", "/")
    return p[2:] if p.startswith("./") else p


def build(path):
    g = json.load(open(path, encoding="utf-8"))
    nodes = {n["id"]: n for n in g["nodes"]}
    up, down = defaultdict(dict), defaultdict(dict)  # file -> {other file: example}
    for e in g.get("links") or g.get("edges") or []:
        # decorator edges resolve `@router.post` to any function named post() by name: pure noise
        if e.get("relation") not in REL or e.get("context") == "decorator":
            continue
        a, b = nodes.get(e["source"]), nodes.get(e["target"])
        if not a or not b:
            continue
        fa, fb = norm(a.get("source_file")), norm(b.get("source_file"))
        if not fa or not fb or fa == fb:
            continue
        ex = f'{e["relation"]} {b.get("label", "?")} @ {fa}:{(e.get("source_location") or "").lstrip("L")}'
        down[fa].setdefault(fb, ex)
        up[fb].setdefault(fa, ex)
    return up, down


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
    a = ap.parse_args()
    up, down = build(a.graph)
    f, entries = norm(a.file), {norm(e) for e in a.entry}
    if f not in up and f not in down:
        sys.exit(f"{f}: not in the graph (wrong path, or no cross-file edges). Paths are relative to the repo root.")
    for name, adj in (("UP (who depends on it)", up), ("DOWN (what it depends on)", down)):
        if a.dir in ("both", name.split()[0].lower()):
            rows, cut = walk(f, adj, a.hops, entries, a.max)
            print(f"{name} - {f}, up to {a.hops} hops")
            print("\n".join(rows) if rows else "  none in the graph (static only: not proof of dead code)")
            if cut:
                print(f"  ... cut at {a.max}; narrow with --hops 1 or a deeper file")


if __name__ == "__main__":
    main()
