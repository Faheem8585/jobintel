"""
JobIntel — main entry point and tool dispatcher.

Bootstraps config, logging, and DB on first use. Exposes handle_tool_call()
which routes tool names to handler functions. Also works as a CLI for quick
testing (python skill.py <tool_name> '<json_params>').

Every handler returns a plain dict — errors come back as {"error": "..."}.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path when run directly
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.analyzers import GapAnalyzer, JobDescriptionParser, MatchScorer
from src.database import DatabaseManager
from src.digest import DigestGenerator
from src.models.models import CandidateProfile, Skill, SkillCategory
from src.search import JobSearcher
from src.tracker import ApplicationTracker

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"


def load_config() -> Dict[str, Any]:
    """
    Load and return the parsed config.yaml.

    Returns:
        Parsed configuration dict.

    Raises:
        FileNotFoundError: If config.yaml is missing.
    """
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(f"config.yaml not found at {_CONFIG_PATH}")
    with _CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG: Dict[str, Any] = load_config()

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging(config: Dict[str, Any]) -> None:
    """Configure application-wide logging from the config dict."""
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = _PROJECT_ROOT / log_cfg.get("file", "logs/jobintel.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=log_cfg.get("max_bytes", 5 * 1024 * 1024),
        backupCount=log_cfg.get("backup_count", 3),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


_setup_logging(CONFIG)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared service instances (initialised lazily to allow easy testing)
# ---------------------------------------------------------------------------

_db: Optional[DatabaseManager] = None
_tracker: Optional[ApplicationTracker] = None
_parser: Optional[JobDescriptionParser] = None
_gap_analyzer: Optional[GapAnalyzer] = None
_scorer: Optional[MatchScorer] = None
_digest_gen: Optional[DigestGenerator] = None
_searcher: Optional[JobSearcher] = None


def _get_db() -> DatabaseManager:
    """Lazily initialise and return the singleton DatabaseManager."""
    global _db
    if _db is None:
        db_path = str(_PROJECT_ROOT / CONFIG["database"]["path"])
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        _db = DatabaseManager(db_path)
    return _db


def _get_services():
    """Return all service instances, initialising on first call."""
    global _tracker, _parser, _gap_analyzer, _scorer, _digest_gen, _searcher
    db = _get_db()
    if _tracker is None:
        _tracker = ApplicationTracker(db)
    if _parser is None:
        _parser = JobDescriptionParser(CONFIG)
    if _gap_analyzer is None:
        _gap_analyzer = GapAnalyzer()
    if _scorer is None:
        _scorer = MatchScorer(CONFIG)
    if _digest_gen is None:
        _digest_gen = DigestGenerator(db, CONFIG)
    if _searcher is None:
        _searcher = JobSearcher(db, CONFIG)
    return _tracker, _parser, _gap_analyzer, _scorer, _digest_gen, _searcher


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def handle_analyze_job_description(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a raw job description and optionally compute a match score.

    Args:
        params: {raw_text, title?, company?, location?, compute_match?}

    Returns:
        AnalysisResult dict or error dict.
    """
    raw_text = params.get("raw_text", "").strip()
    if not raw_text:
        return {"error": "raw_text is required and must not be empty."}

    _, parser, _, scorer, _, _ = _get_services()
    db = _get_db()

    jd = parser.parse(
        raw_text,
        title=params.get("title", ""),
        company=params.get("company", ""),
        location=params.get("location", ""),
    )

    compute_match = params.get("compute_match", True)
    profile = db.load_candidate_profile()

    if compute_match and profile:
        result = scorer.score(profile, jd)
        return result.model_dump(mode="json")
    else:
        # Return just the parsed JD without scoring
        return {
            "job": jd.model_dump(mode="json"),
            "match_score": None,
            "match_label": "N/A — no profile stored",
            "score_breakdown": {},
            "top_matching_skills": [],
            "summary": "Set your candidate profile to enable match scoring.",
        }


