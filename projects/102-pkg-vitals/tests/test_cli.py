"""The pkg-vitals command: output formats, exit codes, usage errors. Local server, no real network."""
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, Case, Server, clean_env, fixture_routes, pkg_vitals as pv  # noqa: E402


class Cli(Case):
    def setUp(self):
        super().setUp()
        self.project = self.home / "project"
        self.project.mkdir()
        cwd = mock.patch("os.getcwd", return_value=str(self.project))
        cwd.start()
        self.addCleanup(cwd.stop)

    def run_main(self, args, routes=None):
        with Server(routes if routes is not None else fixture_routes()) as server, \
                mock.patch.dict(os.environ, server.env()), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = pv.main(args)
            self.hits = list(server.hits)
        return code, out.getvalue()

    def test_command_line_after_double_dash(self):
        code, out = self.run_main(["--", "npm", "install", "left-pad", "this-package-does-not-exist-9f3k", "-D"])
        self.assertEqual(code, 0)
        self.assertIn("npm:left-pad", out)
        self.assertIn("!deprecated", out)
        self.assertIn("!not on registry", out)
        self.assertIn("2 packages · 2 with a serious flag · 1 not found", out)
        self.assertIn("Sources: 127.0.0.1 and 127.0.0.1; retrieved", out)

    def test_whole_command_as_one_string(self):
        code, out = self.run_main(["--", "cd app && npm i left-pad; pip install requests==2.32.0"])
        self.assertIn("npm:left-pad", out)
        self.assertIn("pypi:requests", out)
        self.assertIn("!yanked", out)

    def test_strict_exit_codes(self):
        self.assertEqual(self.run_main(["--strict", "npm", "left-pad"])[0], 1)
        self.assertEqual(self.run_main(["--strict", "pypi", "requests"])[0], 0)
        broken = {path: (500, {}, {}) for path in fixture_routes()}
        code, out = self.run_main(["--strict", "npm", "left-pad"], routes=broken)
        self.assertEqual(code, 2)
        self.assertIn("could not check, 127.0.0.1: HTTP 500", out)  # the registry this run was pointed at
        self.assertIn("1 not checked", out)
        self.assertEqual(self.run_main(["npm", "left-pad"], routes=broken)[0], 0)  # without --strict: a report

    def test_json(self):
        code, out = self.run_main(["--json", "pypi", "requests==2.32.0", "pyfits"])
        data = json.loads(out)
        self.assertEqual([p["name"] for p in data["packages"]], ["requests", "pyfits"])
        self.assertEqual([p["serious"] for p in data["packages"]], [["yanked"], ["archived"]])
        self.assertEqual(data["github"], "census")
        self.assertTrue(data["sources"].startswith("Sources: 127.0.0.1"))

    def test_markdown(self):
        code, out = self.run_main(["--markdown", "npm", "left-pad"])
        self.assertIn("| `npm:left-pad` | 1.3.0 | 2014-03-14 | 1,867,144 |", out)
        self.assertIn("**deprecated**", out)
        self.assertIn("not a verdict on anyone's package", out)

    def test_secrets_never_printed(self):
        cmd = ["npm", "i", "git+https://bot:ghp_hunter2@github.com/o/r.git", "https://x.example/p.tgz?sig=s3cr3t"]
        for fmt in ([], ["--json"], ["--markdown"]):
            code, out = self.run_main(fmt + ["--"] + cmd)
            self.assertNotIn("hunter2", out, fmt)
            self.assertNotIn("s3cr3t", out, fmt)
            self.assertIn("***", out, fmt)
        self.assertEqual(self.hits, [])  # a git or URL spec is never looked up

    def test_offline_sends_nothing(self):
        code, out = self.run_main(["--offline", "--strict", "--", "npm", "install", "foo", "bar@2", "-D"])
        self.assertEqual((code, self.hits), (0, []))
        self.assertIn("npm:foo", out)
        self.assertIn("0 with a serious flag", out)

    def test_nothing_to_check(self):
        code, out = self.run_main(["--", "npm", "install"])
        self.assertEqual(code, 0)
        self.assertIn("Nothing to check", out)
        self.assertIn("no package names: installs what package.json and the lockfile list", out)

    def test_install_command_without_double_dash(self):
        self.assertIn("npm:left-pad", self.run_main(["npm", "install", "left-pad"])[1])
        self.assertIn("pypi:requests", self.run_main(["pip", "install", "requests"])[1])

    def test_usage_errors_exit_2(self):
        for args in ([], ["npm"], ["cargo", "serde"], ["npm", "x", "--", "npm", "i", "y"], ["npm", "x", "--bogus"]):
            with mock.patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as ctx:
                pv.main(args)
            self.assertEqual(ctx.exception.code, 2, args)

    def test_new_days_option(self):
        code, out = self.run_main(["--new-days", "0", "pypi", "apache-airflow-providers-duckdb"])
        self.assertNotIn("!new", out)


class Script(Case):
    def test_the_script_runs_as_a_program(self):
        with Server(fixture_routes()) as server:
            proc = subprocess.run([sys.executable, str(ROOT / "pkg_vitals.py"), "--strict", "--", "npm", "i", "left-pad"],
                                  capture_output=True, text=True, timeout=60, cwd=str(self.home),
                                  env=clean_env({**server.env(), "HOME": str(self.home), "PYTHONIOENCODING": "utf-8"}))
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("npm:left-pad", proc.stdout)


if __name__ == "__main__":
    unittest.main()
