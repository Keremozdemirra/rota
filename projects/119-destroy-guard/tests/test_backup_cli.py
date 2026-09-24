"""`destroy-guard backup` with fake terraform, kubectl, helm and git on PATH: what runs, what is kept, what fails."""
import hashlib
import json
import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated, k8s_list, k8s_object, state_json  # noqa: E402

import destroy_guard as dg  # noqa: E402

POSIX = os.name == "posix"
TF_VERSION = {"args": ["version", "-json"], "stdout": json.dumps({"terraform_version": "1.9.5"})}


def mode(p) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


class Base(Isolated):
    def backup(self, command, cwd=None):
        return self.cli("backup", "--cwd", str(cwd or self.project), "--", *command.split())

    def backup_dirs(self, store=None):
        root = Path(store or self.project / ".destroy-guard") / "backups"
        return sorted(root.iterdir()) if root.exists() else []

    def manifest(self, d):
        return json.loads((d / "manifest.json").read_text(encoding="utf-8"))


class TerraformBackup(Base):
    def test_verified_backup_then_the_hook_is_silent(self):
        secret = "s3cr3t-" + "v" * 16
        self.git_repo()
        (self.project / "infra").mkdir()
        self.fake_tool("terraform", [{"args": ["state", "pull"], "stdout": state_json(secret=secret)}, TF_VERSION])
        self.assertIsNotNone(self.hook("terraform -chdir=infra destroy -auto-approve"))
        code, out, err = self.backup("terraform -chdir=infra destroy -auto-approve")
        self.assertEqual(code, 0, err)
        self.assertIn("verified backup:", out)
        self.assertIn("state serial 7", out)
        self.assertIn("aws_db_instance 1", out)
        self.assertNotIn(secret, out + err)  # contents are never printed
        self.assertIn("Backups can hold secrets", err)
        [d] = self.backup_dirs()
        m = self.manifest(d)
        self.assertEqual(m["targets"], [{"tool": "terraform", "dir": str(self.project / "infra"),
                                         "workspace": "default"}])
        self.assertEqual(m["command"], "terraform -chdir=infra destroy -auto-approve")
        self.assertEqual(m["tool_versions"], {"terraform": "1.9.5"})
        [e] = m["exports"]
        data = (d / e["file"]).read_bytes()
        self.assertEqual((e["bytes"], e["sha256"]), (len(data), hashlib.sha256(data).hexdigest()))
        self.assertEqual(json.loads(data)["serial"], 7)  # stored exactly as pulled, ready for `state push`
        call = self.calls("terraform")[0]
        self.assertEqual(call["args"], ["state", "pull"])
        self.assertEqual(call["cwd"], str(self.project / "infra"))
        self.assertEqual((call["env"]["TF_WORKSPACE"], call["env"]["CHECKPOINT_DISABLE"]), ("default", "1"))
        self.assertIsNone(self.hook("terraform -chdir=infra destroy -auto-approve"))
        self.assertEqual(self.cli("check", "--cwd", str(self.project), "--", "terraform", "-chdir=infra",
                                  "destroy")[0], 0)

    def test_workspace_is_pinned_for_the_export(self):
        self.fake_tool("terraform", [{"args": ["state", "pull"], "stdout": state_json()}, TF_VERSION])
        code, _, err = self.cli("backup", "--cwd", str(self.project), "--",
                                "terraform workspace select prod && terraform destroy")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.calls("terraform")[0]["env"]["TF_WORKSPACE"], "prod")
        self.assertIsNone(self.hook("terraform workspace select prod && terraform destroy"))
        self.assertIsNotNone(self.hook("terraform destroy"))  # the default workspace has no backup

    def test_environment_prefix_reaches_the_export(self):
        self.fake_tool("terraform", [{"args": ["state", "pull"], "stdout": state_json()}, TF_VERSION])
        self.assertEqual(self.backup("AWS_PROFILE=prod terraform destroy")[0], 0)
        self.assertEqual(self.calls("terraform")[0]["env"]["AWS_PROFILE"], "prod")

    def test_failures_write_nothing(self):
        cases = [
            ({"stderr": "Error: Failed to load state: AccessDenied for https://u:pw@s3.example/b?sig=1\n", "rc": 1},
             "exited with 1"),
            ({"stdout": ""}, "printed nothing"),
            ({"stdout": "   \n"}, "printed nothing"),
            ({"stdout": "<html>proxy error</html>"}, "did not print JSON"),
            ({"stdout": "\xff\xfe", "raw": True}, "did not print JSON"),
            ({"stdout": "[1, 2]"}, "did not print a state object"),
            ({"stdout": json.dumps({"version": 4, "resources": [{}]})}, "without a serial and lineage"),
            ({"stdout": json.dumps({"version": 4, "serial": True, "lineage": "x", "resources": [{}]})},
             "without a serial and lineage"),
            ({"stdout": json.dumps({"version": 4, "serial": 1, "lineage": "x"})}, "without a resources list"),
            ({"stdout": state_json(resources=0)}, "lists no resources"),
        ]
        for rule, message in cases:
            with self.subTest(message=message, rule=rule):
                self.fake_tool("terraform", [dict(rule, args=["state", "pull"]), TF_VERSION])
                code, out, err = self.backup("terraform destroy")
                self.assertEqual(code, 1, err)
                self.assertIn(message, err)
                self.assertIn("no backup written", err)
                self.assertNotIn("pw@", err)  # the tool's stderr is masked
                self.assertEqual(self.backup_dirs(), [])  # a half-made backup is removed
                self.assertIsNotNone(self.hook("terraform destroy"))

    def test_missing_tool_and_timeout(self):
        code, _, err = self.backup("tofu destroy")
        self.assertEqual(code, 2)
        self.assertIn("tofu was not found on PATH", err)
        self.fake_tool("terraform", [{"args": ["state", "pull"], "stdout": state_json()}])
        with mock.patch.object(dg, "EXPORT_TIMEOUT", 0.001):
            code, _, err = self.backup("terraform destroy")
        self.assertEqual(code, 1)
        self.assertIn("did not finish", err)
        self.assertEqual(self.backup_dirs(), [])

    def test_disk_full(self):
        self.fake_tool("terraform", [{"args": ["state", "pull"], "stdout": state_json()}])
        with mock.patch.object(dg, "_write_private", side_effect=OSError(28, "No space left on device")):
            code, _, err = self.backup("terraform destroy")
        self.assertEqual(code, 1)
        self.assertIn("No space left on device", err)
        self.assertEqual(self.backup_dirs(), [])

    def test_manifest_write_failure_leaves_nothing(self):
        self.fake_tool("terraform", [{"args": ["state", "pull"], "stdout": state_json()}])
        real = dg._write_private

        def fail_on_manifest(path, data):
            if path.name.startswith("manifest"):
                raise OSError(5, "Input/output error")
            return real(path, data)

        with mock.patch.object(dg, "_write_private", side_effect=fail_on_manifest):
            code, _, err = self.backup("terraform destroy")
        self.assertEqual(code, 1)
        self.assertEqual(self.backup_dirs(), [])  # the state file written before it is gone too

    def test_version_failure_is_not_a_backup_failure(self):
        self.fake_tool("terraform", [{"args": ["state", "pull"], "stdout": state_json()},
                                     {"args": ["version"], "stdout": "garbage"}])
        self.assertEqual(self.backup("terraform destroy")[0], 0)
        self.assertEqual(self.manifest(self.backup_dirs()[0])["tool_versions"], {"terraform": "unknown"})


