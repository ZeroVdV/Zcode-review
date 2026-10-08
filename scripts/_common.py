"""Helpers shared by prepare.py and ledger_check.py. Stdlib only, no LLM."""

import os
import subprocess
import sys

IGNORE_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv", "dist", "build", ".mypy_cache", ".pytest_cache"}
SKIP_EXT = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff", ".woff2", ".ttf", ".exe", ".so", ".dll", ".lock"}
EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def norm(p):
    return p.replace("\\", "/")


def scope_files(scope):
    """Text files under `scope` (a file or a directory), relative paths with '/'."""
    scope = norm(scope).rstrip("/")
    if os.path.isfile(scope):
        return [scope]
    out = []
    for d, dirs, files in os.walk(scope):
        dirs[:] = [x for x in dirs if x not in IGNORE_DIRS]
        for f in files:
            if os.path.splitext(f)[1].lower() not in SKIP_EXT:
                out.append(norm(os.path.join(d, f)))
    return sorted(out)


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
