"""The plugin files, the packaging, the CLI's one-server mode, and all of them against each other."""
import fnmatch
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, Isolated  # noqa: E402

import mcp_upkeep  # noqa: E402
import mcp_upkeep_hook  # noqa: E402

HOOK_FILE = "mcp_upkeep_hook.py"


def handlers(event):
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    return [(g["matcher"], h) for g in hooks[event] for h in g["hooks"]]


class Plugin(Isolated):
    def load(self, rel):
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))

    def test_manifest_and_marketplace_agree(self):
        plugin = self.load(".claude-plugin/plugin.json")
        market = self.load(".claude-plugin/marketplace.json")
        self.assertEqual([p["name"] for p in market["plugins"]], [plugin["name"]])
        self.assertEqual(market["plugins"][0]["source"], "./")
        self.assertTrue(market["owner"]["name"])

    def test_versions_agree(self):
        plugin = self.load(".claude-plugin/plugin.json")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{plugin["version"]}"', pyproject)
        self.assertEqual(mcp_upkeep.VERSION, plugin["version"])

    def test_hook_commands_point_at_files_that_exist(self):
        commands = [h["command"] for event in ("PreToolUse", "PostToolUse") for _, h in handlers(event)]
        self.assertTrue(commands)
        for cmd in commands:
            rels = re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", cmd)
            self.assertEqual(rels, [HOOK_FILE], cmd)
            self.assertTrue((ROOT / rels[0]).is_file(), rels[0])

    def test_hook_timeouts_are_seconds(self):
        for event in ("PreToolUse", "PostToolUse"):
            for _, h in handlers(event):
                self.assertLessEqual(h["timeout"], 60)  # seconds; a value in ms would be a typo

    def test_shell_hook_covers_bash_and_powershell(self):
        # hooks docs: match Bash|PowerShell in hooks that inspect shell commands; one `if` rule matches one tool
        pre = handlers("PreToolUse")
        self.assertEqual({m for m, _ in pre}, {"Bash|PowerShell"})
        self.assertEqual(sorted(h["if"] for _, h in pre), ["Bash(claude mcp add*)", "PowerShell(claude mcp add*)"])

    def test_edit_hook_runs_only_for_mcp_config_files(self):
        # One `if` rule matches one tool's calls (hooks docs; an Edit(...) rule does not fire for Write,
        # observed with Claude Code 2.1.281), so Write and Edit each need a rule per file pattern.
        rules = sorted(h.get("if", "") for _, h in handlers("PostToolUse"))
        self.assertEqual(rules, ["Edit(//**/*mcp*.json)", "Edit(//**/claude_desktop_config.json)",
                                 "Write(//**/*mcp*.json)", "Write(//**/claude_desktop_config.json)"])
        for tool in ("Write", "Edit"):
            patterns = [re.fullmatch(rf"{tool}\(//\*\*/(.+)\)", r).group(1) for r in rules if r.startswith(tool)]
            for name in mcp_upkeep_hook.CONFIG_NAMES:
                matching = [p for p in patterns if fnmatch.fnmatchcase(name, p)]
                self.assertEqual(len(matching), 1, (tool, name, matching))  # exactly one: never twice per call

    def test_skill_front_matter_and_commands(self):
        text = (ROOT / "skills" / "mcp-upkeep" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: mcp-upkeep\ndescription: "))
        rels = re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", text)
        self.assertTrue(rels)
        for rel in rels:
            self.assertEqual(rel, "mcp_upkeep.py")
            self.assertTrue((ROOT / rel).is_file(), rel)


class Packaging(Isolated):
    def test_module_names_do_not_collide(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('py-modules = ["mcp_upkeep", "mcp_upkeep_hook"]', pyproject)
        self.assertIn('mcp-upkeep = "mcp_upkeep:main"', pyproject)
        self.assertIn('mcp-upkeep-hook = "mcp_upkeep_hook:main"', pyproject)
        for old in ("doctor.py", "hook.py"):
            self.assertFalse((ROOT / old).exists(), old)

    def test_sdist_carries_what_the_tests_read(self):
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        for needed in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "hooks/hooks.json",
                       "skills/mcp-upkeep/SKILL.md", ".github/workflows/test.yml", ".github/workflows/release.yml",
                       "recursive-include tests *.py *.json"):
            self.assertIn(needed, manifest)

    def test_no_file_names_the_old_modules(self):
        texts = {p: p.read_text(encoding="utf-8") for p in [ROOT / "README.md", ROOT / "hooks" / "hooks.json",
                                                             ROOT / "skills" / "mcp-upkeep" / "SKILL.md",
                                                             ROOT / "mcp_upkeep.py", ROOT / "mcp_upkeep_hook.py"]}
        for p, text in texts.items():
            self.assertNotRegex(text, r"\bdoctor\.py\b|\bhook\.py\b|import doctor|import hook\b", p.name)

    def test_readme_install_lines_have_pinned_forms(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        version = mcp_upkeep.VERSION
        self.assertIn("https://raw.githubusercontent.com/Keremozdemirra/mcp-upkeep/main/mcp_upkeep.py", readme)
        self.assertIn(f"https://raw.githubusercontent.com/Keremozdemirra/mcp-upkeep/v{version}/mcp_upkeep.py", readme)
        self.assertIn(f"uvx mcp-upkeep@{version}", readme)


class Target(Isolated):
    def resolved(self, words):
        return mcp_upkeep.resolve(mcp_upkeep.target_entry(words))

    def test_command_line(self):
        r = self.resolved(["npx", "-y", "@s/p@1.0.0"])
        self.assertEqual((r["kind"], r["package"], r["pinned"]), ("npm", "@s/p", True))

    def test_prefixes(self):
        self.assertEqual(self.resolved(["npm:@s/p"])["package"], "@s/p")
        self.assertEqual((self.resolved(["pypi:mcp-server-fetch"])["kind"]), "pypi")

    def test_repository(self):
        for word in ("o/n", "https://github.com/o/n", "https://github.com/o/n.git", "github.com/o/n"):
            r = self.resolved([word])
            self.assertEqual((r["kind"], r["repo"], r["pin"]), ("git", "o/n", None), word)

    def test_bare_name_is_npm(self):
        self.assertEqual(self.resolved(["some-server"])["package"], "some-server")

    def test_remote_url(self):
        self.assertEqual(self.resolved(["https://mcp.example.com/mcp"])["kind"], "remote")

    def test_main_strict_on_target(self):
        self.assertEqual(self.run_main(["--offline", "--strict", "--json", "npx", "-y", "p"])[0], 0)


if __name__ == "__main__":
    unittest.main()
