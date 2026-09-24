"""The transcript scan and --redact: counts per type, JSON validity, backups, idempotence, refusals."""
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated, Tty, cr, synthetic  # noqa: E402

rand = synthetic.rand


class Transcripts(Isolated):
    def setUp(self):
        super().setUp()
        self.c = synthetic.canaries()
        self.dir = self.home / ".claude" / "projects" / "-work-app"
        self.session = self.write(".claude/projects/-work-app/s1.jsonl",
                                  "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n"
                                          for x in synthetic.transcript_lines(self.c)))
        self.clean = self.write(".claude/projects/-work-app/s2.jsonl", '{"type":"user","message":"hi"}\n')
        self.sub = self.write(".claude/projects/-work-app/s1/subagents/a.jsonl",
                              json.dumps({"content": "key " + self.c["anthropic"]}) + "\n")
        self.old = self.write(".claude/projects/-work-app/s0.jsonl.superseded-20260901",
                              json.dumps({"content": "npm " + self.c["npm"]}) + "\n")

    def redact(self, answer="redact", extra=()):
        return self.run_main(["--redact", *extra], stdin=Tty(answer + "\n"))

    def secrets(self):
        return [self.c[k] for k in ("gh_classic", "aws_id", "ssh_private", "transcript_password", "anthropic", "npm")]

    def test_scan_counts_per_file_and_type(self):
        sec, hits = cr.scan_transcripts(self.ctx())
        by_file = {p.name: counts for p, counts, _ in hits}
        self.assertEqual(by_file["s1.jsonl"], {"github-classic-pat": 1, "aws-access-key-id": 1, "private-key": 1,
                                               "url-password": 1})
        self.assertEqual(by_file["a.jsonl"], {"anthropic-api-key": 1})
        self.assertEqual(by_file["s0.jsonl.superseded-20260901"], {"npm-token": 1})
        self.assertNotIn("s2.jsonl", by_file)
        out = json.dumps(sec.as_dict())
        for s in self.secrets():
            self.assertNotIn(s, out)
        self.assertIn("in 3 of 4 files", sec.notes[0])

    def test_redact_keeps_json_valid_and_backs_up_first(self):
        before = {p: p.read_bytes() for p in (self.session, self.clean, self.sub, self.old)}
        mode = 0o640
        os.chmod(self.session, mode)
        code, out, err = self.redact()
        self.assertEqual(code, 0, err)
        for p in (self.session, self.sub, self.old):
            text = p.read_text(encoding="utf-8")
            for line in text.splitlines():
                json.loads(line)  # every line still parses
            for s in self.secrets():
                self.assertNotIn(s, text)
        self.assertEqual(self.clean.read_bytes(), before[self.clean])  # untouched
        lines = self.session.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 5)
        self.assertIn("[REDACTED:github-classic-pat]", lines[0])
        self.assertIn("postgres://app:[REDACTED:url-password]@db.internal:5432/app", lines[3])
        self.assertIn("Grüße", lines[3])  # untouched text keeps its characters
        self.assertEqual(json.loads(lines[4]), synthetic.transcript_lines(self.c)[4])
        if os.name != "nt":
            self.assertEqual(self.session.stat().st_mode & 0o777, mode)
        backups = list((self.home / ".claude" / "credential-reach-backups").rglob("*.jsonl*"))
        self.assertEqual(len(backups), 3)
        for b in backups:
            original = next(p for p in before if p.name == b.name)
            self.assertEqual(b.read_bytes(), before[original])
        for s in self.secrets():
            self.assertNotIn(s, out + err)

    def test_second_run_changes_nothing(self):
        self.assertEqual(self.redact()[0], 0)
        after = {p: p.read_bytes() for p in (self.session, self.sub, self.old)}
        code, out, err = self.redact()
        self.assertEqual(code, 0)
        self.assertIn("nothing to redact", out)
        self.assertEqual({p: p.read_bytes() for p in after}, after)
        self.assertEqual(len(list((self.home / ".claude" / "credential-reach-backups").iterdir())), 1)

    def test_declined_or_no_terminal_changes_nothing(self):
        before = self.session.read_bytes()
        code, _, err = self.redact("yes")
        self.assertEqual(code, 1)
        self.assertIn("nothing changed", err)
        code, _, err = self.run_main(["--redact"], stdin=io.StringIO("redact\n"))  # piped, not typed
        self.assertEqual(code, 2)
        self.assertIn("not one", err)
        self.assertEqual(self.session.read_bytes(), before)
        self.assertFalse((self.home / ".claude" / "credential-reach-backups").exists())

    def test_symlinked_transcripts_are_skipped(self):
        target = self.write("elsewhere/t.jsonl", json.dumps({"x": "ghp_" + rand(36)}) + "\n")
        try:
            os.symlink(target, self.dir / "link.jsonl")
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks here")
        self.assertNotIn("link.jsonl", [p.name for p in cr.transcript_files(self.ctx())[1]])

    def test_json_result(self):
        code, out, _ = self.redact(extra=["--json"])
        data = json.loads(out)
        self.assertEqual(len(data["redacted"]), 3)
        self.assertEqual(data["failed"], [])
        for s in self.secrets():
            self.assertNotIn(s, out)


