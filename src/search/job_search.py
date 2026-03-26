"""
Job Search Integration.

Provides a unified interface for querying multiple job boards.
Currently supports:
  - LinkedIn (via public search URL + HTML scraping)
  - Indeed Germany (indeed.de)
  - StepStone (stepstone.de)

Design principles:
  - Each source is a separate private method so new sources can be added
    without touching calling code.
  - Results are cached in the database to avoid hammering external sites.
  - Network errors are caught and logged; partial results are returned
    rather than failing the entire search.
  - No authenticated API calls — uses public search pages only.

NOTE: Scraped HTML structure changes over time. Results are best-effort.
For production use, consider official API partnerships or job aggregator APIs.
"""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from src.database.manager import DatabaseManager
from src.models.models import SearchResult

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_REQUEST_TIMEOUT = 15  # seconds


class JobSearcher:
    """Search for job listings across multiple public job boards."""

    def __init__(
        self,
        db: DatabaseManager,
        config: Dict[str, Any],
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        """
        Initialise the searcher.

        Args:
            db:          DatabaseManager for result caching.
            config:      Parsed config.yaml dict.
            http_client: Optional injected httpx.Client (useful for testing).
        """
        self._db = db
        self._cfg = config.get("search", {})
        self._sources: List[str] = self._cfg.get("sources", ["linkedin", "indeed"])
        self._results_per_query: int = self._cfg.get("results_per_query", 20)
        self._default_location: str = self._cfg.get("default_location", "Germany")
        self._client = http_client or httpx.Client(
            headers=_DEFAULT_HEADERS,
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
        )

    def search(
        self,
        query: str,
        location: Optional[str] = None,
        sources: Optional[List[str]] = None,
        use_cache: bool = True,
    ) -> List[SearchResult]:
        """
        Search for jobs across configured sources.

        Args:
            query:     Job title / keyword string (e.g. "AI Engineer Python").
            location:  Location string (default from config).
            sources:   Override which sources to query.
            use_cache: Whether to use cached results if available.

        Returns:
            Deduplicated list of SearchResult objects.
        """
        location = location or self._default_location
        active_sources = sources or self._sources
        all_results: List[SearchResult] = []

        for source in active_sources:
            cache_key = self._make_cache_key(query, location, source)
            if use_cache:
                cached = self._db.get_cached_results(cache_key, source)
                if cached:
                    logger.debug("Cache hit for %s / %s", source, query)
                    all_results.extend(SearchResult(**r) for r in cached)
                    continue

            try:
                results = self._fetch_source(source, query, location)
                logger.info("Fetched %d results from %s", len(results), source)
                # Cache raw dicts for serialisation
                self._db.cache_search_results(
                    cache_key, location, source,
                    [r.model_dump() for r in results]
                )
                all_results.extend(results)
            except Exception as exc:
                logger.warning("Search source %r failed: %s", source, exc)

        return self._deduplicate(all_results)[: self._results_per_query]

    # ------------------------------------------------------------------
    # Source-specific fetchers
    # ------------------------------------------------------------------

    def _fetch_source(self, source: str, query: str, location: str) -> List[SearchResult]:
        """
        Dispatch to the appropriate source fetcher.

        Args:
            source:   Source name string.
            query:    Search query.
            location: Location string.

        Returns:
            List of SearchResult.
        """
        dispatch = {
            "linkedin": self._fetch_linkedin,
            "indeed": self._fetch_indeed,
            "stepstone": self._fetch_stepstone,
            "xing": self._fetch_xing,
        }
        fetcher = dispatch.get(source.lower())
        if not fetcher:
            logger.warning("Unknown search source: %r", source)
            return []
        return fetcher(query, location)

    def _fetch_linkedin(self, query: str, location: str) -> List[SearchResult]:
        """
        Fetch results from LinkedIn public job search.

        Args:
            query:    Job search keywords.
            location: Location string.

        Returns:
            List of SearchResult.
        """
        params = {
            "keywords": query,
            "location": location,
            "f_TPR": "r604800",  # Last 7 days
        }
        url = "https://www.linkedin.com/jobs/search/?" + urllib.parse.urlencode(params)
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning("LinkedIn returned HTTP %d", e.response.status_code)
            return []

        return self._parse_linkedin_html(resp.text, url)

    def _parse_linkedin_html(self, html: str, base_url: str) -> List[SearchResult]:
        """Parse LinkedIn search results HTML into SearchResult objects."""
        soup = BeautifulSoup(html, "lxml")
        results: List[SearchResult] = []

        # LinkedIn's public search pages render job cards with these selectors
        cards = soup.select("div.job-search-card, li.jobs-search-results__list-item")
        for card in cards[:20]:
            title_el = card.select_one("h3.base-search-card__title, h3.job-result-card__title")
            company_el = card.select_one("h4.base-search-card__subtitle, h4.job-result-card__company-name")
            location_el = card.select_one("span.job-search-card__location, span.job-result-card__location")
            link_el = card.select_one("a.base-card__full-link, a.job-result-card__full-link, a[href*='/jobs/view/']")

            if not title_el:
                continue

            results.append(SearchResult(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "",
                location=location_el.get_text(strip=True) if location_el else "",
                url=link_el.get("href", "") if link_el else base_url,
                source="linkedin",
                snippet=card.get_text(separator=" ", strip=True)[:200],
            ))
        return results

    def _fetch_indeed(self, query: str, location: str) -> List[SearchResult]:
        """
        Fetch results from Indeed Germany.

        Args:
            query:    Job search keywords.
            location: Location string.

        Returns:
            List of SearchResult.
        """
        params = {
            "q": query,
            "l": location,
            "sort": "date",
        }
        url = "https://de.indeed.com/jobs?" + urllib.parse.urlencode(params)
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning("Indeed returned HTTP %d", e.response.status_code)
            return []

        return self._parse_indeed_html(resp.text, "https://de.indeed.com")

    def _parse_indeed_html(self, html: str, base_url: str) -> List[SearchResult]:
        """Parse Indeed search results HTML."""
        soup = BeautifulSoup(html, "lxml")
        results: List[SearchResult] = []

        cards = soup.select("div.jobsearch-SerpJobCard, div.job_seen_beacon, li[class*='css-']")
        for card in cards[:20]:
            title_el = card.select_one("h2 a, h2 span[title]")
            company_el = card.select_one("span.company, div[data-testid='company-name']")
            location_el = card.select_one("div.recJobLoc, div[data-testid='job-location']")
            link_el = card.select_one("a[href*='/rc/clk'], a[href*='/pagead/clk']")

            if not title_el:
                continue

            href = link_el.get("href", "") if link_el else ""
            if href.startswith("/"):
                href = base_url + href

            results.append(SearchResult(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "",
                location=location_el.get_text(strip=True) if location_el else "",
                url=href,
                source="indeed",
                snippet=card.get_text(separator=" ", strip=True)[:200],
            ))
        return results

    def _fetch_stepstone(self, query: str, location: str) -> List[SearchResult]:
        """
        Fetch results from StepStone Germany.

        Args:
            query:    Job search keywords.
            location: Location string.

        Returns:
            List of SearchResult.
        """
        query_slug = re.sub(r"\s+", "-", query.strip().lower())
        location_slug = re.sub(r"\s+", "-", location.strip().lower())
        url = f"https://www.stepstone.de/jobs/{urllib.parse.quote(query_slug)}/in-{urllib.parse.quote(location_slug)}"
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning("StepStone returned HTTP %d", e.response.status_code)
            return []

        return self._parse_stepstone_html(resp.text)

    def _parse_stepstone_html(self, html: str) -> List[SearchResult]:
        """Parse StepStone search results HTML."""
        soup = BeautifulSoup(html, "lxml")
        results: List[SearchResult] = []

        cards = soup.select("article[data-at='job-item'], article.sc-beqWAB")
        for card in cards[:20]:
            title_el = card.select_one("h2 a, span[data-at='job-item-title']")
            company_el = card.select_one("span[data-at='job-item-company-name'], p[data-at='job-item-company-name']")
            location_el = card.select_one("span[data-at='job-item-location']")
            link_el = card.select_one("a[href*='/stellenangebote/']")

            if not title_el:
                continue

            href = link_el.get("href", "") if link_el else ""
            if href.startswith("/"):
                href = "https://www.stepstone.de" + href

            results.append(SearchResult(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "",
                location=location_el.get_text(strip=True) if location_el else "",
                url=href,
                source="stepstone",
                snippet=card.get_text(separator=" ", strip=True)[:200],
            ))
        return results

    def _fetch_xing(self, query: str, location: str) -> List[SearchResult]:
        """
        Fetch results from XING job board.

        Args:
            query:    Job search keywords.
            location: Location string.

        Returns:
            List of SearchResult.
        """
        params = {"keywords": query, "location": location}
        url = "https://www.xing.com/jobs/search?" + urllib.parse.urlencode(params)
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning("XING returned HTTP %d", e.response.status_code)
            return []

        return self._parse_xing_html(resp.text)

    def _parse_xing_html(self, html: str) -> List[SearchResult]:
        """Parse XING search results HTML."""
        soup = BeautifulSoup(html, "lxml")
        results: List[SearchResult] = []

        cards = soup.select("article.job-listing, div[data-testid='job-listing']")
        for card in cards[:20]:
            title_el = card.select_one("h2 a, h3 a")
            company_el = card.select_one("span.company-name, a[data-testid='company-link']")
            location_el = card.select_one("span.location, span[data-testid='location']")

            if not title_el:
                continue

            results.append(SearchResult(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "",
                location=location_el.get_text(strip=True) if location_el else "",
                url=title_el.get("href", ""),
                source="xing",
                snippet=card.get_text(separator=" ", strip=True)[:200],
            ))
        return results

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _make_cache_key(query: str, location: str, source: str) -> str:
        """Generate a stable cache key from the search parameters."""
        raw = f"{query.lower().strip()}|{location.lower().strip()}|{source.lower()}"
        return hashlib.md5(raw.encode()).hexdigest()  # noqa: S324 — not security-sensitive

    @staticmethod
    def _deduplicate(results: List[SearchResult]) -> List[SearchResult]:
        """
        Remove duplicate results based on (title, company) pairs.

        Args:
            results: Raw list of SearchResult objects.

        Returns:
            Deduplicated list preserving first-occurrence order.
        """
        seen: set = set()
        unique: List[SearchResult] = []
        for r in results:
            key = (r.title.lower().strip(), r.company.lower().strip())
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "JobSearcher":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
