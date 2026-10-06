#!/usr/bin/env python3
"""Build site/data/sites.json from the last 30 days (and the last 7) of top Show HN and Reddit posts.

Only posts centred on one standalone website are kept (no GitHub repos,
store pages, blog posts or social links). Each site is then probed to see
whether it can be shown inside an <iframe>; sites that can't stay on the
leaderboard but are left out of live view.

Show HN comes from hn.algolia.com. Reddit comes from its API when
REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are set, otherwise from its public
listings, which give live vote counts. Reddit blocks those listings from
GitHub's servers, so a blocked subreddit falls back to Reddit's RSS feed with
vote counts from the Arctic Shift archive, which run somewhat behind the live
ones. Standard library only.
"""

import argparse
import base64
import datetime as dt
import html
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from html.parser import HTMLParser

OUT = os.path.join(os.path.dirname(__file__), "..", "site", "data", "sites.json")
# Save successful direct scrapes for inspection. Failed runs leave this snapshot
# and the published rankings unchanged.
# Sites that pass every automatic check but still break inside Live's frame (they switch
# features off when framed, or rely on cookies a frame doesn't get). Domain -> why.
LIVE_EXCLUDE = os.path.join(os.path.dirname(__file__), "..", "data", "live-exclude.json")
REDDIT_CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "reddit-cache.json")
# Posts collected from the Arctic Shift archive, used only when Reddit's API,
# listings and RSS feeds all fail. Filled a little at a time across daily runs.
ARCHIVE_CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "archive-cache.json")
# The category the model gave each ranked post, so each post is only sent once.
CATEGORY_CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "categories.json")
UA = "deploylist/1.0 (+https://deploylist.com)"
MONTH_POOL_SIZE = 200  # sites kept and shown for the month, split across the categories
WEEK_POOL_SIZE = 100  # the same for the last week
MIN_VOTES = 10  # Show HN points or Reddit upvotes a post needs to be ranked for the month
WEEK_MIN_VOTES = 3  # lower for the last week, so that list can fill up too
REFRESH_INTERVAL = dt.timedelta(days=3)
# Match the daily due-check in .github/workflows/deploy.yml.
REFRESH_HOUR, REFRESH_MINUTE = 6, 17

# Each contributed at least two standalone sites with 100+ votes in a month (checked Oct 2026);
# r/WebGames and r/alphaandbetausers didn't and were dropped.
SUBREDDITS = ["SideProject", "InternetIsBeautiful", "IMadeThis", "ClaudeAI", "SaaS"]
# Subreddits where most top posts are news, announcements or discussion: only posts
# whose title says the poster made the thing count.
MAKER_ONLY = {"ClaudeAI", "SaaS"}
MAKER_TITLE = re.compile(
    r"\b(i|we|i've|we've|i'm|we're|my|our)\b|^(made|built|created|launched|introducing my)\b|"
    r"\b(made|built|build|building|created|launched|shipped|coded|vibe-?coded|remade|recreated)\b", re.I)

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
    # AI vendors' own pages (announcements, docs, chat links)
    "anthropic.com", "claude.ai", "claude.com", "openai.com", "chatgpt.com", "gemini.google.com",
    # News and publishing
    "businessinsider.com", "theverge.com", "techcrunch.com", "wired.com", "arstechnica.com", "reuters.com",
    "bloomberg.com", "cnbc.com", "cnn.com", "bbc.com", "bbc.co.uk", "nytimes.com", "theguardian.com",
    "forbes.com", "axios.com", "wsj.com", "ft.com", "404media.co", "tomshardware.com", "xda-developers.com",
    "gamesradar.com", "pcgamer.com", "theregister.com", "zdnet.com", "engadget.com", "venturebeat.com",
    "leaddev.com", "infoq.com", "martinfowler.com",
}
BLOG_PATH = re.compile(r"/(blog|posts?|articles?|news|p|story|stories|writing|essays?|\d{4}/\d{2})(/|$)", re.I)
BLOG_TITLE = re.compile(r"^(how|why|what) i\b|\bi wrote\b|\bwrite-?up\b|\bpost-?mortem\b|\blessons learned\b|\bblog\b|"
                        r"^(why|how to|hot take|opinion|explaining|introducing|announcing)\b", re.I)
