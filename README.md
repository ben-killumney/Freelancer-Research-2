# Freelab

Freelab is a small research-focused toolkit for collecting public data from [Freelancer.com](https://www.freelancer.com/). It stores project, user, bid, and status history data so researchers can explore winner's-curse and access-cliff hypotheses.

## Features

- SQLAlchemy models covering projects, bids, users, and longitudinal snapshots.
- Optional integration with the official Freelancer API when an `ACCESS_TOKEN` is provided.
- Selenium-based fallback scraper that uses `undetected-chromedriver`, paced requests, and resilient waits.
- Typer-powered CLI for initializing the database, crawling search results, fetching project details and bids, recrawling outcomes, and exporting CSV files.
- Privacy-preserving hashing of freelancer handles using a configurable salt.

## Installation

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and adjust the values for your environment. Provide a PostgreSQL `DB_URL` if desired; otherwise Freelab will store data in a local SQLite database.

## Quickstart

```bash
python -m freelab.cli init-db
python -m freelab.cli crawl-search --query "python" --max-pages 3
python -m freelab.cli recrawl-outcomes --hours 12
python -m freelab.cli export-csv --out ./exports
```

## CLI Commands

Run `python -m freelab.cli --help` to view all commands.

- `init-db`: Create database tables. Use `--drop-existing` to rebuild.
- `crawl-search`: Crawl search result pages (`--query`, optional `--category`, `--max-pages`).
- `fetch-project`: Fetch a specific project by URL or project ID (when using the API).
- `fetch-bids`: Retrieve bids for a given project.
- `recrawl-outcomes`: Revisit projects in open/pending/unknown states during the last N hours.
- `export-csv`: Dump tidy CSVs for the main tables.

## Data model

The schema provides coverage for variables relevant to winner's-curse research:

- Bid dispersion (min/median/max), winning bids, and bid counts are stored in the `projects` table and refreshed snapshots.
- Worker tenure and reputation proxies are stored in the `users` table and `user_profile_snapshots`.

## Development notes

- Respect robots.txt and Freelancer.com's terms of service when scraping.
- The Selenium client runs in headless mode by default, but you can set `SELENIUM_HEADLESS=false` in `.env` to debug interactions.
- Handle hashes use SHA256 with the configured salt and the raw handle is never persisted.

## Exports

The `export-csv` command uses pandas to dump CSV copies of the main analytical tables into the chosen directory for downstream analysis.

