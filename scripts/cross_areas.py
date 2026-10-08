"""Dependencies BETWEEN review areas, from the code graph. No LLM, no tokens.

Usage: python cross_areas.py <areas.txt> [--graph graphify-out/graph.json] [--ignore AREA ...] [--top 15]

areas.txt: one area per line, `name: path path ...` (a path is a directory or a file); `#` starts a comment.
Counts distinct file->file edges from one area to another (calls, imports, references, inheritance), lists the
heaviest pairs with an example, areas that depend on each other in both directions, and the areas the most other
areas depend on. --ignore drops areas such as the entry point (everything imports from it, which is noise).
Static only and resolved by name: confirm any pair you act on in the code."""

import argparse
import importlib.util
import os
from collections import defaultdict

from _common import norm, read_text, utf8


def load_build():
    spec = importlib.util.spec_from_file_location("review_kit_trace", os.path.join(os.path.dirname(__file__), "trace.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build


def parse_areas(path):
    areas = {}
    for line in read_text(path).splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" in line:
            name, paths = line.split(":", 1)
            areas[name.strip()] = [norm(p).rstrip("/") for p in paths.split()]
    return areas


def area_of(f, areas):
    best, best_len = None, -1
    for name, paths in areas.items():
        for p in paths:
            if (f == p or f.startswith(p + "/")) and len(p) > best_len:  # the most specific path wins
                best, best_len = name, len(p)
    return best


def main():
    utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("areas")
    ap.add_argument("--graph", default="graphify-out/graph.json")
    ap.add_argument("--ignore", nargs="*", default=[])
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    areas = parse_areas(a.areas)
    if not areas:
        raise SystemExit(f"{a.areas}: no areas")
    if not os.path.isfile(a.graph):
        raise SystemExit(f"no graph at {a.graph}: run `graphify update .` first")
    _, down = load_build()(a.graph)
    pairs, unmapped = defaultdict(list), set()
    for f, targets in down.items():
        fa = area_of(f, areas)
        for g, ex in targets.items():
            ga = area_of(g, areas)
            if fa is None or ga is None:
                unmapped.add(f if fa is None else g)
            elif fa != ga and fa not in a.ignore and ga not in a.ignore:
                pairs[(fa, ga)].append((f, g, ex))
    print(f"# Cross-area dependencies ({len(areas)} areas, ignoring: {', '.join(a.ignore) or 'none'})")
    print("\n## Heaviest pairs (A depends on B: distinct file pairs)")
    for (x, y), v in sorted(pairs.items(), key=lambda kv: -len(kv[1]))[:a.top]:
        f, g, ex = v[0]
        print(f"  {x} -> {y}: {len(v)}   e.g. {f} -> {g} ({ex})")
    both = sorted({tuple(sorted(k)) for k in pairs if (k[1], k[0]) in pairs})
    print("\n## Depend on each other in both directions (candidates for a cycle between areas)")
    for x, y in both:
        print(f"  {x} <-> {y}: {len(pairs[(x, y)])} / {len(pairs[(y, x)])}")
    if not both:
        print("  none")
    fan_in = defaultdict(set)
    for (x, y) in pairs:
        fan_in[y].add(x)
    print("\n## Most depended on (how many other areas import from it)")
    for y, xs in sorted(fan_in.items(), key=lambda kv: -len(kv[1]))[:8]:
        print(f"  {y}: {len(xs)} area(s): {', '.join(sorted(xs))}")
    if unmapped:
        print(f"\n(files in the graph outside every area: {len(unmapped)}, e.g. {sorted(unmapped)[0]})")


if __name__ == "__main__":
    main()
