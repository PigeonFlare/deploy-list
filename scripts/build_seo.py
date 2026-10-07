#!/usr/bin/env python3
"""Build crawlable pages from the saved rankings; never collect new posts."""
import json
import re
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://deploylist.com"
CATEGORIES = {
    "games": ("games", "Browser games", "Discover browser games made by independent developers. Browse recent community favorites, follow the original discussions, and find something new to play.",
              "From small experiments to bigger playable projects, this list is a starting point for finding games on the web. Entries are ordered by their recorded community post votes, rather than by a review score. Follow a game's website to learn how to play and check any access requirements."),
    "apps": ("apps", "Indie web apps", "Find indie web apps and useful online tools. Explore recent projects shared by independent makers, ranked by recorded community votes.",
             "Discover tools for everyday tasks, creative work, and new ways to use the web. Each entry links to the app and its original community discussion, so you can investigate features and limitations before using it. Recorded votes reflect the source post's reception, not a product endorsement."),
    "other": ("websites", "Interesting indie websites", "Explore interesting websites, creative web projects, and unusual internet experiments made by independent creators.",
              "Browse projects that go beyond a conventional app or game: personal sites, creative experiments, and other corners of the independent web. Use the original discussion to learn the story behind a project, or head straight to the website to explore it for yourself."),
}


def http_url(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid URL in saved rankings")
    url = urlsplit(value)
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
        raise ValueError("Only public HTTP(S) links are allowed in generated pages")
    return escape(value, quote=True)


def ld_json(value):
    # A post title must not be able to terminate a JSON-LD script element.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("&", "\\u0026")


def metadata(path, title, description, page_type="WebPage", sites=None, index=True):
    url = ORIGIN + path
    website = {"@type": "WebSite", "@id": ORIGIN + "/#website", "url": ORIGIN + "/", "name": "Deploylist",
               "description": "Discover indie websites, web apps, and browser games."}
    page = {"@type": page_type, "@id": url + "#webpage", "url": url, "name": title,
            "description": description, "isPartOf": {"@id": website["@id"]}, "inLanguage": "en"}
    graph = [website, page]
    if path != "/":
        labels = {"/leaderboards/": "Rankings", "/games/": "Browser games", "/apps/": "Indie web apps",
                  "/websites/": "Interesting websites", "/discover/": "Discover", "/about/": "About", "/live/": "Live view"}
        breadcrumb = {"@type": "BreadcrumbList", "@id": url + "#breadcrumb", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": ORIGIN + "/"},
            {"@type": "ListItem", "position": 2, "name": labels[path], "item": url}]}
        page["breadcrumb"] = {"@id": breadcrumb["@id"]}
        graph.append(breadcrumb)
    if sites is not None:
        listing = {"@type": "ItemList", "@id": url + "#list", "numberOfItems": len(sites),
                   "itemListOrder": "https://schema.org/ItemListOrderDescending",
                   "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": s["url"], "name": s["title"]}
                                       for i, s in enumerate(sites)]}
        page["mainEntity"] = {"@id": listing["@id"]}
        graph.append(listing)
    e = lambda v: escape(v, quote=True)
    return f'''  <title>{e(title)}</title>
  <meta name="description" content="{e(description)}">
  <meta name="robots" content="{'index' if index else 'noindex'}, follow, max-image-preview:large">
  <link rel="canonical" href="{url}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Deploylist">
  <meta property="og:locale" content="en_US">
  <meta property="og:title" content="{e(title)}">
  <meta property="og:description" content="{e(description)}">
  <meta property="og:url" content="{url}">
  <meta property="og:image" content="{ORIGIN}/assets/social-preview.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="Deploylist — discover indie websites, web apps, and browser games">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{e(title)}">
  <meta name="twitter:description" content="{e(description)}">
  <meta name="twitter:image" content="{ORIGIN}/assets/social-preview.png">
  <meta name="twitter:image:alt" content="Deploylist — discover indie websites, web apps, and browser games">
  <script type="application/ld+json">{ld_json({"@context": "https://schema.org", "@graph": graph})}</script>'''