class KubectlBackup(Base):
    def setUp(self):
        super().setUp()
        self.kubeconfig("kind-prod")

    def test_objects(self):
        self.fake_tool("kubectl", [
            {"args": ["get", "deploy", "web"], "stdout": k8s_object("Deployment", "web", "prod")},
            {"args": ["version"], "stdout": json.dumps({"clientVersion": {"gitVersion": "v1.31.0"}})}])
        code, out, err = self.backup("kubectl delete deploy web -n prod")
        self.assertEqual(code, 0, err)
        call = self.calls("kubectl")[0]
        self.assertIn("--context=kind-prod", call["args"])  # pinned to the context the target names
        self.assertIn("--namespace=prod", call["args"])
        self.assertEqual(call["args"][call["args"].index("-o") + 1], "json")
        m = self.manifest(self.backup_dirs()[0])
        self.assertEqual(m["tool_versions"], {"kubectl": "v1.31.0"})
        self.assertIsNone(self.hook("kubectl delete deployment web --namespace=prod"))
        self.assertIsNotNone(self.hook("kubectl delete deployment web --namespace=staging"))
        self.assertIsNotNone(self.hook("kubectl --context other delete deployment web -n prod"))

    def test_wrong_object_or_failure(self):
        cases = [({"stdout": k8s_object("Service", "web", "prod")}, "returned a Service, expected a Deployment"),
                 ({"stdout": k8s_object("Deployment", "api", "prod")}, "did not return an object named web"),
                 ({"stdout": ""}, "printed nothing"),
                 ({"stdout": "{not json"}, "did not print JSON"),
                 ({"stderr": 'Error from server (NotFound): deployments.apps "web" not found\n', "rc": 1},
                  "exited with 1")]
        for rule, message in cases:
            with self.subTest(message=message):
                self.fake_tool("kubectl", [dict(rule, args=["get"])])
                code, _, err = self.backup("kubectl delete deploy web -n prod")
                self.assertEqual(code, 1)
                self.assertIn(message, err)
                self.assertEqual(self.backup_dirs(), [])

    def test_unicode_names_that_sanitise_alike(self):
        self.fake_tool("kubectl", [
            {"args": ["get", "configmap", "配置"], "stdout": k8s_object("ConfigMap", "配置", "prod")},
            {"args": ["get", "configmap", "設定"], "stdout": k8s_object("ConfigMap", "設定", "prod")}])
        code, out, err = self.backup("kubectl delete configmap 配置 設定 -n prod")
        self.assertEqual(code, 0, err)
        self.assertEqual(len({e["file"] for e in self.manifest(self.backup_dirs()[0])["exports"]}), 2)
        self.assertIsNone(self.hook("kubectl delete configmap 設定 -n prod"))

    def test_namespace_takes_its_contents(self):
        self.fake_tool("kubectl", [
            {"args": ["api-resources"], "stdout": "configmaps\nevents\nsecrets\npods\ndeployments.apps\n"},
            {"args": ["get", "configmaps,secrets,pods,deployments.apps"],
             "stdout": k8s_list(k8s_object("Secret", "db", "prod"), k8s_object("Pod", "web-1", "prod"))},
            {"args": ["get", "ns", "prod"], "stdout": k8s_object("Namespace", "prod")},
            {"args": ["version"], "rc": 1}])
        code, out, err = self.backup("kubectl delete ns prod")
        self.assertEqual(code, 0, err)
        self.assertIn("2 objects in namespace prod", out)
        files = [e["file"] for e in self.manifest(self.backup_dirs()[0])["exports"]]
        self.assertEqual(len(files), 2)
        self.assertNotIn("events", " ".join(c for call in self.calls("kubectl") for c in call["args"][-4:-3]))

    def test_namespace_contents_must_be_a_list(self):
        self.fake_tool("kubectl", [{"args": ["api-resources"], "stdout": "pods\n"},
                                   {"args": ["get", "pods"], "stdout": "{}"},
                                   {"args": ["get", "ns", "prod"], "stdout": k8s_object("Namespace", "prod")}])
        code, _, err = self.backup("kubectl delete ns prod")
        self.assertEqual(code, 1)
        self.assertIn("did not print a list of objects", err)

    def test_selector_needs_matches(self):
        self.fake_tool("kubectl", [{"args": ["get", "pods"], "stdout": k8s_list()}])
        code, _, err = self.backup("kubectl delete pods -l app=web -n prod")
        self.assertEqual(code, 1)
        self.assertIn("matched no objects", err)
        self.fake_tool("kubectl", [{"args": ["get", "pods", "--selector=app=web"],
                                    "stdout": k8s_list(k8s_object("Pod", "web-1", "prod"))}])
        self.assertEqual(self.backup("kubectl delete pods -l app=web -n prod")[0], 0)
        self.assertIsNone(self.hook("kubectl delete pods -l app=web -n prod"))

    def test_manifest_file(self):
        (self.project / "app.yaml").write_text("kind: ConfigMap\n")
        self.fake_tool("kubectl", [{"args": ["get", "-f"], "stdout": k8s_object("ConfigMap", "a", "default")}])
        self.assertEqual(self.backup("kubectl delete -f app.yaml")[0], 0)
        self.assertIsNone(self.hook("kubectl delete -f app.yaml"))
        (self.project / "app.yaml").write_text("kind: ConfigMap\n# changed\n")
        self.assertIsNotNone(self.hook("kubectl delete -f app.yaml"))  # other content: the backup no longer matches


