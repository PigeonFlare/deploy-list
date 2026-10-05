"""Unit tests for scraper logic and URL validation."""

import datetime as dt
import unittest
from unittest.mock import MagicMock, patch

import scrape


class ScraperTests(unittest.TestCase):
    def test_site_url_valid(self):
        self.assertEqual(scrape.site_url("https://example.com/app", "Cool app"), "https://example.com/app")
        self.assertEqual(scrape.site_url("http://sub.example.org/", "Project"), "http://sub.example.org/")
        self.assertEqual(scrape.site_url("https://example.com", "Title"), "https://example.com/")

    def test_site_url_strips_auth_credentials(self):
        cleaned = scrape.site_url("https://user:password@example.com/path", "App")
        self.assertEqual(cleaned, "https://example.com/path")
        self.assertNotIn("user", cleaned)
        self.assertNotIn("password", cleaned)

    def test_site_url_blocked_hosts(self):
        for host in ["github.com", "x.com", "deploylist.com", "youtube.com", "reddit.com"]:
            with self.subTest(host=host):
                self.assertIsNone(scrape.site_url(f"https://{host}/repo", "Title"))
                self.assertIsNone(scrape.site_url(f"https://sub.{host}/repo", "Title"))

    def test_site_url_rejects_vendor_news_and_article_links(self):
        for url in ["https://www.anthropic.com/news/x", "https://claude.ai/share/x", "https://www.businessinsider.com/x",
                    "https://blog.cloudflare.com/x", "https://shopify.engineering/x"]:
            with self.subTest(url=url):
                self.assertIsNone(scrape.site_url(url, "Title"))
        for title in ["Why CSS-Tricks has been quiet", "How to write a design doc", "Hot take: React is fine",
                      "Introducing Claude Opus 5.5"]:
            with self.subTest(title=title):
                self.assertIsNone(scrape.site_url("https://example.com/", title))
        self.assertIsNotNone(scrape.site_url("https://example.com/", "Page Rage: destroy any page"))

    def test_page_summary_feeds_category(self):
        page = b"""<html><head><title>Page Rage</title>
          <meta name="description" content="A browser game: fly around and shoot any web page to pieces">
          <meta property="og:title" content='Page Rage &amp; friends'></head></html>"""
        summary = scrape.page_summary(page)
        self.assertIn("shoot any web page", summary)
        self.assertEqual(scrape.category("I built a website for safe area insets in Simulator", "r/SideProject"), "other")
        self.assertIn("Page Rage & friends", summary)
        self.assertEqual(scrape.category("Destroy any web page " + summary, "r/webdev"), "games")

    def test_maker_title(self):
        for title in ["Made a Destroy Any Website game", "I made a virtual lounge", "My SaaS crossed 1M users",
                      "hey opus can you build me a news network"]:
            with self.subTest(title=title):
                self.assertTrue(scrape.MAKER_TITLE.search(title))
        for title in ["Anthropic researcher quits", "Claude Opus 5.5 official prompting guide"]:
            with self.subTest(title=title):
                self.assertFalse(scrape.MAKER_TITLE.search(title))

    def test_site_url_rejects_non_http(self):
        self.assertIsNone(scrape.site_url("javascript:alert(1)", "Title"))
        self.assertIsNone(scrape.site_url("data:text/html,test", "Title"))
        self.assertIsNone(scrape.site_url("file:///etc/passwd", "Title"))

    def test_site_url_rejects_raw_ip_addresses_and_unusual_ports(self):
        self.assertIsNone(scrape.site_url("http://127.0.0.1/", "Title"))
        self.assertIsNone(scrape.site_url("http://169.254.169.254/latest", "Title"))
        self.assertIsNone(scrape.site_url("http://[::1]/", "Title"))
        self.assertIsNone(scrape.site_url("https://example.com:22/", "Title"))
        self.assertIsNone(scrape.site_url("https://example.com:25/", "Title"))
        # Standard ports 80, 443, 8080, 8443 are allowed
        self.assertIsNotNone(scrape.site_url("https://example.com:8080/", "Title"))

    def test_site_url_rejects_blog_and_static_files(self):
        self.assertIsNone(scrape.site_url("https://example.com/blog/my-post", "Title"))
        self.assertIsNone(scrape.site_url("https://example.com/posts/2026/01/post", "Title"))
        self.assertIsNone(scrape.site_url("https://example.com/doc.pdf", "Title"))
        self.assertIsNone(scrape.site_url("https://example.com/image.png", "Title"))
        self.assertIsNone(scrape.site_url("https://example.com/demo", "Why I built this: blog post"))

    def test_category_classification(self):
        self.assertEqual(scrape.category("Cool browser game", "r/SideProject"), "games")
        self.assertEqual(scrape.category("Random project", "r/WebGames"), "games")
        self.assertEqual(scrape.category("AI task manager and calendar", "r/SideProject"), "apps")
        self.assertEqual(scrape.category("A generative art showcase", "r/SideProject"), "other")

    def test_pick_site(self):
        self.assertEqual(
            scrape.pick_site("App", "https://example.com/app"),
            "https://example.com/app"
        )
        self.assertEqual(
            scrape.pick_site("App", None, ["https://example.com/app/deep/path", "https://example.com/"]),
            "https://example.com/"
        )
        # Multiple different domains in body links should be rejected
        self.assertIsNone(
            scrape.pick_site("App", None, ["https://example.com/", "https://other.com/"])
        )

    @patch("scrape.public_host", return_value=True)
    def test_embeddable_headers(self, _public):
        def make_mock_response(url="https://example.com", status=200, headers=None):
            headers = headers or {}
            mock = MagicMock()
            mock.geturl.return_value = url
            mock.status = status
            mock_headers = MagicMock()
            mock_headers.get = lambda k, d=None: headers.get(k, d)
            mock_headers.get_all = lambda k, d=None: [headers[k]] if k in headers else (d or [])
            mock.headers = mock_headers
            return mock

        # Normal HTTPS site is embeddable
        with patch.object(scrape._PROBE, "open") as mock_open:
            mock_open.return_value.__enter__.return_value = make_mock_response()
            self.assertTrue(scrape.embeddable("https://example.com"))

        # X-Frame-Options DENY / SAMEORIGIN block framing
        for xfo in ["DENY", "SAMEORIGIN"]:
            with patch.object(scrape._PROBE, "open") as mock_open:
                mock_open.return_value.__enter__.return_value = make_mock_response(
                    headers={"X-Frame-Options": xfo}
                )
                self.assertFalse(scrape.embeddable("https://example.com"))

        # ALLOW-FROM is ignored by current browsers, so the site still frames
        with patch.object(scrape._PROBE, "open") as mock_open:
            mock_open.return_value.__enter__.return_value = make_mock_response(
                headers={"X-Frame-Options": "ALLOW-FROM https://other.com"}
            )
            self.assertTrue(scrape.embeddable("https://example.com"))

        # CSP frame-ancestors
        with patch.object(scrape._PROBE, "open") as mock_open:
            mock_open.return_value.__enter__.return_value = make_mock_response(
                headers={"Content-Security-Policy": "frame-ancestors 'none'"}
            )
            self.assertFalse(scrape.embeddable("https://example.com"))

        with patch.object(scrape._PROBE, "open") as mock_open:
            mock_open.return_value.__enter__.return_value = make_mock_response(
                headers={"Content-Security-Policy": "frame-ancestors *"}
            )
            self.assertTrue(scrape.embeddable("https://example.com"))

        # Redirects to plain HTTP, blocked hosts, or IP addresses are refused before connecting
        for target in ["http://insecure.example.com", "https://github.com/my/repo", "https://169.254.169.254/secret"]:
            redirect = scrape.urllib.error.HTTPError("https://example.com", 302, "Found", {"Location": target}, None)
            with patch.object(scrape._PROBE, "open", side_effect=redirect) as mock_open:
                self.assertFalse(scrape.embeddable("https://example.com"))
                self.assertEqual(mock_open.call_count, 1)

    def test_reddit_feed_malformed_resilience(self):
        bad_feed = "<entry><title>Test</title><published>invalid-date</published></entry>"
        with patch("scrape.reddit_get", return_value=bad_feed):
            since = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
            posts = scrape.reddit_feed("SideProject", since)
            self.assertEqual(posts, [])


    def test_site_url_rejects_malformed_ports(self):
        self.assertIsNone(scrape.site_url("https://example.com:abc/", "Title"))
        self.assertIsNone(scrape.site_url("https://example.com:99999/", "Title"))

    def test_embeddable_refuses_private_destinations(self):
        with patch("scrape.public_host", return_value=False), patch.object(scrape._PROBE, "open") as mock_open:
            self.assertFalse(scrape.embeddable("https://example.com"))
            mock_open.assert_not_called()

    def test_embeddable_checks_redirect_targets_before_connecting(self):
        redirect = scrape.urllib.error.HTTPError("https://example.com", 302, "Found",
                                                 {"Location": "https://internal.example/"}, None)
        with patch("scrape.public_host", side_effect=lambda h: h == "example.com"), \
                patch.object(scrape._PROBE, "open", side_effect=redirect) as mock_open:
            self.assertFalse(scrape.embeddable("https://example.com"))
            self.assertEqual(mock_open.call_count, 1)

    @patch("scrape.public_host", return_value=True)
    @patch("scrape.time.sleep")
    def test_embeddable_retries_a_dropped_connection(self, _sleep, _public):
        ok = MagicMock()
        ok.status = 200
        ok.headers.get_all = lambda k, d=None: d or []
        ok.__enter__.return_value = ok
        with patch.object(scrape._PROBE, "open", side_effect=[scrape.urllib.error.URLError("reset"), ok]) as mock_open:
            self.assertTrue(scrape.embeddable("https://example.com"))
            self.assertEqual(mock_open.call_count, 2)


if __name__ == "__main__":
    unittest.main()
