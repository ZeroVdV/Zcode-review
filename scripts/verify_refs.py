"""Check that the file:line citations in a review report point at something real. No LLM, no tokens.

Usage: python verify_refs.py <report.md>

For each `path:line` or `path:start-end`: the file must exist (a partial path or bare file name is resolved
against the files git knows; ambiguous names pass if any candidate fits) and the line must be inside the file:
at least 1, a range in order, not past the end.
Code-looking spans (containing ( = [ or {) in backticks on the same report line are looked up in the cited
file(s); one that is not found is only a WARN (the report may paraphrase).
A citation written in a shape that cannot be checked (`path:L10`, `path#L10`, `path (line 10)`, a path outside
the project) is listed as UNCHECKED: rewrite it as `path:line`.
Exit code 1 if any citation is BAD, or if nothing could be checked while UNCHECKED ones exist.
Catches invented or stale references; it cannot tell whether the finding is right."""

import os
import re
import sys

from _common import SOURCE_EXT, clean, git_files, norm, read_text, safe, utf8

CODE_EXT = SOURCE_EXT | {"md", "rst", "txt", "json", "yml", "yaml", "toml", "cfg", "ini", "xml"}
NO_EXT = r"Dockerfile|Makefile|Gemfile|Rakefile|Procfile|Jenkinsfile|Vagrantfile|Justfile"
# a path part may hold [ ] ( ) @ +, as in route folders such as `[id]` or `(group)`
PART = r"[\w.@+()\[\]-]+"
PATH = r"(?:[A-Za-z]:)?[/\\]?(?:" + PART + r"[/\\])*"
CITE = re.compile(r"(?<![\w.@+()\[\]/\\:-])(" + PATH + r"(?:" + PART + r"\.([A-Za-z0-9]{1,7})|" + NO_EXT + r"))"
                  r":(\d+)(?:[-–](\d+))?")
LOOSE = re.compile(r"(" + PATH + PART + r"\.[A-Za-z0-9]{1,7})(?::L|#L|\s*\(lines?\s+)\d+")
SPAN = re.compile(r"`([^`\n]+)`")
CODEISH = re.compile(r"[(=\[{]")
URL = re.compile(r"\w+://\S*$")
ABSOLUTE = re.compile(r"(?:[A-Za-z]:)?[/\\]")  # also a POSIX path seen on Windows, and the other way round
PATHLIKE = re.compile(PATH + PART)


def known_files():
    return [norm(f) for f in git_files(".") or [] if os.path.isfile(f)]


def resolve(path, files):
    """Files the cited path may mean. Wrapping that came with the match is dropped when the path does not resolve
    with it: an opening bracket as in `(src/jobs.py:3)`, a markdown link's `[text](`, emphasis marks."""
    p = clean(path)
    low = {f.lower(): f for f in files}
    while True:
        hits = [f for f in files if f == p or f.endswith("/" + p)]
        if not hits and os.name == "nt" and p.lower() in low:  # the file system does not tell case apart
            hits = [low[p.lower()]]
        if hits:
            return hits
        if p and p[0] in "_*([":
            p = p[1:]
            continue
        cut = min((i for i in (p.find("("), p.find("[")) if i > 0), default=-1)
        if cut < 0 or p[cut - 1] != "]":  # only a link's `](` may sit in front of a path
            return []
        p = p[cut + 1:]


def main():
    utf8()
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    report = sys.argv[1]
    files = known_files()
    cache = {}

    def content(f):
        if f not in cache:
            cache[f] = read_text(f)
        return cache[f]

    ok = bad = warn = 0
    problems, unchecked = [], []
    for n, line in enumerate(read_text(report).splitlines(), 1):
        cited, spans = [], set()
        for m in CITE.finditer(line):
            path, ext, a, b = m.group(1), (m.group(2) or "").lower(), int(m.group(3)), m.group(4)
            if URL.search(line[:m.start()]) or "://" in path:
                continue
            spans.add(m.span())
            end = int(b) if b else a
            where = f"{safe(path, 80)}:{a}{'-' + b if b else ''}"
            cands = resolve(path, files)
            if not cands and ABSOLUTE.match(path):
                unchecked.append(f"  UNCHECKED report:{n}  {where}  outside this project: cite a relative path")
                continue
            if not cands and ext and ext not in CODE_EXT and "/" not in norm(path):
                continue  # `example.com:443`, `v1.2.3:4`: not a file
            if a < 1 or end < a:
                bad += 1
                problems.append(f"  BAD  report:{n}  {where}  not a line or range (lines start at 1)")
            elif not cands:
                bad += 1
                problems.append(f"  BAD  report:{n}  {where}  file not found")
            else:
                fits = [f for f in cands if end <= content(f).count("\n") + (0 if content(f).endswith("\n") else 1)]
                if not fits:
                    bad += 1
                    problems.append(f"  BAD  report:{n}  {where}  past the end of {', '.join(cands)}")
                else:
                    ok += 1
                    cited += fits
        for m in LOOSE.finditer(line):
            if not any(s <= m.start() < e for s, e in spans):
                unchecked.append(f"  UNCHECKED report:{n}  {safe(m.group(0), 80)}  write it as path:line")
        if cited:
            blob = " ".join(" ".join(content(f).split()) for f in set(cited))
            for span in SPAN.findall(line):
                s = " ".join(span.split())
                if (len(s) < 10 or len(s) > 120 or not CODEISH.search(s) or CITE.search(s) or s.startswith("[")
                        or PATHLIKE.fullmatch(s)):
                    continue  # only code-looking spans: a bare name or a path may live in another file
                if s not in blob:
                    warn += 1
                    problems.append(f"  WARN report:{n}  `{safe(s, 70)}` not found in the cited file(s)")
    print(f"{report}: {ok} ok, {bad} bad, {warn} warn, {len(unchecked)} unchecked")
    print("\n".join(problems + unchecked))
    if not ok and not bad:
        print("WARNING: no citation was checked. A report with findings cites `path:line` for each one.")
    sys.exit(1 if bad or (unchecked and not ok) else 0)


if __name__ == "__main__":
    main()
