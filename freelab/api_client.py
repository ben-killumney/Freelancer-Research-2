"""Freelancer.com API client integration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

import dateparser
import requests
from requests import Response

from .config import settings

LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://www.freelancer.com/api"


class FreelancerAPIError(RuntimeError):
    """Raised when the Freelancer API returns an unexpected response."""


class FreelancerAPIClient:
    """Thin wrapper around the official Freelancer.com API."""

    def __init__(self, access_token: str | None = None) -> None:
        self.access_token = access_token or settings.access_token
        if not self.access_token:
            raise ValueError("ACCESS_TOKEN is required to use the API client")

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: object) -> Response:
        url = f"{API_BASE_URL}{path}"
        response = requests.request(method=method, url=url, headers=self._headers, timeout=30, **kwargs)
        if not response.ok:
            LOGGER.error("Freelancer API error %s: %s", response.status_code, response.text)
            raise FreelancerAPIError(f"API request failed with status {response.status_code}: {response.text}")
        return response

    def search_projects(self, query: str, category: Optional[str] = None, limit: int = 50) -> List[Dict[str, object]]:
        """Search for projects matching the given query."""

        params = {"query": query, "limit": limit}
        if category:
            params["category"] = category
        response = self._request("GET", "/projects/0.1/projects/search/active/", params=params)
        data = response.json()
        result = data.get("result") or {}
        projects = result.get("projects") or data.get("projects", [])
        LOGGER.debug("Retrieved %s projects from API", len(projects))
        return projects

    def get_project(self, project_id: int) -> Dict[str, object]:
        """Fetch a single project's details."""

        response = self._request("GET", f"/projects/0.1/projects/{project_id}/", params={"full_description": True})
        return response.json().get("result", {})

    def get_project_bids(self, project_id: int) -> List[Dict[str, object]]:
        """Return bids associated with a project."""

        response = self._request("GET", f"/projects/0.1/projects/{project_id}/bids/")
        return response.json().get("result", {}).get("bids", [])

    @staticmethod
    def parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if value is None:
            return None
        return dateparser.parse(value)


__all__ = ["FreelancerAPIClient", "FreelancerAPIError"]
