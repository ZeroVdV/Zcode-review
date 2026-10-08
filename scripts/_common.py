"""Helpers shared by the review-kit scripts. Stdlib only, no LLM."""

import fnmatch
import importlib.util
import os
import posixpath
import re
import subprocess
import sys

STATE_DIR = ".review-kit"  # reports, ledgers and working files of the project being reviewed
# never reviewed, wherever they are: tool state and dependency folders
ALWAYS_SKIP = {".git", ".claude", STATE_DIR, "graphify-out", "node_modules", "__pycache__"}
# also skipped when git cannot say what is ignored (not a repository)
IGNORE_DIRS = ALWAYS_SKIP | {".venv", "venv", "env", ".env", "dist", "build", "target", "coverage", ".next", ".tox",
                             ".mypy_cache", ".pytest_cache"}
SKIP_EXT = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff", ".woff2", ".ttf", ".exe", ".so", ".dll", ".lock"}
SOURCE_EXT = {"py", "js", "ts", "tsx", "jsx", "mjs", "cjs", "go", "rs", "java", "rb", "php", "cs", "kt", "swift",
              "c", "h", "cpp", "hpp", "cc", "hh", "m", "mm", "sql", "sh", "ps1", "vue", "svelte", "astro", "scala",
              "dart", "ex", "exs", "erl", "lua", "r", "pl", "pm", "fs", "clj", "hs", "ml", "zig", "groovy",
              "html", "css", "scss", "tf", "proto", "graphql"}
EXCLUDE_GLOBS = ["*.lock", "*-lock.json", "*.min.*", "*.map", "*_pb2.py", "*.generated.*", "*.gen.*"]
ENV_EXAMPLE = re.compile(r"\.(example|sample|template|tpl|dist|defaults|schema)$|^(example|sample|template)\.env$")
ENV_SECRET = re.compile(r"(^|[._-])env([._~-]|$)|^\.(envrc|flaskenv)$")
EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
MAX_BYTES = 2_000_000  # bigger files are listed, never scanned line by line


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


def safe(text, limit=160):
    """Text taken from the project, made safe to print on one line: no control characters, cut at `limit`."""
    text = "".join(c if c.isprintable() else " " for c in text).strip()
    return text if len(text) <= limit else text[:limit - 3] + "..."


def is_secret_env(path):
    """A real env file (.env, .env.local, prod.env, .envrc): never read. Example files and source code are fine."""
    name = posixpath.basename(norm(path)).lower()
    if ENV_EXAMPLE.search(name):
        return False
    if not name.startswith(".env") and os.path.splitext(name)[1].lstrip(".") in SOURCE_EXT:
        return False  # env.py, env.d.ts: code about the environment, not the environment
    return bool(ENV_SECRET.search(name))


def is_source(path, ext=()):
    """Reviewable source: a known (or passed) extension, and not generated, minified or a lock file."""
    e = os.path.splitext(path)[1].lower().lstrip(".")
    if e not in SOURCE_EXT and e not in {x.lower().lstrip(".") for x in ext}:
        return False
    return not any(fnmatch.fnmatch(path, g) for g in EXCLUDE_GLOBS)


def git(*args, **kw):
    """Run git; None when git is not installed."""
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    except FileNotFoundError:
        return None


def git_files(scope="."):
    """Files git tracks or would track under `scope` (respects .gitignore); None when git cannot answer."""
    r = git("--literal-pathspecs", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", scope)
    if r is None or r.returncode != 0:
        return None
    return [f for f in r.stdout.split("\0") if f]


def all_files(scope="."):
    """Every file under `scope` that exists and may be read: clean paths, no tool state, no real env files,
    no symbolic links (a link can point outside the project)."""
    scope = clean(scope)
    if not os.path.exists(scope):
        raise SystemExit(f"{scope}: no such file or directory (paths are relative to the current directory)")
    if os.path.isfile(scope):
        return [] if is_secret_env(scope) or is_secret_env(os.path.realpath(scope)) else [scope]
    found, skip = git_files(scope), ALWAYS_SKIP
    if found is None:
        found, skip = [], IGNORE_DIRS
        for d, dirs, files in os.walk(scope):
            dirs[:] = [x for x in dirs if x not in skip]
            found += [os.path.join(d, f) for f in files]
    out = set()
    for f in found:
        f = clean(f)
        if (os.path.isfile(f) and not os.path.islink(f) and not skip.intersection(f.split("/")[:-1])
                and not is_secret_env(f)):
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
    paths = [p for p in dict.fromkeys(paths) if os.path.isfile(p)]
    if not paths:
        return {}
    # absolute paths: git resolves relative ones against the top of the repository, not the current directory
    r = git("hash-object", "--stdin-paths", input="\n".join(norm(os.path.abspath(p)) for p in paths) + "\n")
    if r is None:
        raise SystemExit("git is not installed or not on PATH: the ledger needs it")
    hashes = r.stdout.split()
    if r.returncode != 0 or len(hashes) != len(paths):
        raise SystemExit("git hash-object failed: " + safe(r.stderr or "unexpected output"))
    return dict(zip(paths, hashes))


def read_text(path):
    """Text of a file: UTF-8, or UTF-16 when it starts with that byte-order mark; a UTF-8 mark is dropped."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise SystemExit(f"{path}: cannot read ({e.strerror})")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    return data.decode("utf-8-sig", "replace").replace("\r\n", "\n")


def state_path(path, what):
    """`path` if it is inside the project's .review-kit/ folder, else stop: the scripts write nowhere else."""
    root = os.path.realpath(STATE_DIR)
    real = os.path.realpath(path)
    if real != root and not real.startswith(root + os.sep):
        raise SystemExit(f"{path}: {what} must be inside {STATE_DIR}/ of the project (run from the project root)")
    return path


def ensure_state_dir():
    """Create .review-kit/ with a .gitignore of its own, so its working files never show up in git."""
    os.makedirs(STATE_DIR, exist_ok=True)
    ignore = os.path.join(STATE_DIR, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8", newline="\n") as f:
            f.write("*\n")


def load_graph(path, extracted_only=False):
    """(up, down, files) from trace.py's build(), loaded by path because its name is also a stdlib module's.
    Raises ValueError when the graph cannot be read."""
    spec = importlib.util.spec_from_file_location("review_kit_trace", os.path.join(os.path.dirname(__file__), "trace.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build(path, extracted_only)
