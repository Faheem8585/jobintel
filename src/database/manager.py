"""
SQLite database manager for JobIntel.

Design principles:
- All SQL is parameterised — no string interpolation (prevents SQL injection).
- Connection is kept open for the lifetime of the manager instance; callers
  should use it as a context manager or call .close() explicitly.
- Thread safety: SQLite's check_same_thread=False is set and all writes
  are serialised through a threading.Lock so the skill can safely serve
  concurrent tool calls from a single process.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models.models import Application, ApplicationStatus, CandidateProfile

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class DatabaseManager:
    """Thread-safe SQLite manager providing CRUD for all JobIntel entities."""

    def __init__(self, db_path: str) -> None:
        """
        Initialise the database, creating the file and schema if absent.

        Args:
            db_path: Filesystem path to the SQLite database file.
        """
        self._db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row
        self._apply_schema()
        logger.info("DatabaseManager initialised at %s", db_path)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _apply_schema(self) -> None:
        """Execute the schema SQL, creating tables if they do not exist."""
        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(schema_sql)
            self._conn.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute(
        self,
        sql: str,
        params: tuple = (),
        *,
        fetch: str = "none",
    ) -> Any:
        """
        Execute a parameterised SQL statement under the write lock.

        Args:
            sql:    Parameterised SQL string.
            params: Tuple of bind parameters.
            fetch:  One of 'none', 'one', 'all'.

        Returns:
            None, a single Row, or a list of Rows depending on *fetch*.
        """
        with self._lock:
            cursor = self._conn.execute(sql, params)
            if fetch == "one":
                return cursor.fetchone()
            if fetch == "all":
                return cursor.fetchall()
            self._conn.commit()
            return cursor.lastrowid

    @staticmethod
    def _now() -> str:
        """Return the current UTC time as an ISO-8601 string."""
        return datetime.utcnow().isoformat()

    @staticmethod
    def _row_to_application(row: sqlite3.Row) -> Application:
        """Deserialise a DB row into an Application model."""
        d = dict(row)
        # Convert ISO strings back to Python date objects
        for field in ("applied_date", "deadline"):
            if d.get(field):
                d[field] = date.fromisoformat(d[field])
        for field in ("created_at", "updated_at"):
            if d.get(field):
                d[field] = datetime.fromisoformat(d[field])
        return Application(**d)

    # ------------------------------------------------------------------
    # Application CRUD
    # ------------------------------------------------------------------

    def add_application(self, app: Application) -> Application:
        """
        Insert a new application record.

        Args:
            app: Validated Application model.

        Returns:
            The same application (id unchanged).

        Raises:
            ValueError: If an application with this id already exists.
        """
        now = self._now()
        app.created_at = datetime.fromisoformat(now)
        app.updated_at = datetime.fromisoformat(now)

        self._execute(
            """
            INSERT INTO applications
                (id, company, role, location, url, status, applied_date, deadline,
                 notes, contact, salary_min, salary_max, match_score, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                app.id,
                app.company,
                app.role,
                app.location,
                app.url,
                app.status.value,
                app.applied_date.isoformat() if app.applied_date else None,
                app.deadline.isoformat() if app.deadline else None,
                app.notes,
                app.contact,
                app.salary_min,
                app.salary_max,
                app.match_score,
                now,
                now,
            ),
        )
        logger.info("Added application %s (%s @ %s)", app.id, app.role, app.company)
        return app

    def get_application(self, app_id: str) -> Optional[Application]:
        """
        Retrieve a single application by primary key.

        Args:
            app_id: UUID string of the application.

        Returns:
            Application model or None if not found.
        """
        row = self._execute(
            "SELECT * FROM applications WHERE id = ?", (app_id,), fetch="one"
        )
        return self._row_to_application(row) if row else None

    def update_application(self, app_id: str, updates: Dict[str, Any]) -> Optional[Application]:
        """
        Partially update an application record.

        Only the keys present in *updates* are modified. The updated_at
        timestamp is always refreshed.

        Args:
            app_id:  UUID of the application to update.
            updates: Dict of field → new value.

        Returns:
            Updated Application model, or None if id not found.
        """
        # Normalise status enum to string
        if "status" in updates and isinstance(updates["status"], ApplicationStatus):
            updates["status"] = updates["status"].value
        if "applied_date" in updates and isinstance(updates["applied_date"], date):
            updates["applied_date"] = updates["applied_date"].isoformat()
        if "deadline" in updates and isinstance(updates["deadline"], date):
            updates["deadline"] = updates["deadline"].isoformat()

        now = self._now()
        updates["updated_at"] = now

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [app_id]

        self._execute(
            f"UPDATE applications SET {set_clause} WHERE id = ?",  # noqa: S608
            tuple(values),
        )
        return self.get_application(app_id)

    def delete_application(self, app_id: str) -> bool:
        """
        Delete an application record.

        Args:
            app_id: UUID of the application.

        Returns:
            True if a row was deleted, False if not found.
        """
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM applications WHERE id = ?", (app_id,)
            )
            self._conn.commit()
            deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Deleted application %s", app_id)
        return deleted

    def list_applications(
        self,
        status: Optional[ApplicationStatus] = None,
        company: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Application]:
        """
        Query applications with optional filters.

        Args:
            status:  Filter by ApplicationStatus.
            company: Filter by company name (case-insensitive substring).
            limit:   Maximum rows to return.
            offset:  Pagination offset.

        Returns:
            List of Application models ordered by updated_at descending.
        """
        conditions: List[str] = []
        params: List[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status.value)
        if company:
            conditions.append("LOWER(company) LIKE ?")
            params.append(f"%{company.lower()}%")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params += [limit, offset]

        rows = self._execute(
            f"SELECT * FROM applications {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",  # noqa: S608
            tuple(params),
            fetch="all",
        )
        return [self._row_to_application(r) for r in rows]

    def get_upcoming_deadlines(self, within_days: int = 3) -> List[Application]:
        """
        Return applications with deadlines within *within_days* from today.

        Args:
            within_days: Look-ahead window in days.

        Returns:
            List of Application models sorted by deadline ascending.
        """
        today = date.today().isoformat()
        rows = self._execute(
            """
            SELECT * FROM applications
            WHERE deadline IS NOT NULL
              AND deadline >= ?
              AND status NOT IN ('rejected', 'withdrawn', 'accepted')
            ORDER BY deadline ASC
            LIMIT 50
            """,
            (today,),
            fetch="all",
        )
        # Python-side filter for upper bound (SQLite date comparison is string-based)
        from datetime import timedelta

        cutoff = (date.today() + timedelta(days=within_days)).isoformat()
        return [
            self._row_to_application(r)
            for r in rows
            if dict(r)["deadline"] <= cutoff
        ]

    def get_stats(self) -> Dict[str, int]:
        """
        Return a count of applications grouped by status.

        Returns:
            Dict mapping status label → count.
        """
        rows = self._execute(
            "SELECT status, COUNT(*) as cnt FROM applications GROUP BY status",
            fetch="all",
        )
        return {r["status"]: r["cnt"] for r in rows}

    # ------------------------------------------------------------------
    # Candidate profile
    # ------------------------------------------------------------------

    def save_candidate_profile(self, profile: CandidateProfile) -> None:
        """
        Upsert the singleton candidate profile.

        Args:
            profile: Validated CandidateProfile model.
        """
        now = self._now()
        profile.updated_at = datetime.fromisoformat(now)
        self._execute(
            """
            INSERT INTO candidate_profile (id, profile_json, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET profile_json = excluded.profile_json,
                                          updated_at   = excluded.updated_at
            """,
            (profile.model_dump_json(), now),
        )
        logger.info("Candidate profile saved.")

    def load_candidate_profile(self) -> Optional[CandidateProfile]:
        """
        Load the stored candidate profile.

        Returns:
            CandidateProfile model or None if not yet configured.
        """
        row = self._execute(
            "SELECT profile_json FROM candidate_profile WHERE id = 1",
            fetch="one",
        )
        if not row:
            return None
        return CandidateProfile.model_validate_json(row["profile_json"])

    # ------------------------------------------------------------------
    # Search cache
    # ------------------------------------------------------------------

    def cache_search_results(
        self, query: str, location: str, source: str, results: list
    ) -> None:
        """
        Store raw search results to reduce redundant HTTP calls.

        Args:
            query:    Search query string.
            location: Target location string.
            source:   Source name (e.g. 'linkedin').
            results:  List of serialisable dicts.
        """
        cache_id = str(uuid.uuid4())
        self._execute(
            """
            INSERT INTO search_cache (id, query, location, source, results_json, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cache_id, query, location, source, json.dumps(results), self._now()),
        )

    def get_cached_results(
        self, query: str, source: str, max_age_hours: int = 6
    ) -> Optional[list]:
        """
        Retrieve cached search results if they are fresh enough.

        Args:
            query:         Search query string.
            source:        Source name.
            max_age_hours: Maximum acceptable cache age.

        Returns:
            List of result dicts or None if cache miss / stale.
        """
        from datetime import timedelta

        cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat()
        row = self._execute(
            """
            SELECT results_json FROM search_cache
            WHERE query = ? AND source = ? AND fetched_at >= ?
            ORDER BY fetched_at DESC LIMIT 1
            """,
            (query, source, cutoff),
            fetch="one",
        )
        return json.loads(row["results_json"]) if row else None

    # ------------------------------------------------------------------
    # Digest history
    # ------------------------------------------------------------------

    def save_digest(self, digest_json: str) -> str:
        """
        Persist a digest report for auditing purposes.

        Args:
            digest_json: JSON-serialised DigestReport.

        Returns:
            The generated digest id.
        """
        digest_id = str(uuid.uuid4())
        self._execute(
            "INSERT INTO digest_history (id, generated_at, digest_json) VALUES (?, ?, ?)",
            (digest_id, self._now(), digest_json),
        )
        return digest_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()
        logger.info("DatabaseManager connection closed.")

    def __enter__(self) -> "DatabaseManager":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
