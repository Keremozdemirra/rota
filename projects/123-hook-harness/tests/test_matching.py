"""Which handlers a call starts: matchers, `if` rules for Bash, file paths and other tools, and deduplication.

Rows marked "docs" come from the page named in the comment (checked 2026-09-24). Rows marked "observed" were seen
with Claude Code 2.1.281 and are reproduced by tools/crosscheck_claude_code.py.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated, hh  # noqa: E402

H = "https://code.claude.com/docs/en/hooks"
P = "https://code.claude.com/docs/en/permissions"
CTX = hh.Context(cwd="/proj", project_dir="/proj", home="/home/u")


def fires(rule, tool="Bash", ctx=CTX, **tool_input):
    if tool in ("Bash", "PowerShell") and "command" not in tool_input:
        raise ValueError
    return hh.rule_fires(rule, tool, tool_input, ctx).fires


class Matchers(unittest.TestCase):
    # H, "Matcher patterns" table and the paragraphs under it
    TABLE = [
        ("*", "PreToolUse", "Bash", True), ("", "PreToolUse", "Write", True), (None, "PreToolUse", "Read", True),
        ("Bash", "PreToolUse", "Bash", True), ("Bash", "PreToolUse", "PowerShell", False),
        ("Edit|Write", "PreToolUse", "Write", True), ("Edit, Write", "PreToolUse", "Write", True),
        ("Edit ,Write", "PreToolUse", "Edit", True), ("code-reviewer", "SubagentStart", "senior-code-reviewer", False),
        ("^Notebook", "PreToolUse", "NotebookEdit", True), ("mcp__memory__.*", "PreToolUse", "mcp__memory__create_entities", True),
        ("Edit.*", "PreToolUse", "NotebookEdit", True), ("^Edit$", "PreToolUse", "NotebookEdit", False),
        ("mcp__memory", "PreToolUse", "mcp__memory__create_entities", False),  # exact string, matches no tool
        ("mcp__brave-search__.*", "PreToolUse", "mcp__brave-search__web", True),
        ("mcp__.*__write.*", "PreToolUse", "mcp__fs__write_file", True),
        ("^my-plugin:reviewer$", "SubagentStart", "my-plugin:reviewer", True),
        ("bash", "PreToolUse", "Bash", False),  # hooks guide: matchers are case-sensitive
        ("startup", "SessionStart", "startup", True), ("resume", "SessionStart", "startup", False),
    ]

    def test_documented_table(self):
        for matcher, event, value, want in self.TABLE:
            self.assertEqual(hh.matcher_matches(matcher, event, value)[0], want, (matcher, value))

    def test_narrow_events_keep_hyphens_on_the_regex_path(self):
        # FileChanged and StopFailure: only letters, digits, _ and | are exact; a comma stays a regex character
        self.assertEqual(hh.matcher_mode("rate_limit,overloaded", "StopFailure")[0], "regex")
        self.assertEqual(hh.matcher_mode("rate_limit|overloaded", "StopFailure")[0], "exact")
        self.assertTrue(hh.matcher_matches(".envrc|.env", "FileChanged", "/p/.env")[0])

    def test_events_without_matcher_support_ignore_it(self):
        self.assertTrue(hh.matcher_matches("Bash", "Stop", None)[0])

    def test_observed_mcp_forms(self):
        # observed: mcp__probe__* is a regex (the underscore repeats) and matches every probe tool
        self.assertTrue(hh.matcher_matches("mcp__probe__*", "PreToolUse", "mcp__probe__write_note")[0])
        self.assertTrue(hh.matcher_matches("Bash|", "PreToolUse", "Bash")[0])

    def test_invalid_regex_is_a_mismatch_with_a_reason(self):
        ok, why = hh.matcher_matches("(Bash", "PreToolUse", "Bash")
        self.assertFalse(ok)
        self.assertIn("not a regular expression", why)


class BashRules(unittest.TestCase):
    # H, "Bash matching table" (#bash-if-matching) and the hooks guide's table
    DOCS = [
        ("Bash(git *)", "FOO=bar git push", True), ("Bash(git *)", "npm test && git push", True),
        ("Bash(rm *)", "echo $(rm -rf /)", True), ("Bash(rm *)", "echo $(date)", False),
        ("Bash(cat *)", "echo before $(date) after", False), ("Bash(git *)", "$TOOL git push", True),
        ("Bash(git push *)", "echo $(date)", True), ("Bash(git *)", "git push", True),
        ("Bash(git *)", "echo $(git log)", True), ("Bash(rm *)", "rm -rf /tmp/build", True),
    ]
    # P, "Wildcard patterns" table
    WILDCARDS = [
        ("Bash(npm run build)", "npm run build", True), ("Bash(npm run build)", "npm run build --watch", False),
        ("Bash(npm run *)", "npm run build", True), ("Bash(npm run *)", "npm run test --watch", True),
        ("Bash(npm run *)", "npm run", True), ("Bash(npm run *)", "npm install", False),
        ("Bash(git log * main)", "git log --oneline main", True), ("Bash(git log * main)", "git log main", False),
        ("Bash(git log * main)", "git push origin main", False), ("Bash(git * main)", "git merge main", True),
        ("Bash(git * main)", "git log", False), ("Bash(* --version)", "node --version", True),
        ("Bash(* --version)", "node -v", False), ("Bash(ls *)", "ls -la", True), ("Bash(ls *)", "ls", True),
        ("Bash(ls *)", "lsof", False), ("Bash(ls*)", "lsof", True), ("Bash(* --help *)", "npm --help x", True),
        ("Bash(* --help *)", "npm --help", False), ("Bash(ls:*)", "ls -la", True), ("Bash(git:* push)", "git push", False),
        ("Bash", "anything at all", True), ("Bash(*)", "anything at all", True),
        ("Bash(safe-cmd *)", "safe-cmd && other-cmd", True),  # compound: the subcommand matches
        ("Bash(git clean *)", "cd /tmp && git clean -f", True), ("Bash(grep *)", "xargs grep pattern", True),
        ("Bash(grep *)", "xargs -n1 grep pattern", False), ("Bash(npm test *)", "NODE_ENV=test npm test", True),
        ("Bash(curl *)", "/usr/bin/curl https://example.com", False), ("Bash(rm *)", "bash -c 'rm -rf build/'", False),
        ("Bash(git push *)", "git -C . push origin main", False), ("Bash(npm *)", "npm test &&", True),
    ]
    # observed with Claude Code 2.1.281, where the docs are silent or say otherwise
    OBSERVED = [
        ("Bash(npm test *)", "timeout 30 npm test", False),  # wrappers are not stripped in an `if`
        ("Bash(git *)", "nice git push", False), ("Bash(git *)", "command git push", False),
        ("Bash(git push *)", "git 'push' origin main", True),  # quotes are removed before matching
        ("Bash(git push *)", "\\git push origin main", True), ("Bash(git push *)", "git  push  origin main", True),
        ("Bash(git commit -m fix bug)", "git commit -m 'fix bug'", True), ("Bash(git  push *)", "git push x", True),
        ("Bash(npm test)", "npm test > /dev/null", True),  # redirections are not part of the text
        ("Bash(git *)", "git status # git push", True), ("Bash(git push *)", "git status # git push", False),
        ("Bash(git push *)", "echo $HOME", False),  # $HOME counts as static
        ("Bash(git push *)", "ls $DIR", True), ("Bash(ls *)", "echo $DIR", False),  # names-only patterns do not fire
        ("Bash(ls *)", "ls \"$DIR\"", True), ("Bash(npm *)", "echo \"$DIR\"", True),  # quoted "$VAR": every handler
        ("Bash(npm *)", "echo ${HOME}", True), ("Bash(npm *)", "cat <<EOF\nx\nEOF", True),
        ("Bash(npm *)", "cat <<'EOF'\nnpx x\nEOF", False), ("Bash(npm *)", "python3 - <<'PY'\nprint(1)\nPY\nnpm ci", True),
        ("Bash(npm *)", "echo $DIR && ls", True), ("Bash(npm *)", "echo $(date) | cat", True),
        ("Bash(npm *)", "echo $(date) &", False), ("Bash(npm run *)", "echo $(date) &", True),
        ("Bash(npm *)", "bash scripts/setup.sh $DIR", True), ("Bash(npm *)", "git log $DIR", False),
        ("Bash(npm *)", "ls $DIR > f", True), ("Bash(npm *)", "echo a$DIR", True), ("Bash(npm *)", "echo $/x", True),
        ("Bash(git push *)", "echo \"at $(date)\"", False), ("Bash(git push *)", "echo \"$(date)\"", True),
        ("Bash(date)", "echo \"at $(date)\"", True),  # the inner command is still checked
        ("Bash(git push *)", "FOO=$(date)", False), ("Bash(npm *)", "X=1 echo $X", True),
        ("Bash([[ *)", "[ -f x ] && ls", True), ("Bash(echo *)", "echo \"unbalanced", True),
        ("Bash(npm *)", "echo a\\ b", True), ("Bash(npm *)", "{ git push; }", True),
        ("Bash(npm *)", "case x in x) ls;; esac", True), ("Bash(npm *)", "diff <(ls) <(ls)", True),
        ("Bash(npm *)", "echo x" + " x" * 5001, True),  # longer than 10,000 characters
        ("Bash(run_in_background:true)", "sleep 1", False),  # not a parameter rule in an `if`
    ]

    def check(self, rows):
        for rule, command, want in rows:
            self.assertEqual(fires(rule, command=command), want, (rule, command))

    def test_hooks_docs_table(self):
        self.check(self.DOCS)

    def test_permissions_docs_wildcards(self):
        self.check(self.WILDCARDS)

    def test_observed_behaviour(self):
        self.check(self.OBSERVED)

    def test_pattern_classes(self):
        for spec, want in (("git *", True), ("git*", True), ("git:*", True), ("git push *", False), ("npm run build", False),
                           ("date", False), ("[[ *", False), ("g*t *", False), ("git  *", False), ("* main", False),
                           ("./run.sh *", True), ("/usr/bin/git *", True)):
            self.assertEqual(hh.names_only(spec), want, spec)

    def test_analysis_explains_itself(self):
        a = hh.analyze_bash("cd app && npm ci")
        self.assertIsNone(a.every)
        self.assertEqual(a.commands, [["cd app"], ["npm ci"]])
        self.assertIn("here-document", hh.analyze_bash("cat <<EOF\nx\nEOF").every)

    def test_hostile_input_is_bounded(self):
        for command in ("$(" * 3000, "(" * 3000, "`" * 3001, "'" + "a" * 100, '"' * 7, "\\", "$", ";;;", "|||", "&&&&"):
            hh.analyze_bash(command)  # no exception, no hang


class PowerShellRules(unittest.TestCase):
    # P, "PowerShell": same shape as Bash rules, aliases canonicalized, case-insensitive; not cross-checked
    def test_documented_behaviour(self):
        rows = [("PowerShell(Get-ChildItem *)", "gci -Recurse", True), ("PowerShell(Get-ChildItem *)", "ls", True),
                ("PowerShell(Get-ChildItem *)", "dir C:\\x", True), ("PowerShell(remove-item *)", "Remove-Item x", True),
                ("PowerShell(Remove-Item *)", "Get-Date; rm -Recurse x", True),
                ("PowerShell(git commit *)", "git status | Out-Host", False),
                ("PowerShell(npm install*)", "Set-Location app; npm install left-pad", True),
                ("PowerShell(claude mcp add*)", "& 'C:\\bin\\claude.exe' mcp add x", False)]
        for rule, command, want in rows:
            self.assertEqual(fires(rule, "PowerShell", command=command), want, (rule, command))

    def test_variables_are_assumed_to_fire_specific_patterns(self):
        v = hh.rule_fires("PowerShell(npm install *)", "PowerShell", {"command": "echo $env:PATH"}, CTX)
        self.assertTrue(v.fires)
        self.assertEqual(v.basis, "assumed")


class PathRules(unittest.TestCase):
    CTX = hh.Context(cwd="/p", project_dir="/p", home="/h")
    # P, "Read and Edit": anchors, depth rules and the src/vendor example, applied to an `if` (allow-rule depth,
    # as the hooks docs state for `if`)
    DOCS = [
        ("Edit(src/**)", "/p/src/app.ts", True), ("Edit(src/**)", "/p/vendor/pkg/src/lib.js", False),
        ("Edit(/src/**)", "/p/src/app.ts", True), ("Edit(/src/**)", "/p/vendor/pkg/src/lib.js", False),
        ("Edit(**/src/**)", "/p/src/app.ts", True), ("Edit(**/src/**)", "/p/vendor/pkg/src/lib.js", True),
        ("Read(.env)", "/p/.env", True), ("Read(.env)", "/p/sub/.env", True), ("Read(**/.env)", "/p/sub/.env", True),
        ("Read(.env)", "/.env", False), ("Read(//**/.env)", "/elsewhere/.env", True),
        ("Read(~/Documents/*.pdf)", "/h/Documents/a.pdf", True), ("Edit(//tmp/scratch.txt)", "/tmp/scratch.txt", True),
        ("Edit(*.ts)", "/p/src/deep/x.ts", True), ("Edit(*.ts)", "/p/src/x.js", False),
        ("Edit(./Finance (2024)/**)", "/p/Finance (2024)/r.txt", True),
        ("Read(//c/**/.env)", "C:\\proj\\.env", True),  # Windows paths are normalized to /c/...
    ]
    OBSERVED = [
        ("Edit(*.ts)", "/p/SRC/APP.TS", True),  # case-insensitive
        ("Read(./.env)", "/p/sub/.env", True),  # ./x behaved like x
        ("Edit(src)", "/p/vendor/pkg/src/lib.js", True), ("Edit(docs/)", "/p/docs/a.md", True),
        ("Edit(*)", "/h/notes.txt", True), ("Edit(**)", "/elsewhere/x", True), ("Edit(/proj/src/**)", "/p/src/a", False),
        ("Edit(../p/src/a.ts)", "/p/src/a.ts", False), ("Edit(s?c/**)", "/p/src/a", True), ("Edit([st]rc/**)", "/p/src/a", True),
        ("Write(///p/src/**)", "/p/src/a", True), ("Edit(src/*.ts)", "/p/src/deep/x.ts", False),
    ]

    def check(self, rows):
        for rule, path, want in rows:
            tool = rule.split("(")[0]
            field = "file_path"
            self.assertEqual(hh.rule_fires(rule, tool, {field: path}, self.CTX).fires, want, (rule, path))

    def test_documented_patterns(self):
        self.check(self.DOCS)

    def test_observed_patterns(self):
        self.check(self.OBSERVED)

    def test_one_rule_one_tool(self):
        # H: "A single if rule matches only one tool's calls"
        self.assertFalse(hh.rule_fires("Edit(//**/*mcp*.json)", "Write", {"file_path": "/p/.mcp.json"}, self.CTX).fires)
        self.assertTrue(hh.rule_fires("Write(//**/*mcp*.json)", "Write", {"file_path": "/p/.mcp.json"}, self.CTX).fires)

    def test_grep_and_glob_default_to_the_working_directory(self):
        self.assertTrue(hh.rule_fires("Grep(//p)", "Grep", {"pattern": "x"}, self.CTX).fires)
        self.assertFalse(hh.rule_fires("Grep(//q)", "Grep", {"pattern": "x"}, self.CTX).fires)


class OtherTools(unittest.TestCase):
    def test_bare_and_star_match(self):
        for rule in ("WebFetch", "WebFetch(*)"):
            self.assertTrue(fires(rule, "WebFetch", url="https://example.com"))

    def test_observed_specifiers_never_match(self):
        for rule, tool, inp in (("WebFetch(domain:example.com)", "WebFetch", {"url": "https://example.com/x"}),
                                ("Agent(Explore)", "Agent", {"subagent_type": "Explore"}),
                                ("mcp__probe__echo(x)", "mcp__probe__echo", {"x": "1"})):
            v = hh.rule_fires(rule, tool, inp, CTX)
            self.assertEqual((v.fires, v.basis), (False, "observed"), rule)
        self.assertEqual(hh.rule_fires("Skill(deploy *)", "Skill", {"skill": "deploy"}, CTX).basis, "assumed")

    def test_tool_names_are_exact(self):
        for rule in ("mcp__probe", "mcp__probe__*", "*", "mcp__*"):
            self.assertFalse(fires(rule, "mcp__probe__echo"), rule)
        self.assertTrue(fires("mcp__probe__echo", "mcp__probe__echo"))

    def test_rule_syntax(self):
        r = hh.parse_rule("Edit(./Finance (2024)/**)")
        self.assertEqual((r.tool, r.spec), ("Edit", "./Finance (2024)/**"))  # parentheses inside are literal
        self.assertIsNotNone(hh.parse_rule(["Bash(x)"]).error)
        self.assertIsNotNone(hh.parse_rule("(x)").error)


class Choosing(Isolated):
    def test_duplicates_start_once_and_a_different_if_starts_again(self):
        same = {"type": "command", "command": "run-me"}
        hooks = {"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [same, dict(same, timeout=5), dict(same, statusMessage="x"),
                                          dict(same, **{"if": "Bash(echo *)"})]},
            {"matcher": "*", "hooks": [same]}]}}
        path = self.tmp / "settings.json"
        path.write_text(json.dumps(hooks))
        src = hh.load_source(path)
        choices = hh.choose(src, "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "echo hi"}}, CTX)
        self.assertEqual(sum(c.runs for c in choices), 2)
        self.assertEqual(sum(1 for c in choices if c.duplicate_of), 3)

    def test_if_on_a_non_tool_event_never_runs(self):
        path = self.tmp / "s.json"
        path.write_text('{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x", "if": "Bash(*)"}]}]}}')
        choices = hh.choose(hh.load_source(path), "Stop", {}, CTX)
        self.assertFalse(choices[0].runs)


if __name__ == "__main__":
    unittest.main()