def replace_block(text, name, value):
    start, end = f"<!-- SEO:{name} -->", f"<!-- /SEO:{name} -->"
    pattern = re.escape(start) + r".*?" + re.escape(end)
    if len(re.findall(pattern, text, flags=re.S)) != 1:
        raise ValueError(f"Expected one {name} marker block")
    return re.sub(pattern, lambda _: start + "\n" + value + "\n" + end, text, flags=re.S)


def rows(sites):
    output = []
    for i, s in enumerate(sites):
        medal = " medal r" + str(i + 1) if i < 3 else ""
        tag = "" if s.get("embeddable") else '<span class="tag">' + ("Website down" if s.get("live_issue") == "down" else "Not in Live") + "</span>"
        source = escape(s["source"])
        output.append(f'''<tr><td class="rank"><span class="badge{medal}">{i + 1}</span></td>
<td class="domain-cell"><div class="line"><a class="domain" href="{http_url(s['url'])}" target="_blank" rel="ugc noopener noreferrer"><span class="dn">{escape(s['domain'])}</span></a>{tag}</div>
<div class="title">{escape(s['title'])}</div><a class="src-line" href="{http_url(s['post_url'])}" target="_blank" rel="ugc noopener noreferrer">{source}</a></td>
<td class="num votes">{s['votes']:,}</td><td class="src"><a href="{http_url(s['post_url'])}" target="_blank" rel="ugc noopener noreferrer">{source}</a></td></tr>''')
    return "\n".join(output) or '<tr><td colspan="4" class="updated">No projects in this category in the latest snapshot.</td></tr>'


def navigation(current=""):
    links = [("/", "Home"), ("/games/", "Games"), ("/apps/", "Apps"), ("/websites/", "Websites"), ("/leaderboards/", "Rankings"), ("/discover/", "Discover"), ("/about/", "About")]
    return '<nav class="browse-nav" aria-label="Explore Deploylist">' + "".join(
        f'<a href="{url}"' + (' aria-current="page"' if url == current else '') + f'>{label}</a>' for url, label in links) + '</nav>'


def category_cards():
    return '<div class="category-cards">' + "".join(
        f'<a class="category-card" href="/{slug}/"><h3>{escape(name)}</h3><p>{escape(desc)}</p><span>Explore {name.lower()} →</span></a>'
        for slug, name, desc, _ in CATEGORIES.values()) + '</div>'


def footer():
    return '<footer class="site-foot"><span>© 2026 deploylist.com</span><a href="/about/">How it works</a><a href="https://buymeacoffee.com/0wtynrfutb" target="_blank" rel="noopener noreferrer">Donate</a></footer>'


def document(path, title, description, content, sites=None, page_type="WebPage"):
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'">
  <meta name="referrer" content="strict-origin-when-cross-origin">
  <meta name="theme-color" content="#eef1f7">
{metadata(path, title, description, page_type, sites)}
  <link rel="icon" href="../assets/favicon-play.svg" type="image/svg+xml">
  <link rel="preload" href="../assets/fonts/inter-latin.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="../assets/style.css">
</head>
<body class="directory-page">
  <header class="directory-header"><a class="wordmark" href="/">deploy<span>list</span></a>{navigation(path)}</header>
  <main class="directory-main">{content}</main>
  {footer()}
