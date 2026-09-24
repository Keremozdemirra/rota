"""The release files agree with each other, and the README quotes output the tool really produces."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import financed_emissions as fe  # noqa: E402


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


class Consistency(unittest.TestCase):
    def test_versions_agree(self):
        pyproject = re.search(r'^version = "([^"]+)"', read("pyproject.toml"), re.M).group(1)
        server = json.loads(read("server.json"))
        self.assertEqual(pyproject, fe.__version__)
        self.assertEqual(server["version"], fe.__version__)
        self.assertEqual(server["packages"][0]["version"], fe.__version__)

    def test_registry_name_and_launch(self):
        server = json.loads(read("server.json"))
        self.assertIn(f"<!-- mcp-name: {server['name']} -->", read("README.md"))
        package = server["packages"][0]
        self.assertEqual(package["identifier"], "financed-emissions")
        self.assertEqual(package["packageArguments"][0]["value"], "mcp")
        self.assertLess(len(server["description"]), 100)

    def test_workflow_pins(self):
        test = read(".github/workflows/test.yml")
        self.assertIn("actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0", test)
        self.assertIn("actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0", test)
        self.assertIn("runs-on: ubuntu-24.04", test)
        self.assertIn('python: ["3.9", "3.12"]', test)

    def test_licence(self):
        self.assertIn("Copyright (c) 2026 Kerem Özdemir", read("LICENSE"))

    def test_no_top_level_module_names_that_collide(self):
        modules = re.search(r"py-modules = \[(.*?)\]", read("pyproject.toml")).group(1)
        for name in ("cli", "server", "utils", "hook", "doctor"):
            self.assertNotIn(f'"{name}"', modules)


class ReadmeQuotesRealOutput(unittest.TestCase):
    def test_example_block_matches_current_output(self):
        result = fe.compute_file(str(ROOT / "examples" / "portfolio.csv"), reporting_currency="EUR")
        text = fe.render(result).splitlines()
        explain = fe.render(result, explain=True).splitlines()
        blocks, current = [], None
        for line in read("README.md").splitlines():
            if line.startswith("```"):
                if current is None:
                    current = []
                else:
                    blocks.append("\n".join(current))
                    current = None
            elif current is not None:
                current.append(line)
        quoted = [b for b in blocks if "By PCAF asset class" in b or "attribution factor =" in b]
        self.assertEqual(len(quoted), 2)
        for line in (x for b in quoted for x in b.splitlines() if x.strip()):
            self.assertIn(line, text + explain, "README quotes a line the tool no longer prints")


if __name__ == "__main__":
    unittest.main()
