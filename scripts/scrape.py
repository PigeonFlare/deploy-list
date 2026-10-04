#!/usr/bin/env python3
"""Build site/data/sites.json directly from this month's top Reddit posts.

Only posts centred on one standalone website are kept (no GitHub repos,
store pages, blog posts or social links). Each site is then probed to see
whether it can be shown inside an <iframe>; sites that can't stay on the
leaderboard but are left out of live view.

Standard library only. Reddit's API is used when REDDIT_CLIENT_ID and
REDDIT_CLIENT_SECRET are set; otherwise its public listings and RSS are read.
Post details and vote counts always come from Reddit itself.
"""

import argparse
import base64
import datetime as dt
import html
import ipaddress
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

OUT = os.path.join(os.path.dirname(__file__), "..", "site", "data", "sites.json")
# Save successful direct scrapes for inspection. Failed runs leave this snapshot
# and the published rankings unchanged.
REDDIT_CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "reddit-cache.json")
UA = "deploylist/1.0 (+https://deploylist.com)"
POOL_SIZE = 100  # candidates kept; the pages show the top 25 per category
REFRESH_INTERVAL = dt.timedelta(days=3)
# Match the daily due-check in .github/workflows/deploy.yml.
REFRESH_HOUR, REFRESH_MINUTE = 6, 17

SUBREDDITS = ["SideProject", "InternetIsBeautiful", "WebGames", "alphaandbetausers", "IMadeThis"]

# Hosts that are never "a standalone website" for our purposes.
BLOCKED_HOSTS = {
    "github.com", "gist.github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "sr.ht",
    "apps.apple.com", "itunes.apple.com", "play.google.com", "chromewebstore.google.com",
    "chrome.google.com", "addons.mozilla.org", "microsoftedge.microsoft.com", "store.steampowered.com",
    "itch.io", "producthunt.com", "npmjs.com", "pypi.org", "crates.io", "huggingface.co",
    "marketplace.visualstudio.com", "kickstarter.com", "indiegogo.com",
    "medium.com", "substack.com", "dev.to", "hashnode.dev", "wordpress.com", "blogspot.com",
    "notion.site", "notion.so", "docs.google.com", "drive.google.com", "forms.gle",
    "youtube.com", "youtu.be", "vimeo.com", "loom.com", "twitter.com", "x.com", "linkedin.com",
    "facebook.com", "instagram.com", "tiktok.com", "threads.net", "bsky.app", "mastodon.social",
    "reddit.com", "redd.it", "redditstatic.com", "redditmedia.com", "reddit.app.link", "onelink.me", "app.link", "imgur.com", "i.imgur.com", "news.ycombinator.com", "discord.gg",
    "discord.com", "t.me", "arxiv.org", "wikipedia.org", "bit.ly", "tinyurl.com", "linktr.ee",
    "deploylist.com", "pigeonflare.github.io",  # never frame our own origin
}
BLOG_PATH = re.compile(r"/(blog|posts?|articles?|news|p|story|stories|writing|essays?|\d{4}/\d{2})(/|$)", re.I)
BLOG_TITLE = re.compile(r"^(how|why|what) i\b|\bi wrote\b|\bwrite-?up\b|\bpost-?mortem\b|\blessons learned\b|\bblog\b", re.I)
GAME_WORDS = re.compile(
    r"\b(game|games|gaming|play|playable|puzzle|puzzles|wordle|chess|arcade|multiplayer|trivia|sudoku|"
    r"crossword|roguelike|platformer|idle|clicker|quiz|guess|geoguessr|tetris|snake|minesweeper|solitaire|"
    r"factorio|simulator|rpg|mmo|io game)\b", re.I)
APP_WORDS = re.compile(
    r"\b(app|apps|tool|tools|editor|generator|tracker|converter|platform|dashboard|ai|saas|api|manager|"
    r"builder|calculator|planner|extension|assistant|analytics|search|engine|notes?|budget|finance|"
    r"crm|chat|convert|compress|pdf|resume|invoice|scheduler|calendar|monitor|ide|cli|database|workflow|"
    r"agents?|harness|workspace|sandbox|email|course|learn|translate|password|tasks?|todo|productivity)\b", re.I)
