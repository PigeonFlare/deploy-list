#!/usr/bin/env python3
"""Refresh page metadata and initial rankings; never collect new posts."""
import json
import re
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://deploylist.com"


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


def metadata(path, title, description, page_type="WebPage", index=True):
    url = ORIGIN + path
    website = {"@type": "WebSite", "@id": ORIGIN + "/#website", "url": ORIGIN + "/", "name": "Deploylist",
               "description": "Discover indie websites, web apps, and browser games."}
    page = {"@type": page_type, "@id": url + "#webpage", "url": url, "name": title,
            "description": description, "isPartOf": {"@id": website["@id"]}, "inLanguage": "en"}
    graph = [website, page]
    if path != "/":
        labels = {"/leaderboards/": "Rankings", "/live/": "Live view"}
        breadcrumb = {"@type": "BreadcrumbList", "@id": url + "#breadcrumb", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": ORIGIN + "/"},
            {"@type": "ListItem", "position": 2, "name": labels[path], "item": url}]}
        page["breadcrumb"] = {"@id": breadcrumb["@id"]}
        graph.append(breadcrumb)
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
  <meta name="twitter:card" content="summary">
  <meta name="twitter:title" content="{e(title)}">
  <meta name="twitter:description" content="{e(description)}">
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
    monthly_games = [s for s in data["sites"] if s["category"] == "games" and s.get("month") is not False]
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
            text = replace_block(text, "rows", rows(monthly_games))
            text = replace_block(text, "updated", f'Last updated {stamp}')
        writes[site / filename] = text
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("", namespace)
    sitemap = ET.Element(f"{{{namespace}}}urlset")
    for path in ("/", "/leaderboards/"):
        entry = ET.SubElement(sitemap, f"{{{namespace}}}url")
        ET.SubElement(entry, f"{{{namespace}}}loc").text = ORIGIN + path
    writes[site / "sitemap.xml"] = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(sitemap, encoding="unicode") + "\n"
    # Validate everything before writing; malformed data must not produce a partial build.
    for path, content in writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return len(writes)


if __name__ == "__main__":
    print(f"Refreshed {build()} files from the saved rankings.")
