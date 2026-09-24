"""Running handlers the way the hooks docs describe, reading what they print, and checking the case expectations."""
import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import PY, Isolated, hh, one_handler, py_handler, script  # noqa: E402

POSIX = os.name == "posix"
ASK = script('print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", '
             '"permissionDecisionReason": "asked about " + payload["tool_input"]["command"]}}))')


class Payload(Isolated):
    def test_common_and_tool_fields(self):
        case = {"event": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": "src/a.ts", "content": "x"}}
        p = hh.build_payload(case, "/work", "/h", "s1", "/t.jsonl")
        self.assertEqual({k for k in p}, {"session_id", "transcript_path", "cwd", "permission_mode", "hook_event_name",
                                         "tool_name", "tool_input", "tool_use_id"})
        self.assertEqual(p["tool_input"]["file_path"], os.path.normpath("/work/src/a.ts"))  # made absolute
        self.assertTrue(p["tool_use_id"].startswith("toolu_"))
        again = hh.build_payload(case, "/work", "/h", "s1", "/t.jsonl")
        self.assertNotEqual(p["tool_use_id"], again["tool_use_id"])  # a lock keyed on it must not block the next case

    def test_home_and_windows_paths(self):
        p = hh.build_payload({"event": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "~/x"}},
                             "/w", "/home/me", "s", "/t")
        self.assertEqual(p["tool_input"]["file_path"], "/home/me/x")
        p = hh.build_payload({"event": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "C:\\p\\a.ts"}},
                             "/w", "/h", "s", "/t")
        self.assertEqual(p["tool_input"]["file_path"], "C:\\p\\a.ts")

    def test_event_specific_fields_and_overrides(self):
        p = hh.build_payload({"event": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": "ls"}},
                             "/w", "/h", "s", "/t")
        self.assertNotIn("tool_use_id", p)  # PermissionRequest input has no tool_use_id
        p = hh.build_payload({"event": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"},
                              "tool_response": {"stdout": "x"}, "payload": {"permission_mode": "plan"}}, "/w", "/h", "s", "/t")
        self.assertEqual((p["tool_response"], p["permission_mode"]), ({"stdout": "x"}, "plan"))
        p = hh.build_payload({"event": "SessionStart", "payload": {"source": "startup"}}, "/w", "/h", "s", "/t")
        self.assertNotIn("permission_mode", p)


class Running(Isolated):
    def run_one(self, handler_extra=None, body=ASK, event="PreToolUse", tool="Bash", tool_input=None, expect=None,
                extra_scripts=None, **top):
        hooks = self.plugin(one_handler(event, None, py_handler("h.py", **(handler_extra or {}))),
                            dict({"h.py": body}, **(extra_scripts or {})))
        case = {"name": "c", "event": event, "tool_name": tool, "tool_input": tool_input or {"command": "npm i x"},
                "expect": expect or {}}
        cases = self.cases([case], **top)
        code, out, err = self.main("run", hooks, cases, "--json", "--scratch-home")
        self.assertIn(code, (0, 1, 2), err)
        return code, json.loads(out)["cases"][0] if out else None, err

    def test_the_payload_and_placeholders_reach_the_script(self):
        body = script('print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": '
                      'json.dumps([payload["hook_event_name"], payload["tool_input"], os.environ["CLAUDE_PLUGIN_ROOT"], '
                      'os.environ["CLAUDE_PROJECT_DIR"], os.environ["HOME"], os.getcwd(), sys.argv[1:]])}}))')
        code, case, _ = self.run_one(body=body, expect={"handlers": 1})
        self.assertEqual(code, 0)
        event, tool_input, root, project, home, cwd, argv = json.loads(case["runs"][0]["contexts"][0])
        self.assertEqual((event, tool_input), ("PreToolUse", {"command": "npm i x"}))
        self.assertEqual(Path(root), (self.tmp / "plugin").resolve())
        self.assertNotEqual(home, str(self.home))  # --scratch-home
        self.assertEqual(Path(cwd).resolve(), Path(project).resolve())

    def test_exec_form_passes_each_argument_verbatim(self):
        hooks = self.plugin(one_handler("PreToolUse", "Bash", {"type": "command", "command": sys.executable,
                                                               "args": ["${CLAUDE_PLUGIN_ROOT}/h.py", "a b", "$HOME", "`x`"]}),
                            {"h.py": script('print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", '
                                            '"additionalContext": json.dumps(sys.argv[1:])}}))')})
        code, out, _ = self.main("run", hooks, self.cases([{"tool_name": "Bash", "tool_input": {"command": "x"}}]), "--json")
        self.assertEqual(json.loads(json.loads(out)["cases"][0]["runs"][0]["contexts"][0]), ["a b", "$HOME", "`x`"])

    @unittest.skipUnless(POSIX, "process groups")
    def test_timeout_kills_the_handler_and_its_children(self):
        body = script("import subprocess\nsubprocess.Popen(['sleep', '30'])\ntime.sleep(30)")
        start = time.monotonic()
        code, case, _ = self.run_one({"timeout": 1}, body=body, expect={"decision": "none"})
        took = time.monotonic() - start
        self.assertLess(took, 12)
        run = case["runs"][0]
        self.assertTrue(run["timed_out"])
        self.assertIn("discards the output", run["outcome"])
        self.assertEqual(code, 1)  # a timed-out handler fails its case

    def test_parallel_handlers_and_max_duration(self):
        slow = script("time.sleep(1)")
        hooks = self.plugin({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            py_handler("a.py"), py_handler("b.py"), py_handler("c.py")]}]}}, {"a.py": slow, "b.py": slow, "c.py": slow})
        cases = self.cases([{"name": "p", "tool_name": "Bash", "tool_input": {"command": "x"},
                             "expect": {"handlers": 3, "max_duration": 2.8}}])
        code, out, _ = self.main("run", hooks, cases)
        self.assertEqual(code, 0, out)  # three one-second handlers in parallel take about one second

    def test_ask_decision_and_reason(self):
        code, case, _ = self.run_one(expect={"decision": "ask", "reason_contains": "npm i x", "max_handlers": 1})
        self.assertEqual((code, case["status"], case["decision"]), (0, "pass", "ask"))

    def test_failed_expectations_exit_1(self):
        code, case, _ = self.run_one(expect={"decision": "deny", "context_contains": "nothing like this"})
        self.assertEqual((code, case["status"]), (1, "fail"))
        self.assertEqual([c["ok"] for c in case["checks"]], [False, False])

    def test_exit_2_denies_with_stderr_as_reason(self):
        code, case, _ = self.run_one(body=script('sys.stderr.write("blocked: no\\n"); sys.exit(2)'),
                                     expect={"decision": "deny", "reason_contains": "blocked: no"})
        self.assertEqual(code, 0)

    def test_exit_1_is_a_non_blocking_error(self):
        code, case, _ = self.run_one(body=script('sys.exit(1)'), expect={"decision": "none"})
        self.assertIn("non-blocking error (exit 1)", case["runs"][0]["outcome"])

    def test_missing_script_is_reported(self):
        code, case, _ = self.run_one(body=None or script(""), extra_scripts={},
                                     handler_extra={"command": f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/missing.py"'},
                                     expect={"decision": "none"})
        self.assertNotEqual(case["runs"][0]["exit_code"], 0)

    def test_unicode_and_non_utf8_output(self):
        body = script('sys.stdout.buffer.write(b"\\xff\\xfe not text")')
        _code, case, _ = self.run_one(body=body)
        self.assertIn("stdout is not valid UTF-8", json.dumps(case["runs"][0]["problems"]))
        body = script('print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": '
                      '"ask", "permissionDecisionReason": "Paket für Größe ✓ " + payload["tool_input"]["command"]}}))')
        code, case, _ = self.run_one(body=body, tool_input={"command": "npm i ünïcode-✓"},
                                     expect={"reason_contains": "Größe ✓ npm i ünïcode-✓"})
        self.assertEqual(code, 0)

    def test_huge_output_is_capped(self):
        _code, case, _ = self.run_one(body=script('sys.stdout.write("x" * 3000000)'))
        self.assertIn("only the start was kept", json.dumps(case["runs"][0]["problems"]))

    def test_user_config_in_shell_form_fails_as_documented(self):
        hooks = self.plugin(one_handler("PreToolUse", "Bash", {"type": "command", "command": "echo ${user_config.url}"}))
        code, out, _ = self.main("run", hooks, self.cases([{"tool_name": "Bash", "tool_input": {"command": "x"}}]), "--json")
        self.assertIn("fails with an error instead of running", out)
        self.assertEqual(code, 1)  # Claude Code fails the same way: a real failure, not a harness gap
        hooks = self.plugin(one_handler("PreToolUse", "Bash", {"type": "command", "command": sys.executable,
                                                               "args": ["-c", "print()", "${user_config.url}"]}))
        code, out, _ = self.main("run", hooks, self.cases([{"tool_name": "Bash", "tool_input": {"command": "x"}}]))
        self.assertEqual(code, 2)  # the cases file gave no value: this run could not check the handler
        self.assertIn("could not run", out)
        cases = self.cases([{"tool_name": "Bash", "tool_input": {"command": "x"}}], user_config={"url": "https://e.x"})
        self.assertEqual(self.main("run", hooks, cases)[0], 0)

    def test_dry_run_runs_nothing(self):
        marker = self.tmp / "ran"
        body = script(f"open({str(marker)!r}, 'w').close()")
        code, case, _ = self.run_one(body=body, expect={"handlers": 1})
        self.assertTrue(marker.exists())
        marker.unlink()
        hooks = self.plugin(one_handler("PreToolUse", None, py_handler("h.py")), {"h.py": body})
        code, out, _ = self.main("run", hooks, self.cases([{"tool_name": "Bash", "tool_input": {"command": "x"},
                                                             "expect": {"handlers": 1}}]), "--dry-run")
        self.assertEqual(code, 0)
        self.assertFalse(marker.exists())
        self.assertIn("not run", out)


class OutputShape(unittest.TestCase):
    def problems(self, event, obj):
        return [m for _s, m in hh.validate_output(event, obj)]

    def test_valid_documented_examples(self):
        # hooks docs examples: PreToolUse decision control, PostToolUse context, PermissionRequest allow
        self.assertEqual(self.problems("PreToolUse", {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow", "permissionDecisionReason": "r",
            "updatedInput": {"field_to_modify": "v"}, "additionalContext": "c"}}), [])
        self.assertEqual(self.problems("PostToolUse", {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                                              "additionalContext": "c"}}), [])
        self.assertEqual(self.problems("PermissionRequest", {"hookSpecificOutput": {
            "hookEventName": "PermissionRequest", "decision": {"behavior": "allow", "updatedInput": {"command": "x"}}}}),
            [])
        self.assertEqual(self.problems("Stop", {"decision": "block", "reason": "tests fail"}), [])

    def test_mismatches(self):
        cases = [
            ("PreToolUse", {"hookSpecificOutput": {"hookEventName": "PostToolUse", "permissionDecision": "ask"}},
             "hookEventName is 'PostToolUse'"),
            ("PreToolUse", {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "maybe"}},
             "permissionDecision must be one of"),
            ("PreToolUse", {"hookSpecificOutput": {"permissionDecision": "ask"}}, "has no hookEventName"),
            ("PreToolUse", {"permissionDecision": "deny"}, "belongs inside hookSpecificOutput"),
            ("PostToolUse", {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": 5}},
             "additionalContext must be a string"),
            ("PostToolUse", {"decision": "deny"}, "must be \"block\""),
            ("PreToolUse", {"decision": "approve"}, "deprecated"),
            ("PreToolUse", {"hookSpecificOutput": "ask"}, "must be an object"),
            ("PreToolUse", {"continue": "no"}, "continue must be true or false"),
            ("PreToolUse", {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "x" * 10001}},
             "10,000"),
            ("SessionStart", {"hookSpecificOutput": {"hookEventName": "SessionStart", "permissionDecision": "allow"}},
             "not a documented field"),
        ]
        for event, obj, fragment in cases:
            self.assertTrue(any(fragment in m for m in self.problems(event, obj)), (obj, self.problems(event, obj)))

    def test_classify_stdout(self):
        self.assertEqual(hh.classify_stdout("")[0], "empty")
        self.assertEqual(hh.classify_stdout("  {\"a\": 1}\n")[0], "json")
        self.assertEqual(hh.classify_stdout("Shell ready\n{\"decision\": \"block\"}")[0], "plain")  # hooks guide
        self.assertEqual(hh.classify_stdout("{\"a\": 1}\n{\"b\": 2}")[0], "plain")
        self.assertEqual(hh.classify_stdout("{\"a\": 1}\n{\"continue\": false}")[0], "parse-failure")
        self.assertEqual(hh.classify_stdout("{not json}")[0], "parse-failure")
        self.assertEqual(hh.classify_stdout("[1, 2]")[0], "plain")


