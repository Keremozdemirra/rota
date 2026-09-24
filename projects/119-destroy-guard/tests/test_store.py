"""Manifest matching: only a fresh, verified, intact backup of exactly the same target counts."""
import datetime as dt
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated, minutes_ago  # noqa: E402

import destroy_guard as dg  # noqa: E402

POSIX = os.name == "posix"


class Matching(Isolated):
    def setUp(self):
        super().setUp()
        self.op = self.ops("terraform destroy -auto-approve")[0]
        self.target = self.op["targets"][0]

    def status(self, op=None):
        return dg.find_backup(op or self.op)

    def test_exact_target_covers(self):
        self.assertEqual(self.status()["status"], "missing")
        d = self.write_backup([self.target])
        r = self.status()
        self.assertEqual(r["status"], "covered")
        self.assertEqual(r["backups"][0][0], d)

    def test_other_workspace_directory_or_tool_does_not(self):
        for change in ({"workspace": "prod"}, {"dir": str(self.project / "other")}, {"tool": "tofu"}):
            with self.subTest(change=change):
                self.write_backup([dict(self.target, **change)])
                self.assertEqual(self.status()["status"], "missing")

    def test_freshness_window(self):
        self.write_backup([self.target], created=minutes_ago(31))
        r = self.status()
        self.assertEqual(r["status"], "missing")
        self.assertEqual(round(r["newest_age"].total_seconds() / 60), 31)
        self.write_backup([self.target], created=minutes_ago(29))
        self.assertEqual(self.status()["status"], "covered")

    def test_window_is_configurable_and_bad_values_fall_back(self):
        self.write_backup([self.target], created=minutes_ago(10))
        with mock.patch.dict(os.environ, {dg.MAX_AGE_ENV: "5"}):
            self.assertEqual(dg.max_age(), dt.timedelta(minutes=5))
            self.assertEqual(self.status()["status"], "missing")
        for bad in ("abc", "-1", "0", "nan", "1e9", ""):
            with mock.patch.dict(os.environ, {dg.MAX_AGE_ENV: bad}):
                self.assertEqual(dg.max_age(), dt.timedelta(minutes=30), bad)

    def test_future_dates(self):
        self.write_backup([self.target], created=dg.now_utc() + dt.timedelta(seconds=30))
        self.assertEqual(self.status()["status"], "covered")  # a clock a little ahead
        for d in (self.project / ".destroy-guard" / "backups").iterdir():
            import shutil
            shutil.rmtree(d)
        self.write_backup([self.target], created=dg.now_utc() + dt.timedelta(days=365))
        self.assertEqual(self.status()["status"], "missing")  # not a backup of now

    @unittest.skipUnless(POSIX, "permission bits")
    def test_directory_readable_by_others_is_ignored(self):
        self.write_backup([self.target], mode=0o755)  # what a git checkout or a copy would give
        self.assertEqual(self.status()["status"], "missing")

    def test_tampered_or_incomplete_backups_are_ignored(self):
        d = self.write_backup([self.target], files={"terraform.tfstate": b'{"serial": 1}'})
        self.assertEqual(self.status()["status"], "covered")
        (d / "terraform.tfstate").write_bytes(b"{}")  # other size
        self.assertEqual(self.status()["status"], "missing")
        (d / "terraform.tfstate").unlink()
        self.assertEqual(self.status()["status"], "missing")

    def test_malformed_manifests(self):
        bodies = [b"not json", b"\xff\xfe", b"[]", b"null", json.dumps({"format": 2}).encode(),
                  json.dumps({"format": 1, "verified": "yes"}).encode()]
        for i, body in enumerate(bodies):
            d = self.write_backup([self.target], name=f"20260924T10000{i}Z-{'a' * 12}")
            (d / "manifest.json").write_bytes(body)
        d = self.write_backup([self.target], verified=False)
        m = json.loads((d / "manifest.json").read_text())
        m["verified"] = False
        self.assertEqual(self.status()["status"], "missing")
        d = self.write_backup([self.target])
        m = json.loads((d / "manifest.json").read_text())
        m["exports"] = [{"file": "../../../etc/passwd", "bytes": 1}]
        (d / "manifest.json").write_text(json.dumps(m))
        self.assertEqual(self.status()["status"], "missing")
        m["exports"], m["created_utc"] = [], "2026-09-24T10:00:00Z"
        (d / "manifest.json").write_text(json.dumps(m))
        self.assertEqual(self.status()["status"], "missing")

    def test_oversized_manifest_is_not_read(self):
        d = self.write_backup([self.target])
        with open(d / "manifest.json", "ab") as f:
            f.write(b" " * (dg.MAX_MANIFEST_BYTES + 10))
        self.assertEqual(self.status()["status"], "missing")

    def test_every_object_must_be_covered(self):
        self.kubeconfig()
        op = self.ops("kubectl delete pods web api -n prod")[0]
        web, api = op["targets"]
        self.write_backup([web])
        self.assertEqual(dg.find_backup(op)["status"], "missing")
        self.write_backup([api])
        self.assertEqual(dg.find_backup(op)["status"], "covered")  # two backups, one object each

    def test_backup_of_more_covers_less(self):
        self.kubeconfig()
        both = self.ops("kubectl delete pods web api -n prod")[0]
        self.write_backup(both["targets"])
        self.assertEqual(dg.find_backup(self.ops("kubectl delete pod web -n prod")[0])["status"], "covered")

    def test_stray_directories_and_targets_are_ignored(self):
        root = self.project / ".destroy-guard" / "backups"
        root.mkdir(parents=True)
        (root / "notes").mkdir()
        (root / "20260924T100000Z-" ).mkdir()
        (root / "README").write_text("x")
        d = self.write_backup(["not a dict", 5, self.target])
        self.assertEqual(self.status()["backups"][0][0], d)

    def test_store_location(self):
        self.git_repo()
        (self.project / "a" / "b").mkdir(parents=True)
        self.assertEqual(dg.store_dir(self.project / "a" / "b"), self.project / ".destroy-guard")
        self.assertEqual(dg.store_dir(self.tmp), self.tmp / ".destroy-guard")
        with mock.patch.dict(os.environ, {dg.STORE_ENV: str(self.tmp / "vault")}):
            self.assertEqual(dg.store_dir(self.project), self.tmp / "vault")
            self.write_backup([self.target], store=self.tmp / "vault")
            self.assertEqual(self.status()["status"], "covered")

    def test_terraform_backup_found_from_the_target_directory_store(self):
        # backup made from inside infra/ (no git): the store sits there, and the hook, running
        # `terraform -chdir=infra destroy` from the parent, looks there too
        (self.project / "infra").mkdir()
        op = self.ops("terraform -chdir=infra destroy")[0]
        self.write_backup(op["targets"], store=self.project / "infra" / ".destroy-guard")
        self.assertEqual(dg.find_backup(op)["status"], "covered")


