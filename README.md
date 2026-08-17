# GitHub Trending Crawler

A small, dependency-light data collector for GitHub Trending.

Its job is deliberately narrow: **fetch fresh Weekly and Monthly Trending pages directly from a GitHub Actions runner, parse the current Top 10, and publish machine-readable snapshots.** It does not generate AI summaries.

## Output

Two files are maintained:

- `data/github-trending/latest.json` — the latest fetch attempt, including explicit errors if it failed
- `data/github-trending/latest-success.json` — updated only when both Weekly and Monthly were fetched and parsed successfully

The JSON records:

- fetch timestamps in UTC and Asia/Taipei
- source and actual request URLs
- HTTP status and selected freshness-related response headers
- SHA-256 of the fetched HTML
- Weekly Top 10 and Monthly Top 10 in GitHub's page order
- repository URL, description, language, total stars, forks, and `stars this week/month`
- explicit per-period errors when fetching/parsing fails

The crawler never substitutes a previous snapshot for a failed current attempt. A downstream consumer may use `latest-success.json` only after independently checking that its timestamp is still recent enough for its purpose.

## Schedule

GitHub Actions runs twice every Monday morning in Asia/Taipei:

- **06:45** (`22:45 UTC Sunday`)
- **07:30** (`23:30 UTC Sunday`)

The redundant same-morning run reduces the chance that a short transient GitHub/network failure blocks the later ChatGPT report. A downstream report should reject `latest-success.json` if it is not from the current Taiwan date or otherwise exceeds its freshness window.

The workflow also supports manual execution (`workflow_dispatch`) and runs when the crawler/workflow code itself changes.

## Freshness policy

Each Weekly/Monthly page is fetched directly from `https://github.com/trending` by the GitHub-hosted runner with cache-busting request parameters and `Cache-Control: no-cache` headers.

For each period the crawler:

1. makes up to 3 attempts;
2. requires HTTP 200;
3. rejects an obviously stale HTTP `Date` header;
4. rejects a response `Age` over 15 minutes when that header is present;
5. requires at least 10 parsable repository cards;
6. requires the Top 10 cards to expose the expected `stars this week/month` value;
7. records the response HTML hash and timestamps for auditing.

A GitHub/CDN response can still involve normal short-lived edge caching; the goal here is to avoid ChatGPT/search-index snapshots that may be days old, not to bypass GitHub's own normal delivery infrastructure.

## Files

- `scripts/fetch_github_trending.py` — fetcher/parser/validator
- `.github/workflows/fetch-trending.yml` — scheduled GitHub Actions job
- `data/github-trending/latest.json` — latest attempt
- `data/github-trending/latest-success.json` — latest fully successful attempt

## Manual run

Open **Actions → Fetch GitHub Trending → Run workflow**.

No repository secrets are required. The workflow uses only public GitHub pages and the built-in `GITHUB_TOKEN` to commit generated JSON back to this repository.
