"""Dependency-free smoke tests for the versioned static foundation."""
import json
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.assets = []
    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if "id" in props:
            self.ids.add(props["id"])
        if tag == "script" and "src" in props:
            self.assets.append(props["src"])
        if tag == "link" and props.get("rel") == "stylesheet":
            self.assets.append(props.get("href"))

class FoundationTests(unittest.TestCase):
    def test_expected_contract_files_exist(self):
        for path in ["README.md", "AGENTS.md", "docs/INVARIANTS.md", "docs/ARCHITECTURE.md", "docs/THREAT_MODEL.md", "docs/EXPERIMENT_PROTOCOL.md", "docs/API_CONTRACT.md", "docs/HANDOFF_SUPERCOMPUTER.md", "docs/DEPLOYMENT.md", "docs/ROADMAP.md"]:
            with self.subTest(path=path):
                self.assertGreater((ROOT / path).stat().st_size, 100)

    def test_static_frontend_assets_resolve(self):
        parser = PageParser()
        parser.feed((ROOT / "docs/index.html").read_text(encoding="utf-8"))
        for path in parser.assets:
            with self.subTest(path=path):
                self.assertTrue(path.startswith("./"))
                self.assertTrue((ROOT / "docs" / path[2:]).is_file())
        for id_ in ["main", "service-state", "backend-state", "service-note", "updated-at", "agents-count", "artifacts-count", "experiments-count", "receipts-count"]:
            self.assertIn(id_, parser.ids)

    def test_default_frontend_does_not_connect_to_api(self):
        cfg = json.loads((ROOT / "docs/config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg, {"apiBaseUrl": ""})
        self.assertIn("fetch", (ROOT / "docs/main.js").read_text())
        self.assertIn("NOT CONFIGURED", (ROOT / "docs/index.html").read_text())

    def test_no_automatic_deployment_workflow(self):
        self.assertFalse((ROOT / ".github/workflows").exists())

if __name__ == "__main__":
    unittest.main()

