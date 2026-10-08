"""Dependencies BETWEEN review areas, from the code graph. No LLM, no tokens.

Usage: python cross_areas.py <areas.txt> [--graph graphify-out/graph.json] [--ignore AREA ...] [--top 15]

areas.txt: one area per line, `name: path path ...` (a path is a directory or a file, in double quotes when it
has spaces); a line or a word that starts with `#` begins a comment.
Counts distinct file->file edges from one area to another (calls, imports, references, inheritance), lists the
heaviest pairs with an example, areas that depend on each other in both directions, and the areas the most other
areas depend on. --ignore drops areas such as the entry point (everything imports from it, which is noise).
Static only, and partly resolved by name ([inferred] examples): confirm any pair you act on in the code.
The graph keeps one edge per pair of nodes, so two areas that import each other can show one direction only."""

import argparse
import os
import re
from collections import defaultdict

from _common import clean, load_graph, read_text, safe, under, utf8

TOKEN = re.compile(r'"([^"]*)"|(\S+)')


def parse_areas(path):
    areas = {}
    for n, line in enumerate(read_text(path).splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise SystemExit(f"{path}:{n}: expected `name: path path ...`")
        name, rest = line.split(":", 1)
        name, paths = name.strip(), []
        for quoted, bare in TOKEN.findall(rest):
            if bare.startswith("#"):
                break
            paths.append(clean(quoted or bare))
        if name in areas:
            raise SystemExit(f"{path}:{n}: area `{name}` is defined twice")
        missing = [p for p in paths if not os.path.exists(p)]
        if missing or not paths:
            raise SystemExit(f"{path}:{n}: area `{name}` has " + ("no paths" if not paths else "paths that do not "
                             "exist here: " + ", ".join(missing) + " (paths are relative to the current directory; "
                             "one path per word, in double quotes when it has spaces)"))
        areas[name] = paths
    return areas


def area_of(f, areas):
    best, best_len = None, -1
    for name, paths in areas.items():
        for p in paths:
            n = 0 if p == "." else len(p)
            if under(f, p) and n > best_len:  # the most specific path wins
                best, best_len = name, n
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
    unknown = [x for x in a.ignore if x not in areas]
    if unknown:
        raise SystemExit(f"--ignore {' '.join(unknown)}: no such area (areas: {', '.join(areas)})")
    if not os.path.isfile(a.graph):
        raise SystemExit(f"no graph at {a.graph}: run `graphify update .` first")
    try:
        _, down, files = load_graph(a.graph)
    except ValueError as e:
        raise SystemExit(str(e))
    unmapped = sorted(f for f in files if area_of(f, areas) is None)
    pairs = defaultdict(list)
    for f, targets in down.items():
        fa = area_of(f, areas)
        for g, ex in targets.items():
            ga = area_of(g, areas)
            if fa and ga and fa != ga and fa not in a.ignore and ga not in a.ignore:
                pairs[(fa, ga)].append((f, g, ex))
    print(f"# Cross-area dependencies ({len(areas)} areas, ignoring: {', '.join(a.ignore) or 'none'})")
    if unmapped:
        print(f"WARNING: {len(unmapped)} of {len(files)} files in the graph belong to no area, e.g. "
              f"{safe(unmapped[0])}. Their dependencies are not counted below"
              + (": the areas match nothing in the graph, check the paths." if len(unmapped) == len(files) else "."))
    print("\n## Heaviest pairs (A depends on B: distinct file pairs)")
    for (x, y), v in sorted(pairs.items(), key=lambda kv: -len(kv[1]))[:a.top]:
        f, g, ex = v[0]
        print(f"  {x} -> {y}: {len(v)}   e.g. {safe(f)} -> {safe(g)} ({ex})")
    if not pairs:
        print("  none in the graph")
    both = sorted({tuple(sorted(k)) for k in pairs if (k[1], k[0]) in pairs})
    print("\n## Depend on each other in both directions (candidates for a cycle between areas; may under-report)")
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
    if not fan_in:
        print("  none")


if __name__ == "__main__":
    main()
