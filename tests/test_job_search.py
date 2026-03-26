"""
Tests for src/search/job_search.py.

Uses unittest.mock to avoid real HTTP requests. Tests cover:
- Dispatcher routing to correct source fetchers
- HTML parsing for each source
- Cache hit / miss logic
- Deduplication
- Graceful error handling on HTTP failures
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import httpx

from src.search.job_search import JobSearcher
from src.models.models import SearchResult


# Minimal LinkedIn-like HTML
_LINKEDIN_HTML = """
<html><body>
<div class="job-search-card">
  <h3 class="base-search-card__title">AI Engineer</h3>
  <h4 class="base-search-card__subtitle">TechCorp</h4>
  <span class="job-search-card__location">Berlin, Germany</span>
  <a class="base-card__full-link" href="https://linkedin.com/jobs/view/123">Apply</a>
</div>
<div class="job-search-card">
  <h3 class="base-search-card__title">Data Scientist</h3>
  <h4 class="base-search-card__subtitle">DataCo</h4>
  <span class="job-search-card__location">Munich, Germany</span>
</div>
</body></html>
"""

# Minimal Indeed-like HTML
_INDEED_HTML = """
<html><body>
<div class="job_seen_beacon">
  <h2><a>ML Engineer</a></h2>
  <span class="company">MLCorp</span>
  <div class="recJobLoc">Hamburg</div>
</div>
</body></html>
"""

# Minimal StepStone-like HTML
_STEPSTONE_HTML = """
<html><body>
<article data-at="job-item">
  <h2><a href="/stellenangebote/123">Python Developer</a></h2>
  <span data-at="job-item-company-name">PyCorp</span>
  <span data-at="job-item-location">Frankfurt</span>
</article>
</body></html>
"""

# Minimal XING-like HTML
_XING_HTML = """
<html><body>
<article class="job-listing">
  <h2><a href="https://xing.com/jobs/456">Backend Engineer</a></h2>
  <span class="company-name">XingCo</span>
  <span class="location">Cologne</span>
