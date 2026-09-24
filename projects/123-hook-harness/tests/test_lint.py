"""Static checks on crafted hooks files and on real ones (mcp-vitals and pkg-vitals, current and earlier versions)."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import FIXTURES, Isolated, fixture, hh  # noqa: E402

CMD = {"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/h.py\""}


class Lint(Isolated):
    def lint(self, hooks, scripts=("h.py",), text=None, kind="plugin"):
        if kind == "plugin":
            path = self.plugin(hooks if text is None else {}, {s: "" for s in scripts})
        else:
            path = self.tmp / "settings.json"
        if text is not None:
            path.write_text(text, encoding="utf-8")
        elif kind != "plugin":
            path.write_text(json.dumps(hooks), encoding="utf-8")
        return hh.lint(hh.load_source(path))

    def rules(self, findings):
        return {f.rule for f in findings}

    def assertFinds(self, findings, rule, severity=None, fragment=""):
        hits = [f for f in findings if f.rule == rule and (severity is None or f.severity == severity)
                and fragment in f.message]
        self.assertTrue(hits, f"{rule} not in {[(f.rule, f.message) for f in findings]}")
        return hits[0]

    def test_clean_file(self):
        hooks = {"hooks": {"PreToolUse": [{"matcher": "Bash|PowerShell", "hooks": [dict(CMD, timeout=20)]}]}}
        self.assertEqual([f for f in self.lint(hooks) if f.severity != "note"], [])

    def test_json_syntax_error_has_line_and_column(self):
        f = self.lint(None, text='{\n  "hooks": {\n    "PreToolUse": [],\n  }\n}\n')
        hit = self.assertFinds(f, "json-syntax", "error", "trailing comma")
        self.assertEqual(hit.line, 4)
        hit = self.assertFinds(self.lint(None, text='{"hooks": {} // c\n}'), "json-syntax", "error", "comment")
        self.assertEqual(hit.line, 1)

    def test_duplicate_key_and_bom(self):
        f = self.lint(None, text='﻿{"hooks": {"PreToolUse": [{"matcher": "Bash", "matcher": "Write", "hooks": []}]}}')
        self.assertFinds(f, "duplicate-key", "warning", "'matcher'")
        self.assertFinds(f, "json-bom", "warning")

    def test_top_level_shapes(self):
        self.assertFinds(self.lint(None, text="[1]"), "json-shape", "error")
        self.assertFinds(self.lint({"PreToolUse": []}), "hooks-key", "error", "at the top level")
        self.assertFinds(self.lint({"description": "x"}), "hooks-key", "error")
        self.assertFinds(self.lint({"hooks": {"PreToolUse": [{"hooks": [dict(CMD)]}]}, "disableAllHooks": True}),
                         "disable-all-hooks", "warning")

    def test_unknown_event_and_handler_type(self):
        f = self.lint({"hooks": {"preToolUse": [{"hooks": [CMD]}], "Stop": [{"hooks": [{"type": "shell", "command": "x"}]}]}})
        self.assertFinds(f, "unknown-event", "error", "case-sensitive: PreToolUse")
        self.assertFinds(f, "handler-type", "error", "'shell'")

    def test_fan_out_of_one_command(self):
        # the pkg-vitals layout before its review: many `if` rules, one command
        hooks = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [dict(CMD, **{"if": f"Bash(npm {v} *)"})
                                                                       for v in ("install", "i", "add", "ci")]}]}}
        hit = self.assertFinds(self.lint(hooks), "fan-out", "warning", "4 PreToolUse handlers")
        self.assertIn("starts 4 of them at once", hit.message)

    def test_if_rule_outside_the_matcher(self):
        hooks = {"hooks": {"PostToolUse": [{"matcher": "Write", "hooks": [dict(CMD, **{"if": "Edit(*.json)"})]}]}}
        self.assertFinds(self.lint(hooks), "if-outside-matcher", "error", "never matches Edit")

    def test_edit_rules_leave_write_uncovered(self):
        f = hh.lint(hh.load_source(self._fixture_plugin("mcp-vitals-edit-rules-only.json", "mcp_vitals_hook.py")))
        self.assertFinds(f, "if-uncovered-tool", "warning", "Write calls reach this group")

    def test_timeouts(self):
        f = self.lint({"hooks": {"PreToolUse": [{"hooks": [dict(CMD, timeout=5000)]}],
                                 "Stop": [{"hooks": [dict(CMD, timeout=0)]}]}})
        self.assertFinds(f, "timeout-ms", "warning", "looks like milliseconds")
        self.assertFinds(f, "timeout", "error")
        self.assertNotIn("timeout-ms", self.rules(self.lint({"hooks": {"PreToolUse": [{"hooks": [dict(CMD, timeout=600)]}]}})))

    def test_missing_plugin_file_and_executable_bit(self):
        f = self.lint({"hooks": {"PreToolUse": [{"hooks": [dict(CMD, command="python3 \"${CLAUDE_PLUGIN_ROOT}/nope.py\"")]}]}})
        self.assertFinds(f, "plugin-file", "error", "nope.py does not exist")
        if os.name == "posix":
            f = self.lint({"hooks": {"PreToolUse": [{"hooks": [{"type": "command",
                                                                 "command": "\"${CLAUDE_PLUGIN_ROOT}\"/run.sh"}]}]}},
                          scripts=("run.sh",))
            self.assertFinds(f, "script-not-executable", "error")

    def test_windows_findings(self):
        f = self.lint({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [CMD]}]}})
        self.assertFinds(f, "windows-powershell", "warning", "PowerShell")
        self.assertFinds(f, "windows-interpreter", "note", "python3")
        f = self.lint({"hooks": {"PreToolUse": [{"matcher": "Bash|PowerShell", "hooks": [dict(CMD, **{"if": "Bash(npm *)"})]}]}})
        self.assertFinds(f, "windows-powershell", "warning")  # the only handler's `if` excludes PowerShell
        f = self.lint({"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "npx", "args": ["eslint"]}]}]}})
        self.assertFinds(f, "windows-exec-shim", "warning")
        f = self.lint({"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "shell": "powershell",
                                                             "command": "& $CLAUDE_PROJECT_DIR/x.ps1"}]}]}})
        self.assertFinds(f, "powershell-env", "warning")

    def test_command_forms(self):
        f = self.lint({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": "node script.js", "args": []},
            {"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/h.py"},
            {"type": "command", "command": "curl ${user_config.url}"},
            {"type": "command", "command": "x", "shell": "zsh"}]}]}})
        self.assertFinds(f, "exec-command", "error")
        self.assertFinds(f, "placeholder-quotes", "warning")
        self.assertFinds(f, "user-config-shell", "error")
        self.assertFinds(f, "shell", "error")

    def test_if_and_matcher_findings(self):
        f = self.lint({"hooks": {
            "Stop": [{"matcher": "Bash", "hooks": [dict(CMD, **{"if": "Bash(*)"})]}],
            "PreToolUse": [{"matcher": "bash|mcp__memory", "hooks": [CMD]},
                           {"matcher": "(Bash", "hooks": [CMD]},
                           {"hooks": [dict(CMD, **{"if": "Bash(git *) && Bash(npm *)"}),
                                      dict(CMD, **{"if": ["Bash(x)"]}),
                                      dict(CMD, **{"if": "WebFetch(domain:example.com)"}),
                                      dict(CMD, **{"if": "mcp__memory__*"}),
                                      dict(CMD, **{"if": "Bash(run_in_background:true)"})]}],
            "SessionStart": [{"matcher": "Startup", "hooks": [{"type": "http", "url": "http://x"}]}]}})
        for rule, sev, frag in (("matcher-ignored", "warning", "Stop"), ("if-non-tool-event", "error", ""),
                                ("matcher-unknown-tool", "error", "case-sensitive"), ("matcher-mcp", "error", "__.*"),
                                ("matcher-invalid", "error", ""), ("if-syntax", "error", "no &&"),
                                ("if-syntax", "error", "not a list"), ("if-specifier", "warning", "WebFetch"),
                                ("if-tool-name", "warning", "exact"), ("if-param-rule", "warning", ""),
                                ("matcher-unknown-value", "warning", "startup"), ("handler-type", "error", "SessionStart")):
            self.assertFinds(f, rule, sev, frag)

    def test_async_and_once(self):
        f = self.lint({"hooks": {"PreToolUse": [{"hooks": [dict(CMD, **{"async": True, "once": True})]}]}})
        self.assertFinds(f, "async-decision", "warning")
        self.assertFinds(f, "once-ignored", "note")

    def test_settings_file_without_plugin_root(self):
        f = self.lint({"hooks": {"PreToolUse": [{"matcher": "Bash|PowerShell", "hooks": [CMD]}]}}, kind="settings")
        self.assertFinds(f, "plugin-root", "warning")

    def test_duplicates_are_a_note(self):
        f = self.lint({"hooks": {"PreToolUse": [{"matcher": "Bash|PowerShell", "hooks": [CMD, dict(CMD, timeout=9)]}]}})
        self.assertFinds(f, "duplicate-handler", "note", "runs it once")
        self.assertNotIn("fan-out", self.rules(f))

    def test_line_numbers_point_at_the_field(self):
        text = json.dumps({"hooks": {"PreToolUse": [{"hooks": [dict(CMD, timeout=9000)]}]}}, indent=2)
        hit = self.assertFinds(self.lint(None, text=text), "timeout-ms")
        self.assertEqual(text.splitlines()[hit.line - 1].strip(), '"timeout": 9000')

    def _fixture_plugin(self, name, script_name):
        path = self.plugin(fixture(f"hooks/{name}"), {script_name: ""}, name=name.replace(".json", ""))
        return path


class RealHooks(Isolated):
    """The hooks this project was built against. Lessons: fan-out (pkg-vitals before review), Edit rules that never
    matched Write calls (mcp-vitals before its second review)."""

    assertFinds = Lint.assertFinds
    _fixture_plugin = Lint._fixture_plugin

    def findings(self, name, script_name):
        return hh.lint(hh.load_source(self._fixture_plugin(name, script_name)))

    def test_current_files_have_no_errors_or_warnings(self):
        for name, s in (("mcp-vitals-current.json", "mcp_vitals_hook.py"), ("pkg-vitals-current.json", "pkg_vitals_hook.py")):
            bad = [(x.rule, x.message) for x in self.findings(name, s) if x.severity != "note"]
            self.assertEqual(bad, [], name)

    def test_72_handler_file_fans_out(self):
        f = self.findings("pkg-vitals-72-handlers.json", "pkg_vitals_hook.py")
        hit = self.assertFinds(f, "fan-out", "warning", "36 PreToolUse handlers")
        self.assertIn("starts 32 of them at once", hit.message)
        self.assertIn("starts all 36", hit.message)

    def test_fixtures_are_the_real_files(self):
        self.assertEqual(sum(len(g["hooks"]) for g in fixture("hooks/pkg-vitals-72-handlers.json")["hooks"]["PreToolUse"]), 72)
        self.assertTrue((FIXTURES / "hooks" / "mcp-vitals-current.json").is_file())


if __name__ == "__main__":
    unittest.main()
