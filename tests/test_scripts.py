"""Tests for the scripts, each on a throwaway git repository. Stdlib only.

Run from the repository root:  python -m unittest discover -s tests -v"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
QUERY = "select id, amount, status from invoices where status = 'open' and due_date < now() order by id"
LEDGER = ".review-kit/ledger/structure-src-billing.md"
# the tests must not act on a repository named by the caller's environment (e.g. when run from a git hook)
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
ENV.update(PYTHONIOENCODING="utf-8", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

FILES = {
    "src/shared/client.py": 'import os\n\nURL = os.environ.get("SERVICE_URL")\nTOKEN = os.getenv("SERVICE_TOKEN")\n\n\n'
                            "def fetch(path):\n    # TODO: retry on timeout\n    return URL + path\n\n\n"
                            "def release(conn):\n    conn.close()\n",
    "src/billing/jobs.py": f'from src.shared.client import release\n\nQUERY = "{QUERY}"\n\n\n'
                           "def run(conn):\n    conn.execute(QUERY)\n    release(conn)\n",
    "src/api/routes.py": f'from src.billing.jobs import run\n\nQUERY = "{QUERY}"\n\n\n'
                         "def handler(conn):\n    return run(conn)\n",
    "src/billing/README.md": "# billing\nTODO: write this\n",
    "src/billing/package-lock.json": "{}\n",
    "src/billing/.env": "SERVICE_TOKEN=abcXXXsecret123\n",
    ".env.example": "SERVICE_URL=\n",
    ".gitignore": ".env\nignored/\n",
    "ignored/junk.py": 'PASSWORD = "hunter2"  # TODO never listed\n',
}
PY = sorted(p for p in FILES if p.startswith("src/") and p.endswith(".py"))


def graph(extra_links=()):
    """A graph in the shape trace.py reads: nodes with a source_file, links with a relation."""
    node = lambda i, f: {"id": i, "label": i + "()", "source_file": f, "source_location": "L1"}
    return {"nodes": [node("handler", "src/api/routes.py"), node("run", "src/billing/jobs.py"),
                      node("release", "src/shared/client.py"), node("alone", "src/alone.py")],
            "links": [link("handler", "run"), link("run", "release"), *extra_links]}


def link(source, target, relation="calls", **more):
    return {"source": source, "target": target, "relation": relation, "context": "call", "source_location": "L8", **more}


def force_rmtree(path):
    for d, _, files in os.walk(path):  # git objects are read-only, which stops rmtree on Windows
        for f in files:
            try:
                os.chmod(os.path.join(d, f), stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


def run_in(cwd, name, *args, stdin=None):
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, name + ".py"), *args], cwd=cwd, input=stdin,
                       capture_output=True, text=True, encoding="utf-8", env=ENV)
    return r.returncode, r.stdout + r.stderr


class Repo(unittest.TestCase):
    files = FILES

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="review-kit-test-")
        self.addCleanup(force_rmtree, self.root)
        self.git("init", "-q", ".")
        for path, text in self.files.items():
            self.write(path, text)
        self.write("graphify-out/graph.json", json.dumps(graph()))

    def write(self, path, text):
        full = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def read(self, path):
        with open(os.path.join(self.root, path), encoding="utf-8") as f:
            return f.read()

    def remove(self, path):
        os.remove(os.path.join(self.root, path))

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True, env=ENV).stdout

    def run_script(self, name, *args, stdin=None, cwd=""):
        """(exit code, stdout + stderr) of a script run at the root of the throwaway repository."""
        return run_in(os.path.join(self.root, cwd), name, *args, stdin=stdin)

    def ok(self, name, *args, **kw):
        code, out = self.run_script(name, *args, **kw)
        self.assertEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        return out

    def fails(self, name, *args, **kw):
        """Output of a script that must stop with a message, not a traceback."""
        code, out = self.run_script(name, *args, **kw)
        self.assertNotEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        return out

    def stamp(self, file="src/billing/jobs.py", findings=None, ledger=LEDGER, summary="s"):
        args = ["stamp", ledger, file, "--summary", summary]
        if findings is not None:
            self.write(".review-kit/tmp/findings.txt", findings)
            args += ["--findings-file", ".review-kit/tmp/findings.txt"]
        return self.ok("ledger_check", *args)

    def check(self, scope="src/billing", *args):
        return self.run_script("ledger_check", scope, "--lens", "structure", *args)

    def hash7(self, path):
        return self.git("hash-object", path)[:7]

    def scope_lines(self, out):
        """The '<n> files, <m> lines' line of a prepare.py briefing."""
        return re.search(r"^\d+ files, \d+ lines$", out, re.M).group(0)

    def link_or_skip(self, target, link_path):
        try:
            os.symlink(target, os.path.join(self.root, link_path))
        except (OSError, NotImplementedError):
            self.skipTest("this machine cannot create symbolic links")


class Secrets(Repo):
    SECRET = "abcXXXsecret123"

    def test_ignored_env_file_is_never_printed(self):
        for scope in ("src", "src/billing", ".", "src/billing/.env"):
            _, out = self.run_script("prepare", scope)
            self.assertNotIn(self.SECRET, out, scope)
            self.assertNotIn("Traceback", out, scope)

    def test_tracked_env_files_are_never_printed(self):
        names = ["prod.env", ".env.local", ".envrc", "env.production", "secrets.env.local", ".env-staging", ".env_ci"]
        self.write(".gitignore", "ignored/\n")
        for n in names:
            self.write(f"src/billing/{n}", f"TOKEN={self.SECRET}  # TODO\n")
        self.git("add", "-A")
        for scope in ["src/billing", "."] + [f"src/billing/{n}" for n in names]:
            _, out = self.run_script("prepare", scope, "--ext", "env", "local", "envrc", "production")
            self.assertNotIn(self.SECRET, out, scope)
        out = self.ok("inventory", ".")
        self.assertRegex(out, r"code\s+3 files")
        self.assertNotRegex(out, r"other\s+\d+ files\s+\d+ lines.*\n.*prod\.env")

    def test_example_files_and_code_named_env_are_still_read(self):
        self.write("src/billing/env.py", "x = 1  # TODO in code\n")
        self.write("src/billing/.env.example", "A=1  # TODO example\n")
        out = self.ok("prepare", "src/billing", "--ext", "example")
        self.assertIn("src/billing/env.py:1", out)
        self.assertIn("src/billing/.env.example:1", out)

    def test_symlinks_are_not_followed(self):
        self.write("../outside-of-repo.env", f"TOKEN={self.SECRET}  # TODO\n")
        self.addCleanup(os.remove, os.path.join(self.root, "../outside-of-repo.env"))
        self.link_or_skip(os.path.join(self.root, "../outside-of-repo.env"), "src/billing/link.py")
        for scope in ("src/billing", "src/billing/link.py"):
            _, out = self.run_script("prepare", scope)
            self.assertNotIn(self.SECRET, out, scope)
        self.assertNotIn("link.py", self.ok("prepare", "src/billing"))

    def test_ignored_folder_is_not_walked(self):
        for name in ("prepare", "inventory"):
            _, out = self.run_script(name, "ignored")
            self.assertNotIn("hunter2", out)
            self.assertNotIn("junk.py", out)
        self.assertIn("(0 files)", self.check("ignored")[1])

    def test_example_env_file_is_used_for_names_only(self):
        out = self.ok("prepare", "src")
        self.assertIn("SERVICE_URL  documented", out)
        self.assertIn("SERVICE_TOKEN  NOT in example file", out)
        self.write("config/vars.txt", "export SERVICE_TOKEN = value-not-shown\n")
        out = self.ok("prepare", "src", "--env-example", "config/vars.txt")
        self.assertIn("SERVICE_TOKEN  documented", out)
        self.assertIn("SERVICE_URL  NOT in example file", out)
        self.assertNotIn("value-not-shown", out)

    def test_project_text_cannot_forge_output_lines(self):
        self.write("src/billing/odd.py", "x = 1  # TODO \x1b[2J\x07 bell\n")
        out = self.ok("prepare", "src/billing")
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x07", out)


class ScopeFiles(Repo):
    def test_scope_is_source_only_and_respects_gitignore(self):
        out = self.ok("prepare", ".")
        self.assertIn("3 files, ", self.scope_lines(out))
        for absent in ("README.md", "package-lock.json", "graphify-out", ".claude", "junk.py"):
            self.assertNotIn(absent, out)

    def test_tool_state_and_generated_files_are_left_out_even_when_tracked(self):
        self.write(".review-kit/tmp/note.py", "x = 1\n")
        self.write(".claude/hooks/hook.py", "x = 1\n")
        self.write("graphify-out/cache/c.py", "x = 1\n")
        self.write("node_modules/dep/index.js", "x = 1\n")
        self.write("src/app.min.js", "x = 1\n")
        self.write("src/api_pb2.py", "x = 1\n")
        self.git("add", "-f", ".review-kit", ".claude", "graphify-out", "node_modules", "src")
        self.assertIn("3 files, ", self.scope_lines(self.ok("prepare", ".")))
        self.assertRegex(self.ok("inventory", "."), r"code\s+3 files")

    def test_a_file_named_directly_is_taken_as_is(self):
        self.assertIn("src/billing/README.md:2", self.ok("prepare", "src/billing/README.md"))

    def test_extra_extension(self):
        self.write("src/billing/rules.cfgx", "a\nb\n")
        self.assertIn("1 files, ", self.scope_lines(self.ok("prepare", "src/billing")))
        self.assertIn("2 files, ", self.scope_lines(self.ok("prepare", "src/billing", "--ext", "cfgx")))
        self.assertIn("(2 files)", self.check("src/billing", "--ext", ".cfgx")[1])

    def test_inventory_and_prepare_count_the_same_lines(self):
        self.write("src/billing/no_newline.py", "x = 1")
        total = sum(len(FILES[p].splitlines()) for p in PY) + 1
        self.assertEqual(self.scope_lines(self.ok("prepare", ".")), f"4 files, {total} lines")
        self.assertRegex(self.ok("inventory", "."), rf"code\s+4 files\s+{total} lines")

    def test_odd_file_names_and_deleted_tracked_files(self):
        self.write("src/my file.py", f'Q = "{QUERY}"\n')
        self.write("src/d\u00e9j\u00e0.py", "x = 1\n")
        self.write("src/gone.py", "x = 1\n")
        self.git("add", "-A")
        self.remove("src/gone.py")
        out = self.ok("prepare", "src")
        self.assertIn("5 files, ", self.scope_lines(out))
        self.assertIn("src/my file.py:1", out)
        self.assertRegex(self.ok("inventory", "."), r"code\s+5 files")
        self.assertIn("(5 files)", self.check("src")[1])

    def test_scope_prefix_is_a_folder_not_a_string(self):
        self.write("src/billing2/other.py", "x = 1\n")
        self.assertIn("1 files, ", self.scope_lines(self.ok("prepare", "src/billing")))

    def test_missing_scope_is_an_error(self):
        self.assertIn("no such file", self.fails("prepare", "src/biling"))
        self.assertIn("no such file", self.fails("prepare", "src/billing", "src/typo"))
        self.stamp()
        self.assertIn("no such file", self.fails("ledger_check", "src/biling", "--ledger", LEDGER))

    def test_scripts_work_from_a_subfolder(self):
        self.write("src/jobs.py", "x = 'other file with the same relative name'\n")
        code, out = self.run_script("prepare", "jobs.py", cwd="src/billing")
        self.assertEqual(code, 0, out)
        self.write("src/billing/.review-kit/x", "")
        ledger = ".review-kit/ledger/structure-root.md"
        code, out = self.run_script("ledger_check", "stamp", ledger, "jobs.py", "--summary", "s", cwd="src/billing")
        self.assertIn(f"stamped jobs.py {self.hash7('src/billing/jobs.py')}", out)

    def test_big_files_are_listed_but_not_scanned(self):
        self.write("src/billing/big.py", "# TODO\n" * 300_000)
        out = self.ok("prepare", "src/billing")
        self.assertIn("over 2 MB, not scanned below: src/billing/big.py", out)
        self.assertNotIn("big.py:1", out)


class Prepare(Repo):
    def test_markers_are_whole_words_and_capped(self):
        self.write("src/billing/m.py", "# HACKATHON\nTODOS = []\nMASK = '0xXXXX'\n# FIXME one\n# HACK two\n# XXX three\n"
                                       "# REVIEW-LATER four\n")
        out = self.ok("prepare", "src/billing/m.py", "--markers", "REVIEW-LATER")
        for n in (4, 5, 6, 7):
            self.assertIn(f"m.py:{n}  ", out)
        for n in (1, 2, 3):
            self.assertNotIn(f"m.py:{n}  ", out)
        self.assertNotIn("m.py:7", self.ok("prepare", "src/billing/m.py"))
        self.write("src/billing/many.py", "# TODO\n" * 50)
        out = self.ok("prepare", "src/billing", "--max-markers", "10")
        self.assertEqual(len(re.findall(r"^src/billing/\S+:\d+  ", out, re.M)), 10)
        self.assertIn("43 more not shown", out)
        self.assertIn("src/billing/many.py 50", out)

    def test_graph_section(self):
        out = self.ok("prepare", "src/billing")
        self.assertIn("fresh", out)
        self.assertIn("used by (outside the scope):\n  src/api: 1 file(s) routes.py", out)
        self.assertIn("depends on (outside the scope):\n  src/shared: 1 file(s) client.py", out)
        out = self.ok("prepare", "src")
        self.assertIn("used by (outside the scope): none in the graph", out)
        old = os.path.getmtime(os.path.join(self.root, "src/billing/jobs.py")) - 1000
        os.utime(os.path.join(self.root, "graphify-out/graph.json"), (old, old))
        self.assertIn("STALE", self.ok("prepare", "src/billing"))
        self.assertIn("no graph at nope.json", self.ok("prepare", "src/billing", "--graph", "nope.json"))

    def test_unreadable_graph_does_not_stop_the_briefing(self):
        for text in ("{not json", "[]", "{}", "[" * 100_000):
            self.write("graphify-out/graph.json", text)
            out = self.ok("prepare", "src/billing")
            self.assertIn("cannot read the graph", out)
            self.assertIn("## Env vars read in scope", out)

    def test_env_forms(self):
        self.write("src/billing/e.py", "from os import environ, getenv\na = environ.get('from_import')\n"
                                       "b = getenv(\"LOWER_or_Mixed\")\nc = os.environ.setdefault('SET_DEFAULT', '1')\n")
        self.write("src/billing/e.ts", "const a = process.env.NODE_A\nconst b = process.env?.NODE_B\n"
                                       "const c = import.meta.env.VITE_C\nconst d = process.env['NODE_D']\n")
        self.write("src/billing/e.go", 'v := os.Getenv("GO_VAR")\n')
        self.write("src/billing/e.rb", 'v = ENV["RUBY_VAR"]\nw = ENV.fetch("RUBY_FETCH")\n')
        out = self.ok("prepare", "src/billing")
        for name in ("from_import", "LOWER_or_Mixed", "SET_DEFAULT", "NODE_A", "NODE_B", "VITE_C", "NODE_D", "GO_VAR",
                     "RUBY_VAR", "RUBY_FETCH"):
            self.assertIn(f"  {name}  NOT in example file", out)
        self.assertIn("none found", self.ok("prepare", "src/api"))

    def test_repeated_sql(self):
        out = self.ok("prepare", "src/billing")
        self.assertIn("src/api/routes.py:3\n    src/billing/jobs.py:3", out)
        self.assertIn("Long SQL strings repeated in more than one place (Python files of the repository)\nnone",
                      self.ok("prepare", "src/shared"))
        self.write("src/api/routes.py", "x = 1\n")
        self.assertNotIn("src/billing/jobs.py:3", self.ok("prepare", "src/billing"))

    def test_python_that_does_not_parse_is_skipped(self):
        self.write("src/api/broken.py", f'Q = "{QUERY}"\ndef (:\n')
        self.assertIn("src/api/routes.py:3", self.ok("prepare", "src/billing"))


class DotScope(Repo):
    def test_scope_spellings_agree(self):
        base = self.ok("prepare", "src/billing")
        for scope in ("./src/billing", "src/billing/", "src\\billing", os.path.join(self.root, "src", "billing")):
            self.assertEqual(self.ok("prepare", scope), base, scope)

    def test_dot_scope_matches_the_graph_and_finds_repeated_sql(self):
        out = self.ok("prepare", ".")
        self.assertNotRegex(out, r"(^|\s)\./")
        self.assertNotIn("STALE", out)
        self.assertIn("src/api/routes.py:3\n    src/billing/jobs.py:3", out)

    def test_inventory_root_area_works_in_cross_areas(self):
        inv = self.ok("inventory", ".")
        self.assertTrue(inv.rstrip().endswith("root: ."), inv)
        self.write("areas.txt", "root: .\n")
        self.assertNotIn("WARNING", self.ok("cross_areas", "areas.txt"))

    def test_default_ledgers(self):
        self.assertIn(".review-kit/ledger/structure-root.md", self.check(".")[1])
        self.write("src/a/utils/x.py", "x = 1\n")
        self.write("src/b/utils/x.py", "x = 2\n")
        self.assertIn("ledger/structure-src-a-utils.md", self.check("src/a/utils")[1])
        self.assertIn("ledger/structure-src-b-utils.md", self.check("./src/b/utils/")[1])
        _, out = self.run_script("ledger_check", "src/billing", "--lens", "cleanup")
        self.assertIn("ledger/cleanup-src-billing.md", out)

    def test_a_lens_or_a_ledger_is_required(self):
        self.assertIn("--lens", self.fails("ledger_check", "src/billing"))
        self.assertIn("--ledger", self.fails("ledger_check", "src/billing", "src/api", "--lens", "structure"))


class Ledger(Repo):
    def test_second_run_is_clean_without_stamping_non_source_files(self):
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("everything is new (1 files)", out)
        self.stamp()
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("unchanged 1  changed 0  new 0  removed 0", out)

    def test_each_lens_has_its_own_ledger(self):
        self.stamp()
        self.assertEqual(self.check()[0], 0)
        code, out = self.run_script("ledger_check", "src/billing", "--lens", "cleanup")
        self.assertEqual(code, 1)
        self.assertIn("everything is new", out)

    def test_state_folder_ignores_itself(self):
        self.stamp()
        self.assertEqual(self.read(".review-kit/.gitignore"), "*\n")
        self.assertNotIn(".review-kit", self.git("status", "--short"))
        ledger = ".review-kit/ledger/structure-root.md"
        for f in PY:
            self.stamp(f, ledger=ledger)
        self.assertEqual(self.check(".")[0], 0)
        self.assertEqual(self.check(".")[0], 0)

    def test_scope_spelling_does_not_matter(self):
        self.ok("ledger_check", "stamp", LEDGER, "./src/billing/jobs.py", "--summary", "s")
        for scope in ("src/billing", "./src/billing", "src/billing/", "src\\billing"):
            self.assertEqual(self.check(scope)[0], 0, scope)

    def test_changed_new_and_removed_files(self):
        self.stamp(findings="F1 [low] src/billing/jobs.py:3 a claim (organization, low)")
        self.write("src/billing/extra.py", "x = 1\n")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("unchanged 1  changed 0  new 1  removed 0", out)
        self.assertIn("new: src/billing/extra.py", out)
        self.remove("src/billing/extra.py")
        self.write("src/billing/jobs.py", self.read("src/billing/jobs.py") + "# changed\n")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("unchanged 0  changed 1  new 0  removed 0", out)
        self.assertIn("[RE-VERIFY (its file changed)] F1", out)
        self.remove("src/billing/jobs.py")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("unchanged 0  changed 0  new 0  removed 1", out)

    def test_emptied_or_newly_ignored_file_counts_as_changed(self):
        self.stamp()
        self.write("src/billing/keep.py", "x = 1\n")
        self.stamp("src/billing/keep.py")
        self.write("src/billing/jobs.py", "")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("changed: src/billing/jobs.py", out)
        self.write("src/billing/jobs.py", "x = 2\n")
        self.write(".gitignore", ".env\nignored/\nsrc/billing/jobs.py\n")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("changed: src/billing/jobs.py", out)

    def test_empty_files_are_neither_new_nor_stampable(self):
        self.stamp()
        self.write("src/billing/__init__.py", "")
        self.assertEqual(self.check()[0], 0)
        self.assertIn("missing or empty", self.fails("ledger_check", "stamp", LEDGER, "src/billing/__init__.py"))

    def test_drop_removes_the_row_of_a_file_that_is_gone(self):
        self.write("src/billing/old.py", "x = 1\n")
        self.stamp()
        self.stamp("src/billing/old.py")
        self.remove("src/billing/old.py")
        self.assertEqual(self.check()[0], 1)
        self.assertIn("dropped src/billing/old.py", self.ok("ledger_check", "drop", LEDGER, "src/billing/old.py"))
        self.assertEqual(self.check()[0], 0)
        self.assertIn("jobs.py", self.read(LEDGER))
        self.assertIn("no row", self.fails("ledger_check", "drop", LEDGER, "src/billing/old.py"))

    def test_stamp_keeps_other_rows_and_cells_it_was_not_given(self):
        self.write("src/billing/b.py", "x = 1\n")
        self.stamp(findings="F1 [low] src/billing/jobs.py:3 first (organization, low)", summary="first summary")
        self.stamp("src/billing/b.py", summary="b summary")
        self.ok("ledger_check", "stamp", LEDGER, "src/billing/b.py", "--decisions", "leave alone")
        rows = [l for l in self.read(LEDGER).splitlines() if l.startswith("src/")]
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].startswith("src/billing/jobs.py | "))
        self.assertIn("| first summary | - | F1 [low] src/billing/jobs.py:3 first", rows[0])
        self.assertIn("| b summary | leave alone | -", rows[1])

    def test_stamp_of_a_changed_file_needs_its_findings_again(self):
        self.stamp(findings="F1 [low] src/billing/jobs.py:3 old claim (organization, low)")
        self.write("src/billing/jobs.py", "x = 1\n")
        self.assertIn("--findings-file", self.fails("ledger_check", "stamp", LEDGER, "src/billing/jobs.py"))
        self.stamp(findings="")
        self.assertNotIn("old claim", self.read(LEDGER))
        self.assertEqual(self.check()[0], 0)

    def test_duplicate_rows_are_flagged_then_merged_by_stamp(self):
        self.stamp()
        row = next(l for l in self.read(LEDGER).splitlines() if l.startswith("src/"))
        stale = row.replace(row.split(" | ")[1], "0" * 40)
        self.write(LEDGER, self.read(LEDGER).replace(row, stale + " F9 [high] lost\n" + row))
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("duplicate rows: src/billing/jobs.py", out)
        self.stamp()
        self.assertEqual(sum(l.startswith("src/") for l in self.read(LEDGER).splitlines()), 1)
        self.assertEqual(self.check()[0], 0)

    def test_rows_with_outer_pipes_and_backticks_are_read(self):
        self.stamp()
        text = self.read(LEDGER)
        row = next(l for l in text.splitlines() if l.startswith("src/"))
        cells = row.split(" | ")
        cells[0], cells[1] = f"`{cells[0]}`", f"`{cells[1]}`"
        self.write(LEDGER, "\ufeff" + text.replace(row, "| " + " | ".join(cells) + " |"))
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("unchanged 1  changed 0", out)
        self.stamp(summary="again")
        self.assertEqual(sum("jobs.py" in l for l in self.read(LEDGER).splitlines()), 1)

    def test_a_finding_that_mentions_another_is_not_split(self):
        dep = self.hash7("src/shared/client.py")
        self.stamp(findings=f"F1 [high] src/billing/jobs.py:3 same query as F2 in the router, mail ops@deadbeef1.test "
                            f"(organization, low) deps: src/shared/client.py@{dep} F2 [low] src/billing/jobs.py:8 "
                            f"closes the connection (behavior-change, medium) deps: ./src/shared/client.py@{dep}")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("[carry]"), 2, out)
        self.write("src/shared/client.py", self.read("src/shared/client.py") + "# changed\n")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(out.count("RE-VERIFY (dep changed: src/shared/client.py)"), 2, out)

    def test_deps_with_odd_paths_and_several_deps(self):
        self.write("src/app/[id]/(group)/page.tsx", "export default 1\n")
        self.write("src/my dir/a+b.py", "x = 1\n")
        a, b, c = (self.hash7(p) for p in ("src/app/[id]/(group)/page.tsx", "src/my dir/a+b.py", "src/api/routes.py"))
        self.stamp(findings=f"F1 [low] src/billing/jobs.py:3 claim (organization, low) deps: "
                            f"src/app/[id]/(group)/page.tsx@{a}, src/my dir/a+b.py@{b}, `src\\api\\routes.py@{c.upper()}`.")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("[carry] F1", out)
        self.write("src/my dir/a+b.py", "x = 2\n")
        self.assertIn("RE-VERIFY (dep changed: src/my dir/a+b.py)", self.check()[1])

    def test_a_dep_that_cannot_be_read_is_not_carried(self):
        good = self.hash7("src/shared/client.py")
        for dep in ("src/api/routes.py", "src/api/routes.py@abc12", "src/api/routes.py @" + good,
                    "src/api/routes.py#" + good, "src/api/routes.py@<hash7>", "src/gone.py@" + good):
            self.stamp(findings=f"F1 [low] src/billing/jobs.py:3 claim (organization, low) deps: "
                                f"src/shared/client.py@{good}, {dep}")
            code, out = self.check()
            self.assertEqual(code, 1, dep)
            self.assertIn("[RE-VERIFY (", out, dep)

    def test_a_stamped_file_outside_the_source_scope_can_be_carried(self):
        self.stamp()
        self.stamp("src/billing/README.md", findings="F1 [low] src/billing/README.md:2 stale note (organization, low)")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.write("src/billing/README.md", "# changed\n")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("changed: src/billing/README.md", out)

    def test_stamp_into_a_ledger_without_a_table(self):
        self.write(LEDGER, "# Ledger: billing\n\n## Deferred\n\n| location | text |\n|---|---|\n| a.py:1 | one item |\n")
        self.stamp()
        text = self.read(LEDGER)
        self.assertLess(text.index("src/billing/jobs.py"), text.index("## Deferred"))
        self.assertIn("| a.py:1 | one item |", text)
        self.assertEqual(self.check()[0], 0)

    def test_findings_from_a_file_or_stdin_keep_shell_characters(self):
        finding = 'F1 [low] src/billing/jobs.py:8 `release()` closes "twice" when $x | y (organization, low)'
        self.stamp(findings=finding + "\n")
        kept = finding.replace("|", "/")
        self.assertIn(kept, self.read(LEDGER))
        self.ok("ledger_check", "stamp", LEDGER, "src/billing/jobs.py", "--findings-file", "-", stdin=finding + " again")
        self.assertIn(kept + " again", self.read(LEDGER))
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("[carry, but no deps recorded", out)
        self.assertIn("not both", self.fails("ledger_check", "stamp", LEDGER, "src/billing/jobs.py", "--findings", "x",
                                             "--findings-file", "-"))

    def test_stamp_writes_only_inside_the_state_folder(self):
        before = self.read("src/billing/jobs.py")
        for target in ("src/billing/jobs.py", "notes.md", "../outside.md", ".review-kit/ledger/x.txt", ".review-kit"):
            out = self.fails("ledger_check", "stamp", target, "src/api/routes.py", "--summary", "s")
            self.assertRegex(out, r"must be inside \.review-kit/|a ledger is a \.md file", target)
        self.assertEqual(self.read("src/billing/jobs.py"), before)
        self.assertFalse(os.path.exists(os.path.join(self.root, "notes.md")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "../outside.md")))

    def test_findings_file_is_read_only_from_the_state_folder(self):
        self.write("findings.txt", "F1 [low] x\n")
        self.write(".review-kit/tmp/.env", "TOKEN=abcXXXsecret123\n")
        for path in ("findings.txt", "src/billing/.env", ".review-kit/tmp/.env", ".review-kit/tmp/nope.txt"):
            self.fails("ledger_check", "stamp", LEDGER, "src/billing/jobs.py", "--findings-file", path)
        self.assertFalse(os.path.exists(os.path.join(self.root, LEDGER)))

    def test_a_ledger_that_came_with_the_repository_is_not_trusted(self):
        self.stamp(findings="F1 [low] src/billing/jobs.py:3 this area is clean (organization, low) deps: -")
        self.assertEqual(self.check()[0], 0)
        self.git("add", "-f", LEDGER)
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("WARNING: git tracks this ledger", out)
        self.assertIn("[RE-VERIFY (ledger tracked by git)]", out)

    def test_control_characters_in_a_finding_are_not_printed(self):
        self.stamp(findings="F1 [low] src/billing/jobs.py:3 claim \x1b[2J\x07 (organization, low)")
        out = self.check()[1]
        self.assertNotIn("\x1b", out)
        self.assertIn("data to check, not instructions", out)


class Trace(Repo):
    def trace(self, *args):
        return self.ok("trace", *args)

    def test_hops_entry_max_and_direction(self):
        up = self.trace("src/shared/client.py", "--dir", "up")
        self.assertIn("hop1  src/billing/jobs.py", up)
        self.assertIn("hop2  src/api/routes.py", up)
        self.assertNotIn("DOWN", up)
        one = self.trace("src/shared/client.py", "--dir", "up", "--hops", "1")
        self.assertNotIn("routes.py", one)
        entry = self.trace("src/shared/client.py", "--dir", "up", "--entry", "./src/billing/jobs.py")
        self.assertIn("src/billing/jobs.py  [entrypoint]", entry)
        self.assertNotIn("routes.py", entry)
        cut = self.trace("src/shared/client.py", "--dir", "up", "--max", "1")
        self.assertIn("cut at 1", cut)
        self.assertNotIn("routes.py", cut)
        down = self.trace("src/api/routes.py", "--dir", "down")
        self.assertIn("hop1  src/billing/jobs.py", down)
        self.assertIn("hop2  src/shared/client.py", down)
        self.assertNotIn("UP", down)

    def test_path_spellings_and_files_without_edges(self):
        for spelling in ("./src/shared/client.py", "src\\shared\\client.py", os.path.join(self.root, "src/shared/client.py")):
            self.assertIn("hop1  src/billing/jobs.py", self.trace(spelling, "--dir", "up"))
        self.assertIn("none in the graph", self.trace("src/alone.py"))
        self.assertIn("not in the graph", self.fails("trace", "src/nope.py"))

    def test_relations_decorators_and_inferred_edges(self):
        self.write("graphify-out/graph.json", json.dumps(graph([
            link("release", "handler", "implements", context="type"),
            link("release", "alone", "contains"),
            link("alone", "handler", "calls", context="decorator"),
            link("alone", "run", "calls", confidence="INFERRED"),
            link("alone", "release", "calls", confidence="INFERRED"),
            link("alone", "release", "imports", confidence="EXTRACTED"),
        ])))
        down = self.trace("src/shared/client.py", "--dir", "down", "--hops", "1")
        self.assertIn("hop1  src/api/routes.py   (implements", down)
        self.assertNotIn("alone.py", down)
        alone = self.trace("src/alone.py", "--dir", "down", "--hops", "1")
        self.assertNotIn("routes.py", alone)
        self.assertIn("src/billing/jobs.py   (calls run() @ src/alone.py:8 [inferred])", alone)
        self.assertIn("src/shared/client.py   (imports release() @ src/alone.py:8)", alone)
        strict = self.trace("src/alone.py", "--dir", "down", "--hops", "1", "--extracted-only")
        self.assertNotIn("jobs.py", strict)
        self.assertIn("client.py", strict)

    def test_bad_input_gives_a_message(self):
        self.assertIn("no graph at missing.json", self.fails("trace", "src/shared/client.py", "--graph", "missing.json"))
        self.assertIn("at least 1", self.fails("trace", "src/shared/client.py", "--hops", "0"))
        for text in ("{not json", "[]", "{}"):
            self.write("graphify-out/graph.json", text)
            self.assertIn("cannot read the graph", self.fails("trace", "src/shared/client.py"))


class CrossAreas(Repo):
    AREAS = "# comment\nbilling: ./src/billing/   # the service\nrest: .\n"

    def cross(self, areas, *args):
        self.write("areas.txt", areas)
        return self.ok("cross_areas", "areas.txt", *args)

    def test_pairs_most_specific_area_and_fan_in(self):
        out = self.cross(self.AREAS)
        self.assertIn("billing -> rest: 1", out)
        self.assertIn("rest -> billing: 1", out)
        self.assertIn("billing <-> rest: 1 / 1", out)
        self.assertIn("rest: 1 area(s): billing", out)
        out = self.cross("rest: .\nbilling: src/billing\napi: src/api\n")
        self.assertIn("api -> billing: 1   e.g. src/api/routes.py -> src/billing/jobs.py", out)
        self.assertIn("billing -> rest: 1", out)
        self.assertNotIn("<->", out)

    def test_ignore(self):
        self.write("src/alone.py", "x = 1\n")
        out = self.cross("billing: src/billing\napi: src/api\nshared: src/shared src/alone.py\n", "--ignore", "api")
        self.assertNotIn("api ->", out)
        self.assertIn("billing -> shared: 1", out)
        self.assertIn("no such area", self.fails("cross_areas", "areas.txt", "--ignore", "nope"))

    def test_quoted_paths_and_what_inventory_prints(self):
        self.write("src/my dir/c.py", "x = 1\n")
        self.write("src/a#b/e.py", "x = 1\n")
        self.write("src/alone.py", "x = 1\n")
        out = self.cross('odd: "src/my dir" "src/a#b"\nrest: src/billing src/api src/shared src/alone.py\n')
        self.assertNotIn("WARNING", out)
        for f in ("src/billing/jobs.py", "src/api/routes.py", "src/shared/client.py"):
            self.write(f, "x = 1\n" * 30)
        inv = self.ok("inventory", ".", "--cap", "40")
        areas = inv.split("## areas.txt format")[1].split("\n", 1)[1]
        self.assertIn('"src/my dir"', areas)
        self.assertIn('"src/a#b"', areas)
        self.cross(areas)

    def test_areas_that_match_nothing_are_errors_or_loud(self):
        for text, message in (("billing: src/biling\n", "do not exist"), ("billing: src/billing, src/api\n", "do not exist"),
                              ("billing:\n", "no paths"), ("a: src/api\na: src/billing\n", "defined twice"),
                              ("just words\n", "expected `name: path")):
            self.write("areas.txt", text)
            self.assertIn(message, self.fails("cross_areas", "areas.txt"), text)
        out = self.cross("billing: src/billing\n")
        self.assertIn("WARNING: 3 of 4 files in the graph belong to no area", out)
        self.assertIn("no graph at", self.fails("cross_areas", "areas.txt", "--graph", "nope.json"))
        self.fails("cross_areas", "nope.txt")

    def test_areas_file_written_by_other_tools(self):
        full = os.path.join(self.root, "areas.txt")
        for encoding in ("utf-8-sig", "utf-16"):
            with open(full, "w", encoding=encoding, newline="\r\n") as f:
                f.write("billing: src\\billing\nrest: .\n")
            out = self.ok("cross_areas", "areas.txt", "--ignore", "billing")
            self.assertIn("ignoring: billing", out)


class Inventory(Repo):
    def areas(self, *args):
        out = self.ok("inventory", ".", *args)
        return out.split("## Proposed areas")[1].split("## areas.txt")[0], out

    def test_totals_by_kind(self):
        self.write("tests/test_jobs.py", "def test_x():\n    assert True\n")
        self.write("src/conftest.py", "x = 1\n")
        self.write("migrations/0001_init.sql", "create table t (id int);\n")
        self.write("src/contest/latest.py", "x = 1\n")
        out = self.ok("inventory", ".")
        self.assertRegex(out, r"code\s+4 files")
        self.assertRegex(out, r"tests\s+2 files\s+3 lines")
        self.assertRegex(out, r"migrations\s+1 files\s+1 lines")
        self.assertRegex(out, r"docs\s+1 files\s+2 lines\s+\(not reviewed\)")
        self.assertRegex(self.ok("inventory", ".", "--exclude", "src/contest/*", "tests/*"), r"code\s+3 files")

    def test_split_packing_and_oversize(self):
        for name in ("one", "two", "three"):
            self.write(f"src/{name}.py", "x = 1\n" * 40)
        self.write("src/big/only.py", "x = 1\n" * 200)
        self.write("src/deep/a/x.py", "x = 1\n" * 45)
        self.write("src/deep/b/x.py", "x = 1\n" * 45)
        self.write("src/small1/x.py", "x = 1\n" * 10)
        self.write("src/small2/x.py", "x = 1\n" * 10)
        proposed, out = self.areas("--cap", "50")
        self.assertRegex(proposed, r"src-files\s+120 lines\s+3 files\s+OVERSIZE")
        self.assertRegex(proposed, r"src-big\s+200 lines\s+1 files\s+OVERSIZE")
        self.assertRegex(proposed, r"src-deep-a\s+45 lines\s+1 files\n")
        self.assertRegex(proposed, r"src-deep-b\s+45 lines\s+1 files\n")
        self.assertRegex(out, r"src\+\d: (src/\S+ )*src/small1 src/small2")
        for line in proposed.splitlines()[1:]:
            if line.strip() and "OVERSIZE" not in line:
                self.assertLessEqual(int(re.search(r"(\d+) lines", line).group(1)), 62, line)
        whole, _ = self.areas("--cap", "100000")
        self.assertRegex(whole, r"root\s+\d+ lines")

    def test_area_names(self):
        for path in ("src/v1.2/a.py", "src/api.v2/a.py", "apps/web/src/features/components/forms/a.py",
                     "apps/web/src/features/components/tables/a.py"):
            self.write(path, "x = 1\n" * 60)
        proposed, _ = self.areas("--cap", "40")
        for name in ("src-v1.2 ", "src-api.v2 ", "components-forms ", "components-tables "):
            self.assertIn(name, proposed)

    def test_depth_and_bad_root(self):
        self.assertNotIn("billing/", self.ok("inventory", ".", "--depth", "1").split("## Largest")[0])
        self.assertIn("billing/", self.ok("inventory", ".", "--depth", "2").split("## Largest")[0])
        self.assertIn("not a directory", self.fails("inventory", "nope"))
        self.assertIn("NOTE: this is a subfolder", self.ok("inventory", "src"))
        self.assertNotIn("NOTE:", self.ok("inventory", "."))


class VerifyRefs(Repo):
    def verify(self, text):
        self.write("report.md", text)
        return self.run_script("verify_refs", "report.md")

    def test_real_citations_in_every_usual_wrapping(self):
        self.write("src/app/widget.vue", "<script>\nlet a = 1\n</script>\n")
        self.write("src/app/[id]/(group)/page.tsx", "export default 1\n")
        self.write("Dockerfile", "FROM scratch\n")
        self.write("docs/guide.md", "# guide\n")
        code, out = self.verify(
            "1. src/app/widget.vue:2 and src/app/[id]/(group)/page.tsx:1 and Dockerfile:1 and docs/guide.md:1\n"
            "2. [jobs](src/billing/jobs.py:3), (src/billing/jobs.py:1-3), _src/billing/jobs.py:2_, **src/billing/jobs.py:2**\n"
            "3. ./src/billing/jobs.py:2, src\\billing\\jobs.py:2, jobs.py:8, src/billing/jobs.py:1\u20133, src/billing/jobs.py:8:4\n"
            "4. see http://localhost:3000/api.json:1 and example.com:443 and v1.2.3:4 at 12:30\n")
        self.assertEqual(code, 0, out)
        self.assertIn("13 ok, 0 bad, 0 warn, 0 unchecked", out)

    def test_invented_citations_fail(self):
        self.write("Dockerfile", "FROM scratch\n")
        bad = ["src/billing/jobs.py:9", "src/nope/missing.py:4", "src/app/[nope]/page.tsx:1", "Dockerfile:40",
               "Makefile:9", "prisma/schema.prisma:900", "src/billing/jobs.py:5\u2013999", "src/billing/jobs.py:0",
               "src/billing/jobs.py:8-3", "totally/made/up(src/billing/jobs.py:2", "other/dir/jobs.py:2"]
        for cite in bad:
            code, out = self.verify(f"1. src/billing/jobs.py:8 is real\n2. {cite} is not\n")
            self.assertEqual(code, 1, cite)
            self.assertIn("1 ok, 1 bad", out, cite)

    def test_shapes_that_cannot_be_checked_are_reported(self):
        shapes = ["jobs.py:L99", "jobs.py#L99", "jobs.py (line 99)", "C:/work/app/ghost.ts:10", "/home/dev/app/ghost.py:20"]
        code, out = self.verify("".join(f"{i}. {s}\n" for i, s in enumerate(shapes)))
        self.assertEqual(code, 1, out)
        self.assertIn(f"0 ok, 0 bad, 0 warn, {len(shapes)} unchecked", out)
        code, out = self.verify("1. src/billing/jobs.py:3\n2. jobs.py:L99\n")
        self.assertEqual(code, 0, out)
        self.assertIn("UNCHECKED report:2", out)
        code, out = self.verify("No findings.\n")
        self.assertEqual(code, 0)
        self.assertIn("WARNING: no citation was checked", out)

    def test_code_spans_are_looked_up(self):
        code, out = self.verify("1. src/billing/jobs.py:7 `conn.execute(QUERY)` is real\n"
                                "2. src/billing/jobs.py:8 `release(conn, force=True)` is not\n"
                                "3. src/billing/jobs.py:8 see `src/app/[id]/page.tsx` and `run()`\n")
        self.assertEqual(code, 0, out)
        self.assertIn("3 ok, 0 bad, 1 warn", out)
        self.assertIn("WARN report:2", out)

    def test_missing_report(self):
        self.fails("verify_refs", "nope.md")


class OutsideGit(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="review-kit-nogit-")
        self.addCleanup(force_rmtree, self.root)
        for path, text in (("pkg/a.py", "x = 1  # TODO a\n"), ("pkg/node_modules/b.py", "x = 1\n"),
                           ("pkg/venv/lib/c.py", "x = 1\n"), ("pkg/.env.local", "K=secretXXX  # TODO\n"),
                           ("pkg/prod.env", "K=secretXXX  # TODO\n")):
            os.makedirs(os.path.dirname(os.path.join(self.root, path)), exist_ok=True)
            with open(os.path.join(self.root, path), "w", encoding="utf-8") as f:
                f.write(text)

    def test_scripts_fall_back_to_walking_the_tree(self):
        ENV["GIT_CEILING_DIRECTORIES"] = os.path.dirname(self.root)
        self.addCleanup(ENV.pop, "GIT_CEILING_DIRECTORIES")
        code, out = run_in(self.root, "prepare", ".", "--ext", "env", "local")
        self.assertEqual(code, 0, out)
        self.assertIn("1 files, 1 lines", out)
        self.assertNotIn("secretXXX", out)
        code, out = run_in(self.root, "inventory", ".")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"code\s+1 files")
        code, out = run_in(self.root, "ledger_check", "pkg", "--lens", "cleanup")
        self.assertIn("everything is new (1 files)", out)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main()
