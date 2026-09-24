"""Release metadata agrees with itself, and nothing token-shaped is in the repository."""
import json
import re
import unittest
from pathlib import Path

import support
from support import fm

ROOT = Path(__file__).resolve().parent.parent
NAME = "io.github.Keremozdemirra/firds-mcp"


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class Packaging(unittest.TestCase):
    def test_pyproject(self):
        try:
            import tomllib
        except ImportError:  # Python < 3.11: the version line is enough to compare
            self.assertIn(f'version = "{fm.VERSION}"', read("pyproject.toml"))
            return
        data = tomllib.loads(read("pyproject.toml"))
        project = data["project"]
        self.assertEqual(project["name"], "firds-mcp")
        self.assertEqual(project["version"], fm.VERSION)
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(project["requires-python"], ">=3.9")
        self.assertEqual(project["dependencies"], [])
        self.assertEqual(project["scripts"], {"firds-mcp": "firds_mcp:main"})
        self.assertEqual(data["build-system"]["requires"], ["setuptools>=77"])
        # One top-level module, named after the project: nothing called server, cli or utils.
        self.assertEqual(data["tool"]["setuptools"]["py-modules"], ["firds_mcp"])

    def test_server_json(self):
        server = json.loads(read("server.json"))
        self.assertEqual(server["$schema"], "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json")
        self.assertEqual(server["name"], NAME)
        self.assertRegex(server["name"], r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$")
        self.assertTrue(1 <= len(server["description"]) < 100)
        self.assertTrue(1 <= len(server["title"]) <= 100)
        self.assertEqual(server["version"], fm.VERSION)
        self.assertEqual(server["repository"], {"url": "https://github.com/Keremozdemirra/firds-mcp", "source": "github"})
        self.assertEqual(server["packages"], [{"registryType": "pypi", "identifier": "firds-mcp", "version": fm.VERSION,
                                               "runtimeHint": "uvx", "transport": {"type": "stdio"}}])

    def test_readme_carries_the_ownership_line(self):
        self.assertIn(f"<!-- mcp-name: {NAME} -->", read("README.md").splitlines())

    def test_readme_ends_with_what_this_is_not(self):
        headings = [line for line in read("README.md").splitlines() if line.startswith("## ")]
        self.assertEqual(headings[-1], "## What this is not")

    def test_licence(self):
        text = read("LICENSE")
        self.assertTrue(text.startswith("MIT License"))
        self.assertIn("Copyright (c) 2026 Kerem Özdemir", text)

    def test_sdist_ships_the_tests_needs(self):
        manifest = read("MANIFEST.in")
        for line in ("include LICENSE README.md server.json", "recursive-include tests *.py *.json *.html *.md",
                     "recursive-include .github *.yml"):
            self.assertIn(line, manifest.splitlines())

    def test_actions_are_pinned(self):
        test = read(".github/workflows/test.yml")
        self.assertIn("actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0", test)
        self.assertIn("actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0", test)
        self.assertIn('python: ["3.9", "3.12"]', test)
        for name in ("test.yml", "release.yml"):
            text = read(f".github/workflows/{name}")
            self.assertNotIn("ubuntu-latest", text)
            for ref in re.findall(r"uses:\s*(\S+)", text):
                self.assertRegex(ref, r"@[0-9a-f]{40}$", f"{name}: {ref} is not pinned to a commit")
        self.assertIn("pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33", read(".github/workflows/release.yml"))

    def test_nothing_token_shaped_anywhere(self):
        # The patterns the publishing script refuses (projects/publish.sh).
        pattern = re.compile(r"sk-ant-[A-Za-z0-9_-]{20}|sk-[A-Za-z0-9]{32}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40}"
                             r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|r8_[A-Za-z0-9]{32}")
        for path in ROOT.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and ".git" not in path.parts:
                text = path.read_bytes().decode("utf-8", "replace")
                self.assertIsNone(pattern.search(text), str(path.relative_to(ROOT)))

    def test_user_agent_names_the_version(self):
        self.assertEqual(fm.USER_AGENT, f"firds-mcp/{fm.VERSION} (+https://github.com/Keremozdemirra/firds-mcp)")


if __name__ == "__main__":
    unittest.main()
