"""
Tests for src/tracker/application_tracker.py.

Covers: add, update, delete, status transitions (valid and invalid),
        listing with filters, deadline queries, and stats.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.tracker.application_tracker import ApplicationTracker
from src.models.models import ApplicationStatus


@pytest.fixture
def tracker(db) -> ApplicationTracker:
    return ApplicationTracker(db)


class TestAdd:
    def test_add_minimal(self, tracker):
        app = tracker.add(company="Celonis", role="ML Engineer")
        assert app.id is not None
        assert app.company == "Celonis"
        assert app.status == ApplicationStatus.WISHLIST

    def test_add_with_all_fields(self, tracker):
        app = tracker.add(
            company="SAP",
            role="Data Scientist",
            location="Berlin",
            status="applied",
            applied_date="2026-03-01",
            deadline="2026-04-01",
            notes="Great role",
            contact="Bob",
            salary_min=70000,
            salary_max=90000,
            match_score=0.75,
        )
        assert app.status == ApplicationStatus.APPLIED
        assert app.applied_date == date(2026, 3, 1)
        assert app.salary_min == 70000
        assert app.match_score == pytest.approx(0.75)

    def test_add_invalid_status_raises(self, tracker):
        with pytest.raises(ValueError, match="Invalid status"):
            tracker.add(company="X", role="Y", status="flying")

    def test_add_empty_company_raises(self, tracker):
        with pytest.raises(ValueError):
            tracker.add(company="", role="Engineer")

    def test_add_empty_role_raises(self, tracker):
        with pytest.raises(ValueError):
            tracker.add(company="Apple", role="")


class TestUpdateStatus:
    def test_valid_transition(self, tracker):
        app = tracker.add(company="BMW", role="Dev", status="applied")
        updated = tracker.update_status(app.id, "phone_screen")
        assert updated.status == ApplicationStatus.PHONE_SCREEN

    def test_invalid_transition_raises(self, tracker):
        app = tracker.add(company="VW", role="Eng", status="wishlist")
        with pytest.raises(ValueError, match="Cannot transition"):
            tracker.update_status(app.id, "offer")

    def test_update_to_same_status_ok(self, tracker):
        """Updating to the same status should not raise."""
        app = tracker.add(company="BMW", role="Dev", status="applied")
        updated = tracker.update_status(app.id, "applied")
        assert updated.status == ApplicationStatus.APPLIED

    def test_rejection_from_applied(self, tracker):
        app = tracker.add(company="Siemens", role="Eng", status="applied")
        updated = tracker.update_status(app.id, "rejected")
        assert updated.status == ApplicationStatus.REJECTED

    def test_update_nonexistent_raises(self, tracker):
        with pytest.raises(ValueError, match="not found"):
            tracker.update_status("ghost-id", "applied")

    def test_invalid_status_value_raises(self, tracker):
        app = tracker.add(company="Audi", role="Dev")
        with pytest.raises(ValueError, match="Invalid status"):
            tracker.update_status(app.id, "flying")

    def test_full_pipeline_happy_path(self, tracker):
        """Walk an application through the full acceptance pipeline."""
        app = tracker.add(company="Google", role="AI Engineer", status="applied")
        app = tracker.update_status(app.id, "phone_screen")
        app = tracker.update_status(app.id, "technical")
        app = tracker.update_status(app.id, "onsite")
        app = tracker.update_status(app.id, "offer")
        app = tracker.update_status(app.id, "accepted")
        assert app.status == ApplicationStatus.ACCEPTED


class TestUpdateNotes:
    def test_update_notes(self, tracker):
        app = tracker.add(company="X", role="Y")
        updated = tracker.update_notes(app.id, "Very interesting company.")
        assert updated.notes == "Very interesting company."

    def test_update_notes_nonexistent_raises(self, tracker):
        with pytest.raises(ValueError):
            tracker.update_notes("ghost", "notes")


class TestDelete:
    def test_delete_existing(self, tracker):
        app = tracker.add(company="Deleted Corp", role="Dev")
        result = tracker.delete(app.id)
        assert result is True
        assert tracker.get(app.id) is None

    def test_delete_nonexistent_returns_false(self, tracker):
        assert tracker.delete("ghost-id") is False


class TestList:
    def _seed(self, tracker):
        a1 = tracker.add(company="Alpha", role="Eng", status="applied")
        a2 = tracker.add(company="Beta", role="Dev", status="rejected")
        a3 = tracker.add(company="Alpha", role="Sci", status="phone_screen")
        return a1, a2, a3

    def test_list_all(self, tracker):
        self._seed(tracker)
        apps = tracker.list()
        assert len(apps) == 3

    def test_filter_by_status(self, tracker):
        self._seed(tracker)
        apps = tracker.list(status="applied")
        assert len(apps) == 1
        assert apps[0].status == ApplicationStatus.APPLIED

    def test_filter_by_company(self, tracker):
        self._seed(tracker)
        apps = tracker.list(company="alpha")
        assert len(apps) == 2
        assert all(a.company == "Alpha" for a in apps)

    def test_invalid_status_filter_ignored(self, tracker):
        """An invalid status filter should return all records (graceful degradation)."""
        self._seed(tracker)
        apps = tracker.list(status="flying_spaghetti_monster")
        assert len(apps) == 3


class TestUpcomingDeadlines:
    def test_upcoming_deadlines_returned(self, tracker):
        tomorrow = date.today() + timedelta(days=1)
        app = tracker.add(
            company="Siemens",
            role="Dev",
            status="applied",
            deadline=tomorrow.isoformat(),
        )
        deadlines = tracker.upcoming_deadlines(within_days=3)
        assert any(a.id == app.id for a in deadlines)

    def test_no_deadlines_when_empty(self, tracker):
        tracker.add(company="X", role="Y")
        deadlines = tracker.upcoming_deadlines()
        assert deadlines == []


class TestStats:
    def test_stats_aggregation(self, tracker):
        tracker.add(company="A", role="R1", status="applied")
        tracker.add(company="B", role="R2", status="applied")
        tracker.add(company="C", role="R3", status="rejected")
        stats = tracker.stats()
        assert stats.get("applied", 0) == 2
        assert stats.get("rejected", 0) == 1


class TestActiveApplications:
    def test_active_excludes_terminal(self, tracker):
        tracker.add(company="A", role="R1", status="applied")
        tracker.add(company="B", role="R2", status="rejected")
        tracker.add(company="C", role="R3", status="accepted")
        active = tracker.active_applications()
        statuses = [a.status for a in active]
        assert ApplicationStatus.REJECTED not in statuses
        assert ApplicationStatus.ACCEPTED not in statuses
        assert len(active) == 1
