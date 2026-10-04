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

    def test_embeddable_headers(self):
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
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value = make_mock_response()
            self.assertTrue(scrape.embeddable("https://example.com"))

        # X-Frame-Options DENY / SAMEORIGIN block framing
        for xfo in ["DENY", "SAMEORIGIN"]:
            with patch("urllib.request.urlopen") as mock_open:
                mock_open.return_value.__enter__.return_value = make_mock_response(
                    headers={"X-Frame-Options": xfo}
                )
                self.assertFalse(scrape.embeddable("https://example.com"))

        # ALLOW-FROM is ignored by current browsers, so the site still frames
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value = make_mock_response(
                headers={"X-Frame-Options": "ALLOW-FROM https://other.com"}
            )
            self.assertTrue(scrape.embeddable("https://example.com"))

        # CSP frame-ancestors
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value = make_mock_response(
                headers={"Content-Security-Policy": "frame-ancestors 'none'"}
            )
            self.assertFalse(scrape.embeddable("https://example.com"))

        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value = make_mock_response(
                headers={"Content-Security-Policy": "frame-ancestors *"}
            )
            self.assertTrue(scrape.embeddable("https://example.com"))

        # Non-HTTPS URL after redirect is rejected
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value = make_mock_response(
                url="http://insecure.example.com"
            )
            self.assertFalse(scrape.embeddable("https://example.com"))

        # Redirect to a blocked host is rejected
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value = make_mock_response(
                url="https://github.com/my/repo"
            )
            self.assertFalse(scrape.embeddable("https://example.com"))

        # Redirect to an IP address is rejected
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value = make_mock_response(
                url="https://169.254.169.254/secret"
            )
            self.assertFalse(scrape.embeddable("https://example.com"))

    def test_reddit_feed_malformed_resilience(self):
        bad_feed = "<entry><title>Test</title><published>invalid-date</published></entry>"
        with patch("scrape.reddit_get", return_value=bad_feed):
            since = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
            posts = scrape.reddit_feed("SideProject", since)
            self.assertEqual(posts, [])


if __name__ == "__main__":
    unittest.main()