class HelmBackup(Base):
    def test_release(self):
        self.kubeconfig("kind-prod")
        self.fake_tool("helm", [{"args": ["get", "all", "web"], "stdout": "NAME: web\nNAMESPACE: prod\nMANIFEST:\n"},
                                {"args": ["version"], "stdout": "v3.16.2+g13654a5\n"}])
        code, out, err = self.backup("helm uninstall web -n prod")
        self.assertEqual(code, 0, err)
        args = self.calls("helm")[0]["args"]
        self.assertEqual(args[:3], ["get", "all", "web"])
        self.assertIn("--kube-context=kind-prod", args)
        self.assertIn("--namespace=prod", args)
        self.assertIsNone(self.hook("helm uninstall web --namespace prod"))
        self.assertIsNotNone(self.hook("helm uninstall web"))  # no namespace given: another target

    def test_failures(self):
        self.kubeconfig()
        for rule, message in (({"stdout": ""}, "printed nothing"), ({"stdout": "\n\n"}, "printed nothing"),
                              ({"stdout": "NAME: other\n"}, "do not name release web"),
                              ({"rc": 1, "stderr": "Error: release: not found\n"}, "exited with 1")):
            with self.subTest(message=message):
                self.fake_tool("helm", [dict(rule, args=["get", "all"])])
                code, _, err = self.backup("helm uninstall web")
                self.assertEqual(code, 1)
                self.assertIn(message, err)