</body>
</html>
'''


def build(site=ROOT / "site"):
    data = json.loads((site / "data/sites.json").read_text())
    if not isinstance(data.get("sites"), list):
        raise ValueError("Saved rankings must contain a sites array")
    date = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
    for s in data["sites"]:
        http_url(s["url"])
        http_url(s["post_url"])
        if not isinstance(s["votes"], int) or isinstance(s["votes"], bool) or s["votes"] < 0:
            raise ValueError("Saved votes must be a nonnegative integer")
    monthly = [s for s in data["sites"] if s.get("month") is not False]
    groups = {key: [s for s in monthly if s["category"] == key] for key in CATEGORIES}
    stamp = f'<time datetime="{escape(data["generated_at"], quote=True)}">{date.strftime("%B %d, %Y")} (UTC)</time>'
    pages = {
        "index.html": ("/", "Deploylist — Discover Indie Websites, Web Apps & Browser Games", "Discover indie websites, useful web apps, and browser games. Browse community-ranked projects or explore the independent web with Live view.", "WebPage", True),
        "leaderboards/index.html": ("/leaderboards/", "Indie Website Rankings — Community Favorites | Deploylist", "Explore recent indie websites, web apps, and browser games ranked by recorded community votes. Filter by category and the last month or week.", "CollectionPage", True),
        "live/index.html": ("/live/", "Explore Indie Websites in Live View | Deploylist", "Explore indie websites, web apps, and browser games one at a time with Deploylist's Live view. Skip forward and discover something new.", "WebPage", False),
    }
    writes = {}
    for filename, (path, title, desc, kind, index) in pages.items():
        text = replace_block((site / filename).read_text(), "head", metadata(path, title, desc, kind, index=index))
        if filename == "leaderboards/index.html":
            # Match the current Games default. The interactive filters still work normally.
            text = replace_block(text, "rows", rows(groups["games"]))
            text = replace_block(text, "updated", "Updated " + stamp)
        if filename == "index.html":
            text = replace_block(text, "discover", f'''<section class="discovery" aria-labelledby="discover-title">
  <div class="discovery-inner"><p class="eyebrow">The independent web, in one place</p>
  <h2 id="discover-title">Discover indie websites, web apps, and browser games</h2>
  <p>Explore what independent makers are building. Deploylist brings together recent projects shared in public developer communities, with recorded post votes and links to the original discussions.</p>
  {category_cards()}
  <h2>A new way to explore the web</h2><p>Start with the <a href="/leaderboards/">rankings</a> to browse at your own pace, or try <a href="/discover/">StumbleUpon-style website discovery</a> to move through projects one at a time. Use the category and time filters to find your next game, tool, or unexpected corner of the internet.</p>
  <p>Curious about the list? Read <a href="/about/">how projects are selected and ranked</a>.</p>{navigation()}
  </div></section>{footer()}''')
        writes[site / filename] = text
    for key, (slug, name, desc, detail) in CATEGORIES.items():
        content = f'''<p class="eyebrow">Explore the independent web</p><h1>{name}</h1><p class="directory-lead">{desc}</p>
<p class="updated">Latest rankings snapshot: {stamp}. This list covers the last 30 days of that snapshot.</p>
<div class="directory-actions"><a class="lg tinted pill" href="/leaderboards/?cat={key}">Open interactive rankings</a><a class="lg pill" href="/live/?cat={key}">Try Live view</a></div>
<div class="card"><table class="ranks"><caption class="table-caption">{name} ranked by recorded community votes</caption><thead><tr><th class="rank" scope="col">Rank</th><th scope="col">Website</th><th class="num votes" scope="col">Votes</th><th class="src" scope="col">Source</th></tr></thead><tbody>{rows(groups[key])}</tbody></table></div>
<section class="directory-note"><h2>How to use this list</h2><p>{detail}</p><p>Open a website to explore it, or follow its source link for the original community discussion. Votes are a snapshot of the source post, not ratings or guarantees of quality. Projects that cannot be embedded remain in the rankings but are excluded from Live view.</p><p><a href="/about/">Learn how Deploylist works</a>, or explore another category below.</p>{category_cards()}</section>'''
        writes[site / slug / "index.html"] = document(f"/{slug}/", f"{name} — Recent Community Favorites | Deploylist", desc, content, groups[key], "CollectionPage")
    source_links = ", ".join(f'<a href="{http_url(s["url"])}" target="_blank" rel="noopener noreferrer">{escape(s["name"])}</a>' for s in data.get("sources", []))
    about = f'''<p class="eyebrow">Behind the list</p><h1>How Deploylist works</h1><p class="directory-lead">A directory for discovering indie websites, useful web apps, and browser games.</p>