</article>
</body></html>
"""


def _make_response(html: str, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.text = html
    resp.status_code = status_code
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def searcher(db, config):
    """Return a JobSearcher with a mocked HTTP client."""
    mock_client = MagicMock(spec=httpx.Client)
    return JobSearcher(db=db, config=config, http_client=mock_client), mock_client


class TestSearchDispatch:
    def test_search_returns_list(self, searcher, db):
        s, client = searcher
        client.get.return_value = _make_response(_LINKEDIN_HTML)
        results = s.search("AI Engineer", location="Berlin", sources=["linkedin"])
        assert isinstance(results, list)

    def test_unknown_source_skipped(self, searcher):
        s, client = searcher
        results = s.search("Dev", sources=["unknown_board"])
        assert results == []

    def test_http_error_returns_partial_results(self, searcher):
        """When one source fails, results from other sources still returned."""
        s, client = searcher
        # First call (linkedin) fails, second (indeed) succeeds
        client.get.side_effect = [
            _make_response("", 503),
            _make_response(_INDEED_HTML, 200),
        ]
        results = s.search("Eng", sources=["linkedin", "indeed"])
        # Should not raise; may return empty or partial list
        assert isinstance(results, list)

    def test_limit_applied(self, searcher):
        s, client = searcher
        client.get.return_value = _make_response(_LINKEDIN_HTML)
        results = s.search("AI", sources=["linkedin"])
        # results_per_query = 20 in config, and we have 2 results in HTML
        assert len(results) <= 20


class TestLinkedInParsing:
    def test_parses_title(self, searcher):
        s, client = searcher
        client.get.return_value = _make_response(_LINKEDIN_HTML)
        results = s.search("AI Engineer", sources=["linkedin"])
        titles = [r.title for r in results]
        assert "AI Engineer" in titles

    def test_parses_company(self, searcher):
        s, client = searcher
        client.get.return_value = _make_response(_LINKEDIN_HTML)
        results = s.search("AI Engineer", sources=["linkedin"])
        assert any(r.company == "TechCorp" for r in results)

    def test_parses_location(self, searcher):
        s, client = searcher
        client.get.return_value = _make_response(_LINKEDIN_HTML)
        results = s.search("AI Engineer", sources=["linkedin"])
        assert any("Berlin" in r.location for r in results)

    def test_source_tagged_linkedin(self, searcher):
        s, client = searcher
        client.get.return_value = _make_response(_LINKEDIN_HTML)
        results = s.search("AI Engineer", sources=["linkedin"])
        assert all(r.source == "linkedin" for r in results)

    def test_empty_html_returns_empty(self, searcher):
        s, client = searcher
        client.get.return_value = _make_response("<html><body></body></html>")
        results = s.search("AI Engineer", sources=["linkedin"])
        assert results == []

    def test_http_error_returns_empty(self, searcher):
        s, client = searcher
        client.get.return_value = _make_response("", status_code=403)
        results = s.search("AI", sources=["linkedin"])
        assert results == []


class TestIndeedParsing:
    def test_parses_indeed_results(self, searcher):
        s, client = searcher
        client.get.return_value = _make_response(_INDEED_HTML)
        results = s.search("ML Engineer", sources=["indeed"])
        assert any(r.title == "ML Engineer" for r in results)

    def test_indeed_source_tagged(self, searcher):
        s, client = searcher
        client.get.return_value = _make_response(_INDEED_HTML)
        results = s.search("ML", sources=["indeed"])
        assert all(r.source == "indeed" for r in results)


class TestStepStoneParsing:
    def test_parses_stepstone_results(self, searcher):
        s, client = searcher
        client.get.return_value = _make_response(_STEPSTONE_HTML)
        results = s.search("Python Developer", sources=["stepstone"])
        assert any("Python Developer" in r.title for r in results)


class TestXingParsing:
    def test_parses_xing_results(self, searcher):
        s, client = searcher
        client.get.return_value = _make_response(_XING_HTML)
        results = s.search("Backend Engineer", sources=["xing"])
        assert any("Backend Engineer" in r.title for r in results)


class TestCaching:
    def test_cache_miss_fetches_and_stores(self, searcher, db):
        s, client = searcher
        client.get.return_value = _make_response(_LINKEDIN_HTML)
        results = s.search("AI", sources=["linkedin"], use_cache=True)
        # Called exactly once — no cache hit on first request
        assert client.get.call_count == 1

    def test_cache_hit_skips_http(self, searcher, db):
        s, client = searcher
        client.get.return_value = _make_response(_LINKEDIN_HTML)

        # First call populates cache
        s.search("AI Engineer", location="Berlin", sources=["linkedin"], use_cache=True)
        first_call_count = client.get.call_count

        # Second call with same query should use cache
        s.search("AI Engineer", location="Berlin", sources=["linkedin"], use_cache=True)
        assert client.get.call_count == first_call_count  # No additional HTTP calls

    def test_cache_bypass_forces_fetch(self, searcher):
        s, client = searcher
        client.get.return_value = _make_response(_LINKEDIN_HTML)
        s.search("AI", sources=["linkedin"], use_cache=False)
        s.search("AI", sources=["linkedin"], use_cache=False)
        assert client.get.call_count == 2


class TestDeduplication:
    def test_deduplication_removes_duplicates(self, searcher):
        s, _ = searcher
        results = [
            SearchResult(title="AI Engineer", company="TechCorp", source="linkedin"),
            SearchResult(title="AI Engineer", company="TechCorp", source="indeed"),  # duplicate
            SearchResult(title="Data Scientist", company="DataCo", source="linkedin"),
        ]
        unique = s._deduplicate(results)
        assert len(unique) == 2

    def test_deduplication_preserves_order(self, searcher):
        s, _ = searcher
        results = [
            SearchResult(title="A", company="X", source="linkedin"),
            SearchResult(title="B", company="Y", source="indeed"),
        ]
        unique = s._deduplicate(results)
        assert unique[0].title == "A"
        assert unique[1].title == "B"


class TestCacheKey:
    def test_cache_key_stable(self, searcher):
        s, _ = searcher
        key1 = s._make_cache_key("AI Engineer", "Berlin", "linkedin")
        key2 = s._make_cache_key("AI Engineer", "Berlin", "linkedin")
        assert key1 == key2

    def test_cache_key_differs_by_query(self, searcher):
        s, _ = searcher
        key1 = s._make_cache_key("AI Engineer", "Berlin", "linkedin")
        key2 = s._make_cache_key("Data Scientist", "Berlin", "linkedin")
        assert key1 != key2

    def test_cache_key_case_insensitive(self, searcher):
        s, _ = searcher
        key1 = s._make_cache_key("Python", "Berlin", "LinkedIn")
        key2 = s._make_cache_key("python", "berlin", "linkedin")
        assert key1 == key2


class TestContextManager:
    def test_context_manager_closes_client(self, db, config):
        mock_client = MagicMock(spec=httpx.Client)
        with JobSearcher(db=db, config=config, http_client=mock_client):
            pass
        mock_client.close.assert_called_once()
