#!/usr/bin/env python3
"""Build site/data/sites.json from this month's top Show HN and Reddit posts.

Only posts centred on one standalone website are kept (no GitHub repos,
store pages, blog posts or social links). Each site is then probed to see
whether it can be shown inside an <iframe>; sites that can't stay on the
leaderboard but are left out of live view.

Standard library only. Reddit's API is used when REDDIT_CLIENT_ID and
REDDIT_CLIENT_SECRET are set; otherwise its public web pages are read.
"""

import base64
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

OUT = os.path.join(os.path.dirname(__file__), "..", "site", "data", "sites.json")
# Reddit often blocks GitHub's runners, so the last successful Reddit scrape (from
# any machine) is saved here and reused when a run can't reach Reddit.
REDDIT_CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "reddit-cache.json")
UA = "deploylist/1.0 (+https://deploylist.com)"
POOL_SIZE = 100  # candidates kept; the pages show the top 25 per category

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
        return r.read()


def host_of(url):
    h = (urllib.parse.urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def blocked(host):
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


def site_url(url, title):
    """Return a cleaned URL if this link is a standalone website, else None."""
    url = html.unescape(url).rstrip(".,;:!?")
    parts = urllib.parse.urlsplit(url)
    host = host_of(url)
    if parts.scheme not in ("http", "https") or not host or "." not in host or blocked(host):
        return None
    if BLOG_PATH.search(parts.path) or BLOG_TITLE.search(title or ""):
        return None
    if re.search(r"\.(pdf|png|jpe?g|gif|mp4|zip)$", parts.path, re.I):
        return None
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def category(text, source):
    if source == "r/WebGames" or GAME_WORDS.search(text):
        return "games"
    if APP_WORDS.search(text):
        return "apps"
    return "other"


def window_start():
    # A rolling 30-day window, so the board isn't nearly empty early in a calendar month.
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)


def show_hn(since):
    q = urllib.parse.urlencode({
        "tags": "show_hn",
        "numericFilters": f"created_at_i>={int(since.timestamp())},points>=10",
        "hitsPerPage": 1000,
    })
    hits = json.loads(fetch(f"https://hn.algolia.com/api/v1/search?{q}"))["hits"]
    out = []
    for h in hits:
        title = re.sub(r"^show hn:\s*", "", h.get("title") or "", flags=re.I)
        url = site_url(h.get("url") or "", title)
        if not url:
            continue
        out.append({
            "url": url, "title": title, "votes": h.get("points") or 0,
            "source": "Hacker News", "source_url": "https://news.ycombinator.com/show",
            "post_url": f"https://news.ycombinator.com/item?id={h['objectID']}",
            "created": h.get("created_at_i"),
        })
    return out


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
            if p.get("created_utc", 0) < since.timestamp() or p.get("over_18") or p.get("stickied"):
                continue
            title = p.get("title") or ""
            direct = None if p.get("is_self") else p.get("url_overridden_by_dest") or p.get("url")
            url = pick_site(title, direct, URL_RE.findall(p.get("selftext") or ""))
            if url:
                out.append(reddit_entry(sub, url, title, p.get("score") or 0, p["permalink"], int(p.get("created_utc", 0))))
    return out


def reddit_entry(sub, url, title, votes, permalink, created):
    return {
        "url": url, "title": title, "votes": votes,
        "source": f"r/{sub}", "source_url": f"https://www.reddit.com/r/{sub}/",
        "post_url": "https://www.reddit.com" + permalink, "created": created,
    }


# Without API keys, read Reddit's public RSS feeds, which work even from GitHub's
# servers. A subreddit's "top this month" feed has each post's link and text but no
# score, so scores come from the subreddit's web listing when it's reachable, else
# from the Arctic Shift Reddit archive, whose counts lag behind the live ones.
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
LISTING_PAGES = 4  # about 25 posts per page


def reddit_get(url, attempts=4):
    for i in range(attempts):
        time.sleep(1.5)  # stay well under Reddit's rate limit
        try:
            return fetch(url, {"User-Agent": BROWSER_UA, "Accept-Language": "en-US"}).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == attempts - 1:
                raise
            time.sleep(20 * (i + 1))


