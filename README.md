# deploylist

The best snapshot of online development: the month's most-upvoted small websites, ranked, plus a StumbleUpon-style live view.

- `site/` is the static site deployed to GitHub Pages (homepage, `/leaderboards/`, `/live/`).
- `scripts/scrape.py` builds `site/data/sites.json` from the last 30 days of Show HN (via hn.algolia.com) and Reddit posts that center on one standalone website. Sites that refuse to be framed stay on the leaderboard but are left out of live view.
- `.github/workflows/deploy.yml` scrapes and deploys on every push to `main` and every 3 days.

## Setup

1. Settings → Pages → Source: **GitHub Actions**. Custom domain: `deploylist.com`.
2. Reddit is read through its public RSS feeds. Vote counts come from Reddit's web listing where it's reachable, otherwise from the Arctic Shift archive (slightly behind live counts). Optional: set `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` repo secrets to use Reddit's API instead.

## Local

```sh
python3 scripts/scrape.py
python3 -m http.server -d site 8000
```
