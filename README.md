# GitHub Trending Crawler

A small, dependency-light data collector for GitHub Trending.

Its job is deliberately narrow: **fetch fresh Weekly and Monthly Trending pages directly from a GitHub Actions runner, parse the current Top 10, and publish a machine-readable snapshot.** It does not generate AI summaries.

## Output

The latest attempt is written to:

- `data/github-trending/latest.json`

The JSON records:

- fetch timestamps in UTC and Asia/Taipei
- source and actual request URLs
- HTTP status and selected freshness-related response headers
- SHA-256 of the fetched HTML
- Weekly Top 10 and Monthly Top 10 in GitHub's page order
- repository URL, description, language, total stars, forks, and `stars this week/month` when present
- explicit per-period errors when fetching/parsing fails

Previous data is **never** substituted for a failed current fetch.

## Schedule

GitHub Actions runs every Monday at **07:15 Asia/Taipei** (`23:15 UTC Sunday`), leaving time for a downstream 08:00 ChatGPT summary job.

The workflow also supports manual execution (`workflow_dispatch`) and runs when the crawler/workflow code itself changes.

## Freshness policy

Each Weekly/Monthly page is fetched directly from `https://github.com/trending` by the GitHub-hosted runner with cache-busting request parameters and `Cache-Control: no-cache` headers.

For each period the crawler:

1. makes up to 3 attempts;
2. requires HTTP 200;
3. rejects an obviously stale HTTP `Date` header;
4. rejects a response `Age` over 15 minutes when that header is present;
5. requires at least 10 parsable repository cards;
6. records the response HTML hash and timestamps for auditing.

A GitHub/CDN response can still involve normal short-lived edge caching; the goal here is to avoid ChatGPT/search-index snapshots that may be days old, not to bypass GitHub's own normal delivery infrastructure.

## Files

- `scripts/fetch_github_trending.py` — fetcher/parser/validator
- `.github/workflows/fetch-trending.yml` — scheduled GitHub Actions job
- `data/github-trending/latest.json` — generated snapshot (after the first run)

## Manual run

Open **Actions → Fetch GitHub Trending → Run workflow**.

No repository secrets are required. The workflow uses only public GitHub pages and the built-in `GITHUB_TOKEN` to commit the generated JSON back to this repository.