def reddit_feed(sub, since):
    feed = reddit_get(f"https://www.reddit.com/r/{sub}/top/.rss?t=month&limit=100")
    posts = []
    for e in re.findall(r"<entry>(.*?)</entry>", feed, re.S):
        get = lambda tag: html.unescape((re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", e, re.S) or [None, ""])[1])
        created = dt.datetime.fromisoformat(get("published")).timestamp()
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
    return posts


def listing_scores(sub):
    """Live scores from the subreddit's web listing, or {} where Reddit blocks it."""
    scores, after = {}, None
    try:
        for _ in range(LISTING_PAGES):
            q = {"t": "MONTH", "name": sub, **({"after": after} if after else {})}
            page = reddit_get("https://www.reddit.com/svc/shreddit/community-more-posts/top/?" + urllib.parse.urlencode(q))
            for tag in re.findall(r'<shreddit-post\b([^>]*\bid="t3_[^"]*"[^>]*)>', page):
                pid, score = re.search(r'\bid="t3_(\w+)"', tag).group(1), re.search(r'\bscore="(-?\d+)"', tag)
                if score:
                    scores[pid] = int(score.group(1))
            m = re.search(r'more-posts-cursor="([^"]+)"', page)
            if not m:
                break
            after = m.group(1)
    except Exception as e:
        print(f"warn: r/{sub} listing: {e}", file=sys.stderr)
    return scores


def archive_scores(ids):
    scores = {}
    for i in range(0, len(ids), 100):
        q = urllib.parse.urlencode({"ids": ",".join(ids[i:i + 100]), "fields": "id,score"})
        try:
            data = json.loads(fetch(f"https://arctic-shift.photon-reddit.com/api/posts/ids?{q}", timeout=40))
            scores.update({p["id"]: p["score"] for p in data.get("data") or []})
        except Exception as e:
            print(f"warn: Arctic Shift: {e}", file=sys.stderr)
    return scores


def cached_scores():
    try:
        with open(REDDIT_CACHE) as f:
            return {re.search(r"/comments/(\w+)", p["post_url"]).group(1): p["votes"] for p in json.load(f)["posts"]}
    except (FileNotFoundError, ValueError, KeyError):
        return {}


def reddit_pages(since):
    out, live = [], True
    cache = cached_scores()
    for sub in SUBREDDITS:
        try:
            posts = reddit_feed(sub, since)
        except Exception as e:
            print(f"warn: r/{sub}: {e}", file=sys.stderr)
            continue
        for p in posts:
            p["url"] = None if NSFW.search(p["title"]) else pick_site(p["title"], p["direct"], p["body"])
        posts = [p for p in posts if p["url"]]
        scores = listing_scores(sub) if live else {}
        live = live and bool(scores)  # once the listing is blocked, don't keep retrying it
        missing = [p["id"] for p in posts if p["id"] not in scores]
        archived = archive_scores(missing) if missing else {}
        for p in posts:
            # Archive counts only ever lag, so never drop below a count seen earlier.
            votes = scores.get(p["id"]) or max(archived.get(p["id"], 0), cache.get(p["id"], 0))
            out.append(reddit_entry(sub, p["url"], p["title"], votes, p["permalink"], p["created"]))
        print(f"r/{sub}: {len(posts)} sites ({'live' if scores else 'archived'} scores)", flush=True)
    return out


def reddit(since):
    token = reddit_token()
    try:
        posts = reddit_api(since, token) if token else reddit_pages(since)
    except Exception as e:
        print(f"warn: Reddit failed: {e}", file=sys.stderr)
        posts = []
    if posts:
        os.makedirs(os.path.dirname(REDDIT_CACHE), exist_ok=True)
        with open(REDDIT_CACHE, "w") as f:
            json.dump({"scraped_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "posts": posts}, f, indent=1)
        return posts
    try:
        with open(REDDIT_CACHE) as f:
            cache = json.load(f)
    except FileNotFoundError:
        return []
    print(f"Reddit unreachable; using cached posts from {cache['scraped_at']}")
    return [p for p in cache["posts"] if p["created"] >= since.timestamp()]


def embeddable(url):
    """True when the site loads over HTTPS and doesn't forbid framing."""
    try:
        req = urllib.request.Request(url.replace("http://", "https://", 1),
                                     headers={"User-Agent": "Mozilla/5.0 (deploylist iframe check)"})
        with urllib.request.urlopen(req, timeout=12) as r:
            if not r.geturl().startswith("https://") or r.status >= 400:
                return False
            xfo = (r.headers.get("X-Frame-Options") or "").lower()
            if "deny" in xfo or "sameorigin" in xfo:
                return False
            for csp in r.headers.get_all("Content-Security-Policy") or []:
                m = re.search(r"frame-ancestors([^;]*)", csp, re.I)
                if m and "*" not in m.group(1).split():
                    return False
            return True
    except Exception:
        return False


def main():
    since = window_start()
    posts = []
    for name, fn in (("Show HN", lambda: show_hn(since)), ("Reddit", lambda: reddit(since))):
        try:
            got = fn()
            print(f"{name}: {len(got)} candidate posts")
            posts += got
        except Exception as e:
            print(f"warn: {name} failed: {e}", file=sys.stderr)
    if not posts:
        sys.exit("no posts scraped; keeping existing data")

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
    with open(OUT, "w") as f:
        json.dump({
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "since": since.isoformat(timespec="seconds"),
            "sources": [{"name": "Show HN", "url": "https://news.ycombinator.com/show"}]
                       + [{"name": f"r/{s}", "url": f"https://www.reddit.com/r/{s}/"} for s in SUBREDDITS],
            "sites": sites,
        }, f, indent=1)
    print(f"wrote {len(sites)} sites ({sum(flags)} embeddable) to {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
