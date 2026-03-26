"""
Tests for src/digest/daily_digest.py.

Covers: digest generation, formatting, stats, deadline detection,
        and recent updates filtering.
"""

from __future__ import annotations

from datetime import datetime, timedelta, date

import pytest
from freezegun import freeze_time

from src.database.manager import DatabaseManager
from src.digest.daily_digest import DigestGenerator
from src.models.models import Application, ApplicationStatus


@pytest.fixture
def digest_gen(db: DatabaseManager, config: dict) -> DigestGenerator:
    return DigestGenerator(db, config)


def _add_app(db: DatabaseManager, **kwargs) -> Application:
    """Helper to add a minimal application directly to the DB."""
    app = Application(
        company=kwargs.get("company", "TestCo"),
        role=kwargs.get("role", "Engineer"),
        status=kwargs.get("status", ApplicationStatus.APPLIED),
        deadline=kwargs.get("deadline"),
    )
    return db.add_application(app)


class TestGenerate:
    def test_returns_digest_report(self, digest_gen):
        report = digest_gen.generate()
        assert report.generated_at is not None
        assert isinstance(report.stats, dict)
        assert isinstance(report.summary, str)

    def test_empty_db_gives_zero_stats(self, digest_gen):
        report = digest_gen.generate()
        assert sum(report.stats.values()) == 0
        assert report.pending_applications == []

    def test_pending_applications_populated(self, digest_gen, db):
        _add_app(db, status=ApplicationStatus.APPLIED)
        _add_app(db, status=ApplicationStatus.PHONE_SCREEN)
        report = digest_gen.generate()
        assert len(report.pending_applications) == 2

    def test_terminal_states_excluded_from_pending(self, digest_gen, db):
        _add_app(db, status=ApplicationStatus.REJECTED)
        _add_app(db, status=ApplicationStatus.ACCEPTED)
        _add_app(db, status=ApplicationStatus.APPLIED)
        report = digest_gen.generate()
        # Only the APPLIED one should be in pending
        assert len(report.pending_applications) == 1
        assert report.pending_applications[0].status == ApplicationStatus.APPLIED

    def test_upcoming_deadlines_detected(self, digest_gen, db):
        tomorrow = date.today() + timedelta(days=1)
        _add_app(db, status=ApplicationStatus.APPLIED, deadline=tomorrow)
        report = digest_gen.generate()
        assert len(report.upcoming_deadlines) >= 1

    def test_stats_keys_match_statuses(self, digest_gen, db):
        _add_app(db, status=ApplicationStatus.APPLIED)
        _add_app(db, status=ApplicationStatus.REJECTED)
        report = digest_gen.generate()
        assert "applied" in report.stats
        assert "rejected" in report.stats

    def test_digest_persisted_to_db(self, digest_gen, db):
        """Generating a digest should persist it in the digest_history table."""
        digest_gen.generate()
        row = db._execute(
            "SELECT COUNT(*) as cnt FROM digest_history", fetch="one"
        )
        assert row["cnt"] == 1


class TestRecentUpdates:
    @freeze_time("2026-03-26 12:00:00")
    def test_recent_updates_within_window(self, db, config):
        """Applications updated within the lookback window should appear in recent_updates."""
        gen = DigestGenerator(db, config)
        app = Application(company="X", role="Y", status=ApplicationStatus.APPLIED)
        # updated_at defaults to utcnow() which is frozen to 2026-03-26
        db.add_application(app)
        report = gen.generate()
        assert any(a.id == app.id for a in report.recent_updates)

    @freeze_time("2026-03-26 12:00:00")
    def test_old_updates_excluded(self, db, config):
        """Applications updated more than lookback_days ago should not appear."""
        gen = DigestGenerator(db, config)

        # Manually insert an old application
        old_time = (datetime(2026, 3, 26) - timedelta(days=30)).isoformat()
        db._execute(
            """
            INSERT INTO applications
                (id, company, role, location, url, status, applied_date, deadline,
                 notes, contact, salary_min, salary_max, match_score, created_at, updated_at)
            VALUES ('old-id', 'OldCo', 'OldRole', '', NULL, 'applied',
                    NULL, NULL, '', '', NULL, NULL, NULL, ?, ?)
            """,
            (old_time, old_time),
        )
        report = gen.generate()
        assert not any(a.id == "old-id" for a in report.recent_updates)


class TestFormatText:
    def test_format_returns_string(self, digest_gen):
        report = digest_gen.generate()
        text = digest_gen.format_text(report)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_format_contains_header(self, digest_gen):
        report = digest_gen.generate()
        text = digest_gen.format_text(report)
        assert "JobIntel Daily Digest" in text

    def test_format_contains_stats_section(self, digest_gen, db):
        _add_app(db)
        report = digest_gen.generate()
        text = digest_gen.format_text(report)
        assert "Stats" in text or "stats" in text.lower()

    def test_format_contains_deadline_section_when_present(self, digest_gen, db):
        tomorrow = date.today() + timedelta(days=1)
        _add_app(db, deadline=tomorrow)
        report = digest_gen.generate()
        text = digest_gen.format_text(report)
        assert "Deadline" in text or "deadline" in text.lower()

    def test_format_shows_pending_applications(self, digest_gen, db):
        _add_app(db, company="Celonis", role="ML Engineer")
        report = digest_gen.generate()
        text = digest_gen.format_text(report)
        assert "Celonis" in text


class TestSummary:
    def test_summary_mentions_total(self, digest_gen, db):
        _add_app(db)
        _add_app(db)
        report = digest_gen.generate()
        assert "2" in report.summary

    def test_summary_mentions_offer_when_present(self, digest_gen, db):
        _add_app(db, status=ApplicationStatus.OFFER)
        report = digest_gen.generate()
        assert "offer" in report.summary.lower()

    def test_summary_mentions_deadline_when_upcoming(self, digest_gen, db):
        tomorrow = date.today() + timedelta(days=1)
        _add_app(db, deadline=tomorrow)
        report = digest_gen.generate()
        assert "deadline" in report.summary.lower()