# Words that mean the post is about a game. Only the post title is held to this list:
# a site's own description mentions games in passing far too often ("mini games",
# "references to memes, games, films", "a cursor, a clicker and a slide remote").
GAME_WORDS = re.compile(
    r"\b(game|gameplay|playable|puzzle game|wordle|chess|arcade|trivia|sudoku|crossword|"
    r"roguelike|roguelite|platformer|clicker game|idle game|quiz game|geoguessr|tetris|minesweeper|solitaire|rpg|mmo|io game|"
    r"shooter|stickman|pok[eé]mon|tower defense|pinball|speedrun|match-3|flight simulator)\b", re.I)
# In a site's description, only phrases that say the site itself is a game.
GAME_PAGE = re.compile(
    r"\b(?:(?:a|an|free|online|browser|web|multiplayer|puzzle|word|card|board|idle|casual|indie|daily|"
    r"retro|pixel|arcade|strategy|racing|platform|survival|physics|rhythm|trivia|2d|3d)[- ]game|"
    r"play (?:it )?(?:now|free|online|for free|in your browser)|roguelike|roguelite|platformer|sudoku|crossword|"
    r"wordle|tetris|minesweeper|solitaire|tower defense|pinball|match-3|geoguessr)\b", re.I)
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
    try:
        port = parts.port  # raises ValueError for malformed or out-of-range ports
    except ValueError:
        return None
    if port and port not in (80, 443, 8080, 8443):
        return None
    if host.startswith(("blog.", "engineering.")) or host.endswith(".engineering") or BLOG_PATH.search(parts.path) or BLOG_TITLE.search(title or ""):
        return None
    if re.search(r"\.(pdf|png|jpe?g|gif|mp4|zip)$", parts.path, re.I):
        return None
    netloc = (parts.hostname or "") + (f":{port}" if port else "")
    if not netloc:
        return None
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def page_summary(body):
    """The words a page uses to describe itself: its title, description and keywords."""
    text = body.decode("utf-8", "replace")
    parts = re.findall(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)[:1]
    for m in re.finditer(r"<meta\b[^>]*>", text, re.I):
        tag = m.group(0)
        if re.search(r"""(name|property)\s*=\s*["']?(description|keywords|og:title|og:description|twitter:description)["'\s>]""", tag, re.I):
            c = re.search(r"""content\s*=\s*(["'])(.*?)\1""", tag, re.I | re.S)
            if c:
                parts.append(c.group(2))
    return html.unescape(" ".join(p.strip() for p in parts))[:2000]


def category(title, source, summary=""):
    """The post title decides first; the site's own description only fills in when the
    title doesn't say what the project is."""
    if source == "r/WebGames" or GAME_WORDS.search(title):
        return "games"
    if APP_WORDS.search(title):
        return "apps"
    if GAME_PAGE.search(summary):
        return "games"
    if APP_WORDS.search(summary):
        return "apps"
    return "other"


# A language model double-checks the keyword categories when an OpenAI key is set
# (OPENAI_API_KEY; OPENAI_MODEL overrides the model); without one, or if the call fails, the keywords stand.
LLM_BATCH = 50
LLM_PROMPT = (
    "Sort each website into exactly one category. \"games\": something you play in the browser "
    "(a game, puzzle, quiz, toy or playful interactive experience). \"apps\": a tool, product or "
    "service people use to get something done. \"other\": everything else (art, writing, data, "
    "reference, portfolios, experiments). Reply with JSON: {\"categories\": {\"<id>\": \"games|apps|other\"}}.")


