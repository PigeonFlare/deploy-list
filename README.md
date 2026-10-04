# deploylist

The best snapshot of online development: the month's most-upvoted small websites, ranked, plus a StumbleUpon-style live view.

- `site/` is the static site deployed to GitHub Pages (homepage, `/leaderboards/`, `/live/`).
- `scripts/scrape.py` builds `site/data/sites.json` directly from the last 30 days of Reddit posts that center on one standalone website. It reads r/SideProject, r/InternetIsBeautiful, r/WebGames, r/alphaandbetausers, and r/IMadeThis. Sites that refuse to be framed stay on the leaderboard but are left out of live view.
- `.github/workflows/deploy.yml` checks daily at 06:17 UTC and collects posts when the three-day refresh is due. The saved `next_refresh_at` keeps the cadence across month boundaries and runner delays. Pushes deploy the committed site without collecting posts; a manual workflow run refreshes immediately.

## Setup

1. Settings → Pages → Source: **GitHub Actions**. Custom domain: `deploylist.com`.
2. Reddit's public listings supply posts and live vote counts; its RSS feeds supply website links from text posts. No Hacker News or third-party Reddit archive is used. Optional: set `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` repo secrets to use Reddit's API instead.
3. If Reddit is unreachable or returns no posts with known scores, the workflow reports a warning and retains the last successful rankings and their original update timestamp. `data/reddit-cache.json` records successful direct scrapes for inspection; cached posts are never republished as fresh results.

## Local

```sh
python3 scripts/scrape.py
python3 -m http.server -d site 8000
```

Use `python3 scripts/scrape.py --if-due` to honor the saved refresh time. Run the ingestion checks with `python3 -B -m unittest discover -s scripts -p 'test_*.py'`.
