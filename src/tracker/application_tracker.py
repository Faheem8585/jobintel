"""
Application Tracker.

Business logic layer sitting between the skill interface and the database
manager. Handles:
  - Creating and updating applications with validation
  - Status transition rules (prevents invalid state changes)
  - Rich formatted output for display

The tracker is deliberately thin: validation lives in the Pydantic models,
persistence lives in DatabaseManager. This layer orchestrates the two.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from src.database.manager import DatabaseManager
from src.models.models import Application, ApplicationStatus

logger = logging.getLogger(__name__)

# Valid status transitions: a mapping of current status → allowed next statuses.
# Rejection and withdrawal can happen from any non-terminal state.
_TERMINAL_STATES = {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN, ApplicationStatus.ACCEPTED}

_TRANSITIONS: Dict[ApplicationStatus, List[ApplicationStatus]] = {
    ApplicationStatus.WISHLIST: [
        ApplicationStatus.APPLIED, ApplicationStatus.WITHDRAWN,
    ],
    ApplicationStatus.APPLIED: [
        ApplicationStatus.PHONE_SCREEN, ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    ],
    ApplicationStatus.PHONE_SCREEN: [
        ApplicationStatus.TECHNICAL, ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    ],
    ApplicationStatus.TECHNICAL: [
        ApplicationStatus.ONSITE, ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    ],
    ApplicationStatus.ONSITE: [
        ApplicationStatus.OFFER, ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    ],
    ApplicationStatus.OFFER: [
        ApplicationStatus.ACCEPTED, ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    ],
    ApplicationStatus.REJECTED: [],
    ApplicationStatus.WITHDRAWN: [],
    ApplicationStatus.ACCEPTED: [],
}


class ApplicationTracker:
    """High-level interface for managing job applications."""

    def __init__(self, db: DatabaseManager) -> None:
        """
        Initialise the tracker.

        Args:
            db: Initialised DatabaseManager instance.
        """
        self._db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(
        self,
        company: str,
        role: str,
        *,
        location: str = "",
        url: Optional[str] = None,
        status: str = "wishlist",
        applied_date: Optional[str] = None,
        deadline: Optional[str] = None,
        notes: str = "",
        contact: str = "",
        salary_min: Optional[int] = None,
        salary_max: Optional[int] = None,
        match_score: Optional[float] = None,
    ) -> Application:
        """
        Create and persist a new job application.

        Args:
            company:      Company name (required).
            role:         Job title (required).
            location:     City / country of the role.
            url:          Link to the job posting.
            status:       Initial status string (default: 'wishlist').
            applied_date: ISO-8601 date string (YYYY-MM-DD).
            deadline:     Application deadline as ISO-8601 date string.
            notes:        Free-form notes.
            contact:      Recruiter or contact name.
            salary_min:   Minimum salary expectation in the local currency.
            salary_max:   Maximum salary expectation.
            match_score:  Pre-computed match score (0.0–1.0).

        Returns:
            The saved Application model.
        """
        try:
            app_status = ApplicationStatus(status.lower())
        except ValueError:
            valid = [s.value for s in ApplicationStatus]
            raise ValueError(f"Invalid status '{status}'. Must be one of: {valid}")

        app = Application(
            company=company,
            role=role,
            location=location,
            url=url,
            status=app_status,
            applied_date=date.fromisoformat(applied_date) if applied_date else None,
            deadline=date.fromisoformat(deadline) if deadline else None,
            notes=notes,
            contact=contact,
            salary_min=salary_min,
            salary_max=salary_max,
            match_score=match_score,
        )
        return self._db.add_application(app)

    def update_status(self, app_id: str, new_status: str) -> Application:
        """
        Transition an application to a new status.

        Enforces the state machine defined in _TRANSITIONS so invalid
        jumps (e.g. Wishlist → Offer) are caught early.

        Args:
            app_id:     UUID of the application.
            new_status: Target status string.

        Returns:
            Updated Application.

        Raises:
            ValueError: If the application is not found or the transition is invalid.
        """
        app = self._db.get_application(app_id)
        if not app:
            raise ValueError(f"Application {app_id!r} not found.")

        try:
            target = ApplicationStatus(new_status.lower())
        except ValueError:
            valid = [s.value for s in ApplicationStatus]
            raise ValueError(f"Invalid status '{new_status}'. Must be one of: {valid}")

        allowed = _TRANSITIONS.get(app.status, [])
        if target not in allowed and target != app.status:
            raise ValueError(
                f"Cannot transition {app.status.value!r} → {target.value!r}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        updated = self._db.update_application(app_id, {"status": target})
        logger.info(
            "Application %s transitioned %s → %s", app_id, app.status.value, target.value
        )
        return updated  # type: ignore[return-value]

    def update_notes(self, app_id: str, notes: str) -> Application:
        """
        Append or overwrite notes on an application.

        Args:
            app_id: UUID of the application.
            notes:  New notes string (replaces existing).

        Returns:
            Updated Application.
        """
        app = self._get_or_raise(app_id)
        updated = self._db.update_application(app_id, {"notes": notes})
        return updated  # type: ignore[return-value]

    def update_fields(self, app_id: str, **fields: Any) -> Application:
        """
        Generic partial update — update any set of fields at once.

        Args:
            app_id:  UUID of the application.
            **fields: Field name → new value mappings.

        Returns:
            Updated Application.
        """
        self._get_or_raise(app_id)
        updated = self._db.update_application(app_id, dict(fields))
        return updated  # type: ignore[return-value]

    def delete(self, app_id: str) -> bool:
        """
        Delete an application record.

        Args:
            app_id: UUID of the application.

        Returns:
            True if deleted, False if not found.
        """
        return self._db.delete_application(app_id)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list(
        self,
        status: Optional[str] = None,
        company: Optional[str] = None,
        limit: int = 50,
    ) -> List[Application]:
        """
        List applications with optional filters.

        Args:
            status:  Filter by status string.
            company: Case-insensitive company name substring filter.
            limit:   Maximum number of results.

        Returns:
            List of Application models.
        """
        status_enum: Optional[ApplicationStatus] = None
        if status:
            try:
                status_enum = ApplicationStatus(status.lower())
            except ValueError:
                pass  # Invalid status → ignore filter rather than crash

        return self._db.list_applications(
            status=status_enum, company=company, limit=limit
        )

    def get(self, app_id: str) -> Optional[Application]:
        """
        Retrieve a single application by ID.

        Args:
            app_id: UUID of the application.

        Returns:
            Application model or None.
        """
        return self._db.get_application(app_id)

    def stats(self) -> Dict[str, int]:
        """
        Return application counts grouped by status.

        Returns:
            Dict of status → count.
        """
        return self._db.get_stats()

    def upcoming_deadlines(self, within_days: int = 3) -> List[Application]:
        """
        Return applications with deadlines approaching within *within_days*.

        Args:
            within_days: Look-ahead window in days.

        Returns:
            List of Application models sorted by deadline.
        """
        return self._db.get_upcoming_deadlines(within_days=within_days)

    def active_applications(self) -> List[Application]:
        """
        Return all applications not in a terminal state.

        Returns:
            List of in-progress applications.
        """
        all_apps = self._db.list_applications(limit=500)
        return [a for a in all_apps if a.status not in _TERMINAL_STATES]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_raise(self, app_id: str) -> Application:
        """
        Fetch an application or raise ValueError if not found.

        Args:
            app_id: UUID string.

        Returns:
            Application model.
        """
        app = self._db.get_application(app_id)
        if not app:
            raise ValueError(f"Application {app_id!r} not found.")
        return app