class Decisions(unittest.TestCase):
    def reading(self, event, stdout="", code=0, stderr=""):
        return hh.read_run(event, hh.Run(label="h", exit_code=code, stdout=stdout, stderr=stderr, timeout=5))

    def test_precedence_deny_defer_ask_allow(self):
        def pre(d):
            return self.reading("PreToolUse", json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                                                  "permissionDecision": d}}))
        self.assertEqual(hh.combine("PreToolUse", [pre("allow"), pre("ask"), pre("defer")]), "defer")
        self.assertEqual(hh.combine("PreToolUse", [pre("ask"), pre("deny"), pre("allow")]), "deny")
        self.assertEqual(hh.combine("PreToolUse", [pre("allow"), self.reading("PreToolUse")]), "allow")
        self.assertEqual(hh.combine("PreToolUse", [self.reading("PreToolUse")]), "none")

    def test_exit_codes(self):
        self.assertEqual(self.reading("PreToolUse", code=2, stderr="no").decision, "deny")
        self.assertEqual(self.reading("PermissionRequest", code=2).decision, None)  # exit 2 not honoured there
        r = self.reading("PostToolUse", code=2, stderr="look at this")
        self.assertEqual((r.decision, r.reasons), (None, ["look at this"]))  # shown to Claude, nothing blocked
        valid = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask"}})
        self.assertEqual(self.reading("PreToolUse", valid, code=1).decision, "ask")  # valid JSON decides alone

    def test_plain_stdout_is_context_only_on_some_events(self):
        self.assertEqual(self.reading("SessionStart", "branch main").contexts, ["branch main"])
        r = self.reading("PreToolUse", "hello")
        self.assertEqual(r.contexts, [])
        self.assertIn("debug log only", json.dumps(r.problems))

    def test_async_handlers_decide_nothing(self):
        r = hh.read_run("PreToolUse", hh.Run(label="h", exit_code=2, stderr="x"), is_async=True)
        self.assertIsNone(r.decision)