NSFW = re.compile(r"\bnsfw\b|\bporn|\bonlyfans\b|\bxxx\b", re.I)
URL_RE = re.compile(r"https?://[^\s)\]>\"'|]+")


def fetch(url, headers=None, data=None, timeout=20):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(20_000_000)  # cap response size


def host_of(url):
    h = (urllib.parse.urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def blocked(host):
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


def is_ip(host):
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def site_url(url, title):
    """Return a cleaned URL if this link is a standalone website, else None."""
    url = html.unescape(url).rstrip(".,;:!?")
    try:
        parts = urllib.parse.urlsplit(url)
    except Exception:
        return None
    host = host_of(url)
    if parts.scheme not in ("http", "https") or not host or "." not in host or is_ip(host) or blocked(host):
        return None
    if parts.port and parts.port not in (80, 443, 8080, 8443):
        return None
    if BLOG_PATH.search(parts.path) or BLOG_TITLE.search(title or ""):
        return None
    if re.search(r"\.(pdf|png|jpe?g|gif|mp4|zip)$", parts.path, re.I):
        return None
    netloc = (parts.hostname or "") + (f":{parts.port}" if parts.port else "")
    if not netloc:
        return None
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def category(text, source):
    if source == "r/WebGames" or GAME_WORDS.search(text):
        return "games"
    if APP_WORDS.search(text):
        return "apps"
    return "other"


def window_start():
    # A rolling 30-day window, so the board isn't nearly empty early in a calendar month.
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)


def refresh_due(now):
    """Refresh when due, or immediately when migrating the old mixed feed."""
    try:
        with open(OUT, encoding="utf-8") as f:
            data = json.load(f)
        if (not data.get("sites") or not data.get("next_refresh_at")
                or any(not p.get("source", "").startswith("r/") for p in data["sites"])):
            return True
        generated = dt.datetime.fromisoformat(data["generated_at"])
        due = dt.datetime.fromisoformat(data["next_refresh_at"])
        if generated.tzinfo is None or due.tzinfo is None or generated > now:
            return True
        return now >= due
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return True


def next_refresh_time(now):
    """Anchor the next collection to the clock so runner delays don't add a day."""
    slot = now.astimezone(dt.timezone.utc).replace(
        hour=REFRESH_HOUR, minute=REFRESH_MINUTE, second=0, microsecond=0)
    if slot > now:
        slot -= dt.timedelta(days=1)
    return slot + REFRESH_INTERVAL


def reddit_token():
    cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return None
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    body = fetch("https://www.reddit.com/api/v1/access_token",
                 headers={"Authorization": f"Basic {auth}"},
                 data=b"grant_type=client_credentials")
    return json.loads(body)["access_token"]


def pick_site(title, direct, body_links=()):
    """The post's site: its link if it has one, else the single site its text links to."""
    url = site_url(direct or "", title)
    if url:
        return url
    links = {site_url(u, title) for u in body_links} - {None}
    if len({host_of(u) for u in links}) != 1:
        return None
    return sorted(links, key=len)[0]


def reddit_api(since, token):
    out = []
    for sub in SUBREDDITS:
        try:
            data = json.loads(fetch(f"https://oauth.reddit.com/r/{sub}/top.json?t=month&limit=100&raw_json=1",
                                    {"Authorization": f"bearer {token}"}))
        except Exception as e:  # one subreddit failing shouldn't sink the run
            print(f"warn: r/{sub}: {e}", file=sys.stderr)
            continue
        for c in data["data"]["children"]:
            p = c["data"]
            if not isinstance(p.get("score"), int):
                continue
            if p.get("created_utc", 0) < since.timestamp() or p.get("over_18") or p.get("stickied"):
                continue
            title = p.get("title") or ""
            direct = None if p.get("is_self") else p.get("url_overridden_by_dest") or p.get("url")
            url = pick_site(title, direct, URL_RE.findall(p.get("selftext") or ""))
            if url:
                out.append(reddit_entry(sub, url, title, p["score"], p["permalink"], int(p.get("created_utc", 0))))
    return out


