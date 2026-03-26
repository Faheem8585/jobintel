"""
JobIntel MCP Server — Model Context Protocol adapter.

Exposes every tool as an MCP-compatible tool so any MCP host can call them
directly without going through the HTTP API layer.

Run with:
    mcp dev mcp_server.py          # interactive inspector
    python mcp_server.py           # stdio transport (for desktop clients)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path bootstrap — allow running from any CWD
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP
import skill as sk

# ---------------------------------------------------------------------------
# Initialise services eagerly (DB connection, service singletons)
# ---------------------------------------------------------------------------
sk._get_services()

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "JobIntel",
    instructions=(
        "JobIntel is an intelligent job search and application tracking assistant. "
        "Use it to analyse job descriptions, track applications in a local SQLite "
        "database, find skill gaps in your CV, run a daily digest of your pipeline, "
        "and search for live job postings across LinkedIn, Indeed, StepStone, and XING."
    ),
)


# ---------------------------------------------------------------------------
# Tool 1 — Analyse a job description
# ---------------------------------------------------------------------------
@mcp.tool()
def analyze_job_description(
    raw_text: str,
    title: str = "",
    company: str = "",
    location: str = "",
    compute_match: bool = True,
) -> dict:
    """Parse a job posting and return extracted skills, seniority level, salary
    range, remote policy, and a match score against the stored candidate profile.

    Args:
        raw_text:      Full text of the job posting (required).
        title:         Job title override (optional).
        company:       Company name (optional).
        location:      Job location (optional).
        compute_match: Whether to compute a match score (default True).
    """
    return sk.handle_analyze_job_description(
        {
            "raw_text": raw_text,
            "title": title,
            "company": company,
            "location": location,
            "compute_match": compute_match,
        }
    )


# ---------------------------------------------------------------------------
# Tool 2 — Log a new job application
# ---------------------------------------------------------------------------
@mcp.tool()
def track_application(
    company: str,
    role: str,
    location: str = "",
    url: Optional[str] = None,
    status: str = "wishlist",
    applied_date: Optional[str] = None,
    deadline: Optional[str] = None,
    notes: str = "",
    contact: str = "",
    salary_min: Optional[int] = None,
    salary_max: Optional[int] = None,
) -> dict:
    """Log a new job application to the local SQLite tracker.

    Args:
        company:      Company name (required).
        role:         Job title / role name (required).
        location:     Job location.
        url:          Link to the job posting.
        status:       Pipeline stage — one of: wishlist, applied, phone_screen,
                      technical, onsite, offer, rejected, withdrawn, accepted.
        applied_date: ISO-8601 date you applied (YYYY-MM-DD).
        deadline:     Application deadline (YYYY-MM-DD).
        notes:        Free-text notes.
        contact:      Recruiter / hiring manager name.
        salary_min:   Minimum salary in EUR.
        salary_max:   Maximum salary in EUR.
    """
    return sk.handle_track_application(
        {
            "company": company,
            "role": role,
            "location": location,
            "url": url,
            "status": status,
            "applied_date": applied_date,
            "deadline": deadline,
            "notes": notes,
            "contact": contact,
            "salary_min": salary_min,
            "salary_max": salary_max,
        }
    )


# ---------------------------------------------------------------------------
# Tool 3 — Update application status
# ---------------------------------------------------------------------------
@mcp.tool()
def update_application_status(app_id: str, new_status: str) -> dict:
    """Advance a tracked application to a new pipeline stage.

    Args:
        app_id:     UUID of the application (from track_application or list_applications).
        new_status: Target status — one of: wishlist, applied, phone_screen,
                    technical, onsite, offer, rejected, withdrawn, accepted.
    """
    return sk.handle_update_application_status(
        {"app_id": app_id, "new_status": new_status}
    )


# ---------------------------------------------------------------------------
# Tool 4 — List / search applications
# ---------------------------------------------------------------------------
@mcp.tool()
def list_applications(
    status: Optional[str] = None,
    company: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Query the application tracker with optional filters.

    Args:
        status:  Filter to a single pipeline stage (optional).
        company: Case-insensitive substring match on company name (optional).
        limit:   Maximum number of results to return (default 50, max 200).
    """
    return sk.handle_list_applications(
        {"status": status, "company": company, "limit": limit}
    )


