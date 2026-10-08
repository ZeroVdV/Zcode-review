"""Tests for the scripts, each on a throwaway git repository. Stdlib only.

Run from the repository root:  python -m unittest discover -s tests -v"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
QUERY = "select id, amount, status from invoices where status = 'open' and due_date < now() order by id"
LEDGER = ".claude/state/review/ledger/billing.md"

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
    "ignored/junk.py": "x = 1  # TODO never listed\n",
}


def graph():
    """A graph in the shape trace.py reads: nodes with a source_file, links with a relation."""
    node = lambda i, f: {"id": i, "label": i + "()", "source_file": f, "source_location": "L1"}
    link = lambda s, t, f: {"source": s, "target": t, "relation": "calls", "context": "call",
                            "source_file": f, "source_location": "L8"}
    return {"nodes": [node("handler", "src/api/routes.py"), node("run", "src/billing/jobs.py"),
                      node("release", "src/shared/client.py")],
            "links": [link("handler", "run", "src/api/routes.py"), link("run", "release", "src/billing/jobs.py")]}


class Repo(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="review-kit-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        subprocess.run(["git", "init", "-q", "."], cwd=self.root, check=True)
        for path, text in FILES.items():
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

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def run_script(self, name, *args, stdin=None):
        """(exit code, stdout + stderr) of a script run at the root of the throwaway repository."""
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, name + ".py"), *args], cwd=self.root, input=stdin,
                           capture_output=True, text=True, encoding="utf-8",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        return r.returncode, r.stdout + r.stderr

    def ok(self, name, *args, stdin=None):
        code, out = self.run_script(name, *args, stdin=stdin)
        self.assertEqual(code, 0, out)
        return out

    def stamp_all(self, *scopes, ledger=LEDGER):
        for f in ("src/billing/jobs.py",) if not scopes else scopes:
            self.ok("ledger_check", "stamp", ledger, f, "--summary", "s")


class Secrets(Repo):
    def test_real_env_file_is_never_printed(self):
        for scope in ("src", "src/billing", ".", "src/billing/.env"):
            _, out = self.run_script("prepare", scope)
            self.assertNotIn("abcXXXsecret123", out, scope)

    def test_real_env_file_is_refused_as_the_example(self):
        code, out = self.run_script("prepare", "src", "--env-example", "src/billing/.env")
        self.assertNotEqual(code, 0)
        self.assertNotIn("abcXXXsecret123", out)

    def test_example_env_file_is_still_used(self):
        out = self.ok("prepare", "src")
        self.assertIn("SERVICE_URL  documented", out)
        self.assertIn("SERVICE_TOKEN  NOT in example file", out)


class ScopeFiles(Repo):
    def test_scope_is_source_only_and_respects_gitignore(self):
        out = self.ok("prepare", ".")
        self.assertIn("3 files", out)
        for absent in ("README.md", "package-lock.json", "graphify-out", ".claude", "junk.py"):
            self.assertNotIn(absent, out)

    def test_a_file_named_directly_is_taken_as_is(self):
        self.assertIn("src/billing/README.md:2", self.ok("prepare", "src/billing/README.md"))

    def test_extra_extension(self):
        self.write("src/billing/rules.cfgx", "a\nb\n")
        self.assertIn("1 files", self.ok("prepare", "src/billing"))
        self.assertIn("2 files", self.ok("prepare", "src/billing", "--ext", "cfgx"))

    def test_inventory_and_prepare_count_the_same_lines(self):
        self.write("src/billing/no_newline.py", "x = 1")
        inv = self.ok("inventory", ".")
        prep = self.ok("prepare", ".")
        total = sum(len(t.splitlines()) for p, t in FILES.items() if p.startswith("src/") and p.endswith(".py")) + 1
        self.assertIn(f"{total} lines", prep)
        self.assertRegex(inv, rf"code\s+4 files\s+{total} lines")

    def test_odd_file_names_and_deleted_tracked_files(self):
        self.write("src/my file.py", f'Q = "{QUERY}"\n')
        self.write("src/relatório.py", "x = 1\n")
        self.write("src/gone.py", "x = 1\n")
        self.git("add", "-A")
        os.remove(os.path.join(self.root, "src/gone.py"))
        out = self.ok("prepare", "src")
        self.assertIn("5 files", out)
        self.assertIn("src/my file.py:1", out)
        self.assertRegex(self.ok("inventory", "."), r"code\s+5 files")
        code, out = self.run_script("ledger_check", "src", "--ledger", LEDGER)
        self.assertIn("(5 files)", out)


class DotScope(Repo):
    def test_dot_scope_matches_the_graph_and_finds_repeated_sql(self):
        for scope in ("src/billing", "./src/billing", "src/billing/", "src\\billing"):
            out = self.ok("prepare", scope)
            self.assertIn("src/api: 1 file(s) routes.py", out, scope)
            self.assertIn("src/shared: 1 file(s) client.py", out, scope)
        out = self.ok("prepare", ".")
        self.assertNotIn("./", out)
        self.assertNotIn("STALE", out)
        self.assertIn("src/api/routes.py:3\n    src/billing/jobs.py:3", out)

    def test_inventory_root_area_works_in_cross_areas(self):
        inv = self.ok("inventory", ".")
        self.assertTrue(inv.rstrip().endswith("root: ."), inv)
        self.write("areas.txt", "root: .\n")
        self.assertNotIn("outside every area", self.ok("cross_areas", "areas.txt"))
        self.write("areas.txt", "billing: ./src/billing/\nrest: .\n")
        out = self.ok("cross_areas", "areas.txt")
        self.assertIn("billing -> rest: 1", out)
        self.assertIn("rest -> billing: 1", out)

    def test_trace_accepts_a_dot_slash_path(self):
        self.assertIn("hop1  src/billing/jobs.py", self.ok("trace", "./src/shared/client.py", "--dir", "up"))

    def test_default_ledger_of_the_root_scope(self):
        _, out = self.run_script("ledger_check", ".")
        self.assertIn("ledger/root.md", out)


class Ledger(Repo):
    def test_second_run_is_clean_without_stamping_non_source_files(self):
        code, out = self.run_script("ledger_check", "src/billing")
        self.assertEqual(code, 1)
        self.assertIn("everything is new (1 files)", out)
        self.stamp_all()
        self.assertIn("unchanged 1  changed 0  new 0  removed 0", self.ok("ledger_check", "src/billing"))

    def test_whole_project_ledger_does_not_contain_itself(self):
        ledger = ".claude/state/review/ledger/root.md"
        self.stamp_all("src/billing/jobs.py", "src/api/routes.py", "src/shared/client.py", ledger=ledger)
        self.ok("ledger_check", ".")
        self.ok("ledger_check", ".")

    def test_scope_spelling_does_not_matter(self):
        self.ok("ledger_check", "stamp", LEDGER, "./src/billing/jobs.py", "--summary", "s")
        for scope in ("src/billing", "./src/billing", "src/billing/", "src\\billing"):
            self.ok("ledger_check", scope, "--ledger", LEDGER)

    def test_changed_new_and_removed_files(self):
        self.stamp_all()
        self.write("src/billing/jobs.py", self.read("src/billing/jobs.py") + "# changed\n")
        self.write("src/billing/extra.py", "x = 1\n")
        code, out = self.run_script("ledger_check", "src/billing")
        self.assertEqual(code, 1)
        self.assertIn("changed: src/billing/jobs.py", out)
        self.assertIn("new: src/billing/extra.py", out)
        os.remove(os.path.join(self.root, "src/billing/jobs.py"))
        self.assertIn("removed: src/billing/jobs.py", self.run_script("ledger_check", "src/billing")[1])

    def test_rows_with_outer_pipes_and_backticks_are_read(self):
        self.stamp_all()
        text = self.read(LEDGER).splitlines()
        row = next(l for l in text if l.startswith("src/"))
        cells = row.split(" | ")
        cells[0], cells[1] = f"`{cells[0]}`", f"`{cells[1]}`"
        self.write(LEDGER, "\n".join(text).replace(row, "| " + " | ".join(cells) + " |") + "\n")
        self.assertIn("unchanged 1", self.ok("ledger_check", "src/billing"))
        self.ok("ledger_check", "stamp", LEDGER, "src/billing/jobs.py", "--summary", "again")
        self.assertEqual(sum("jobs.py" in l for l in self.read(LEDGER).splitlines()), 1)

    def test_a_finding_that_mentions_another_is_not_split(self):
        dep = subprocess.run(["git", "hash-object", "src/shared/client.py"], cwd=self.root, capture_output=True,
                             text=True).stdout[:7]
        findings = (f"F1 [rank 1] src/billing/jobs.py:3 same query as F2 in the router (organization, low) "
                    f"deps: src/shared/client.py@{dep} F2 [rank 2] src/billing/jobs.py:8 closes the connection "
                    f"(behavior-change, medium) deps: ./src/shared/client.py@{dep}")
        self.ok("ledger_check", "stamp", LEDGER, "src/billing/jobs.py", "--findings", findings)
        out = self.ok("ledger_check", "src/billing")
        self.assertEqual(out.count("[carry]"), 2, out)
        self.assertNotIn("no deps recorded", out)
        self.write("src/shared/client.py", self.read("src/shared/client.py") + "# changed\n")
        code, out = self.run_script("ledger_check", "src/billing")
        self.assertEqual(code, 1)
        self.assertEqual(out.count("RE-VERIFY (dep changed: src/shared/client.py)"), 2, out)

    def test_stamp_into_a_ledger_without_a_table(self):
        self.write(LEDGER, "# Ledger: billing\n\n## Deferred\n- one item\n")
        self.stamp_all()
        text = self.read(LEDGER)
        self.assertLess(text.index("src/billing/jobs.py"), text.index("## Deferred"))
        self.assertIn("- one item", text)
        self.ok("ledger_check", "src/billing")

    def test_findings_from_a_file_or_stdin_keep_shell_characters(self):
        finding = 'F1 [rank 1] src/billing/jobs.py:8 `release()` closes "twice" when $x | y (organization, low)'
        self.write("findings.txt", finding + "\n")
        self.ok("ledger_check", "stamp", LEDGER, "src/billing/jobs.py", "--findings-file", "findings.txt")
        kept = finding.replace("|", "/")
        self.assertIn(kept, self.read(LEDGER))
        self.ok("ledger_check", "stamp", LEDGER, "src/billing/jobs.py", "--findings-file", "-", stdin=finding + " again")
        self.assertIn(kept + " again", self.read(LEDGER))
        self.assertIn("[carry, but no deps recorded", self.ok("ledger_check", "src/billing"))


class VerifyRefs(Repo):
    def test_bad_citations_fail(self):
        self.write("report.md", "1. src/billing/jobs.py:3 real\n2. src/billing/jobs.py:999 past the end\n"
                                "3. src/nope/missing.py:4 invented\n")
        code, out = self.run_script("verify_refs", "report.md")
        self.assertEqual(code, 1)
        self.assertIn("1 ok, 2 bad", out)


class OutsideGit(unittest.TestCase):
    def test_scripts_fall_back_to_walking_the_tree(self):
        root = tempfile.mkdtemp(prefix="review-kit-nogit-")
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "pkg", "node_modules"))
        for path, text in (("pkg/a.py", "x = 1\n"), ("pkg/node_modules/b.py", "x = 1\n"), ("pkg/.env", "K=secretXXX\n")):
            with open(os.path.join(root, path), "w", encoding="utf-8") as f:
                f.write(text)
        env = {**os.environ, "GIT_CEILING_DIRECTORIES": os.path.dirname(root), "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "prepare.py"), "."], cwd=root, env=env,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 files", r.stdout)
        self.assertNotIn("secretXXX", r.stdout)


if __name__ == "__main__":
    unittest.main()