class CaseFiles(Isolated):
    def load(self, data):
        p = self.tmp / "c.json"
        p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return hh.load_suite(p)

    def test_errors_name_the_problem(self):
        bad = [("[", "JSON syntax error"), ("{}", "non-empty list"), ([], "non-empty list"), ([1], "not an object"),
               ([{"tool_name": "Bash", "expect": {"max_handler": 1}}], "unknown expectation"),
               ([{"tool_name": "Bash", "expect": {"decision": "maybe"}}], "decision must be"),
               ([{"tool_name": "bash"}], "tool names are case-sensitive: Bash"),
               ([{"tool_name": "Frobnicate"}], "unknown tool_name"),
               ([{"event": "PreToolUse"}], "needs tool_name"), ([{"event": "preToolUse", "tool_name": "Bash"}], "unknown event"),
               ([{"event": "SessionStart"}], "payload.source"),
               ([{"tool_name": "Bash", "expect": {"max_duration": -1}}], "positive number"),
               ([{"tool_name": "Bash", "expect": {"handlers": True}}], "whole number"),
               ([{"name": "a", "tool_name": "Bash"}, {"name": "a", "tool_name": "Bash"}], "used twice"),
               ({"cases": [{"tool_name": "Bash"}], "cwd": "x"}, "unknown top-level key"),
               ([{"tool_name": "Bash", "colour": 1}], "unknown key")]
        for data, fragment in bad:
            with self.assertRaises(hh.CaseFileError, msg=str(data)) as cm:
                self.load(data)
            self.assertIn(fragment, str(cm.exception), data)

    def test_not_utf8(self):
        p = self.tmp / "c.json"
        p.write_bytes(b"\xff\xfe[")
        with self.assertRaises(hh.CaseFileError):
            hh.load_suite(p)


if __name__ == "__main__":
    unittest.main()
