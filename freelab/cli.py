"""Command line interface for the freelab package."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import typer

from . import db
from .api_client import FreelancerAPIClient
from .config import settings
from .models import Bid, Project, ProjectStatusSnapshot, User
from .scheduler import mark_revisited, projects_due_for_revisit
from .selenium_client import SeleniumClient

app = typer.Typer(add_completion=False, help="Collect Freelancer.com project and bid data")
LOGGER = logging.getLogger(__name__)

PROJECT_FIELDS = {
    "project_id",
    "url",
    "title",
    "category",
    "subcategory",
    "description_text",
    "budget_type",
    "min_budget",
    "max_budget",
    "currency",
    "posted_at",
    "employer_id",
    "employer_country",
    "num_bids_reported",
    "avg_bid_reported",
    "status",
    "awarded_to_id",
    "awarded_at",
    "accepted_at",
    "closed_at",
}

BID_FIELDS = {
    "bid_id",
    "project_id",
    "bidder_id",
    "amount",
    "currency",
    "delivery_days",
    "placed_at",
    "is_winner",
    "bid_position_from_lowest",
    "text_excerpt",
}


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _hash_handle(handle: Optional[str]) -> Optional[str]:
    if not handle:
        return None
    return db.hash_handle(handle, settings.hash_salt)


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    return FreelancerAPIClient.parse_datetime(str(value))


def _clean_bid_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(data)
    cleaned["amount"] = _to_float(cleaned.get("amount"))
    cleaned["delivery_days"] = _to_int(cleaned.get("delivery_days"))
    cleaned["placed_at"] = _to_datetime(cleaned.get("placed_at"))
    return cleaned


def _clean_project_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(data)
    for key in ("min_budget", "max_budget", "avg_bid_reported"):
        if key in cleaned:
            cleaned[key] = _to_float(cleaned.get(key))
    if "posted_at" in cleaned:
        cleaned["posted_at"] = _to_datetime(cleaned.get("posted_at"))
    for key in ("awarded_at", "accepted_at", "closed_at"):
        if key in cleaned:
            cleaned[key] = _to_datetime(cleaned.get(key))
    return cleaned


# Database initialisation ------------------------------------------------------
@app.command("init-db")
def init_db(drop_existing: bool = typer.Option(False, help="Drop existing tables before creation")) -> None:
    """Create the database tables."""

    db.init_db(drop_existing=drop_existing)
    typer.echo("Database initialised")


# Search crawling --------------------------------------------------------------
def _store_project_stub(project_data: dict) -> None:
    if not project_data.get("project_id"):
        LOGGER.warning("Skipping project without identifier: %s", project_data)
        return
    with db.session_scope() as session:
        employer_id = project_data.get("employer_id")
        employer_handle = project_data.pop("employer_handle", None)
        if employer_handle:
            hashed = _hash_handle(employer_handle)
            if employer_id is None:
                employer_id = int(project_data["project_id"]) * 10 + 1
            user_payload = {
                "user_id": employer_id,
                "handle_hash": hashed,
                "country": project_data.get("employer_country"),
            }
            db.upsert_user(session, user_payload)
        payload = {key: project_data.get(key) for key in PROJECT_FIELDS if key in project_data}
        if employer_id:
            payload["employer_id"] = employer_id
        db.upsert_project(session, payload)


@app.command("crawl-search")
def crawl_search(
    query: str = typer.Option(..., help="Search query string"),
    category: Optional[str] = typer.Option(None, help="Freelancer category filter"),
    max_pages: int = typer.Option(1, min=1, max=20, help="Maximum number of result pages to crawl"),
) -> None:
    """Collect project metadata from search results."""

    if settings.access_token:
        client = FreelancerAPIClient()
        projects = client.search_projects(query=query, category=category, limit=max_pages * 50)
        for project in projects:
            project_id = int(project["id"]) if "id" in project else int(project["project_id"])
            employer = project.get("owner") or {}
            _store_project_stub(
                {
                    "project_id": project_id,
                    "url": project.get("url", f"https://www.freelancer.com/projects/{project_id}"),
                    "title": project.get("title", ""),
                    "category": project.get("category", {}).get("name"),
                    "subcategory": project.get("sub_category", {}).get("name"),
                    "description_text": project.get("preview_description"),
                    "budget_type": project.get("type"),
                    "min_budget": project.get("budget", {}).get("minimum"),
                    "max_budget": project.get("budget", {}).get("maximum"),
                    "currency": project.get("currency", {}).get("code"),
                    "posted_at": FreelancerAPIClient.parse_datetime(project.get("submitdate")),
                    "employer_id": employer.get("id"),
                    "employer_country": (employer.get("location") or {}).get("country"),
                    "employer_handle": employer.get("username"),
                    "num_bids_reported": project.get("bid_count"),
                    "status": project.get("status"),
                }
            )
        typer.echo(f"Stored {len(projects)} projects from API search")
        return

    with SeleniumClient() as client:
        for page in range(1, max_pages + 1):
            url = _build_search_url(query=query, category=category, page=page)
            client.get(url)
            for card in client.parse_search_cards():
                _store_project_stub(
                    {
                        "project_id": card.project_id,
                        "url": card.url,
                        "title": card.title,
                        "category": card.category,
                        "description_text": card.budget,
                        "currency": card.currency,
                        "posted_at": card.posted_at,
                        "employer_country": card.employer_country,
                        "num_bids_reported": card.num_bids,
                        "status": "open",
                    }
                )
            typer.echo(f"Processed search page {page}")


def _build_search_url(query: str, category: Optional[str], page: int) -> str:
    from urllib.parse import quote_plus

    base = "https://www.freelancer.com/jobs/"
    params = f"?keyword={quote_plus(query)}&page={page}"
    if category:
        params += f"&category={quote_plus(category)}"
    return base + params


# Project fetching -------------------------------------------------------------
def _store_project_details(result_project: dict) -> None:
    _store_project_stub(_clean_project_dict(result_project))


@app.command("fetch-project")
def fetch_project(project_url: str = typer.Argument(..., help="Full project URL")) -> None:
    """Fetch detailed information for a single project."""

    if settings.access_token and project_url.isdigit():
        client = FreelancerAPIClient()
        project_id = int(project_url)
        project = client.get_project(project_id)
        owner = project.get("owner") or {}
        _store_project_details(
            {
                "project_id": project_id,
                "url": project.get("seo_url", project_url),
                "title": project.get("title", ""),
                "category": project.get("category", {}).get("name"),
                "subcategory": project.get("sub_category", {}).get("name"),
                "description_text": project.get("description"),
                "budget_type": project.get("type"),
                "min_budget": project.get("budget", {}).get("minimum"),
                "max_budget": project.get("budget", {}).get("maximum"),
                "currency": project.get("currency", {}).get("code"),
                "posted_at": FreelancerAPIClient.parse_datetime(project.get("submitdate")),
                "employer_id": owner.get("id"),
                "employer_handle": owner.get("username"),
                "employer_country": (owner.get("location") or {}).get("country"),
                "status": project.get("status"),
                "awarded_to_id": (project.get("selected_bids") or [{}])[0].get("bidder_id"),
            }
        )
        typer.echo(f"Stored project {project_id} via API")
        return

    with SeleniumClient() as client:
        client.get(project_url)
        result = client.parse_project_details()
        project = _clean_project_dict(asdict(result.project))
        _store_project_details(project)
        if result.bids:
            _store_bids(
                project_id=project["project_id"],
                bids=[_clean_bid_dict(asdict(bid)) for bid in result.bids],
            )
        typer.echo(f"Stored project {project['project_id']} via Selenium")


# Bid scraping -----------------------------------------------------------------
def _store_bids(project_id: int, bids: Iterable[Dict[str, Any]]) -> None:
    with db.session_scope() as session:
        for bid in bids:
            if not bid.get("bid_id"):
                LOGGER.warning("Skipping bid without identifier: %s", bid)
                continue
            bidder_handle = bid.get("bidder_handle")
            bidder_id = bid.get("bidder_id") or bid.get("bid_id")
            hashed = _hash_handle(bidder_handle) if bidder_handle else None
            user_id = bidder_id or random_surrogate_id(project_id)
            if hashed:
                db.upsert_user(
                    session,
                    {
                        "user_id": user_id,
                        "handle_hash": hashed,
                        "country": bid.get("country"),
                        "rating": bid.get("rating"),
                        "reviews_count": bid.get("reviews_count"),
                    },
                )
            bid_payload = {key: bid.get(key) for key in BID_FIELDS}
            bid_payload["project_id"] = project_id
            bid_payload["bidder_id"] = user_id
            db.upsert_bid(session, bid_payload)
        db.compute_bid_positions(session, project_id)
        db.update_project_bid_metrics(session, project_id)
        project = session.get(Project, project_id)
        if project:
            db.determine_winner(session, project)


def random_surrogate_id(project_id: int) -> int:
    return int(f"{project_id}999")


@app.command("fetch-bids")
def fetch_bids(project_id: int = typer.Argument(..., help="Numeric project identifier")) -> None:
    """Fetch bids for a project via API or Selenium."""

    if settings.access_token:
        client = FreelancerAPIClient()
        bids = client.get_project_bids(project_id)
        parsed_bids = []
        for bid in bids:
            bidder = bid.get("bidder") or {}
            reputation = bidder.get("reputation") or {}
            parsed_bids.append(
                {
                    "bid_id": bid.get("id"),
                    "bidder_id": bidder.get("id"),
                    "bidder_handle": bidder.get("username"),
                    "amount": bid.get("amount"),
                    "currency": (bid.get("currency") or {}).get("code"),
                    "delivery_days": bid.get("period"),
                    "placed_at": FreelancerAPIClient.parse_datetime(bid.get("submitdate")),
                    "text_excerpt": bid.get("description"),
                    "rating": reputation.get("overall"),
                    "reviews_count": reputation.get("reviews"),
                    "country": (bidder.get("location") or {}).get("country"),
                }
            )
        _store_bids(project_id, [_clean_bid_dict(bid) for bid in parsed_bids])
        typer.echo(f"Stored {len(parsed_bids)} bids via API")
        return

    project_url = f"https://www.freelancer.com/projects/{project_id}"
    with SeleniumClient() as client:
        client.get(project_url)
        result = client.parse_project_details()
        _store_project_details(_clean_project_dict(asdict(result.project)))
        _store_bids(project_id, [_clean_bid_dict(asdict(bid)) for bid in result.bids])
        typer.echo(f"Stored {len(result.bids)} bids via Selenium")


# Outcome recrawling -----------------------------------------------------------
@app.command("recrawl-outcomes")
def recrawl_outcomes(hours: int = typer.Option(24, min=1, help="Look-back window for refreshing projects")) -> None:
    """Revisit open projects and append status snapshots."""

    with db.session_scope() as session:
        projects = projects_due_for_revisit(session, hours=hours)
        typer.echo(f"Found {len(projects)} projects due for revisit")
    if not projects:
        return

    for project in projects:
        fetch_project(str(project.project_id))
        with db.session_scope() as session:
            refreshed = session.get(Project, project.project_id)
            if refreshed:
                mark_revisited(refreshed)


# Exporting --------------------------------------------------------------------
@app.command("export-csv")
def export_csv(out: Path = typer.Option(Path("./exports"), help="Output directory")) -> None:
    """Export tidy CSV snapshots for analysis."""

    ensure_output_dir(out)
    engine = db.get_engine()
    tables = {
        "projects": Project,
        "bids": Bid,
        "users": User,
        "project_status_snapshots": ProjectStatusSnapshot,
    }
    for name, model in tables.items():
        df = pd.read_sql_table(model.__tablename__, engine)
        path = out / f"{name}.csv"
        df.to_csv(path, index=False)
        typer.echo(f"Exported {path}")


def main() -> None:
    logging.basicConfig(level=os.getenv("FREELAB_LOG_LEVEL", "INFO"))
    app()


if __name__ == "__main__":
    main()
