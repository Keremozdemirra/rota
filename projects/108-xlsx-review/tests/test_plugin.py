"""The plugin, the MCP registry entry and the packaging agree with each other and with the code."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, Case, xlsx_review as xr  # noqa: E402


class Packaging(Case):
    def load(self, rel):
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))

    def test_versions_agree(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{xr.VERSION}"', pyproject)
        self.assertEqual(self.load(".claude-plugin/plugin.json")["version"], xr.VERSION)
        server = self.load("server.json")
        self.assertEqual((server["version"], server["packages"][0]["version"]), (xr.VERSION, xr.VERSION))

    def test_manifest_and_marketplace_agree(self):
        plugin = self.load(".claude-plugin/plugin.json")
        market = self.load(".claude-plugin/marketplace.json")
        self.assertEqual([p["name"] for p in market["plugins"]], [plugin["name"]])
        self.assertEqual(market["plugins"][0]["source"], "./")
        self.assertTrue(market["description"])

    def test_no_hook_on_purpose(self):
        # Agents change workbooks by running code (openpyxl, pandas) or inside Excel, not with the
        # Write or Edit tool, so a hook would never see an .xlsx edit; the skill runs the diff instead.
        self.assertFalse((ROOT / "hooks").exists())
        self.assertIn("no hook", xr.__doc__)

    def test_skill_front_matter_and_paths(self):
        text = (ROOT / "skills" / "xlsx-review" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: xlsx-review\ndescription: "))
        rule = re.search(r"^allowed-tools: Bash\((.*) \*\)$", text, re.M).group(1)
        self.assertIn(rule + " diff", text)  # the pre-approved command is the one the skill runs
        for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", text):
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_registry_name_is_in_the_readme(self):
        name = self.load("server.json")["name"]
        self.assertIn(f"<!-- mcp-name: {name} -->", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertLess(len(self.load("server.json")["description"]), 100)

    def test_module_names_are_prefixed(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        modules = re.search(r"py-modules = \[(.*)\]", pyproject).group(1)
        self.assertEqual(modules, '"xlsx_review", "xlsx_review_mcp"')