class Evaluate(Isolated):
    def test_statuses(self):
        self.git_repo()
        results = dg.evaluate("terraform destroy; psql -c 'DROP TABLE t'; kubectl delete pod $P; echo hi",
                              "bash", str(self.project))
        self.assertEqual([r["status"] for r in results], ["missing", "manual", "unresolved"])

    def test_reason_text(self):
        results = dg.evaluate("terraform destroy -auto-approve", "bash", str(self.project))
        text = dg.reason(results, str(self.project))
        self.assertIn(f"`terraform destroy` destroys everything in the Terraform state of {self.project}", text)
        self.assertIn("No backup of it from the last 30 min.", text)
        self.assertIn("backup -- terraform destroy -auto-approve` on its own first.", text)
        self.assertIn("The 30 min window is destroy-guard's own choice", text)
        self.assertIn("not the data inside databases or volumes", text)
        self.write_backup(results[0]["op"]["targets"], created=minutes_ago(125))
        text = dg.reason(dg.evaluate("terraform destroy -auto-approve", "bash", str(self.project)), str(self.project))
        self.assertIn("The newest backup of it is 2 h 5 min old", text)

    def test_reason_is_bounded_and_single_line(self):
        cmd = " && ".join(f"kubectl delete pod p{i} -n $NS{i}" for i in range(200))
        self.kubeconfig()
        text = dg.reason(dg.evaluate(cmd, "bash", str(self.project)), str(self.project))
        self.assertLessEqual(len(text), dg.MAX_REASON)
        self.assertNotIn("\n", text)

    def test_fmt_age(self):
        self.assertEqual([dg.fmt_age(dt.timedelta(seconds=s)) for s in (-5, 42, 600, 7500, 200000)],
                         ["0 s", "42 s", "10 min", "2 h 5 min", "2 d 7 h"])


if __name__ == "__main__":
    unittest.main()