class GitBackupFailures(Base):
    def test_remote_without_the_branch(self):
        self.git_repo()
        self.fake_tool("git", [{"args": ["ls-remote"], "stdout": "abc\trefs/heads/other\n"}])
        code, _, err = self.backup("git push -f origin main")
        self.assertEqual(code, 1)
        self.assertIn("has no refs/heads/main", err)

    def test_fetched_commit_missing(self):
        self.git_repo()
        sha = "a" * 40
        self.fake_tool("git", [{"args": ["ls-remote"], "stdout": f"{sha}\trefs/heads/main\n"},
                               {"args": ["fetch"]}, {"args": ["cat-file"], "rc": 1}])
        code, _, err = self.backup("git push -f origin main")
        self.assertEqual(code, 1)
        self.assertIn("is not in the local repository", err)
        fetch = [c for c in self.calls("git") if "fetch" in c["args"]][0]
        self.assertIn("--refmap=", fetch["args"])
        self.assertEqual(fetch["env"]["GIT_TERMINAL_PROMPT"], "0")


class CliContract(Base):
    def test_exit_codes(self):
        self.assertEqual(self.cli()[0], 2)
        self.assertEqual(self.cli("--help")[0], 0)
        self.assertEqual(self.cli("--version")[1].strip(), f"destroy-guard {dg.VERSION}")
        self.assertEqual(self.cli("frobnicate")[0], 2)
        self.assertEqual(self.cli("backup")[0], 2)
        self.assertEqual(self.cli("backup", "--bogus", "--", "terraform", "destroy")[0], 2)
        self.assertEqual(self.cli("backup", "--cwd", str(self.tmp / "nope"), "--", "terraform", "destroy")[0], 2)
        code, _, err = self.cli("backup", "--cwd", str(self.project), "--", "ls", "-la")
        self.assertEqual(code, 2)
        self.assertIn("not a command destroy-guard knows as destructive", err)
        code, _, err = self.cli("backup", "--cwd", str(self.project), "--", "psql", "-c", "DROP TABLE t")
        self.assertEqual(code, 2)
        self.assertIn("pg_dump", err)
        code, _, err = self.cli("backup", "--cwd", str(self.project), "--", "kubectl", "delete", "pod", "$P")
        self.assertEqual(code, 2)

    def test_command_as_one_string_and_without_double_dash(self):
        self.fake_tool("terraform", [{"args": ["state", "pull"], "stdout": state_json()}])
        self.assertEqual(self.cli("backup", "--cwd", str(self.project), "terraform", "destroy")[0], 0)
        self.assertEqual(self.cli("backup", "--cwd", str(self.project), "--", "terraform destroy")[0], 0)

    def test_check(self):
        code, out, _ = self.cli("check", "--cwd", str(self.project), "--", "terraform", "destroy")
        self.assertEqual(code, 1)
        self.assertIn("make one:", out)
        self.assertEqual(self.cli("check", "--cwd", str(self.project), "--", "terraform", "plan")[0], 0)
        code, out, _ = self.cli("check", "--json", "--cwd", str(self.project), "--", "terraform destroy; dropdb x")
        data = json.loads(out)
        self.assertEqual([o["status"] for o in data["operations"]], ["missing", "manual"])
        self.assertEqual(data["window_minutes"], 30)

    def test_list_and_checksum_verification(self):
        self.fake_tool("terraform", [{"args": ["state", "pull"], "stdout": state_json()}])
        self.backup("terraform destroy")
        code, out, _ = self.cli("list", "--cwd", str(self.project))
        self.assertEqual(code, 0)
        self.assertIn("ok", out)
        [d] = self.backup_dirs()
        f = d / "terraform.tfstate"
        data = bytearray(f.read_bytes())
        data[0:1] = b"["  # same size, other content
        f.write_bytes(bytes(data))
        code, out, _ = self.cli("list", "--json", "--cwd", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("checksum differs", json.loads(out)["backups"][0]["status"])


@unittest.skipUnless(POSIX, "permission bits and symbolic links")
class StoreSafety(Base):
    def setUp(self):
        super().setUp()
        self.fake_tool("terraform", [{"args": ["state", "pull"], "stdout": state_json()}])

    def test_permissions(self):
        self.assertEqual(self.backup("terraform destroy")[0], 0)
        store = self.project / ".destroy-guard"
        [d] = self.backup_dirs()
        self.assertEqual([mode(p) for p in (store, store / "backups", d)], [0o700] * 3)
        self.assertTrue(all(mode(f) == 0o600 for f in d.iterdir()))
        self.assertEqual((store / ".gitignore").read_text().splitlines()[-1], "*")

    def test_loose_store_is_tightened(self):
        store = self.project / ".destroy-guard"
        store.mkdir(mode=0o755)
        os.chmod(store, 0o755)
        code, out, _ = self.backup("terraform destroy")
        self.assertEqual(code, 0)
        self.assertEqual(mode(store), 0o700)
        self.assertIn("tightened", out)

    def test_symlinked_store_is_refused(self):
        (self.tmp / "elsewhere").mkdir()
        (self.project / ".destroy-guard").symlink_to(self.tmp / "elsewhere")
        code, _, err = self.backup("terraform destroy")
        self.assertEqual(code, 2)
        self.assertIn("symbolic link", err)
        self.assertEqual(list((self.tmp / "elsewhere").iterdir()), [])


class GitExclude(Base):
    def setUp(self):
        super().setUp()
        self.fake_tool("terraform", [{"args": ["state", "pull"], "stdout": state_json()}])

    def test_added_once(self):
        self.git_repo()
        self.backup("terraform destroy")
        self.backup("terraform destroy")
        text = (self.project / ".git" / "info" / "exclude").read_text()
        self.assertEqual(text.count("/.destroy-guard/"), 1)

    def test_existing_file_without_newline(self):
        self.git_repo()
        (self.project / ".git" / "info").mkdir()
        (self.project / ".git" / "info" / "exclude").write_text("*.log")
        self.backup("terraform destroy")
        lines = (self.project / ".git" / "info" / "exclude").read_text().splitlines()
        self.assertEqual(lines[0], "*.log")
        self.assertIn("/.destroy-guard/", lines)

    def test_worktree_writes_to_the_common_dir(self):
        main = self.git_repo(self.tmp / "main")
        wtdir = main / ".git" / "worktrees" / "wt"
        wtdir.mkdir(parents=True)
        (wtdir / "HEAD").write_text("ref: refs/heads/wt\n")
        (wtdir / "commondir").write_text("../..\n")
        wt = self.tmp / "wt"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {wtdir}\n")
        self.assertEqual(self.backup("terraform destroy", cwd=wt)[0], 0)
        self.assertIn("/.destroy-guard/", (main / ".git" / "info" / "exclude").read_text())

    def test_outside_git_nothing_to_exclude(self):
        code, out, _ = self.backup("terraform destroy")
        self.assertEqual(code, 0)
        self.assertNotIn("info/exclude", out)
        self.assertTrue((self.project / ".destroy-guard" / ".gitignore").exists())


if __name__ == "__main__":
    unittest.main()
