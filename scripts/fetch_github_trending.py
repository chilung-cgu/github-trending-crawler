#!/usr/bin/env python3
"""Fetch fresh GitHub Trending weekly/monthly Top 10 snapshots.

The crawler never falls back to a previous snapshot. If a current fetch fails after
three attempts, the generated JSON records that failure explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TRENDING_URL = "https://github.com/trending"
PERIODS = {"weekly": "week", "monthly": "month"}
TOP_N = 10
MAX_ATTEMPTS = 3
MAX_HTTP_DATE_SKEW_SECONDS = 15 * 60
MAX_RESPONSE_AGE_SECONDS = 15 * 60
TAIPEI = ZoneInfo("Asia/Taipei")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0 Safari/537.36 "
        "github-trending-crawler/1.0"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache, no-store, max-age=0",
    "Pragma": "no-cache",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def parse_number(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"([0-9][0-9,]*)", text)
    return int(match.group(1).replace(",", "")) if match else None


def parse_page(html: str, period: str) -> tuple[list[dict[str, Any]], int]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("article.Box-row")
    if len(cards) < TOP_N:
        raise ValueError(
            f"parsed only {len(cards)} repository cards; expected at least {TOP_N}"
        )

    period_word = PERIODS[period]
    period_re = re.compile(
        rf"([0-9][0-9,]*)\s+stars?\s+this\s+{period_word}\b", re.IGNORECASE
    )

    items: list[dict[str, Any]] = []
    for rank, card in enumerate(cards[:TOP_N], start=1):
        repo_link = card.select_one("h2 a[href]")
        if repo_link is None:
            raise ValueError(f"rank {rank}: repository link not found")

        href = (repo_link.get("href") or "").strip()
        if not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", href):
            raise ValueError(f"rank {rank}: unexpected repository href {href!r}")

        full_name = href.strip("/")
        description_node = card.select_one("p.col-9") or card.select_one("p.color-fg-muted")
        language_node = card.select_one('[itemprop="programmingLanguage"]')
        stars_node = card.select_one('a[href$="/stargazers"]')
        forks_node = card.select_one('a[href$="/forks"]')

        period_stars: int | None = None
        period_label: str | None = None
        for node in card.find_all(["span", "div"]):
            text = " ".join(node.get_text(" ", strip=True).split())
            match = period_re.search(text)
            if match:
                period_stars = int(match.group(1).replace(",", ""))
                period_label = f"stars this {period_word}"
                break

        items.append(
            {
                "rank": rank,
                "full_name": full_name,
                "url": f"https://github.com/{full_name}",
                "description": (
                    " ".join(description_node.get_text(" ", strip=True).split())
                    if description_node
                    else None
                ),
                "language": (
                    " ".join(language_node.get_text(" ", strip=True).split())
                    if language_node
                    else None
                ),
                "total_stars": parse_number(
                    stars_node.get_text(" ", strip=True) if stars_node else None
                ),
                "forks": parse_number(
                    forks_node.get_text(" ", strip=True) if forks_node else None
                ),
                "period_stars": period_stars,
                "period_label": period_label,
            }
        )

    names = [item["full_name"] for item in items]
    if len(names) != len(set(names)):
        raise ValueError("duplicate repository names found in Top 10")

    return items, len(cards)


def selected_headers(response: requests.Response) -> dict[str, str]:
    wanted = (
        "Date",
        "Age",
        "Cache-Control",
        "ETag",
        "Last-Modified",
        "X-GitHub-Request-Id",
        "Via",
    )
    return {
        key.lower(): value
        for key in wanted
        if (value := response.headers.get(key)) is not None
    }


def validate_freshness(response: requests.Response, fetched_at: datetime) -> None:
    date_header = response.headers.get("Date")
    if date_header:
        response_date = parsedate_to_datetime(date_header)
        if response_date.tzinfo is None:
            response_date = response_date.replace(tzinfo=timezone.utc)
        skew = abs((fetched_at - response_date.astimezone(timezone.utc)).total_seconds())
        if skew > MAX_HTTP_DATE_SKEW_SECONDS:
            raise ValueError(
                f"HTTP Date header is stale or inconsistent: skew={int(skew)} seconds"
            )

    age_header = response.headers.get("Age")
    if age_header and age_header.isdigit():
        age = int(age_header)
        if age > MAX_RESPONSE_AGE_SECONDS:
            raise ValueError(f"response Age header is too old: {age} seconds")


def write_debug(debug_dir: Path, period: str, attempt: int, body: bytes) -> str:
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / f"{period}-attempt-{attempt}.html"
    path.write_bytes(body)
    return str(path)


def fetch_period(
    session: requests.Session, period: str, debug_dir: Path
) -> dict[str, Any]:
    canonical_url = f"{TRENDING_URL}?since={period}"
    errors: list[dict[str, Any]] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        started_at = now_utc()
        response: requests.Response | None = None
        try:
            response = session.get(
                TRENDING_URL,
                params={"since": period, "_fresh": f"{time.time_ns()}-{attempt}"},
                headers=HEADERS,
                timeout=(10, 30),
                allow_redirects=True,
            )
            fetched_at = now_utc()
            response.raise_for_status()
            validate_freshness(response, fetched_at)

            items, card_count = parse_page(response.text, period)
            body = response.content
            headers = selected_headers(response)

            return {
                "status": "ok",
                "source_url": canonical_url,
                "request_url": response.url,
                "attempts": attempt,
                "fetched_at_utc": iso(fetched_at),
                "fetched_at_taipei": iso(fetched_at.astimezone(TAIPEI)),
                "http_status": response.status_code,
                "response_headers": headers,
                "html_sha256": hashlib.sha256(body).hexdigest(),
                "parsed_repository_cards": card_count,
                "items": items,
            }

        except Exception as exc:  # record exact failure and retry
            error: dict[str, Any] = {
                "attempt": attempt,
                "started_at_utc": iso(started_at),
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
            if response is not None:
                error["http_status"] = response.status_code
                error["response_headers"] = selected_headers(response)
                if response.content:
                    error["debug_html"] = write_debug(
                        debug_dir, period, attempt, response.content
                    )
            errors.append(error)
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 * attempt)

    return {
        "status": "error",
        "source_url": canonical_url,
        "attempts": MAX_ATTEMPTS,
        "failed_at_utc": iso(now_utc()),
        "errors": errors,
        "items": [],
    }


def build_snapshot(debug_dir: Path) -> dict[str, Any]:
    generated_at = now_utc()
    with requests.Session() as session:
        periods = {
            period: fetch_period(session, period, debug_dir) for period in PERIODS
        }

    ok_count = sum(result["status"] == "ok" for result in periods.values())
    overall_status = "ok" if ok_count == len(PERIODS) else "partial" if ok_count else "error"

    return {
        "schema_version": 1,
        "status": overall_status,
        "generated_at_utc": iso(generated_at),
        "generated_at_taipei": iso(generated_at.astimezone(TAIPEI)),
        "freshness_policy": {
            "source": "direct HTTPS request from a GitHub-hosted Actions runner to github.com",
            "cache_busting_query_parameter": True,
            "request_cache_control_no_cache": True,
            "max_http_date_skew_seconds": MAX_HTTP_DATE_SKEW_SECONDS,
            "max_response_age_seconds_if_header_present": MAX_RESPONSE_AGE_SECONDS,
            "attempts_per_period": MAX_ATTEMPTS,
            "top_n": TOP_N,
            "fallback_to_previous_snapshot": False,
        },
        "periods": periods,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/github-trending/latest.json")
    parser.add_argument("--debug-dir", default="debug")
    args = parser.parse_args()

    snapshot = build_snapshot(Path(args.debug_dir))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for period, result in snapshot["periods"].items():
        if result["status"] == "ok":
            print(
                f"{period}: OK; top {len(result['items'])}; "
                f"fetched {result['fetched_at_taipei']}"
            )
        else:
            print(f"{period}: ERROR after {result['attempts']} attempts")

    return 0 if snapshot["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
