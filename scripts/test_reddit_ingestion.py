"""Offline regression checks for Reddit and Show HN ingestion and its cadence."""

import contextlib
import datetime as dt
import html
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import scrape


SINCE = dt.datetime(2026, 9, 4, tzinfo=dt.timezone.utc)
REAL_ARCHIVE_GET = scrape.ArchiveClient.get


def listing_html(pid="example", cursor=None, **overrides):
    attrs = {
        "score": "0", "post-title": "A tool & a game", "id": f"t3_{pid}",
        "content-href": "https://example.com/?a=1&b=2",
        "permalink": f"/r/SideProject/comments/{pid}/example/",
        "created-timestamp": "2026-10-03T12:00:00.000000+0000",
        **overrides,
    }
    attributes = " ".join(f'{key}="{html.escape(str(value), quote=True)}"'
                          for key, value in attrs.items() if value is not None)
    return (f"<shreddit-post {attributes}></shreddit-post>"
            + (f'<faceplate-loader more-posts-cursor="{cursor}"></faceplate-loader>' if cursor else ""))


def listed_post(pid="example", **overrides):
    parser = scrape.RedditListing()
    parser.feed(listing_html(pid, **overrides))
    return parser.posts[0]


def entry(url="https://example.com/", votes=0):
    return scrape.reddit_entry("SideProject", url, "A useful tool", votes,
                              "/r/SideProject/comments/example/example/", 1791028800)