# ---------------------------------------------------------------------------
# Tool 5 — CV / skill gap analysis
# ---------------------------------------------------------------------------
@mcp.tool()
def analyze_cv_gap(
    raw_jd_text: str,
    title: str = "",
    company: str = "",
) -> dict:
    """Compare a job description against the stored candidate profile and return
    missing required skills, missing nice-to-have skills, coverage percentage,
    and concrete suggestions for improving the CV before applying.

    Args:
        raw_jd_text: Full text of the job description (required).
        title:       Job title (optional, used in the report).
        company:     Company name (optional, used in the report).
    """
    return sk.handle_analyze_cv_gap(
        {"raw_jd_text": raw_jd_text, "title": title, "company": company}
    )


# ---------------------------------------------------------------------------
# Tool 6 — Daily digest
# ---------------------------------------------------------------------------
@mcp.tool()
def get_daily_digest() -> dict:
    """Generate a structured daily summary of the job search pipeline.

    Returns pending applications, upcoming deadlines, stale applications
    (no updates in 14+ days), and overall pipeline statistics.
    """
    return sk.handle_get_daily_digest({})


# ---------------------------------------------------------------------------
# Tool 7 — Job search
# ---------------------------------------------------------------------------
@mcp.tool()
def search_jobs(
    query: str,
    location: Optional[str] = None,
    sources: Optional[list[str]] = None,
) -> dict:
    """Search for live job postings across LinkedIn, Indeed, StepStone, and XING.

    Args:
        query:    Job title and/or keywords (e.g. "Senior Python Engineer Berlin").
        location: Target location (defaults to Germany).
        sources:  List of sources to search — any subset of
                  ["linkedin", "indeed", "stepstone", "xing"].
                  Defaults to all four.
    """
    return sk.handle_search_jobs(
        {"query": query, "location": location, "sources": sources}
    )


# ---------------------------------------------------------------------------
# Tool 8 — Store / update candidate profile
# ---------------------------------------------------------------------------
@mcp.tool()
def set_candidate_profile(
    name: str,
    email: str = "",
    skills: Optional[list[dict]] = None,
    years_of_experience: float = 0.0,
    education_level: str = "",
    education_field: str = "",
    languages: Optional[list[str]] = None,
    target_roles: Optional[list[str]] = None,
    target_locations: Optional[list[str]] = None,
    cv_raw_text: str = "",
) -> dict:
    """Store or update the candidate profile used for match scoring and gap analysis.

    Args:
        name:                 Full name (required).
        email:                Contact email.
        skills:               List of skill objects, each with keys:
                              'name' (str), 'category' (str, e.g. 'language',
                              'framework', 'tool', 'soft'), 'proficiency' (float 0-1).
        years_of_experience:  Total professional experience in years.
        education_level:      Highest degree (e.g. 'MSc', 'BSc', 'PhD').
        education_field:      Field of study (e.g. 'Computer Science').
        languages:            Spoken languages (e.g. ['English', 'German']).
        target_roles:         Desired job titles.
        target_locations:     Preferred work locations.
        cv_raw_text:          Full CV text for keyword-level matching.
    """
    return sk.handle_set_candidate_profile(
        {
            "name": name,
            "email": email,
            "skills": skills or [],
            "years_of_experience": years_of_experience,
            "education_level": education_level,
            "education_field": education_field,
            "languages": languages or [],
            "target_roles": target_roles or [],
            "target_locations": target_locations or [],
            "cv_raw_text": cv_raw_text,
        }
    )


# ---------------------------------------------------------------------------
# Tool 9 — Pipeline statistics
# ---------------------------------------------------------------------------
@mcp.tool()
def get_stats() -> dict:
    """Return pipeline statistics: total applications, active count, response rate,
    offer rate, and a breakdown by status stage.
    """
    return sk.handle_get_stats({})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # stdio is the standard transport for MCP desktop clients
    mcp.run(transport="stdio")