def llm_categories(sites, summaries):
    """Categories keyed by site index. The model only sees posts it hasn't sorted before;
    earlier answers come from CATEGORY_CACHE. Without a key, or if the call fails, only the
    cached answers are returned."""
    try:
        with open(CATEGORY_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    key, model = os.environ.get("OPENAI_API_KEY"), os.environ.get("OPENAI_MODEL") or "gpt-5.6-luna"
    new = [i for i, s in enumerate(sites) if s["post_url"] not in cache]
    if key and new:
        try:
            for start in range(0, len(new), LLM_BATCH):
                items = [{"id": str(i), "title": sites[i]["title"], "domain": host_of(sites[i]["url"]),
                          "page": summaries[i][:400]} for i in new[start:start + LLM_BATCH]]
                body = json.dumps({"model": model, "response_format": {"type": "json_object"}, "messages": [
                    {"role": "system", "content": LLM_PROMPT},
                    {"role": "user", "content": json.dumps(items, ensure_ascii=False)}]}).encode()
                reply = json.loads(fetch("https://api.openai.com/v1/chat/completions",
                                         {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                         data=body, timeout=120))
                got = json.loads(reply["choices"][0]["message"]["content"])["categories"]
                cache.update({sites[int(i)]["post_url"]: c for i, c in got.items()
                              if c in ("games", "apps", "other") and str(i).isdigit() and int(i) in new})
            print(f"OpenAI ({model}) sorted {len(new)} new sites")
        except Exception as e:
            print(f"warn: OpenAI categories: {e}; new sites keep keyword categories", file=sys.stderr)
    # Keep answers only for posts still ranked.
    cache = {s["post_url"]: cache[s["post_url"]] for s in sites if s["post_url"] in cache}
    os.makedirs(os.path.dirname(CATEGORY_CACHE), exist_ok=True)
    tmp = CATEGORY_CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1, ensure_ascii=False)
    os.replace(tmp, CATEGORY_CACHE)
    return {i: cache[s["post_url"]] for i, s in enumerate(sites) if s["post_url"] in cache}


def window_start():
    # A rolling 30-day window, so the board isn't nearly empty early in a calendar month.
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)


def show_hn(since):
    q = urllib.parse.urlencode({
        "tags": "show_hn",
        "numericFilters": f"created_at_i>={int(since.timestamp())},points>={WEEK_MIN_VOTES}",
        "hitsPerPage": 1000,
    })
    hits = json.loads(fetch(f"https://hn.algolia.com/api/v1/search?{q}"))["hits"]
    out = []
    for h in hits:
        title = re.sub(r"^show hn:\s*", "", h.get("title") or "", flags=re.I)
        url = site_url(h.get("url") or "", title)
        if not url or not isinstance(h.get("points"), int):
            continue
        out.append({
            "url": url, "title": title, "votes": h["points"],
            "source": "Hacker News", "source_url": "https://news.ycombinator.com/show",
            "post_url": f"https://news.ycombinator.com/item?id={h['objectID']}",
            "created": h.get("created_at_i"),
        })
    return out