class Lines(unittest.TestCase):
    def test_raw_replacement_that_would_break_an_escape_falls_back_to_json(self):
        # "\n" followed by "pm_..." is a newline then text in JSON; a raw pattern would bite into the escape
        tok = "npm_" + rand(36)
        body = json.dumps({"a": "x\n" + tok[1:], "b": "real " + tok}).encode()
        new, counts = cr.redact_line(body)
        self.assertEqual(counts, {"npm-token": 1})
        obj = json.loads(new)
        self.assertEqual(obj["a"], "x\n" + tok[1:])
        self.assertEqual(obj["b"], "real [REDACTED:npm-token]")

    def test_key_block_with_escaped_newlines(self):
        key = synthetic.openssh_key()
        body = json.dumps({"out": "before\n" + key + "after"}).encode()
        new, counts = cr.redact_line(body)
        self.assertEqual(counts, {"private-key": 1})
        self.assertEqual(json.loads(new)["out"], "before\n[REDACTED:private-key]\nafter")

    def test_truncated_key_block(self):
        key = synthetic.openssh_key()
        new, counts = cr.redact_line(json.dumps({"out": key[:200]}).encode())
        self.assertEqual(json.loads(new)["out"], "[REDACTED:private-key]")

    def test_invalid_utf8_and_non_json_lines_keep_their_other_bytes(self):
        tok = "ghp_" + rand(36)
        body = b'{"broken": "\xff\xfe ' + tok.encode() + b'"}'
        new, counts = cr.redact_line(body)
        self.assertEqual(counts, {"github-classic-pat": 1})
        self.assertEqual(new, b'{"broken": "\xff\xfe [REDACTED:github-classic-pat]"}')
        new, _ = cr.redact_line(b"not json " + tok.encode())
        self.assertEqual(new, b"not json [REDACTED:github-classic-pat]")

    def test_unicode_escapes_and_line_endings(self):
        tok = "ghp_" + rand(36)
        body = ('{"t":"caf\\u00e9 ' + tok + '","n":1.5e3,"k":[true,null]}').encode()
        new, _ = cr.redact_line(body)
        self.assertEqual(new, ('{"t":"caf\\u00e9 [REDACTED:github-classic-pat]","n":1.5e3,"k":[true,null]}').encode())
        self.assertEqual(cr._split_ending(b"x\r\n"), (b"x", b"\r\n"))
        self.assertEqual(cr._split_ending(b"x"), (b"x", b""))


class RedactFile(Isolated):
    def test_crlf_blank_lines_and_a_last_line_without_newline(self):
        tok = "ghp_" + rand(36)
        p = self.write("t.jsonl", ('{"a":"' + tok + '"}\r\n\r\n{"b":1}').encode())
        counts, why = cr.redact_file(p, self.tmp / "bk" / "t.jsonl")
        self.assertEqual((counts, why), ({"github-classic-pat": 1}, ""))
        self.assertEqual(p.read_bytes(), b'{"a":"[REDACTED:github-classic-pat]"}\r\n\r\n{"b":1}')

    def test_a_file_written_to_meanwhile_is_left_alone(self):
        tok = "ghp_" + rand(36)
        p = self.write("t.jsonl", '{"a":"' + tok + '"}\n')
        before = p.read_bytes()
        real_copy = cr.shutil.copy2

        def copy_then_append(src, dst):
            real_copy(src, dst)
            with open(p, "ab") as f:  # a session appends a line after the backup was taken
                f.write(b'{"new":1}\n')

        with mock.patch.object(cr.shutil, "copy2", copy_then_append):
            counts, why = cr.redact_file(p, self.tmp / "bk" / "t.jsonl")
        self.assertEqual(counts, {})
        self.assertIn("changed while being redacted", why)
        self.assertEqual(p.read_bytes(), before + b'{"new":1}\n')
        self.assertFalse((self.tmp / "bk" / "t.jsonl").exists())
        self.assertEqual([x.name for x in p.parent.iterdir() if x.name.endswith(".tmp")], [])

    def test_nothing_to_do_leaves_no_temp_file(self):
        p = self.write("t.jsonl", '{"a":1}\n')
        self.assertEqual(cr.redact_file(p, self.tmp / "bk" / "t.jsonl"), ({}, ""))
        self.assertEqual(sorted(x.name for x in p.parent.iterdir()), ["t.jsonl"])


if __name__ == "__main__":
    unittest.main()
