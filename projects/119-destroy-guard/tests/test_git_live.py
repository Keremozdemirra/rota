"""The force-push flow end to end with the real git: a bare remote, two clones, a backup, a force push."""
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated  # noqa: E402


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class ForcePushEndToEnd(Isolated):
    def git(self, *args, cwd, check=True):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@example.invalid")
        p = subprocess.run(["git", "-c", "init.defaultBranch=main", *args], cwd=cwd, env=env, capture_output=True,
                           text=True)
        if check and p.returncode:
            self.fail(f"git {' '.join(args)}: {p.stderr}")
        return p

    def commit(self, repo, text):
        (repo / "f.txt").write_text(text)
        self.git("add", "f.txt", cwd=repo)
        self.git("commit", "-qm", text, cwd=repo)
        return self.git("rev-parse", "HEAD", cwd=repo).stdout.strip()

    def test_backup_keeps_the_overwritten_commit(self):
        remote, a, b = self.tmp / "remote.git", self.tmp / "a", self.tmp / "b"
        self.git("init", "-q", "--bare", str(remote), cwd=self.tmp)
        self.git("clone", "-q", str(remote), str(a), cwd=self.tmp)
        c1 = self.commit(a, "one")
        self.git("push", "-q", "origin", "main", cwd=a)
        self.git("clone", "-q", str(remote), str(b), cwd=self.tmp)
        c2 = self.commit(b, "two, pushed by someone else")
        self.git("push", "-q", "origin", "main", cwd=b)
        self.git("commit", "-q", "--amend", "-m", "one, rewritten", cwd=a)  # a has not seen c2

        command = "git push --force origin main"
        self.assertEqual(self.hook(command, cwd=a)["hookSpecificOutput"]["permissionDecision"], "ask")
        code, out, err = self.cli("backup", "--cwd", str(a), "--", *command.split())
        self.assertEqual(code, 0, err)
        self.assertIn(f"refs/heads/main on origin was {c2}", out)
        refs = self.git("for-each-ref", "--format=%(refname) %(objectname)", "refs/destroy-guard", cwd=a).stdout.split()
        self.assertEqual(len(refs), 2)
        self.assertTrue(refs[0].startswith("refs/destroy-guard/main-"))
        self.assertEqual(refs[1], c2)
        # the backup did not move origin/main, so --force-with-lease still refuses on stale information
        self.assertEqual(self.git("rev-parse", "origin/main", cwd=a).stdout.strip(), c1)
        lease = self.git("push", "--force-with-lease", "origin", "main", cwd=a, check=False)
        self.assertNotEqual(lease.returncode, 0)
        self.assertIn("stale info", lease.stderr)

        self.assertIsNone(self.hook(command, cwd=a))  # a verified backup: the normal permission flow decides
        self.git("push", "-q", "--force", "origin", "main", cwd=a)
        self.assertNotEqual(self.git("rev-parse", "main", cwd=remote).stdout.strip(), c2)
        self.assertEqual(self.git("cat-file", "-t", refs[0], cwd=a).stdout.strip(), "commit")
        self.assertEqual(self.git("rev-parse", refs[0], cwd=a).stdout.strip(), c2)  # c2 can be pushed back
        exclude = (a / ".git" / "info" / "exclude").read_text()
        self.assertIn("/.destroy-guard/", exclude)
        self.assertEqual(self.git("status", "--porcelain", cwd=a).stdout, "")  # the store is not untracked noise


if __name__ == "__main__":
    unittest.main()