<section><h2>What makes the rankings?</h2><p>Deploylist looks for community posts centered on a standalone website. It keeps one entry per domain in each ranked time window, using the best-voted eligible post. The monthly list covers a rolling 30 days; the weekly view covers the seven days before the saved snapshot.</p><p>Current sources: {source_links}.</p></section>
<section><h2>What do the votes mean?</h2><p>The number beside a project is its recorded source-post vote count. It is not a Deploylist rating, a live counter, or a measure of active users. Counts may lag behind the original discussion. Rankings reflect only the communities and posts collected, rather than every website on the internet.</p></section>
<section><h2>How often does the list change?</h2><p>Discovery is scheduled every three days. The date displayed on the rankings identifies the latest successful snapshot. If an update fails, the last successful list stays available with its original date.</p><p>Latest saved snapshot: {stamp}.</p></section>
<section><h2>What is Live view?</h2><p>Live view is a StumbleUpon-style way to explore websites one at a time. Choose a category and move forward to the next project or back to a previous one. Some websites are unavailable or do not allow embedded display; those can still appear in the rankings with a direct link.</p><p><a href="/discover/">Learn about Live view</a>.</p></section>
<section><h2>Are these recommendations or endorsements?</h2><p>Inclusion is based on the saved community posts. Deploylist does not guarantee a project's quality, availability, pricing, or safety. Check the website and original discussion to decide whether it is right for you.</p></section>{category_cards()}'''
    about = about.replace(category_cards(), '<section><h2>Can I keep my website out of Live view?</h2><p>If you own a listed website and would like it excluded from Live view, email <a href="mailto:pigeonflare@gmail.com">pigeonflare@gmail.com</a>. Websites that restrict embedded display are also excluded from Live view.</p></section>' + category_cards())
    writes[site / "about/index.html"] = document("/about/", "How Deploylist Works — Sources, Rankings & Live View", "Learn how Deploylist selects indie websites, records community votes, refreshes rankings, and chooses projects for Live view.", about, page_type="AboutPage")
    discover = f'''<p class="eyebrow">Follow your curiosity</p><h1>Discover new websites, one at a time</h1><p class="directory-lead">A StumbleUpon-style way to explore indie websites, web apps, and browser games.</p>
<p>When you want to browse beyond the same familiar websites, Deploylist's Live view brings recent community projects into one place. Move through websites without opening a pile of tabs, then visit a favorite directly when it catches your attention.</p>
<div class="directory-actions"><a class="lg tinted pill" href="/live/">Start exploring</a><a class="lg pill" href="/leaderboards/">Browse the rankings</a></div>
<section><h2>Choose your own trail</h2><p>Use the Games, Apps, Other, or All filter to choose what you see. Switch between the last month and the last week, skip forward to the next website, and return to a previous one with the back control.</p></section>
<section><h2>Find the project and its story</h2><p>Every Live entry links to the website and its original forum post. You can explore the project in its own tab or read what the community thought of it. Websites that cannot run embedded are kept in the rankings for direct browsing.</p></section>
<section><h2>Prefer a list?</h2><p>The <a href="/leaderboards/">interactive rankings</a> let you compare recorded community votes and browse the original discussions at your own pace. Read <a href="/about/">how the directory works</a> for details about sources and refreshes.</p></section>{category_cards()}'''
    writes[site / "discover/index.html"] = document("/discover/", "Discover New Websites — StumbleUpon-Style Browsing | Deploylist", "Find new indie websites, web apps, and browser games with StumbleUpon-style discovery. Explore one project at a time in Deploylist's Live view.", discover)
    paths = ["/", "/leaderboards/", "/games/", "/apps/", "/websites/", "/discover/", "/about/"]
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("", namespace)
    sitemap = ET.Element(f"{{{namespace}}}urlset")
    for path in paths:
        entry = ET.SubElement(sitemap, f"{{{namespace}}}url")
        ET.SubElement(entry, f"{{{namespace}}}loc").text = ORIGIN + path
    writes[site / "sitemap.xml"] = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(sitemap, encoding="unicode") + "\n"
    # Validate everything before writing; malformed data must not produce a partial build.
    for path, content in writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return len(writes)


if __name__ == "__main__":
    print(f"Built {build()} SEO files from the saved rankings.")
