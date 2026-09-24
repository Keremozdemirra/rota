"""The command line: exit codes, formats, the project scan, Windows paths, and canaries in every output."""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated, Response, Tty, cr, synthetic  # noqa: E402

rand = synthetic.rand
HAS_GIT = shutil.which("git") is not None


class Canaries(Isolated):
    """Plant a fake secret in every place the tool reads, then look for it in everything it prints."""

    def setUp(self):
        super().setUp()
        built = synthetic.build(self.tmp, git=HAS_GIT)
        self.home, self.project, self.c = built["home"], built["project"], built["canaries"]
        os.environ.clear()
        os.environ.update(built["env"])
        cwd = mock.patch("pathlib.Path.cwd", return_value=self.project)  # the tool checks the current directory
        cwd.start()
        self.addCleanup(cwd.stop)

    def fragments(self):
        """Every canary, and every 12-character piece of it, so a partial print is caught too."""
        out = set()
        for v in self.c.values():
            out.add(v)
            core = v.split("_", 1)[-1] if v.startswith(("ghp_", "gho_", "npm_")) else v
            out.update(core[i:i + 12] for i in range(0, max(1, len(core) - 11), 4))
        return out

    def assert_clean(self, text, what):
        for frag in self.fragments():
            self.assertNotIn(frag, text, f"{what} leaks a planted secret")

    def test_no_output_contains_a_planted_secret(self):
        outputs = {}
        for fmt in ([], ["--markdown"], ["--json"], ["--strict"]):
            code, out, err = self.run_main(fmt)
            outputs[" ".join(fmt) or "text"] = out + err
        self.serve(Response(json.dumps({"login": "dev"}).encode(), headers={"X-OAuth-Scopes": "repo, delete_repo"}),
                   Response(b"{}", headers={"X-OAuth-Scopes": "repo"}),
                   Response(b"{}", headers={"X-OAuth-Scopes": "gist"}))
        code, out, err = self.run_main(["--probe", "--json"])
        outputs["probe"] = out + err
        self.assertEqual(len(self.web.requests), 3)  # GITHUB_TOKEN, the gh token, the git-credentials token
        for name, text in outputs.items():
            self.assert_clean(text, name)
        code, out, err = self.run_main(["--redact"], stdin=Tty("redact\n"))
        self.assertEqual(code, 0, err)
        self.assert_clean(out + err, "--redact")
        rep = json.loads(outputs["--json"])
        self.assertEqual(rep["values_shown"], False)
        self.assertEqual(rep["not_found"], [])

    def test_report_shape(self):
        code, rep = self.report()
        self.assertEqual(code, 0)
        ids = [s["id"] for s in rep["sections"]]
        self.assertEqual(ids, ["environment", "aws", "gcloud", "azure", "kube", "docker", "npm", "pypi", "netrc",
                               "git", "gh", "ssh", "terraform", "project", "transcripts"])
        self.assertEqual(rep["blast_radius"][0]["severity"], "high")
        self.assertGreater(rep["totals"]["high"], 10)
        for sec in rep["sections"]:
            for f in sec["findings"]:
                self.assertIn(f["severity"], cr.SEVERITIES)

    @unittest.skipUnless(HAS_GIT, "git not installed")
    def test_project_git_status(self):
        _, rep = self.report()
        proj = {f["item"]: f for f in next(s for s in rep["sections"] if s["id"] == "project")["findings"]}
        self.assertEqual(proj[".env"]["git"], "not ignored")
        self.assertEqual(proj[".env"]["credential_variables"], ["GITHUB_TOKEN", "STRIPE_SECRET_KEY", "DATABASE_URL"])
        self.assertEqual(proj["config/.env.local"]["git"], "ignored")
        self.assertEqual(proj[".env.example"]["severity"], "info")
        self.assertEqual(proj["certs/server.key"]["severity"], "high")
        self.assertNotIn("certs/ca.pem", proj)  # a certificate, not a key
        self.assertNotIn("node_modules/pkg/.env", proj)
        self.assertEqual(proj["deploy/terraform.tfstate"]["severity"], "medium")

    def test_markdown_and_text(self):
        _, md, _ = self.run_main(["--markdown"])
        self.assertTrue(md.startswith("## credential-reach report, "))
        self.assertIn("| Severity | Item | Detail |", md)
        _, text, _ = self.run_main([])
        self.assertIn("Blast radius", text)
        self.assertIn("No secret values are shown", text)


class ExitCodes(Isolated):
    def test_clean_home(self):
        self.assertEqual(self.run_main(["--strict"])[0], 0)
        code, out, _ = self.run_main([])
        self.assertIn("nothing found that an agent could use", out)

    def test_strict_is_1_on_a_high_finding(self):
        self.write(".netrc", f"machine h.example password {rand(10)}\n")
        self.assertEqual(self.run_main(["--strict"])[0], 1)
        self.assertEqual(self.run_main([])[0], 0)

    def test_strict_is_2_when_a_file_could_not_be_checked(self):
        self.write(".docker/config.json", "{broken")
        self.assertEqual(self.run_main(["--strict"])[0], 2)
        self.assertEqual(self.run_main([])[0], 0)

    def test_bad_project_path_is_an_error(self):
        code, _, err = self.run_main(["--project", str(self.tmp / "typo")])
        self.assertEqual(code, 2)
        self.assertIn("not a directory", err)

    def test_usage_errors(self):
        with self.assertRaises(SystemExit) as e:
            self.run_main(["--json", "--markdown"])
        self.assertEqual(e.exception.code, 2)

    def test_relative_project_and_a_deleted_working_directory(self):
        self.write(".env", "A_TOKEN=" + rand(20), base=self.project)
        here = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, here)
        code, rep = self.report("--project", "project")
        self.assertEqual(rep["project"], str(self.project))
        with mock.patch("pathlib.Path.cwd", side_effect=FileNotFoundError):
            code, rep = self.report()
        self.assertEqual((code, rep["project"]), (0, None))

    def test_version(self):
        with self.assertRaises(SystemExit):
            self.run_main(["--version"])


