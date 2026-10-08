"""Check that the file:line citations in a review report point at something real. No LLM, no tokens.

Usage: python verify_refs.py <report.md>

For each `path:line` or `path:start-end`: the file must exist (a partial path or bare file name is resolved
against the files git knows; ambiguous names pass if any candidate fits) and the line must be inside the file.
Code-looking spans (containing ( = [ or {) in backticks on the same report line are looked up in the cited
file(s); one that is not found is only a WARN (the report may paraphrase). Exit code 1 if any citation is BAD.
Catches invented or stale references; it cannot tell whether the finding is right."""

import re
import subprocess
import sys

from _common import norm, read_text, utf8

CODE_EXT = {"py", "js", "ts", "tsx", "jsx", "go", "rs", "java", "rb", "php", "md", "sql", "json", "yml", "yaml",
            "toml", "sh", "html", "css", "cs", "kt", "swift", "c", "h", "cpp", "txt", "cfg", "ini"}
CITE = re.compile(r"(?<![\w./\\-])((?:[\w.-]+[/\\])*[\w.-]+\.([A-Za-z0-9]{1,5})):(\d+)(?:-(\d+))?")
SPAN = re.compile(r"`([^`\n]+)`")
CODEISH = re.compile(r"[(=\[{]")


def known_files():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, encoding="utf-8").stdout.split("\n")
    return [norm(f) for f in out if f]


def resolve(path, files):
    p = norm(path)
    return [f for f in files if f == p or f.endswith("/" + p)]


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
    problems = []
    for n, line in enumerate(read_text(report).splitlines(), 1):
        cited = []
        for m in CITE.finditer(line):
            path, ext, a, b = m.group(1), m.group(2).lower(), int(m.group(3)), m.group(4)
            if ext not in CODE_EXT:
                continue
            end = int(b) if b else a
            cands = resolve(path, files)
            if not cands:
                bad += 1
                problems.append(f"  BAD  report:{n}  {path}:{a}  file not found")
                continue
            fits = [f for f in cands if end <= content(f).count("\n") + (0 if content(f).endswith("\n") else 1)]
            if not fits:
                bad += 1
                problems.append(f"  BAD  report:{n}  {path}:{a}{'-' + b if b else ''}  past the end of {', '.join(cands)}")
                continue
            ok += 1
            cited += fits
        if cited:
            blob = " ".join(" ".join(content(f).split()) for f in set(cited))
            for span in SPAN.findall(line):
                s = " ".join(span.split())
                if len(s) < 10 or len(s) > 120 or not CODEISH.search(s) or CITE.fullmatch(s) or s.startswith("["):
                    continue  # only code-looking spans: a bare name may live in another file
                if s not in blob:
                    warn += 1
                    problems.append(f"  WARN report:{n}  `{s[:70]}` not found in the cited file(s)")
    print(f"{report}: {ok} ok, {bad} bad, {warn} warn")
    print("\n".join(problems))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