def reddit_entry(sub, url, title, votes, permalink, created):
    return {
        "url": url, "title": title, "votes": votes,
        "source": f"r/{sub}", "source_url": f"https://www.reddit.com/r/{sub}/",
        "post_url": "https://www.reddit.com" + permalink, "created": created,
    }


# Listings supply live votes and link posts; RSS supplies links in text posts.
LISTING_PAGES = 5  # about 20 posts per page


def reddit_get(url, attempts=3):
    for i in range(attempts):
        time.sleep(1.5)  # stay well under Reddit's rate limit
        try:
            return fetch(url, {"Accept-Language": "en-US"}).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == attempts - 1:
                raise
            time.sleep(10 * (i + 1))


def reddit_feed(sub, since):
    feed = reddit_get(f"https://www.reddit.com/r/{sub}/top/.rss?t=month&limit=100")
    posts = []
    for e in re.findall(r"<entry>(.*?)</entry>", feed, re.S):
        try:
            get = lambda tag: html.unescape((re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", e, re.S) or [None, ""])[1])
            pub = get("published")
            if not pub:
                continue
            created = dt.datetime.fromisoformat(pub).timestamp()
            if created < since.timestamp():
                continue
            anchors = re.findall(r'<a href="([^"]+)">([^<]*)</a>', get("content"))
            direct = next((h for h, text in anchors if text == "[link]"), None)
            permalink = next((h for h, text in anchors if text == "[comments]"), "")
            body = [h for h, text in anchors if text not in ("[link]", "[comments]")]
            posts.append({
                "id": get("id").removeprefix("t3_"), "title": get("title"), "direct": direct, "body": body,
                "permalink": urllib.parse.urlsplit(permalink).path, "created": int(created),
            })
        except Exception:
            continue
    return posts


class RedditListing(HTMLParser):
    """Read scored posts without depending on HTML attribute order."""

    def __init__(self):
        super().__init__()
        self.posts = []
        self.after = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("more-posts-cursor"):
            self.after = attrs["more-posts-cursor"]
        if tag != "shreddit-post" or not attrs.get("id", "").startswith("t3_"):
            return
        try:
            post = {
                "id": attrs["id"].removeprefix("t3_"),
                "title": attrs["post-title"], "direct": attrs.get("content-href"),
                "votes": int(attrs["score"]),
                "permalink": urllib.parse.urlsplit(attrs["permalink"]).path,
                "created": int(dt.datetime.fromisoformat(attrs["created-timestamp"]).timestamp()),
            }
        except (KeyError, TypeError, ValueError):
            return  # Unknown scores must never turn into zero-vote posts.
        if not post["permalink"].startswith("/r/") or "/comments/" not in post["permalink"]:
            return
        post["excluded"] = any(
            key in attrs and attrs[key] in (None, "", "true", "1")
            for key in ("nsfw", "is-nsfw", "is-stickied", "is-pinned", "is-promoted")
        )
        self.posts.append(post)


def listing_posts(sub):
    """Read a bounded number of pages directly from Reddit, with live scores."""
    posts, after = {}, None
    for _ in range(LISTING_PAGES):
        q = {"t": "MONTH", "name": sub, **({"after": after} if after else {})}
        try:
            page = reddit_get("https://www.reddit.com/svc/shreddit/community-more-posts/top/?" + urllib.parse.urlencode(q))
            listing = RedditListing()
            listing.feed(page)
            if not listing.posts:
                raise ValueError("Reddit returned no scored posts")
        except Exception as e:
            if not posts:
                raise
            print(f"warn: r/{sub}: pagination stopped ({e}); keeping the live posts already read", file=sys.stderr)
            break
        new = {p["id"]: p for p in listing.posts if p["id"] not in posts}
        posts.update(new)
        if not new or not listing.after or listing.after == after:
            break
        after = listing.after
    return list(posts.values())


def reddit_pages(since):
    out = []
    for sub in SUBREDDITS:
        try:
            posts = listing_posts(sub)
        except Exception as e:
            print(f"warn: r/{sub}: {e}", file=sys.stderr)
            continue
        posts = [p for p in posts if p["created"] >= since.timestamp()
                 and not p["excluded"] and not NSFW.search(p["title"])]
        feed = {}
        if any(not site_url(p["direct"] or "", p["title"]) for p in posts):
            try:
                feed = {p["id"]: p for p in reddit_feed(sub, since)}
            except Exception as e:
                print(f"warn: r/{sub} text links: {e}", file=sys.stderr)
        kept = 0
        for p in posts:
            text = feed.get(p["id"], {})
            url = pick_site(p["title"], p["direct"] or text.get("direct"), text.get("body", ()))
            if url:
                out.append(reddit_entry(sub, url, p["title"], p["votes"], p["permalink"], p["created"]))
                kept += 1
        print(f"r/{sub}: {kept} sites (live Reddit scores)", flush=True)
    return out


def reddit(since):
    posts = []
    try:
        token = reddit_token()
        if token:
            posts = reddit_api(since, token)
    except Exception as e:
        print(f"warn: Reddit API failed: {e}; trying public listings", file=sys.stderr)
    if not posts:
        posts = reddit_pages(since)
    if posts:
        os.makedirs(os.path.dirname(REDDIT_CACHE), exist_ok=True)
        tmp = REDDIT_CACHE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"scraped_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "posts": posts}, f, indent=1)
        os.replace(tmp, REDDIT_CACHE)
        return posts
    return []


def embeddable(url):
    """True when the site loads over HTTPS and doesn't forbid framing."""
    try:
        req = urllib.request.Request(url.replace("http://", "https://", 1),
                                     headers={"User-Agent": "Mozilla/5.0 (deploylist iframe check)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            final_url = r.geturl()
            if not final_url.startswith("https://") or r.status >= 400:
                return False
            final_host = host_of(final_url)
            if not final_host or blocked(final_host) or is_ip(final_host):
                return False
            for xfo in r.headers.get_all("X-Frame-Options") or []:
                xfo_lower = xfo.lower()
                # ALLOW-FROM is ignored by current browsers, so it doesn't block framing.
                if "deny" in xfo_lower or "sameorigin" in xfo_lower:
                    return False
            for csp in r.headers.get_all("Content-Security-Policy") or []:
                m = re.search(r"frame-ancestors([^;]*)", csp, re.I)
                if m and "*" not in m.group(1).split():
                    return False
            return True
    except Exception:
        return False


def main(if_due=False):
    started = dt.datetime.now(dt.timezone.utc)
    if if_due and not refresh_due(started):
        print("Reddit refresh is not due; keeping the current rankings and update timestamp")
        return
    since = window_start()
    posts = reddit(since)
    print(f"Reddit: {len(posts)} candidate posts")
    if not posts:
        sys.exit("no fresh, scored Reddit posts scraped; keeping existing data")

    # One entry per domain, keeping its best-voted post.
    best = {}
    for p in posts:
        d = host_of(p["url"])
        if d not in best or p["votes"] > best[d]["votes"]:
            best[d] = {**p, "domain": d}
    sites = sorted(best.values(), key=lambda s: -s["votes"])[:POOL_SIZE]

    with ThreadPoolExecutor(16) as ex:
        flags = list(ex.map(lambda s: embeddable(s["url"]), sites))
    for s, ok in zip(sites, flags):
        s["embeddable"] = ok
        s["category"] = category(s["title"], s["source"])
        s["url"] = s["url"].replace("http://", "https://", 1) if ok else s["url"]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "next_refresh_at": next_refresh_time(started).isoformat(timespec="seconds"),
            "since": since.isoformat(timespec="seconds"),
            "sources": [{"name": f"r/{s}", "url": f"https://www.reddit.com/r/{s}/"} for s in SUBREDDITS],
            "sites": sites,
        }, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, OUT)
    print(f"wrote {len(sites)} sites ({sum(flags)} embeddable) to {os.path.normpath(OUT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--if-due", action="store_true", help="skip collection until the next three-day refresh is due")
    main(if_due=parser.parse_args().if_due)
