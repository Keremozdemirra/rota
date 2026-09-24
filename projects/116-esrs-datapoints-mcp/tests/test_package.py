"""Packaging facts that are easy to break, and the promise that no EFRAG content is in this repository."""
import hashlib
import json
import re
import unittest

from support import FIXTURES, ROOT

import esrs_datapoints_mcp
from esrs_datapoints_mcp import sources
from esrs_datapoints_mcp.parse import parse_workbook

TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".yml", ".in", ".txt", ""}


def project_files():
    skip = {"__pycache__", ".git", "build", "dist"}
    return [p for p in ROOT.rglob("*") if p.is_file() and not skip & set(p.relative_to(ROOT).parts)
            and not p.name.endswith(".egg-info")]


class Packaging(unittest.TestCase):
    def test_versions_and_registry_metadata_agree(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
        name = re.search(r'^name = "([^"]+)"', pyproject, re.M).group(1)
        server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
        self.assertEqual(version, esrs_datapoints_mcp.__version__)
        self.assertEqual(server["version"], version)
        self.assertEqual(server["packages"][0]["version"], version)
        self.assertEqual(server["packages"][0]["identifier"], name)
        self.assertEqual(server["name"], f"io.github.Keremozdemirra/{name}")
        self.assertLess(len(server["description"]), 100)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"<!-- mcp-name: {server['name']} -->", readme)
        self.assertTrue(readme.rstrip().endswith("It contains no EFRAG material."))
        self.assertIn("## What this is not", readme)
        self.assertIn('license = "MIT"', pyproject)
        self.assertIn('requires-python = ">=3.9"', pyproject)
        self.assertIn("dependencies = []", pyproject)
        self.assertIn("Copyright (c) 2026 Kerem Özdemir", (ROOT / "LICENSE").read_text(encoding="utf-8"))

    def test_workflows_use_the_pinned_actions(self):
        test = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
        self.assertIn("actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0", test)
        self.assertIn("actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0", test)
        self.assertIn("runs-on: ubuntu-24.04", test)
        self.assertIn('python: ["3.9", "3.12"]', test)
        self.assertIn("id-token: write", (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertIn("recursive-include tests/fixtures *.xlsx", manifest)
        self.assertIn("server.json", manifest)


class NoEfragContent(unittest.TestCase):
    def test_no_official_workbook_anywhere_in_the_tree(self):
        official = {f["sha256"] for f in sources.OFFICIAL_FILES}
        for p in project_files():
            self.assertNotIn(hashlib.sha256(p.read_bytes()).hexdigest(), official, p)
            if p.suffix.lower() in (".xlsx", ".xls", ".xlsm", ".csv"):
                self.assertEqual(p.parent, FIXTURES, p)

    def test_fixture_datapoints_are_invented_placeholders(self):
        for f in FIXTURES.glob("*.xlsx"):
            for dp in parse_workbook(f)["datapoints"]:
                self.assertTrue(dp.get("name", "").startswith("Placeholder"), (f.name, dp["id"]))

    def test_no_bidi_controls_or_token_shaped_literals(self):
        token = re.compile(r"sk-ant-[A-Za-z0-9_-]{20}|sk-[A-Za-z0-9]{32}|ghp_[A-Za-z0-9]{36}|"
                           r"github_pat_[A-Za-z0-9_]{40}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
        for p in project_files():
            if p.suffix not in TEXT_SUFFIXES:
                continue
            text = p.read_text(encoding="utf-8")
            self.assertIsNone(re.search("[‪-‮⁦-⁩]", text), p)
            self.assertIsNone(token.search(text), p)

    def test_no_top_level_modules_that_collide(self):
        self.assertEqual(sorted(p.name for p in ROOT.glob("*.py")), [])
