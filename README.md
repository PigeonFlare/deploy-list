# deploylist

Your best view into the online development scene: the month's most-upvoted small websites, ranked, plus a StumbleUpon-style live view.

- `site/` is the static site deployed to GitHub Pages (homepage, `/leaderboards/`, `/live/`).
- `scripts/scrape.py` builds `site/data/sites.json` from the last 30 days of Show HN (via hn.algolia.com) and Reddit posts that center on one standalone website. It reads r/SideProject, r/InternetIsBeautiful, r/IMadeThis, r/ClaudeAI, and r/SaaS (from the last two, only posts whose title says the poster made something). Posts need at least 10 votes. Sites that refuse to be framed or don't load stay on the leaderboard, tagged "Iframe disabled" or "Website down", but are left out of live view. Every daily run rechecks all ranked sites, so a site that goes down leaves Live and one that comes back returns.
- `scripts/snapshots.cjs` captures desktop, tablet and phone stills of each ranked site into `site/snapshots/` (they scroll past in device frames on the homepage) and loads each Live site in a frame, taking out of Live any that refuse to run framed. Stills are kept until their site leaves the rankings.
- `.github/workflows/deploy.yml` checks daily at 06:17 UTC and collects posts when the three-day refresh is due. The saved `next_refresh_at` keeps the cadence across month boundaries and runner delays. Pushes deploy the committed site without collecting posts; a manual workflow run refreshes immediately.

## Setup

1. Settings → Pages → Source: **GitHub Actions**. Custom domain: `deploylist.com`.
2. Reddit's public listings supply posts and live vote counts, and its RSS feeds supply website links from text posts. Reddit blocks those listings from GitHub's servers, so on GitHub a blocked subreddit falls back to its RSS feed with vote counts from the Arctic Shift archive (somewhat behind live counts, never lower than a count seen earlier). Optional: set `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` repo secrets to use Reddit's API, which works from GitHub with exact counts.
Last resort: if Reddit's API, listing and RSS feed all fail for a subreddit (Reddit ends RSS on 2026-11-13), its posts come from the Arctic Shift archive instead. The archive rate-limits, so each run spends a small request budget, saves its progress in `data/archive-cache.json`, and resumes on the next run; while this fallback is in use, the workflow also tops up the cache every day. Archive vote counts lag behind Reddit's, and new posts show near zero until the archive re-reads them about 36 hours later.

3. If Reddit returns no posts with known scores, or Show HN can't be reached, the workflow reports a warning and retains the last successful rankings and their original update timestamp. `data/reddit-cache.json` records each successful Reddit scrape; its vote counts are only used so an archived count never drops below one seen earlier.

## Local

Page metadata, initial rankings, and the sitemap are refreshed from the saved
rankings by `python3 -B scripts/build_seo.py`. The asset-versioning build also runs
this generator on both hosting services. The sitemap includes Home and Rankings;
the iframe-based `/live/` tool is marked `noindex`. The homepage verification tag
must remain for Google Search Console. Retired category, About, and Discover URLs
redirect to the original Rankings or Live view through Cloudflare Pages.

```sh
python3 scripts/scrape.py
python3 -m http.server -d site 8000
```

Use `python3 scripts/scrape.py --if-due` to honor the saved refresh time. Run the ingestion checks with `python3 -B -m unittest discover -s scripts -p 'test_*.py'`.
