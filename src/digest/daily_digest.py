"""
Daily Digest Generator.

Produces a structured summary of the user's job search activity:
  - Pending (active) applications
  - Upcoming deadlines within the configured window
  - Applications updated in the last N days
  - Overall stats

The report is both structured (DigestReport model) and text-formatted
for display to the user.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from src.database.manager import DatabaseManager
from src.models.models import Application, ApplicationStatus, DigestReport

logger = logging.getLogger(__name__)

_TERMINAL_STATES = {
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
    ApplicationStatus.ACCEPTED,
}

_STATUS_EMOJI: Dict[str, str] = {
    "wishlist": "📋",
    "applied": "📤",
    "phone_screen": "📞",
    "technical": "💻",
    "onsite": "🏢",
    "offer": "🎉",
    "rejected": "❌",
    "withdrawn": "↩️",
    "accepted": "✅",
}


class DigestGenerator:
    """Generate the daily digest report from stored application data."""

    def __init__(self, db: DatabaseManager, config: Dict[str, Any]) -> None:
        """
        Initialise the digest generator.

        Args:
            db:     Initialised DatabaseManager.
            config: Parsed config.yaml dict.
        """
        self._db = db
        self._cfg = config.get("digest", {})
        self._lookback_days: int = self._cfg.get("lookback_days", 7)
        self._deadline_days: int = self._cfg.get("upcoming_deadline_days", 3)

    def generate(self) -> DigestReport:
        """
        Build the complete daily digest.

        Returns:
            DigestReport with all fields populated.
        """
        all_apps = self._db.list_applications(limit=500)
        now = datetime.utcnow()

        pending = [a for a in all_apps if a.status not in _TERMINAL_STATES]
        upcoming = self._db.get_upcoming_deadlines(within_days=self._deadline_days)
        recent_updates = self._filter_recent(all_apps, now, self._lookback_days)
        stats = self._build_stats(all_apps)
        summary = self._build_summary(pending, upcoming, recent_updates, stats, now)

        report = DigestReport(
            generated_at=now,
            pending_applications=pending,
            upcoming_deadlines=upcoming,
            recent_updates=recent_updates,
            stats=stats,
            summary=summary,
        )

        # Persist for audit trail
        self._db.save_digest(report.model_dump_json())
        logger.info("Digest generated: %d pending, %d deadlines soon", len(pending), len(upcoming))
        return report

    def format_text(self, report: DigestReport) -> str:
        """
        Render a DigestReport as a rich plain-text string suitable for terminal display.

        Args:
            report: Generated DigestReport.

        Returns:
            Multi-line formatted string.
        """
        lines: List[str] = [
            "=" * 60,
            f"  JobIntel Daily Digest — {report.generated_at.strftime('%A, %d %B %Y')}",
            "=" * 60,
            "",
        ]

        # Stats bar
        lines.append("📊  Overall Stats")
        lines.append("-" * 40)
        total = sum(report.stats.values())
        lines.append(f"  Total applications: {total}")
        for status, count in sorted(report.stats.items()):
            emoji = _STATUS_EMOJI.get(status, "•")
            lines.append(f"  {emoji}  {status.replace('_', ' ').title()}: {count}")
        lines.append("")

        # Upcoming deadlines
        if report.upcoming_deadlines:
            lines.append("⏰  Upcoming Deadlines")
            lines.append("-" * 40)
            for app in report.upcoming_deadlines:
                deadline_str = app.deadline.isoformat() if app.deadline else "?"
                lines.append(f"  • {app.company} — {app.role} (deadline: {deadline_str})")
            lines.append("")

        # Active / pending applications
        if report.pending_applications:
            lines.append(f"🔄  Active Applications ({len(report.pending_applications)})")
            lines.append("-" * 40)
            for app in report.pending_applications[:15]:  # Cap display at 15
                emoji = _STATUS_EMOJI.get(app.status.value, "•")
                lines.append(f"  {emoji}  {app.company} — {app.role} [{app.status.value}]")
            if len(report.pending_applications) > 15:
                lines.append(f"  ... and {len(report.pending_applications) - 15} more.")
            lines.append("")

        # Recent updates
        if report.recent_updates:
            lines.append(f"📝  Updated in Last {self._lookback_days} Days ({len(report.recent_updates)})")
            lines.append("-" * 40)
            for app in report.recent_updates[:10]:
                updated = app.updated_at.strftime("%d %b") if app.updated_at else "?"
                lines.append(f"  • [{updated}] {app.company} — {app.role} → {app.status.value}")
            lines.append("")

        lines.append(report.summary)
        lines.append("=" * 60)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_recent(
        apps: List[Application], now: datetime, days: int
    ) -> List[Application]:
        """Return applications updated within the last *days* days."""
        cutoff = now - timedelta(days=days)
        return [a for a in apps if a.updated_at and a.updated_at >= cutoff]

    @staticmethod
    def _build_stats(apps: List[Application]) -> Dict[str, int]:
        """Aggregate application counts by status."""
        stats: Dict[str, int] = {}
        for app in apps:
            key = app.status.value
            stats[key] = stats.get(key, 0) + 1
        return stats

    @staticmethod
    def _build_summary(
        pending: List[Application],
        upcoming: List[Application],
        recent: List[Application],
        stats: Dict[str, int],
        now: datetime,
    ) -> str:
        """Build the digest summary sentence."""
        total = sum(stats.values())
        parts = [f"You have {total} total application(s), {len(pending)} active."]
        if upcoming:
            parts.append(f"{len(upcoming)} deadline(s) approaching soon — act now!")
        if recent:
            parts.append(f"{len(recent)} application(s) updated in the last week.")
        offers = stats.get("offer", 0)
        if offers:
            parts.append(f"Congratulations — {offers} offer(s) received!")
        return " ".join(parts)