class RedditIngestionTests(unittest.TestCase):
    def setUp(self):
        self.log = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.log))
        self.enterContext(contextlib.redirect_stderr(self.log))
        # Keep tests off the network and away from the real archive cache.
        self.archive_path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "archive-cache.json"
        self.enterContext(patch.object(scrape, "ARCHIVE_CACHE", str(self.archive_path)))
        self.enterContext(patch.object(scrape.ArchiveClient, "get", side_effect=scrape.ArchivePaused("offline")))
        self.enterContext(patch.object(scrape, "ARCHIVE_PAUSE", 0))

    def test_html_entities_and_attribute_order_preserve_a_real_zero_score(self):
        post = listed_post()
        self.assertEqual(post["votes"], 0)
        self.assertEqual(post["title"], "A tool & a game")
        self.assertEqual(post["direct"], "https://example.com/?a=1&b=2")

    def test_unknown_scores_dates_and_invalid_permalinks_are_skipped(self):
        for overrides in ({"score": None}, {"score": "hidden"},
                          {"created-timestamp": "invalid"}, {"permalink": "/login"}):
            with self.subTest(overrides=overrides):
                parser = scrape.RedditListing()
                parser.feed(listing_html(**overrides))
                self.assertEqual(parser.posts, [])

    def test_pagination_follows_cursor_and_stops_on_duplicate_posts(self):
        pages = [listing_html("first", cursor="next"), listing_html("first", cursor="next")]
        with patch.object(scrape, "reddit_get", side_effect=pages) as get:
            posts = scrape.listing_posts("SideProject")
        self.assertEqual([p["id"] for p in posts], ["first"])
        self.assertEqual(get.call_count, 2)
        self.assertIn("after=next", get.call_args.args[0])
        self.assertTrue(all(c.args[0].startswith("https://www.reddit.com/") for c in get.call_args_list))

    def test_later_page_failure_keeps_already_fetched_live_posts(self):
        with patch.object(scrape, "reddit_get", side_effect=[listing_html(cursor="next"), RuntimeError("blocked")]):
            self.assertEqual(len(scrape.listing_posts("SideProject")), 1)
        self.assertIn("pagination stopped", self.log.getvalue())

    def test_block_page_is_rejected_even_with_http_success(self):
        with patch.object(scrape, "reddit_get", return_value="<html>Log in to continue</html>"):
            with self.assertRaisesRegex(ValueError, "no scored posts"):
                scrape.listing_posts("SideProject")

    def test_one_blocked_subreddit_does_not_disable_the_others(self):
        with patch.object(scrape, "SUBREDDITS", ["Blocked", "Working"]), \
             patch.object(scrape, "listing_posts", side_effect=[RuntimeError("403"), [listed_post()], []]), \
             patch.object(scrape, "feed_fallback", side_effect=RuntimeError("also blocked")), \
             patch.object(scrape, "reddit_feed") as feed:
            posts = scrape.reddit_pages(SINCE)
        self.assertEqual([p["source"] for p in posts], ["r/Working"])
        self.assertEqual(posts[0]["votes"], 0)
        feed.assert_not_called()

    def test_blocked_listing_falls_back_to_feed_with_archived_votes(self):
        feed = [{"id": "a", "title": "Tool", "direct": "https://a.example/", "body": [],
                 "permalink": "/r/Blocked/comments/a/tool/", "created": 1791028800},
                {"id": "b", "title": "Tool", "direct": "https://b.example/", "body": [],
                 "permalink": "/r/Blocked/comments/b/tool/", "created": 1791028800},
                {"id": "c", "title": "Tool", "direct": "https://c.example/", "body": [],
                 "permalink": "/r/Blocked/comments/c/tool/", "created": 1791028800}]
        with patch.object(scrape, "SUBREDDITS", ["Blocked"]), \
             patch.object(scrape, "listing_posts", side_effect=RuntimeError("403")), \
             patch.object(scrape, "reddit_feed", return_value=feed), \
             patch.object(scrape, "archive_scores", return_value={"a": 40, "b": 5}), \
             patch.object(scrape, "cached_scores", return_value={"b": 90}):
            posts = scrape.reddit_pages(SINCE)
        # Archived counts never undercut an earlier count; posts with no known count are skipped.
        self.assertEqual({p["url"]: p["votes"] for p in posts}, {"https://a.example/": 40, "https://b.example/": 90})

    def test_text_post_uses_reddit_feed_links_and_live_listing_score(self):
        post = listed_post(**{"content-href": "https://www.reddit.com/r/SideProject/comments/example/example/", "score": "12"})
        feed = [{"id": "example", "body": ["https://example.com/", "https://example.com/demo"]}]
        with patch.object(scrape, "SUBREDDITS", ["SideProject"]), \
             patch.object(scrape, "listing_posts", return_value=[post]), \
             patch.object(scrape, "reddit_feed", return_value=feed):
            posts = scrape.reddit_pages(SINCE)
        self.assertEqual(posts[0]["url"], "https://example.com/")
        self.assertEqual(posts[0]["votes"], 12)

    def test_text_posts_linking_multiple_sites_are_rejected(self):
        post = listed_post(**{"content-href": None})
        feed = [{"id": "example", "body": ["https://example.com/", "https://other.example/"]}]
        with patch.object(scrape, "SUBREDDITS", ["SideProject"]), \
             patch.object(scrape, "listing_posts", return_value=[post]), \
             patch.object(scrape, "reddit_feed", return_value=feed):
            self.assertEqual(scrape.reddit_pages(SINCE), [])

    def test_expired_sensitive_pinned_and_repository_posts_are_excluded(self):
        posts = [listed_post("expired", **{"created-timestamp": "2026-09-01T00:00:00+00:00"}),
                 listed_post("sensitive", **{"is-nsfw": ""}),
                 listed_post("pinned", **{"is-stickied": "true"}),
                 listed_post("repo", **{"content-href": "https://github.com/example/repo"})]
        with patch.object(scrape, "SUBREDDITS", ["SideProject"]), \
             patch.object(scrape, "listing_posts", return_value=posts), \
             patch.object(scrape, "reddit_feed", return_value=[]):
            self.assertEqual(scrape.reddit_pages(SINCE), [])

    def test_feed_failure_keeps_direct_link_posts(self):
        posts = [listed_post(), listed_post("text", **{"content-href": None})]
        with patch.object(scrape, "SUBREDDITS", ["SideProject"]), \
             patch.object(scrape, "listing_posts", return_value=posts), \
             patch.object(scrape, "reddit_feed", side_effect=RuntimeError("blocked")):
            self.assertEqual(len(scrape.reddit_pages(SINCE)), 1)

    def test_failed_scrape_preserves_snapshot_and_original_update_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            out, cache = Path(directory) / "sites.json", Path(directory) / "reddit-cache.json"
            out.write_text('{"generated_at":"previous","sites":[]}')
            cache.write_text(json.dumps({"scraped_at": "previous", "posts": [entry(votes=999)]}))
            previous = (out.read_bytes(), cache.read_bytes())
            with patch.object(scrape, "OUT", str(out)), patch.object(scrape, "REDDIT_CACHE", str(cache)), \
                 patch.object(scrape, "reddit_token", return_value=None), \
                 patch.object(scrape, "reddit_pages", return_value=[]):
                with self.assertRaisesRegex(SystemExit, "no fresh, scored Reddit posts"):
                    scrape.main()
            self.assertEqual((out.read_bytes(), cache.read_bytes()), previous)

    def test_failed_api_credentials_fall_back_to_public_reddit(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(scrape, "REDDIT_CACHE", str(Path(directory) / "cache.json")), \
             patch.object(scrape, "reddit_token", side_effect=RuntimeError("401")), \
             patch.object(scrape, "reddit_pages", return_value=[entry()]) as pages:
            self.assertEqual(scrape.reddit(SINCE), [entry()])
            pages.assert_called_once_with(SINCE)

    def test_api_keeps_zero_votes_and_skips_unknown_votes(self):
        post = {"created_utc": 1791028800, "url": "https://example.com/", "title": "Tool",
                "permalink": "/r/SideProject/comments/example/example/", "score": 0}
        payload = {"data": {"children": [{"data": post}, {"data": {k: v for k, v in post.items() if k != "score"}}]}}
        with patch.object(scrape, "SUBREDDITS", ["SideProject"]), \
             patch.object(scrape, "fetch", return_value=json.dumps(payload).encode()):
            posts = scrape.reddit_api(SINCE, "test-token")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["votes"], 0)

    def test_maker_only_subreddits_keep_only_posts_about_something_made(self):
        made = scrape.reddit_entry("ClaudeAI", "https://made.example/", "I made a lounge for vibecoders", 900, "/r/ClaudeAI/comments/a/x/", 1)
        news = scrape.reddit_entry("ClaudeAI", "https://news.example/", "Anthropic researcher quits", 900, "/r/ClaudeAI/comments/b/x/", 1)
        other = scrape.reddit_entry("SideProject", "https://other.example/", "Plasma UI panels", 50, "/r/SideProject/comments/c/x/", 1)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(scrape, "REDDIT_CACHE", str(Path(directory) / "cache.json")), \
             patch.object(scrape, "reddit_token", return_value=None), \
             patch.object(scrape, "reddit_pages", return_value=[made, news, other]):
            posts = scrape.reddit(scrape.window_start())
        self.assertEqual([p["url"] for p in posts], ["https://made.example/", "https://other.example/"])

    def test_weekly_listing_adds_lower_voted_posts_without_duplicates(self):
        weekly = {**listed_post(), "id": "week", "permalink": "/r/SideProject/comments/week/x/",
                  "direct": "https://week.example/", "votes": 4}
        with patch.object(scrape, "SUBREDDITS", ["SideProject"]), \
             patch.object(scrape, "listing_posts", side_effect=[[listed_post()], [listed_post(), weekly]]) as listing:
            posts = scrape.reddit_pages(SINCE)
        self.assertEqual([c.args for c in listing.call_args_list], [("SideProject",), ("SideProject", "WEEK")])
        self.assertEqual([p["votes"] for p in posts], [listed_post()["votes"], 4])

    def test_failed_weekly_listing_keeps_the_months_posts(self):
        with patch.object(scrape, "SUBREDDITS", ["SideProject"]), \
             patch.object(scrape, "listing_posts", side_effect=[[listed_post()], RuntimeError("403")]):
            self.assertEqual(len(scrape.reddit_pages(SINCE)), 1)

    def test_api_reads_month_and_week_without_duplicates(self):
        post = {"created_utc": 1791028800, "url": "https://example.com/", "title": "Tool",
                "permalink": "/r/SideProject/comments/example/example/", "score": 5}
        payload = json.dumps({"data": {"children": [{"data": post}]}}).encode()
        with patch.object(scrape, "SUBREDDITS", ["SideProject"]), \
             patch.object(scrape, "fetch", return_value=payload) as fetch:
            posts = scrape.reddit_api(SINCE, "test-token")
        self.assertEqual(len(posts), 1)
        self.assertEqual([("t=week" in c.args[0]) for c in fetch.call_args_list], [False, True])

    def test_week_has_a_lower_vote_minimum_than_the_month(self):
        now = dt.datetime.now(dt.timezone.utc).timestamp()
        def post(url, votes, created):
            return scrape.reddit_entry("SideProject", url, "A useful tool", votes,
                                       f"/r/SideProject/comments/{votes}/x/", int(created))
        posts = [post("https://month.example/", 10, now - 20 * 86400), post("https://old.example/", 9, now - 20 * 86400),
                 post("https://week.example/", 3, now - 86400), post("https://two.example/", 2, now - 86400)]
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "sites.json"
            with patch.object(scrape, "OUT", str(out)), patch.object(scrape, "reddit", return_value=posts), \
                 patch.object(scrape, "show_hn", return_value=[]), \
                 patch.object(scrape, "probe", return_value=(True, "")):
                scrape.main()
            sites = json.loads(out.read_text())["sites"]
        self.assertEqual({s["url"]: s.get("month", True) for s in sites},
                         {"https://month.example/": True, "https://week.example/": False})

    def test_successful_rankings_merge_show_hn_and_keep_highest_vote_per_domain(self):
        hn = {**entry("https://hn.example/", 50), "source": "Hacker News"}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "sites.json"
            posts = [entry(votes=0), entry("https://example.com/demo", 25), entry("https://other.example/", 10),
                     entry("https://few-votes.example/", 9)]
            with patch.object(scrape, "OUT", str(out)), patch.object(scrape, "reddit", return_value=posts), \
                 patch.object(scrape, "show_hn", return_value=[hn]), \
                 patch.object(scrape, "probe", return_value=(True, "")):
                scrape.main()
            data = json.loads(out.read_text())
        self.assertEqual([p["votes"] for p in data["sites"]], [50, 25, 10])
        self.assertEqual(data["sites"][0]["source"], "Hacker News")
        self.assertEqual(data["sources"][0]["name"], "Show HN")
        self.assertIn("next_refresh_at", data)

    def test_show_hn_failure_keeps_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "sites.json"
            out.write_text('{"generated_at":"previous","sites":[]}')
            previous = out.read_bytes()
            with patch.object(scrape, "OUT", str(out)), patch.object(scrape, "reddit", return_value=[entry()]), \
                 patch.object(scrape, "show_hn", side_effect=RuntimeError("down")):
                with self.assertRaisesRegex(SystemExit, "Show HN failed"):
                    scrape.main()
            self.assertEqual(out.read_bytes(), previous)

    def test_rate_limit_retries_are_bounded(self):
        error = urllib.error.HTTPError("https://www.reddit.com/", 429, "Too many requests", {}, None)
        self.addCleanup(error.close)
        with patch.object(scrape, "fetch", side_effect=error) as fetch, patch.object(scrape.time, "sleep") as sleep:
            with self.assertRaises(urllib.error.HTTPError):
                scrape.reddit_get("https://www.reddit.com/")
        self.assertEqual(fetch.call_count, 3)
        self.assertLessEqual(max(c.args[0] for c in sleep.call_args_list), 20)

    def test_cadence_survives_month_boundaries_and_runner_delays(self):
        started = dt.datetime(2026, 10, 31, 6, 25, tzinfo=dt.timezone.utc)
        due = scrape.next_refresh_time(started)
        self.assertEqual(due, dt.datetime(2026, 11, 3, 6, 17, tzinfo=dt.timezone.utc))
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "sites.json"
            out.write_text(json.dumps({"generated_at": started.isoformat(), "next_refresh_at": due.isoformat(), "sites": [entry()]}))
            with patch.object(scrape, "OUT", str(out)):
                self.assertFalse(scrape.refresh_due(dt.datetime(2026, 11, 1, 6, 17, tzinfo=dt.timezone.utc)))
                self.assertFalse(scrape.refresh_due(due - dt.timedelta(seconds=1)))
                self.assertTrue(scrape.refresh_due(due))

    def test_not_due_run_preserves_data_and_performs_no_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "sites.json"
            out.write_text('{"generated_at":"previous","sites":[]}')
            previous = out.read_bytes()
            with patch.object(scrape, "OUT", str(out)), patch.object(scrape, "refresh_due", return_value=False), \
                 patch.object(scrape, "reddit") as reddit:
                scrape.main(if_due=True)
            reddit.assert_not_called()
            self.assertEqual(out.read_bytes(), previous)

    def test_snapshots_without_a_valid_schedule_are_due(self):
        now = dt.datetime(2026, 10, 4, tzinfo=dt.timezone.utc)
        payloads = [{"sites": [entry()], "generated_at": now.isoformat()},
                    {"sites": [], "generated_at": now.isoformat(), "next_refresh_at": "2026-10-07T00:00:00+00:00"},
                    {"sites": [entry()], "generated_at": "invalid", "next_refresh_at": "invalid"}]
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "sites.json"
            with patch.object(scrape, "OUT", str(out)):
                for payload in payloads:
                    with self.subTest(payload=payload):
                        out.write_text(json.dumps(payload))
                        self.assertTrue(scrape.refresh_due(now))


    # ---- Arctic Shift last-resort fallback ----

    def archive_post(self, pid, created, score, url=None):
        return {"id": pid, "title": "Tool", "url": url or f"https://{pid}.example/", "selftext": "",
                "score": score, "created_utc": created, "over_18": False, "stickied": False}

    def test_archive_is_used_only_when_listing_and_rss_both_fail(self):
        with patch.object(scrape, "SUBREDDITS", ["Working", "RssOnly", "Blocked"]), \
             patch.object(scrape, "listing_posts", side_effect=[[listed_post()], [], RuntimeError("403"), RuntimeError("403")]), \
             patch.object(scrape, "feed_fallback", side_effect=[[entry("https://rss.example/", 20)], RuntimeError("RSS gone")]), \
             patch.object(scrape, "archive_sync", side_effect=lambda cache, since: cache) as sync:
            scrape.reddit_pages(SINCE)
        cache = json.loads(self.archive_path.read_text())
        self.assertTrue(cache["active"])
        self.assertEqual(cache["subreddits"], ["Blocked"])
        sync.assert_called_once()

    def test_archive_stays_off_while_other_routes_work(self):
        with patch.object(scrape, "SUBREDDITS", ["Working"]), \
             patch.object(scrape, "listing_posts", return_value=[listed_post()]), \
             patch.object(scrape, "archive_sync") as sync:
            scrape.reddit_pages(SINCE)
        sync.assert_not_called()
        self.assertFalse(self.archive_path.exists())

    def test_archive_sync_pauses_on_rate_limit_and_resumes_from_its_cursor(self):
        now = SINCE.timestamp() + 20 * 86400
        page = [self.archive_post(f"p{i}", int(SINCE.timestamp()) + 60 * i, 50) for i in range(100)]
        cache = {"active": True, "subreddits": ["Blocked"], "cursors": {}, "posts": {}}
        with patch.object(scrape.ArchiveClient, "get", side_effect=[page, scrape.ArchivePaused("slow down")]):
            scrape.archive_sync(cache, SINCE, now=now)
        self.assertEqual(len(cache["posts"]), 100)
        resume = cache["cursors"]["Blocked"]
        self.assertEqual(resume, page[-1]["created_utc"] + 1)
        with patch.object(scrape.ArchiveClient, "get", return_value=[]) as get:
            scrape.archive_sync(cache, SINCE, now=now)
        self.assertEqual(get.call_args_list[0].args[1]["after"], resume)

    def test_archive_budget_caps_requests_per_run(self):
        cache = {"active": True, "subreddits": ["Blocked"], "cursors": {}, "posts": {}}
        start = int(SINCE.timestamp())
        pages = iter(range(10))
        def full_page(url, *args, **kwargs):
            n = next(pages)
            return json.dumps({"data": [self.archive_post(f"r{n}_{i}", start + n * 1000 + i, 5) for i in range(100)]}).encode()
        with patch.object(scrape.ArchiveClient, "get", REAL_ARCHIVE_GET), \
             patch.object(scrape, "fetch", side_effect=full_page) as fetch:
            scrape.archive_sync(cache, SINCE, budget=2, now=start + 20 * 86400)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(len(cache["posts"]), 200)
        self.assertIn("pausing until the next run", self.log.getvalue())

    def test_settled_posts_get_their_counts_re_read(self):
        created = int(SINCE.timestamp())
        now = created + 3 * 86400
        cache = {"active": True, "subreddits": ["Blocked"], "cursors": {"Blocked": now}, "posts": {
            "fresh": {"sub": "Blocked", "title": "Tool", "score": 1, "direct": "https://fresh.example/", "body": [],
                      "permalink": "/r/Blocked/comments/fresh/tool/", "created": created + 60, "settled": False}}}
        with patch.object(scrape.ArchiveClient, "get", side_effect=[[], [{"id": "fresh", "score": 321}]]):
            scrape.archive_sync(cache, SINCE, now=now)
        self.assertEqual(cache["posts"]["fresh"]["score"], 321)
        self.assertTrue(cache["posts"]["fresh"]["settled"])
        with patch.object(scrape, "cached_scores", return_value={"fresh": 400}):
            self.assertEqual(scrape.archive_entries(cache, "Blocked", SINCE)[0]["votes"], 400)

    def test_daily_sync_does_nothing_unless_the_fallback_is_active(self):
        with patch.object(scrape, "archive_sync") as sync:
            scrape.archive_daily_sync()
        sync.assert_not_called()
        self.archive_path.write_text(json.dumps({"active": True, "subreddits": ["Blocked"], "cursors": {}, "posts": {}}))
        with patch.object(scrape, "archive_sync", side_effect=lambda cache, since: cache) as sync:
            scrape.archive_daily_sync()
        sync.assert_called_once()


if __name__ == "__main__":
    unittest.main()
