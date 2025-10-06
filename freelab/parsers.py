"""HTML parsing utilities and selector definitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import dateparser
from selenium.webdriver.remote.webelement import WebElement


# Centralised selectors to make updates easier if the site layout changes.
SEARCH_CARD_SELECTOR = "div.SearchResultCard-item"
PROJECT_TITLE_SELECTOR = "a.ProjectView-title"
PROJECT_DESCRIPTION_SELECTOR = "div.ProjectView-details"
BID_TAB_SELECTOR = "a[data-tab='bids']"
BID_ROW_SELECTOR = "div.BidList-row"


@dataclass(slots=True)
class ProjectCard:
    """Parsed data from a project search card."""

    project_id: int
    title: str
    url: str
    category: Optional[str]
    budget: Optional[str]
    currency: Optional[str]
    employer_country: Optional[str]
    posted_at: Optional[datetime]
    num_bids: Optional[int]


@dataclass(slots=True)
class ProjectDetails:
    """Parsed details from a project page."""

    project_id: int
    url: str
    title: str
    category: Optional[str]
    subcategory: Optional[str]
    description_text: Optional[str]
    employer_handle: Optional[str]
    employer_country: Optional[str]
    posted_at: Optional[datetime]
    status: Optional[str]
    budget_type: Optional[str]
    min_budget: Optional[float]
    max_budget: Optional[float]
    currency: Optional[str]
    awarded_to_handle: Optional[str]
    awarded_at: Optional[datetime]
    accepted_at: Optional[datetime]
    closed_at: Optional[datetime]


@dataclass(slots=True)
class BidData:
    """Parsed bid row."""

    bid_id: int
    bidder_handle: Optional[str]
    amount: Optional[float]
    currency: Optional[str]
    delivery_days: Optional[int]
    placed_at: Optional[datetime]
    text_excerpt: Optional[str]
    rating: Optional[float]
    reviews_count: Optional[int]
    country: Optional[str]


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return dateparser.parse(value)


def parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return int(digits) if digits else None


def parse_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    clean = (
        value.replace(",", "")
        .replace("$", "")
        .replace("USD", "")
        .strip()
    )
    try:
        return float(clean)
    except ValueError:
        return None


def extract_text(element: Optional[WebElement]) -> Optional[str]:
    if element is None:
        return None
    text = element.text.strip()
    return text or None


__all__ = [
    "ProjectCard",
    "ProjectDetails",
    "BidData",
    "parse_datetime",
    "parse_int",
    "parse_float",
    "extract_text",
    "SEARCH_CARD_SELECTOR",
    "PROJECT_TITLE_SELECTOR",
    "PROJECT_DESCRIPTION_SELECTOR",
    "BID_TAB_SELECTOR",
    "BID_ROW_SELECTOR",
]
