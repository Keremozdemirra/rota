"""The plugin files, the CLI's one-server mode, and the two against each other."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import doctor  # noqa: E402


class Plugin(unittest.TestCase):
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
        self.assertEqual(doctor.VERSION, plugin["version"])

    def test_hook_commands_point_at_files_that_exist(self):
        hooks = self.load("hooks/hooks.json")["hooks"]
        commands = [h["command"] for groups in hooks.values() for g in groups for h in g["hooks"]]
        self.assertTrue(commands)
        for cmd in commands:
            for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", cmd):
                self.assertTrue((ROOT / rel).is_file(), rel)

    def test_hook_timeouts_are_seconds(self):
        hooks = self.load("hooks/hooks.json")["hooks"]
        for groups in hooks.values():
            for g in groups:
                for h in g["hooks"]:
                    self.assertLessEqual(h["timeout"], 60)  # seconds; a value in ms would be a typo

    def test_skill_front_matter(self):
        text = (ROOT / "skills" / "mcp-vitals" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: mcp-vitals\ndescription: "))
        for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", text):
            self.assertTrue((ROOT / rel).is_file(), rel)


class Target(unittest.TestCase):
    def resolved(self, words):
        return doctor.resolve(doctor.target_entry(words))

    def test_command_line(self):
        r = self.resolved(["npx", "-y", "@s/p@1.0.0"])
        self.assertEqual((r["kind"], r["package"], r["pinned"]), ("npm", "@s/p", True))

    def test_prefixes(self):
        self.assertEqual(self.resolved(["npm:@s/p"])["package"], "@s/p")
        self.assertEqual((self.resolved(["pypi:mcp-server-fetch"])["kind"]), "pypi")

    def test_repository(self):
        for word in ("o/n", "https://github.com/o/n", "https://github.com/o/n.git"):
            r = self.resolved([word])
            self.assertEqual((r["kind"], r["repo"]), ("git", "o/n"), word)

    def test_bare_name_is_npm(self):
        self.assertEqual(self.resolved(["some-server"])["package"], "some-server")

    def test_remote_url(self):
        self.assertEqual(self.resolved(["https://mcp.example.com/mcp"])["kind"], "remote")

    def test_main_strict_on_target(self):
        self.assertEqual(doctor.main(["--offline", "--strict", "--json", "npx", "-y", "p"]), 0)


if __name__ == "__main__":
    unittest.main()
