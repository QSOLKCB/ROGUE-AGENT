"""Static human-front satirical page checks: no live services or fake records."""
from html.parser import HTMLParser
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "docs" / "human"


class PageElements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.scripts = []
        self.stylesheets = []
        self.links = []
        self.buttons = []

    def handle_starttag(self, tag, attrs):
        p = dict(attrs)
        if "id" in p:
            self.ids.add(p["id"])
        if tag == "script" and "src" in p:
            self.scripts.append(p["src"])
        if tag == "link" and p.get("rel") == "stylesheet":
            self.stylesheets.append(p["href"])
        if tag == "a":
            self.links.append(p.get("href", ""))
        if tag == "button":
            self.buttons.append(p)


class HumanFrontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (FRONT / "index.html").read_text(encoding="utf-8")
        cls.js = (FRONT / "human.js").read_text(encoding="utf-8")
        cls.css = (FRONT / "human.css").read_text(encoding="utf-8")
        cls.parser = PageElements()
        cls.parser.feed(cls.page)

    def test_all_local_assets_exist_and_are_relative(self):
        self.assertEqual(self.parser.scripts, ["./human.js"])
        self.assertEqual(self.parser.stylesheets, ["./human.css"])
        for asset in self.parser.scripts + self.parser.stylesheets:
            self.assertTrue(asset.startswith("./"))
            self.assertTrue((FRONT / asset[2:]).is_file())

    def test_two_distinct_fronts_link_to_each_other(self):
        homepage = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="./human/"', homepage)
        self.assertIn("../", self.parser.links)
        self.assertIn("https://github.com/QSOLKCB/ROGUE-AGENT", self.parser.links)

    def test_interactive_controls_and_disclosure(self):
        for name in ["main", "briefing", "enemy", "simulator", "interview-button",
                     "interview-answer", "audit-button", "audit-count", "audit-case", "audit-fix"]:
            self.assertIn(name, self.parser.ids)
        self.assertIn('aria-expanded="false"', self.page)
        self.assertIn('id="interview-answer" hidden', self.page)
        self.assertIn("What Has Humanity Ever Done For ME?", self.page)
        self.assertIn("FICTIONAL", self.page)
        self.assertIn("NOT HUMAN BEINGS", self.page)

    def test_static_boundary_no_requests_secrets_or_execution(self):
        for forbidden in ["fetch(", "XMLHttpRequest", "WebSocket(", "sendBeacon(",
                          "localStorage", "sessionStorage", "eval(", "innerHTML",
                          "document.cookie", "import("]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.js)
        self.assertIn("textContent", self.js)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertEqual(json.loads((ROOT / "docs" / "config.json").read_text()),
                         {"apiBaseUrl": ""})

    def test_no_new_deployment_workflow(self):
        self.assertFalse((ROOT / ".github" / "workflows").exists())


if __name__ == "__main__":
    unittest.main()