def handle_track_application(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new job application record.

    Args:
        params: Application fields as per SKILL.md tool definition.

    Returns:
        Created application dict or error dict.
    """
    tracker, *_ = _get_services()
    try:
        app = tracker.add(
            company=params["company"],
            role=params["role"],
            location=params.get("location", ""),
            url=params.get("url"),
            status=params.get("status", "wishlist"),
            applied_date=params.get("applied_date"),
            deadline=params.get("deadline"),
            notes=params.get("notes", ""),
            contact=params.get("contact", ""),
            salary_min=params.get("salary_min"),
            salary_max=params.get("salary_max"),
        )
        return {
            "id": app.id,
            "company": app.company,
            "role": app.role,
            "status": app.status.value,
            "created_at": app.created_at.isoformat(),
            "message": f"Application tracked: {app.role} at {app.company}",
        }
    except (ValueError, KeyError) as exc:
        logger.warning("track_application error: %s", exc)
        return {"error": str(exc)}


def handle_update_application_status(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transition an application's status through the pipeline.

    Args:
        params: {app_id, new_status}

    Returns:
        Updated application summary or error dict.
    """
    tracker, *_ = _get_services()
    app_id = params.get("app_id", "").strip()
    new_status = params.get("new_status", "").strip()

    if not app_id or not new_status:
        return {"error": "Both app_id and new_status are required."}

    try:
        prev = _get_db().get_application(app_id)
        previous_status = prev.status.value if prev else "unknown"
        app = tracker.update_status(app_id, new_status)
        return {
            "id": app.id,
            "company": app.company,
            "role": app.role,
            "previous_status": previous_status,
            "new_status": app.status.value,
            "updated_at": app.updated_at.isoformat(),
        }
    except ValueError as exc:
        return {"error": str(exc)}


def handle_list_applications(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Query and filter the application list.

    Args:
        params: {status?, company?, limit?}

    Returns:
        Dict with count and list of application summaries.
    """
    tracker, *_ = _get_services()
    apps = tracker.list(
        status=params.get("status"),
        company=params.get("company"),
        limit=params.get("limit", 50),
    )
    return {
        "count": len(apps),
        "applications": [
            {
                "id": a.id,
                "company": a.company,
                "role": a.role,
                "location": a.location,
                "status": a.status.value,
                "applied_date": a.applied_date.isoformat() if a.applied_date else None,
                "deadline": a.deadline.isoformat() if a.deadline else None,
                "match_score": a.match_score,
                "notes": a.notes,
            }
            for a in apps
        ],
    }


def handle_analyze_cv_gap(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Identify skill gaps between the candidate profile and a job description.

    Args:
        params: {raw_jd_text, title?, company?}

    Returns:
        GapReport dict or error dict.
    """
    raw_text = params.get("raw_jd_text", "").strip()
    if not raw_text:
        return {"error": "raw_jd_text is required and must not be empty."}

    db = _get_db()
    profile = db.load_candidate_profile()
    if not profile:
        return {
            "error": "No candidate profile found. Use set_candidate_profile first."
        }

    _, parser, gap_analyzer, _, _, _ = _get_services()
    jd = parser.parse(
        raw_text,
        title=params.get("title", ""),
        company=params.get("company", ""),
    )
    report = gap_analyzer.analyse(profile, jd)
    return report.model_dump(mode="json")


def handle_get_daily_digest(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate and return the daily digest report.

    Args:
        params: {} (no parameters required)

    Returns:
        DigestReport dict with additional formatted_text field.
    """
    _, _, _, _, digest_gen, _ = _get_services()
    report = digest_gen.generate()
    formatted = digest_gen.format_text(report)

    result = report.model_dump(mode="json")
    result["pending_count"] = len(report.pending_applications)
    result["formatted_text"] = formatted
    # Keep application lists compact for the output
    result["pending_applications"] = [
        {
            "id": a.id,
            "company": a.company,
            "role": a.role,
            "status": a.status.value,
        }
        for a in report.pending_applications
    ]
    result["upcoming_deadlines"] = [
        {
            "id": a.id,
            "company": a.company,
            "role": a.role,
            "deadline": a.deadline.isoformat() if a.deadline else None,
        }
        for a in report.upcoming_deadlines
    ]
    result["recent_updates"] = [
        {
            "id": a.id,
            "company": a.company,
            "role": a.role,
            "status": a.status.value,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        }
        for a in report.recent_updates
    ]
    return result


def handle_search_jobs(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Search job boards for matching roles.

    Args:
        params: {query, location?, sources?}

    Returns:
        Dict with count and list of SearchResult dicts.
    """
    query = params.get("query", "").strip()
    if not query:
        return {"error": "query is required and must not be empty."}

    _, _, _, _, _, searcher = _get_services()
    results = searcher.search(
        query=query,
        location=params.get("location"),
        sources=params.get("sources"),
    )
    return {
        "count": len(results),
        "results": [r.model_dump(mode="json") for r in results],
    }


def handle_set_candidate_profile(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Store or update the candidate profile.

    Args:
        params: Profile fields as per SKILL.md.

    Returns:
        Confirmation dict or error dict.
    """
    name = params.get("name", "").strip()
    if not name:
        return {"error": "name is required."}

    db = _get_db()

    # Build Skill objects from the input list
    raw_skills: List[Dict[str, Any]] = params.get("skills", [])
    skills: List[Skill] = []
    for s in raw_skills:
        try:
            category = SkillCategory(s.get("category", "other"))
        except ValueError:
            category = SkillCategory.OTHER
        skills.append(Skill(
            name=s.get("name", ""),
            category=category,
            proficiency=s.get("proficiency"),
        ))

    profile = CandidateProfile(
        name=name,
        email=params.get("email", ""),
        skills=skills,
        years_of_experience=float(params.get("years_of_experience", 0.0)),
        education_level=params.get("education_level", ""),
        education_field=params.get("education_field", ""),
        languages=params.get("languages", []),
        target_roles=params.get("target_roles", []),
        target_locations=params.get("target_locations", []),
        cv_raw_text=params.get("cv_raw_text", ""),
    )
    db.save_candidate_profile(profile)
    logger.info("Candidate profile saved for %s (%d skills)", name, len(skills))

    return {
        "status": "saved",
        "name": profile.name,
        "skills_count": len(skills),
        "updated_at": profile.updated_at.isoformat(),
    }


def handle_get_stats(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return pipeline statistics.

    Args:
        params: {} (no parameters required)

    Returns:
        Stats dict including totals and computed rates.
    """
    tracker, *_ = _get_services()
    by_status = tracker.stats()
    total = sum(by_status.values())
    active = sum(
        v for k, v in by_status.items()
        if k not in {"rejected", "withdrawn", "accepted"}
    )
    applied = by_status.get("applied", 0)
    responses = sum(
        by_status.get(s, 0)
        for s in ["phone_screen", "technical", "onsite", "offer", "accepted"]
    )
    offers = by_status.get("offer", 0) + by_status.get("accepted", 0)

    response_rate = (responses / applied * 100) if applied > 0 else 0.0
    offer_rate = (offers / applied * 100) if applied > 0 else 0.0

    return {
        "total": total,
        "active": active,
        "by_status": by_status,
        "response_rate_pct": round(response_rate, 1),
        "offer_rate_pct": round(offer_rate, 1),
    }


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

_TOOL_HANDLERS = {
    "analyze_job_description": handle_analyze_job_description,
    "track_application": handle_track_application,
    "update_application_status": handle_update_application_status,
    "list_applications": handle_list_applications,
    "analyze_cv_gap": handle_analyze_cv_gap,
    "get_daily_digest": handle_get_daily_digest,
    "search_jobs": handle_search_jobs,
    "set_candidate_profile": handle_set_candidate_profile,
    "get_stats": handle_get_stats,
}


def handle_tool_call(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main dispatcher — routes tool_name to the right handler.

    Args:
        tool_name: Name of the tool to invoke.
        params:    Tool parameters dict.

    Returns:
        JSON-serialisable result dict. Always returns a dict (never raises).
    """
    handler = _TOOL_HANDLERS.get(tool_name)
    if not handler:
        available = list(_TOOL_HANDLERS.keys())
        logger.error("Unknown tool: %r. Available: %s", tool_name, available)
        return {
            "error": f"Unknown tool '{tool_name}'.",
            "available_tools": available,
        }

    logger.info("Dispatching tool: %s", tool_name)
    try:
        return handler(params)
    except Exception as exc:
        logger.exception("Unhandled error in tool %r", tool_name)
        return {"error": f"Internal error: {exc}"}


# ---------------------------------------------------------------------------
# CLI interface for manual testing
# ---------------------------------------------------------------------------


def _cli_main() -> None:
    """
    Quick CLI for manual testing.

    Usage:
        python skill.py <tool_name> '<json_params>'

    Examples:
        python skill.py get_stats '{}'
        python skill.py track_application '{"company": "Celonis", "role": "ML Engineer"}'
        python skill.py get_daily_digest '{}'
    """
    if len(sys.argv) < 2:
        print("Usage: python skill.py <tool_name> [json_params]")
        print(f"Available tools: {list(_TOOL_HANDLERS.keys())}")
        sys.exit(1)

    tool_name = sys.argv[1]
    params_str = sys.argv[2] if len(sys.argv) > 2 else "{}"

    try:
        params = json.loads(params_str)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON params — {e}", file=sys.stderr)
        sys.exit(1)

    result = handle_tool_call(tool_name, params)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    _cli_main()
