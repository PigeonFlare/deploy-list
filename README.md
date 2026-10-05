# deploylist

The best-curated snapshot of online development: the month's most-upvoted small websites, ranked, plus a StumbleUpon-style live view.

- `site/` is the static site deployed to GitHub Pages (homepage, `/leaderboards/`, `/live/`).
- `scripts/scrape.py` builds `site/data/sites.json` from the last 30 days of Show HN (via hn.algolia.com) and Reddit posts that center on one standalone website. It reads r/SideProject, r/InternetIsBeautiful, r/IMadeThis, r/ClaudeAI, and r/SaaS (from the last two, only posts whose title says the poster made something). Posts need at least 10 votes. Sites that refuse to be framed stay on the leaderboard but are left out of live view.
- `scripts/snapshots.cjs` captures a small still of each ranked site into `site/snapshots/`; they fly past in the homepage's hyperspace. Stills are kept until their site leaves the rankings.
- `.github/workflows/deploy.yml` checks daily at 06:17 UTC and collects posts when the three-day refresh is due. The saved `next_refresh_at` keeps the cadence across month boundaries and runner delays. Pushes deploy the committed site without collecting posts; a manual workflow run refreshes immediately.

## Setup

1. Settings → Pages → Source: **GitHub Actions**. Custom domain: `deploylist.com`.
2. Reddit's public listings supply posts and live vote counts, and its RSS feeds supply website links from text posts. Reddit blocks those listings from GitHub's servers, so on GitHub a blocked subreddit falls back to its RSS feed with vote counts from the Arctic Shift archive (somewhat behind live counts, never lower than a count seen earlier). Optional: set `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` repo secrets to use Reddit's API, which works from GitHub with exact counts.
3. If Reddit returns no posts with known scores, or Show HN can't be reached, the workflow reports a warning and retains the last successful rankings and their original update timestamp. `data/reddit-cache.json` records each successful Reddit scrape; its vote counts are only used so an archived count never drops below one seen earlier.

## Local

```sh
python3 scripts/scrape.py
python3 -m http.server -d site 8000
```

Use `python3 scripts/scrape.py --if-due` to honor the saved refresh time. Run the ingestion checks with `python3 -B -m unittest discover -s scripts -p 'test_*.py'`.