class Project(Isolated):
    def test_home_as_project_is_not_walked(self):
        self.write(".env", "A_TOKEN=" + rand(20))
        code, rep = self.report("--project", str(self.home))
        sec = next(s for s in rep["sections"] if s["id"] == "project")
        self.assertEqual(sec["findings"], [])
        self.assertIn("home directory", sec["notes"][0])

    def test_without_git_the_status_is_unknown(self):
        self.write(".env", "A_TOKEN=" + rand(20), base=self.project)
        with mock.patch.object(cr.subprocess, "run", side_effect=FileNotFoundError):
            sec = cr.scan_project(self.ctx())
        self.assertIn("git is not installed", sec.notes[0])
        self.assertEqual(sec.findings[0]["severity"], "high")

    @unittest.skipUnless(HAS_GIT, "git not installed")
    def test_tracked_file_and_not_a_repository(self):
        self.write(".env", "", base=self.project)
        sec = cr.scan_project(self.ctx())
        self.assertIn("not a git repository", sec.notes[0])
        env = dict(os.environ)
        subprocess.run(["git", "init", "-q"], cwd=self.project, env=env, check=True)
        self.write("keys/id_rsa", synthetic.openssh_key(), base=self.project)
        subprocess.run(["git", "add", "keys/id_rsa"], cwd=self.project, env=env, check=True)
        f = {x["item"]: x for x in cr.scan_project(self.ctx()).findings}
        self.assertEqual(f["keys/id_rsa"]["git"], "tracked")
        self.assertIn("tracked by git", f["keys/id_rsa"]["detail"])

    def test_project_npmrc_and_skipped_dirs(self):
        self.write(".npmrc", f"//registry.npmjs.org/:_authToken={rand(30)}\n", base=self.project)
        self.write(".venv/pyvenv.cfg", "home = /usr\n", base=self.project)
        self.write(".venv/lib/.env", "X_TOKEN=abc\n", base=self.project)
        self.write("sub/.env.production", "API_KEY=abc\n", base=self.project)
        f = {x["item"]: x for x in cr.scan_project(self.ctx()).findings}
        self.assertEqual(f[".npmrc"]["severity"], "high")
        self.assertIn("sub/.env.production", f)
        self.assertNotIn(".venv/lib/.env", f)

    def test_unreadable_env_file_is_an_error(self):
        self.write(".env", "x" * 10, base=self.project)
        with mock.patch.object(cr, "read_file", return_value=(None, "unreadable (PermissionError)")):
            sec = cr.scan_project(self.ctx())
        self.assertTrue(sec.errors)


class WindowsPaths(Isolated):
    def test_display_uses_tilde_and_backslashes(self):
        home = PureWindowsPath(r"C:\Users\Kerem")
        ctx = cr.Context(home, env={}, system="Windows")
        self.assertEqual(ctx.show(PureWindowsPath(r"C:\Users\Kerem\.aws\credentials")), "~\\.aws\\credentials")
        self.assertEqual(ctx.show(PureWindowsPath(r"c:\users\kerem\.kube\config")), "~\\.kube\\config")
        self.assertEqual(ctx.show(PureWindowsPath(r"D:\keys\id_rsa")), "D:\\keys\\id_rsa")
        self.assertEqual(ctx.show(home), "~")

    def test_windows_locations(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
        ctx = self.ctx(system="Windows", env=env)
        self.assertEqual(cr.gcloud_dir(ctx), self.home / "AppData" / "Roaming" / "gcloud")
        self.assertEqual(cr.gh_dir(ctx), self.home / "AppData" / "Roaming" / "GitHub CLI")
        self.assertEqual(cr.gcloud_dir(self.ctx(system="Linux", env=env)), self.home / ".config" / "gcloud")
        self.write("_netrc", "machine w.example password x\n")
        self.write("AppData/Roaming/terraform.rc", 'credentials "t.example" {\n  token = "x"\n}\n')
        rep = cr.audit(ctx, transcripts=False)
        items = {f["item"] for s in rep["sections"] for f in s["findings"]}
        self.assertTrue({"w.example", "t.example"} <= items)
        self.assertIn("~\\_netrc", next(s for s in rep["sections"] if s["id"] == "netrc")["paths"])

    def test_claude_config_dir_is_honoured(self):
        d = self.tmp / "claude-elsewhere"
        self.write("claude-elsewhere/projects/p/s.jsonl", json.dumps({"x": "ghp_" + rand(36)}) + "\n", base=self.tmp)
        sec, hits = cr.scan_transcripts(self.ctx(env={**os.environ, "CLAUDE_CONFIG_DIR": str(d)}))
        self.assertEqual(len(hits), 1)


if __name__ == "__main__":
    unittest.main()