def refresh_due(now):
    """Refresh when the saved next_refresh_at has passed (or the file is unusable)."""
    try:
        with open(OUT, encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("sites") or not data.get("next_refresh_at"):
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
    out, seen = [], set()
    # The week's top list reaches the lower-voted posts the month's top 100 leaves out.
    for sub, t in [(sub, t) for sub in SUBREDDITS for t in ("month", "week")]:
        try:
            data = json.loads(fetch(f"https://oauth.reddit.com/r/{sub}/top.json?t={t}&limit=100&raw_json=1",
                                    {"Authorization": f"bearer {token}"}))
        except Exception as e:  # one subreddit failing shouldn't sink the run
            print(f"warn: r/{sub} ({t}): {e}", file=sys.stderr)
            continue
        for c in data["data"]["children"]:
            p = c["data"]
            if p.get("permalink") in seen:
                continue
            seen.add(p.get("permalink"))
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


def listing_posts(sub, t="MONTH"):
    """Read a bounded number of pages directly from Reddit, with live scores."""
    posts, after = {}, None
    for _ in range(LISTING_PAGES):
        # Reddit hands out the cursor without its base64 padding but only accepts it padded;
        # unpadded, page 2 comes back with no posts.
        q = {"t": t, "name": sub, **({"after": after + "=" * (-len(after) % 4)} if after else {})}
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


def archive_scores(ids):
    scores = {}
    for i in range(0, len(ids), 100):
        q = urllib.parse.urlencode({"ids": ",".join(ids[i:i + 100]), "fields": "id,score"})
        try:
            data = json.loads(fetch(f"https://arctic-shift.photon-reddit.com/api/posts/ids?{q}", timeout=40))
            scores.update({p["id"]: p["score"] for p in data.get("data") or [] if isinstance(p.get("score"), int)})
        except Exception as e:
            print(f"warn: Arctic Shift: {e}", file=sys.stderr)
    return scores


def cached_scores():
    """Vote counts from the last successful scrape, keyed by post id."""
    try:
        with open(REDDIT_CACHE, encoding="utf-8") as f:
            posts = json.load(f)["posts"]
        return {m.group(1): p["votes"] for p in posts if (m := re.search(r"/comments/(\w+)", p.get("post_url", "")))}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def feed_fallback(sub, since):
    """Posts for a subreddit whose listing is blocked: links from its RSS feed,
    votes from the archive. Archive counts only ever lag, so a post never drops
    below a count seen in an earlier scrape. Posts with no known count are skipped."""
    posts = [p for p in reddit_feed(sub, since) if not NSFW.search(p["title"])]
    archived, cache = archive_scores([p["id"] for p in posts]), cached_scores()
    out = []
    for p in posts:
        known = [v for v in (archived.get(p["id"]), cache.get(p["id"])) if isinstance(v, int)]
        url = pick_site(p["title"], p["direct"], p["body"])
        if url and known:
            out.append(reddit_entry(sub, url, p["title"], max(known), p["permalink"], p["created"]))
    return out


# ---- Last resort: the Arctic Shift archive ----
# Used only for subreddits where the API, the listing and the RSS feed all fail
# (Reddit ends RSS on 2026-11-13). The archive rate-limits, so each run spends a
# small request budget, saves its progress, and picks up where it left off; while
# the fallback is active, the workflow also runs a sync every day between refreshes.
ARCHIVE_API = "https://arctic-shift.photon-reddit.com/api/posts"
ARCHIVE_BUDGET = 30   # requests per run
ARCHIVE_PAUSE = 3     # seconds between requests
ARCHIVE_SETTLE = 36 * 3600  # the archive updates a post's score about 36 hours after it's posted
# The search endpoint rejects some field names (permalink, is_self, stickied); permalink is derived.
ARCHIVE_FIELDS = "id,title,url,selftext,score,created_utc,over_18"


class ArchivePaused(Exception):
    """The run's request budget is spent or the archive asked us to slow down."""


class ArchiveClient:
    def __init__(self, budget):
        self.budget = budget

    def get(self, path, params):
        if self.budget <= 0:
            raise ArchivePaused("request budget spent")
        self.budget -= 1
        time.sleep(ARCHIVE_PAUSE)
        try:
            data = json.loads(fetch(f"{ARCHIVE_API}/{path}?{urllib.parse.urlencode(params)}", timeout=40))
        except urllib.error.HTTPError as e:
            if e.code in (422, 429, 503):
                raise ArchivePaused(f"rate limited (HTTP {e.code})")
            raise
        if data.get("error"):
            raise ArchivePaused(data["error"]) if "slow down" in str(data["error"]).lower() else RuntimeError(data["error"])
        return data.get("data") or []


def load_archive():
    try:
        with open(ARCHIVE_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
        if isinstance(cache.get("posts"), dict) and isinstance(cache.get("cursors"), dict):
            return cache
    except (OSError, ValueError, AttributeError):
        pass
    return {"active": False, "subreddits": [], "cursors": {}, "posts": {}}


def save_archive(cache):
    os.makedirs(os.path.dirname(ARCHIVE_CACHE), exist_ok=True)
    cache["synced_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    tmp = ARCHIVE_CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, ARCHIVE_CACHE)


def archive_sync(cache, since, budget=ARCHIVE_BUDGET, now=None):
    """Spend up to `budget` archive requests: first collect new posts for each fallback
    subreddit (oldest first, resuming from a saved cursor), then re-read counts for
    posts that have settled since they were collected. Progress is kept on pause."""
    now = now or time.time()
    client = ArchiveClient(budget)
    posts, cursors = cache["posts"], cache["cursors"]
    for pid in [k for k, p in posts.items() if p["created"] < since.timestamp()]:
        del posts[pid]
    try:
        for sub in cache["subreddits"]:
            while True:
                after = max(int(cursors.get(sub, 0)), int(since.timestamp()))
                batch = client.get("search", {"subreddit": sub, "after": after, "sort": "asc",
                                              "limit": 100, "fields": ARCHIVE_FIELDS})
                for p in batch:
                    if p.get("over_18") or p.get("selftext") in ("[removed]", "[deleted]"):
                        continue
                    posts[p["id"]] = {
                        # A text post's url is its own Reddit page, which pick_site() rejects.
                        "sub": sub, "title": p.get("title") or "", "score": p.get("score"),
                        "direct": p.get("url"), "body": URL_RE.findall(p.get("selftext") or ""),
                        "permalink": f"/r/{sub}/comments/{p['id']}/", "created": int(p["created_utc"]),
                        "settled": now - p["created_utc"] > ARCHIVE_SETTLE,
                    }
                if batch:
                    cursors[sub] = int(batch[-1]["created_utc"]) + 1
                if len(batch) < 100:
                    break
        # Counts collected before a post settled are re-read once it has.
        stale = sorted((k for k, p in posts.items() if not p["settled"] and now - p["created"] > ARCHIVE_SETTLE),
                       key=lambda k: posts[k]["created"])
        for i in range(0, len(stale), 500):
            ids = stale[i:i + 500]
            for p in client.get("ids", {"ids": ",".join(ids), "fields": "id,score"}):
                if p.get("id") in posts and isinstance(p.get("score"), int):
                    posts[p["id"]].update(score=p["score"], settled=True)
    except ArchivePaused as e:
        print(f"Arctic Shift: pausing until the next run ({e}); progress saved", flush=True)
    return cache


def archive_entries(cache, sub, since):
    cache_votes = cached_scores()
    out = []
    for pid, p in cache["posts"].items():
        if p["sub"] != sub or p["created"] < since.timestamp() or NSFW.search(p["title"]):
            continue
        votes = max([v for v in (p["score"], cache_votes.get(pid)) if isinstance(v, int)], default=None)
        url = pick_site(p["title"], p["direct"], p["body"])
        if url and votes is not None:
            out.append(reddit_entry(sub, url, p["title"], votes, p["permalink"], p["created"]))
    return out


def archive_daily_sync():
    """Between refreshes, keep filling the archive cache while the fallback is in use."""
    cache = load_archive()
    if not cache.get("active") or not cache["subreddits"]:
        print("Arctic Shift fallback not in use; nothing to sync")
        return
    save_archive(archive_sync(cache, window_start()))
    print(f"Arctic Shift: {len(cache['posts'])} posts cached for " + ", ".join(f"r/{s}" for s in cache["subreddits"]))


def reddit_pages(since):
    out, unreachable = [], []
    for sub in SUBREDDITS:
        try:
            posts = listing_posts(sub)
        except Exception as e:
            print(f"warn: r/{sub} listing: {e}; using its RSS feed with archived vote counts", file=sys.stderr)
            try:
                got = feed_fallback(sub, since)
            except Exception as e2:
                print(f"warn: r/{sub} RSS: {e2}", file=sys.stderr)
                got = []
            if got:
                out += got
                print(f"r/{sub}: {len(got)} sites (RSS, archived scores)", flush=True)
            else:
                unreachable.append(sub)
            continue
        # The week's top list reaches the lower-voted posts the month's leaves out.
        try:
            ids = {p["id"] for p in posts}
            posts += [p for p in listing_posts(sub, "WEEK") if p["id"] not in ids]
        except Exception as e:
            print(f"warn: r/{sub} weekly listing: {e}; keeping the month's posts", file=sys.stderr)
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

    # Nothing else worked for these subreddits: fall back to the archive.
    cache = load_archive()
    cache["active"], cache["subreddits"] = bool(unreachable), unreachable
    if unreachable:
        print("Arctic Shift fallback for " + ", ".join(f"r/{s}" for s in unreachable), flush=True)
        try:
            archive_sync(cache, since)
        except Exception as e:  # keep whatever is already cached
            print(f"warn: Arctic Shift: {e}", file=sys.stderr)
        for sub in unreachable:
            got = archive_entries(cache, sub, since)
            out += got
            print(f"r/{sub}: {len(got)} sites (Arctic Shift archive)", flush=True)
    if unreachable or os.path.exists(ARCHIVE_CACHE):
        save_archive(cache)
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
        return [p for p in posts if p["source"].removeprefix("r/") not in MAKER_ONLY or MAKER_TITLE.search(p["title"])]
    return []


def public_host(host):
    """True when every address the host resolves to is on the public internet;
    None when the name doesn't resolve at all."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return None
    return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Redirects are followed by hand in embeddable(), so each hop is checked
    # before connecting and redirect bodies are never read.
    def redirect_request(self, *args, **kwargs):
        return None


_PROBE = urllib.request.build_opener(_NoRedirect)
PROBE_HOPS = 5
PROBE_DEADLINE = 30  # seconds per site, across all redirects


def _probe_open(req):
    # One retry on a dropped connection or timeout, so a momentary network blip
    # doesn't keep a frameable site out of Live until the next refresh.
    try:
        return _PROBE.open(req, timeout=10)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        time.sleep(1)
        return _PROBE.open(req, timeout=10)


# Why a ranked site is left out of Live view, stored as "live_issue" next to "embeddable".
DOWN = "down"      # doesn't resolve, doesn't answer, or answers with a missing page or server error
NO_FRAME = "iframe"  # up, but forbids framing (or can't be framed safely, e.g. plain HTTP)


def embeddable(url):
    """True when the site loads over HTTPS and doesn't forbid framing."""
    return probe(url)[0] == "ok"


def _down_status(code):
    # 401/403/429 mostly mean the site turned away an automated visitor, not that it's
    # offline; the browser check in snapshots.cjs decides those.
    return code in (404, 410) or code >= 500


def probe(url):
    """(status, page summary): "ok" when the site loads over HTTPS without forbidding
    framing, otherwise DOWN or NO_FRAME; and how its landing page describes itself."""
    url = url.replace("http://", "https://", 1)
    deadline = time.monotonic() + PROBE_DEADLINE
    try:
        for _ in range(PROBE_HOPS + 1):
            host = host_of(url)
            if not url.startswith("https://") or not host or blocked(host) or is_ip(host):
                return NO_FRAME, ""
            if time.monotonic() > deadline:
                return DOWN, ""
            public = public_host(host)
            if public is None:
                return DOWN, ""
            if not public:
                return NO_FRAME, ""
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (deploylist iframe check)"})
            try:
                r = _probe_open(req)
            except urllib.error.HTTPError as e:
                location = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
                e.close()
                if not location:
                    return (DOWN if _down_status(e.code) else "ok"), ""
                url = urllib.parse.urljoin(url, location)
                continue
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                return DOWN, ""
            with r as resp:
                if resp.status >= 400:
                    return (DOWN if _down_status(resp.status) else "ok"), ""
                summary = ""
                if "html" in (resp.headers.get("Content-Type") or "").lower():
                    try:
                        summary = page_summary(resp.read(200_000))
                    except Exception:
                        pass
                for xfo in resp.headers.get_all("X-Frame-Options") or []:
                    xfo_lower = xfo.lower()
                    # ALLOW-FROM is ignored by current browsers, so it doesn't block framing.
                    if "deny" in xfo_lower or "sameorigin" in xfo_lower:
                        return NO_FRAME, summary
                for csp in resp.headers.get_all("Content-Security-Policy") or []:
                    m = re.search(r"frame-ancestors([^;]*)", csp, re.I)
                    if m and "*" not in m.group(1).split():
                        return NO_FRAME, summary
                return "ok", summary
        return DOWN, ""  # redirect loop
    except Exception:
        return DOWN, ""


def check_live(sites, previous=None):
    """Probe every site in parallel and record whether it can go in Live view. A probe still
    running after the overall limit keeps the site's previous status (or counts as down),
    so one slow refresh doesn't flip sites in and out of Live. Returns page summaries."""
    previous = previous or {}
    try:
        with open(LIVE_EXCLUDE, encoding="utf-8") as f:
            excluded = json.load(f)
    except (OSError, ValueError):
        excluded = {}
    ex = ThreadPoolExecutor(32)
    futures = [ex.submit(probe, s["url"]) for s in sites]
    wait(futures, timeout=PROBE_DEADLINE * 4)
    summaries = []
    for s, f in zip(sites, futures):
        if f.done() and not f.cancelled() and f.exception() is None:
            status, summary = f.result()
        else:
            before = previous.get(s["url"], {})
            status = "ok" if before.get("embeddable") else before.get("live_issue", DOWN)
            summary = ""
        if status == "ok" and host_of(s["url"]) in excluded:
            status = NO_FRAME
        s["embeddable"] = status == "ok"
        if status == "ok":
            s.pop("live_issue", None)
        else:
            s["live_issue"] = status
        summaries.append(summary)
    ex.shutdown(wait=False, cancel_futures=True)
    return summaries


def recheck():
    """Between refreshes: probe the sites already ranked again, so a site that went down
    leaves Live view and one that came back returns, without touching the rankings."""
    with open(OUT, encoding="utf-8") as f:
        data = json.load(f)
    sites = data.get("sites") or []
    before = {s["url"]: dict(s) for s in sites}
    summaries = check_live(sites, before)
    llm = llm_categories(sites, summaries)
    for i, (s, summary) in enumerate(zip(sites, summaries)):
        # Recategorize with the site's current description; a site that didn't answer
        # keeps its category.
        if i in llm:
            s["category"] = llm[i]
        elif summary:
            s["category"] = category(s["title"], s["source"], summary)
        if s["embeddable"]:
            s["url"] = s["url"].replace("http://", "https://", 1)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, OUT)
    down = sum(s.get("live_issue") == DOWN for s in sites)
    print(f"rechecked {len(sites)} sites: {sum(s['embeddable'] for s in sites)} in Live, {down} down")


def main(if_due=False):
    started = dt.datetime.now(dt.timezone.utc)
    if if_due and not refresh_due(started):
        print("Reddit refresh is not due; keeping the current rankings and update timestamp")
        recheck()
        return
    since = window_start()
    posts = reddit(since)
    print(f"Reddit: {len(posts)} candidate posts")
    if not posts:
        sys.exit("no fresh, scored Reddit posts scraped; keeping existing data")
    try:
        hn = show_hn(since)
    except Exception as e:
        sys.exit(f"Show HN failed ({e}); keeping existing data")
    print(f"Show HN: {len(hn)} candidate posts")
    posts += hn
    posts = [p for p in posts if p["votes"] >= WEEK_MIN_VOTES]

    # One entry per domain, keeping its best-voted post. The month and the last week are
    # ranked separately, the week with a lower vote minimum; sites that only make the
    # week's list are marked "month": false.
    def top(posts, size):
        best = {}
        for p in posts:
            d = host_of(p["url"])
            if d not in best or p["votes"] > best[d]["votes"]:
                best[d] = {**p, "domain": d}
        return sorted(best.values(), key=lambda s: -s["votes"])[:size]
    sites = top([p for p in posts if p["votes"] >= MIN_VOTES], MONTH_POOL_SIZE)
    week_start = (started - dt.timedelta(days=7)).timestamp()
    in_month = {s["post_url"] for s in sites}
    sites += [{**s, "month": False} for s in top([p for p in posts if (p.get("created") or 0) >= week_start], WEEK_POOL_SIZE)
              if s["post_url"] not in in_month]
    sites.sort(key=lambda s: -s["votes"])

    try:
        with open(OUT, encoding="utf-8") as f:
            previous = {s["url"]: s for s in json.load(f).get("sites") or []}
    except (OSError, ValueError):
        previous = {}
    summaries = check_live(sites, previous)
    llm = llm_categories(sites, summaries)
    for i, (s, summary) in enumerate(zip(sites, summaries)):
        # The model's call when there is one, else the post title plus the site's own
        # title and description.
        s["category"] = llm.get(i) or category(s["title"], s["source"], summary)
        s["url"] = s["url"].replace("http://", "https://", 1) if s["embeddable"] else s["url"]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "next_refresh_at": next_refresh_time(started).isoformat(timespec="seconds"),
            "since": since.isoformat(timespec="seconds"),
            "sources": [{"name": "Show HN", "url": "https://news.ycombinator.com/show"}]
                       + [{"name": f"r/{s}", "url": f"https://www.reddit.com/r/{s}/"} for s in SUBREDDITS],
            "sites": sites,
        }, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, OUT)
    print(f"wrote {len(sites)} sites ({sum(s['embeddable'] for s in sites)} embeddable) to {os.path.normpath(OUT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--if-due", action="store_true", help="skip collection until the next three-day refresh is due")
    parser.add_argument("--archive-sync", action="store_true",
                        help="only top up the Arctic Shift fallback cache (no-op unless the fallback is in use)")
    args = parser.parse_args()
    if args.archive_sync:
        archive_daily_sync()
    else:
        main(if_due=args.if_due)
