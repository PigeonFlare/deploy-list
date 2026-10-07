import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

import build_seo as seo


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.scripts.append(dict(attrs))


class SEOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name) / "site"
        for name in ("index.html", "leaderboards/index.html", "live/index.html"):
            path = self.site / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text((seo.ROOT / "site" / name).read_text())
        (self.site / "data").mkdir()
        self.data = {"generated_at": "2026-10-06T03:59:26+00:00", "sources": [], "sites": [
            {"url": "https://game.example/", "domain": "game.example", "title": "A browser game", "votes": 20,
             "source": "Show HN", "post_url": "https://news.ycombinator.com/item?id=1", "category": "games", "embeddable": True},
            {"url": "https://app.example/", "domain": "app.example", "title": "A useful tool", "votes": 0,
             "source": "r/SideProject", "post_url": "https://www.reddit.com/r/SideProject/comments/test/", "category": "apps", "embeddable": False},
        ]}

    def save(self):
        (self.site / "data/sites.json").write_text(json.dumps(self.data))

    def test_week_only_projects_do_not_leak_into_monthly_directories(self):
        self.data["sites"][1]["month"] = False
        self.save()
        seo.build(self.site)
        self.assertNotIn("app.example", (self.site / "apps/index.html").read_text())
        self.assertIn("game.example", (self.site / "leaderboards/index.html").read_text())

    def test_titles_cannot_inject_html_or_terminate_jsonld(self):
        self.data["sites"][1]["title"] = '</script><script>alert("x")</script> & a tool'
        self.save()
        seo.build(self.site)
        text = (self.site / "apps/index.html").read_text()
        parser = Scripts()
        parser.feed(text)
        self.assertEqual(parser.scripts, [{"type": "application/ld+json"}])
        self.assertIn("&lt;/script&gt;", text)
        self.assertIn("\\u003c/script>", text)

    def test_unsafe_urls_fail_before_any_generated_page_changes(self):
        before = (self.site / "index.html").read_bytes()
        self.data["sites"][1]["url"] = "javascript:alert(1)"
        self.save()
        with self.assertRaises(ValueError):
            seo.build(self.site)
        self.assertEqual((self.site / "index.html").read_bytes(), before)
        self.assertFalse((self.site / "sitemap.xml").exists())

    def test_rejects_credentials_and_control_characters_in_urls(self):
        for url in ("https://user:secret@example.com/", "https://example.com/\nx", "//example.com/", "data:text/html,x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                seo.http_url(url)

    def test_identical_data_is_idempotent_and_keeps_verification(self):
        self.save()
        seo.build(self.site)
        before = {p: p.read_bytes() for p in self.site.rglob("*.html")}
        seo.build(self.site)
        self.assertEqual({p: p.read_bytes() for p in self.site.rglob("*.html")}, before)
        self.assertIn("google-site-verification", (self.site / "index.html").read_text())
        self.assertEqual(json.loads((self.site / "data/sites.json").read_text()), self.data)

    def test_live_tool_is_not_in_sitemap_and_all_canonical_pages_exist(self):
        self.save()
        seo.build(self.site)
        self.assertIn('content="noindex, follow', (self.site / "live/index.html").read_text())
        urls = [e.text for e in ET.parse(self.site / "sitemap.xml").findall(".//{*}loc")]
        self.assertEqual(len(urls), 7)
        self.assertNotIn(seo.ORIGIN + "/live/", urls)
        for url in urls:
            path = self.site / (url.removeprefix(seo.ORIGIN).strip("/") or ".") / "index.html"
            self.assertTrue(path.is_file(), url)
            self.assertIn(f'rel="canonical" href="{url}"', path.read_text())

    def test_missing_marker_stops_build_without_partial_output(self):
        before = (self.site / "index.html").read_bytes()
        (self.site / "leaderboards/index.html").write_text("missing markers")
        self.save()
        with self.assertRaises(ValueError):
            seo.build(self.site)
        self.assertEqual((self.site / "index.html").read_bytes(), before)
        self.assertFalse((self.site / "games/index.html").exists())


if __name__ == "__main__":
    unittest.main()
