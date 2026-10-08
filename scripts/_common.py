"""Helpers shared by the review-kit scripts. Stdlib only, no LLM."""

import fnmatch
import os
import posixpath
import subprocess
import sys

# never reviewed, wherever they are: tool state and dependency folders
ALWAYS_SKIP = {".git", ".claude", "graphify-out", "node_modules", "__pycache__"}
# also skipped when git cannot say what is ignored (not a repository)
IGNORE_DIRS = ALWAYS_SKIP | {".venv", "venv", "dist", "build", ".mypy_cache", ".pytest_cache"}
SKIP_EXT = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff", ".woff2", ".ttf", ".exe", ".so", ".dll", ".lock"}
SOURCE_EXT = {"py", "js", "ts", "tsx", "jsx", "mjs", "cjs", "go", "rs", "java", "rb", "php", "cs", "kt", "swift",
              "c", "h", "cpp", "hpp", "cc", "hh", "m", "mm", "sql", "sh", "ps1", "vue", "svelte", "astro", "scala",
              "dart", "ex", "exs", "erl", "lua", "r", "pl", "pm", "fs", "clj", "hs", "ml", "zig", "groovy",
              "html", "css", "scss", "tf", "proto", "graphql"}
EXCLUDE_GLOBS = ["*.lock", "*-lock.json", "*.min.*", "*.map", "*_pb2.py", "*.generated.*", "*.gen.*"]
ENV_EXAMPLE_SUFFIX = (".example", ".sample", ".template", ".dist", ".defaults")
EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def norm(p):
    return p.replace("\\", "/")


def clean(p):
    """One spelling per path: '/' separators, relative to the current directory, no './' and no trailing '/'."""
    p = norm(p.strip())
    if os.path.isabs(p):
        try:
            rel = norm(os.path.relpath(p))
            p = p if rel.startswith("..") else rel
        except ValueError:  # another drive
            pass
    return posixpath.normpath(p) if p else "."


def under(path, scope):
    """True when `path` is `scope` or inside it (both already clean)."""
    return scope == "." or path == scope or path.startswith(scope + "/")


def is_secret_env(path):
    """A real env file (.env, .env.local, prod.env): never read. Example files (.env.example) are fine."""
    name = posixpath.basename(norm(path)).lower()
    if name.endswith(ENV_EXAMPLE_SUFFIX) or name.startswith(("env.", "example.", "sample.")):
        return False
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def is_source(path, ext=()):
    """Reviewable source: a known (or passed) extension, and not generated, minified or a lock file."""
    e = os.path.splitext(path)[1].lower().lstrip(".")
    if e not in SOURCE_EXT and e not in {x.lower().lstrip(".") for x in ext}:
        return False
    return not any(fnmatch.fnmatch(path, g) for g in EXCLUDE_GLOBS)


def git_files(scope="."):
    """Files git tracks or would track under `scope` (respects .gitignore), or None outside a repository."""
    r = subprocess.run(["git", "--literal-pathspecs", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                        "--", scope], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not r.stdout:
        return None
    return [f for f in r.stdout.split("\0") if f]


def all_files(scope="."):
    """Every file under `scope` that exists and may be read: clean paths, no tool state, no real env files."""
    scope = clean(scope)
    if os.path.isfile(scope):
        return [] if is_secret_env(scope) else [scope]
    found = git_files(scope)
    skip = ALWAYS_SKIP
    if found is None:
        found, skip = [], IGNORE_DIRS
        for d, dirs, files in os.walk(scope):
            dirs[:] = [x for x in dirs if x not in skip]
            found += [os.path.join(d, f) for f in files]
    out = set()
    for f in found:
        f = clean(f)
        if os.path.isfile(f) and not skip.intersection(f.split("/")[:-1]) and not is_secret_env(f):
            out.add(f)
    return sorted(out)


def scope_files(scope, ext=()):
    """Reviewable source files under `scope` (a file or a directory). A file named directly is taken as is."""
    scope = clean(scope)
    if os.path.isfile(scope):
        return all_files(scope)
    return [f for f in all_files(scope) if is_source(f, ext)]


def count_lines(path):
    with open(path, "rb") as f:
        data = f.read()
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def git_hashes(paths):
    """{path: git blob hash}; one git call for all paths. Missing files are left out."""
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        return {}
    r = subprocess.run(["git", "hash-object", "--stdin-paths"], input="\n".join(paths) + "\n",
                       capture_output=True, text=True, encoding="utf-8", check=True)
    return dict(zip(paths, r.stdout.split()))


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()
