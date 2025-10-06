"""Selenium-based scraper for Freelancer.com when the API is unavailable."""

from __future__ import annotations

import logging
import random
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import undetected_chromedriver as uc
from selenium.webdriver import ChromeOptions
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from tenacity import retry, stop_after_attempt, wait_random_exponential

from .config import settings
from .parsers import (
    BID_ROW_SELECTOR,
    BID_TAB_SELECTOR,
    PROJECT_DESCRIPTION_SELECTOR,
    PROJECT_TITLE_SELECTOR,
    SEARCH_CARD_SELECTOR,
    BidData,
    ProjectCard,
    ProjectDetails,
    extract_text,
    parse_datetime,
    parse_float,
    parse_int,
)

LOGGER = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]


@dataclass(slots=True)
class SeleniumResult:
    """Container for project details and bids."""

    project: ProjectDetails
    bids: List[BidData]


class SeleniumClient(AbstractContextManager):
    """High-level Selenium automation helper."""

    def __init__(self, headless: bool | None = None, driver: Optional[WebDriver] = None) -> None:
        self.headless = settings.selenium_headless if headless is None else headless
        self._driver = driver
        self._wait: Optional[WebDriverWait] = None

    # Context manager protocol -------------------------------------------------
    def __enter__(self) -> "SeleniumClient":
        if self._driver is None:
            self._driver = self._build_driver()
        self._wait = WebDriverWait(self._driver, timeout=20)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self._driver is not None:
            self._driver.quit()
            self._driver = None
        self._wait = None

    # Driver management --------------------------------------------------------
    def _build_driver(self) -> WebDriver:
        options = ChromeOptions()
        options.headless = self.headless
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
        options.add_argument("--window-size=1280,720")
        LOGGER.debug("Launching headless Chrome (headless=%s)", self.headless)
        return uc.Chrome(options=options)

    @property
    def driver(self) -> WebDriver:
        if self._driver is None:
            raise RuntimeError("SeleniumClient not initialised; use as a context manager")
        return self._driver

    @property
    def wait(self) -> WebDriverWait:
        if self._wait is None:
            raise RuntimeError("wait not initialised; did you call __enter__?")
        return self._wait

    # Helpers -----------------------------------------------------------------
    def safe_wait(self, css_selector: str) -> List[WebElement]:
        """Return elements matching selector, waiting until present."""

        self.wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, css_selector)))
        return self.driver.find_elements(By.CSS_SELECTOR, css_selector)

    def random_pause(self, min_seconds: float = 0.5, max_seconds: float = 1.5) -> None:
        time.sleep(random.uniform(min_seconds, max_seconds))

    # Requests -----------------------------------------------------------------
    @retry(wait=wait_random_exponential(multiplier=1, max=20), stop=stop_after_attempt(5))
    def get(self, url: str) -> None:
        LOGGER.debug("Navigating to %s", url)
        self.driver.get(url)
        self.random_pause(1.0, 2.5)

    # Parsing ------------------------------------------------------------------
    def parse_search_cards(self) -> List[ProjectCard]:
        cards = []
        for element in self.safe_wait(SEARCH_CARD_SELECTOR):
            try:
                link = element.find_element(By.CSS_SELECTOR, "a")
                url = link.get_attribute("href")
                project_id = parse_int(element.get_attribute("data-project-id")) or parse_int(url.split("/")[-1])
                cards.append(
                    ProjectCard(
                        project_id=project_id or 0,
                        title=extract_text(link) or "",
                        url=url,
                        category=extract_text(self._safe_find(element, By.CSS_SELECTOR, ".SearchResultCard-category")),
                        budget=extract_text(self._safe_find(element, By.CSS_SELECTOR, ".SearchResultCard-price")),
                        currency=None,
                        employer_country=extract_text(
                            self._safe_find(element, By.CSS_SELECTOR, ".SearchResultCard-location")
                        ),
                        posted_at=parse_datetime(
                            extract_text(self._safe_find(element, By.CSS_SELECTOR, ".SearchResultCard-posted"))
                        ),
                        num_bids=parse_int(
                            extract_text(self._safe_find(element, By.CSS_SELECTOR, ".SearchResultCard-bids"))
                        ),
                    )
                )
            except Exception as error:  # pragma: no cover - robust logging
                LOGGER.warning("Failed to parse project card: %s", error)
        return cards

    def _safe_find(self, element: WebElement, by: str, selector: str) -> Optional[WebElement]:
        try:
            return element.find_element(by, selector)
        except Exception:
            return None

    def parse_project_details(self) -> SeleniumResult:
        project_id = parse_int(self.driver.current_url.split("/")[-1]) or 0
        title_el = self._safe_find(self.driver, By.CSS_SELECTOR, PROJECT_TITLE_SELECTOR)
        description_el = self._safe_find(self.driver, By.CSS_SELECTOR, PROJECT_DESCRIPTION_SELECTOR)

        project = ProjectDetails(
            project_id=project_id,
            url=self.driver.current_url,
            title=extract_text(title_el) or "",
            category=None,
            subcategory=None,
            description_text=extract_text(description_el),
            employer_handle=self._extract_employer_handle(),
            employer_country=self._extract_employer_country(),
            posted_at=self._extract_posted_at(),
            status=self._extract_status(),
            budget_type=self._extract_budget_type(),
            min_budget=self._extract_budget_value("min"),
            max_budget=self._extract_budget_value("max"),
            currency=self._extract_currency(),
            awarded_to_handle=self._extract_awarded_handle(),
            awarded_at=self._extract_datetime_via_selector(".ProjectView-awardedAt"),
            accepted_at=self._extract_datetime_via_selector(".ProjectView-acceptedAt"),
            closed_at=self._extract_datetime_via_selector(".ProjectView-closedAt"),
        )
        bids = self._parse_bids()
        return SeleniumResult(project=project, bids=bids)

    def _extract_employer_handle(self) -> Optional[str]:
        element = self._safe_find(self.driver, By.CSS_SELECTOR, ".EmployerProfile-link")
        return extract_text(element)

    def _extract_employer_country(self) -> Optional[str]:
        element = self._safe_find(self.driver, By.CSS_SELECTOR, ".EmployerProfile-country")
        return extract_text(element)

    def _extract_posted_at(self) -> Optional[datetime]:
        element = self._safe_find(self.driver, By.CSS_SELECTOR, ".ProjectView-posted")
        return parse_datetime(extract_text(element))

    def _extract_status(self) -> Optional[str]:
        element = self._safe_find(self.driver, By.CSS_SELECTOR, ".ProjectView-status")
        return extract_text(element)

    def _extract_budget_type(self) -> Optional[str]:
        element = self._safe_find(self.driver, By.CSS_SELECTOR, ".ProjectView-budgetType")
        return extract_text(element)

    def _extract_budget_value(self, kind: str) -> Optional[float]:
        selector = ".ProjectView-budget"
        element = self._safe_find(self.driver, By.CSS_SELECTOR, selector)
        text = extract_text(element)
        if not text:
            return None
        if kind == "min":
            part = text.split("-")[0]
        else:
            part = text.split("-")[-1]
        return parse_float(part)

    def _extract_currency(self) -> Optional[str]:
        element = self._safe_find(self.driver, By.CSS_SELECTOR, ".ProjectView-budgetCurrency")
        return extract_text(element)

    def _extract_awarded_handle(self) -> Optional[str]:
        element = self._safe_find(self.driver, By.CSS_SELECTOR, ".ProjectView-awardedUser")
        return extract_text(element)

    def _extract_datetime_via_selector(self, selector: str) -> Optional[datetime]:
        element = self._safe_find(self.driver, By.CSS_SELECTOR, selector)
        return parse_datetime(extract_text(element))

    def _open_bid_tab(self) -> None:
        tab = self._safe_find(self.driver, By.CSS_SELECTOR, BID_TAB_SELECTOR)
        if tab:
            tab.click()
            self.random_pause(1.0, 2.0)

    def _scroll_to_bottom(self) -> None:
        last_height = 0
        while True:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            self.random_pause(1.0, 2.0)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

    def _parse_bids(self) -> List[BidData]:
        self._open_bid_tab()
        self._scroll_to_bottom()
        bid_elements = self.driver.find_elements(By.CSS_SELECTOR, BID_ROW_SELECTOR)
        bids: List[BidData] = []
        for element in bid_elements:
            try:
                bid_id = parse_int(element.get_attribute("data-bid-id")) or random.randint(10_000, 999_999)
                bids.append(
                    BidData(
                        bid_id=bid_id,
                        bidder_handle=extract_text(self._safe_find(element, By.CSS_SELECTOR, ".BidList-bidder")),
                        amount=parse_float(extract_text(self._safe_find(element, By.CSS_SELECTOR, ".BidList-amount"))),
                        currency=None,
                        delivery_days=parse_int(
                            extract_text(self._safe_find(element, By.CSS_SELECTOR, ".BidList-delivery"))
                        ),
                        placed_at=parse_datetime(
                            extract_text(self._safe_find(element, By.CSS_SELECTOR, ".BidList-time"))
                        ),
                        text_excerpt=extract_text(self._safe_find(element, By.CSS_SELECTOR, ".BidList-notes")),
                        rating=parse_float(
                            extract_text(self._safe_find(element, By.CSS_SELECTOR, ".BidList-rating"))
                        ),
                        reviews_count=parse_int(
                            extract_text(self._safe_find(element, By.CSS_SELECTOR, ".BidList-reviews"))
                        ),
                        country=extract_text(self._safe_find(element, By.CSS_SELECTOR, ".BidList-country")),
                    )
                )
            except Exception as error:  # pragma: no cover
                LOGGER.warning("Failed to parse bid row: %s", error)
        return bids


__all__ = ["SeleniumClient", "SeleniumResult"]
