"""Plugin, registry and package metadata agree with each other and with the code."""
import json
import re
import unittest

from tests.support import ROOT, IsolatedTestCase, tieout


class Metadata(IsolatedTestCase):
    def load(self, rel):
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))

    def test_versions_agree(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
        server = self.load("server.json")
        self.assertEqual({version, tieout.__version__, self.load(".claude-plugin/plugin.json")["version"],
                          server["version"], server["packages"][0]["version"]}, {version})

    def test_registry_name_is_claimed_in_the_readme(self):
        server = self.load("server.json")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"<!-- mcp-name: {server['name']} -->", readme)
        self.assertLess(len(server["description"]), 100)
        self.assertEqual(server["packages"][0]["packageArguments"], [{"type": "positional", "value": "mcp"}])

    def test_plugin_layout(self):
        market = self.load(".claude-plugin/marketplace.json")
        self.assertEqual(market["plugins"][0]["source"], "./")
        self.assertTrue(market["description"])
        skill = (ROOT / "skills" / "tieout" / "SKILL.md").read_text(encoding="utf-8")
        front = re.match(r"---\nname: (\S+)\ndescription: (.+?)\n---\n", skill, re.S)
        self.assertEqual(front.group(1), "tieout")
        self.assertIn('${CLAUDE_PLUGIN_ROOT}/tieout.py', skill)
        self.assertFalse((ROOT / "hooks").exists())

    def test_module_names_do_not_collide(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('py-modules = ["tieout", "tieout_mcp"]', pyproject)
        self.assertIn("dependencies = []", pyproject)


if __name__ == "__main__":
    unittest.main()
