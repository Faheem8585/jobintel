"""
Tests for src/database/manager.py.

Covers: CRUD for applications, candidate profile upsert,
        search caching, stats, and upcoming deadlines.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.database.manager import DatabaseManager
from src.models.models import Application, ApplicationStatus, CandidateProfile, Skill, SkillCategory


# ---------------------------------------------------------------------------
# Application CRUD
# ---------------------------------------------------------------------------


class TestAddApplication:
    def test_add_returns_application(self, db: DatabaseManager):
        app = Application(company="Celonis", role="ML Engineer")
        saved = db.add_application(app)
        assert saved.id == app.id
        assert saved.company == "Celonis"

    def test_added_application_is_retrievable(self, db: DatabaseManager):
        app = Application(company="Accenture", role="Data Scientist")
        db.add_application(app)
        retrieved = db.get_application(app.id)
        assert retrieved is not None
        assert retrieved.company == "Accenture"
        assert retrieved.role == "Data Scientist"

    def test_add_preserves_all_fields(self, db: DatabaseManager):
        app = Application(
            company="NVIDIA",
            role="AI Research Engineer",
            location="Munich",
            status=ApplicationStatus.APPLIED,
            applied_date=date(2026, 3, 1),
            deadline=date(2026, 4, 1),
            notes="Promising role",
            contact="Alice",
            salary_min=90000,
            salary_max=130000,
            match_score=0.82,
        )
        db.add_application(app)
        got = db.get_application(app.id)
        assert got.location == "Munich"
        assert got.status == ApplicationStatus.APPLIED
        assert got.applied_date == date(2026, 3, 1)
        assert got.deadline == date(2026, 4, 1)
        assert got.salary_min == 90000
        assert got.match_score == pytest.approx(0.82)


class TestGetApplication:
    def test_get_nonexistent_returns_none(self, db: DatabaseManager):
        result = db.get_application("nonexistent-id")
        assert result is None


class TestUpdateApplication:
    def test_update_status(self, db: DatabaseManager):
        app = Application(company="SAP", role="Engineer")
        db.add_application(app)
        updated = db.update_application(app.id, {"status": "applied"})
        assert updated.status == ApplicationStatus.APPLIED

    def test_update_notes(self, db: DatabaseManager):
        app = Application(company="Bosch", role="Dev")
        db.add_application(app)
        updated = db.update_application(app.id, {"notes": "great culture"})
        assert updated.notes == "great culture"

    def test_update_nonexistent_returns_none(self, db: DatabaseManager):
        result = db.update_application("ghost-id", {"notes": "test"})
        assert result is None


class TestDeleteApplication:
    def test_delete_existing(self, db: DatabaseManager):
        app = Application(company="BMW", role="Data Engineer")
        db.add_application(app)
        deleted = db.delete_application(app.id)
        assert deleted is True
        assert db.get_application(app.id) is None

    def test_delete_nonexistent_returns_false(self, db: DatabaseManager):
        assert db.delete_application("ghost") is False


class TestListApplications:
    def _add_many(self, db: DatabaseManager):
        apps = [
            Application(company="Alpha", role="AI Eng", status=ApplicationStatus.APPLIED),
            Application(company="Alpha", role="Data Sci", status=ApplicationStatus.PHONE_SCREEN),
            Application(company="Beta", role="ML Eng", status=ApplicationStatus.APPLIED),
            Application(company="Gamma", role="Backend Dev", status=ApplicationStatus.REJECTED),
        ]
        for a in apps:
            db.add_application(a)
        return apps

    def test_list_all(self, db: DatabaseManager):
        self._add_many(db)
        result = db.list_applications(limit=100)
        assert len(result) == 4

    def test_filter_by_status(self, db: DatabaseManager):
        self._add_many(db)
        result = db.list_applications(status=ApplicationStatus.APPLIED)
        assert len(result) == 2
        assert all(a.status == ApplicationStatus.APPLIED for a in result)

    def test_filter_by_company(self, db: DatabaseManager):
        self._add_many(db)
        result = db.list_applications(company="alpha")
        assert len(result) == 2
        assert all(a.company == "Alpha" for a in result)

    def test_limit(self, db: DatabaseManager):
        self._add_many(db)
        result = db.list_applications(limit=2)
        assert len(result) == 2


class TestUpcomingDeadlines:
    def test_returns_apps_within_window(self, db: DatabaseManager):
        tomorrow = date.today() + timedelta(days=1)
        app = Application(
            company="Airbus",
            role="CV Engineer",
            deadline=tomorrow,
            status=ApplicationStatus.APPLIED,
        )
        db.add_application(app)
        result = db.get_upcoming_deadlines(within_days=3)
        assert any(a.id == app.id for a in result)

    def test_excludes_terminal_status(self, db: DatabaseManager):
        tomorrow = date.today() + timedelta(days=1)
        app = Application(
            company="Airbus",
            role="CV Engineer",
            deadline=tomorrow,
            status=ApplicationStatus.REJECTED,
        )
        db.add_application(app)
        result = db.get_upcoming_deadlines(within_days=3)
        assert not any(a.id == app.id for a in result)

    def test_excludes_far_future_deadlines(self, db: DatabaseManager):
        far = date.today() + timedelta(days=30)
        app = Application(
            company="SomeCompany",
            role="Dev",
            deadline=far,
            status=ApplicationStatus.APPLIED,
        )
        db.add_application(app)
        result = db.get_upcoming_deadlines(within_days=3)
        assert not any(a.id == app.id for a in result)


class TestStats:
    def test_stats_counts_by_status(self, db: DatabaseManager):
        for _ in range(3):
            db.add_application(Application(company="X", role="Y", status=ApplicationStatus.APPLIED))
        db.add_application(Application(company="X", role="Z", status=ApplicationStatus.REJECTED))
        stats = db.get_stats()
        assert stats["applied"] == 3
        assert stats["rejected"] == 1


# ---------------------------------------------------------------------------
# Candidate profile
# ---------------------------------------------------------------------------


class TestCandidateProfile:
    def test_save_and_load(self, db: DatabaseManager, candidate_profile: CandidateProfile):
        db.save_candidate_profile(candidate_profile)
        loaded = db.load_candidate_profile()
        assert loaded is not None
        assert loaded.name == candidate_profile.name
        assert len(loaded.skills) == len(candidate_profile.skills)

    def test_load_when_empty_returns_none(self, db: DatabaseManager):
        assert db.load_candidate_profile() is None

    def test_upsert_replaces_existing(self, db: DatabaseManager, candidate_profile: CandidateProfile):
        db.save_candidate_profile(candidate_profile)
        updated = candidate_profile.model_copy(update={"name": "Updated Name"})
        db.save_candidate_profile(updated)
        loaded = db.load_candidate_profile()
        assert loaded.name == "Updated Name"
