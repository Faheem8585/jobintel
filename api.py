"""
JobIntel REST API (FastAPI).

Thin HTTP wrapper around the skill tools — each endpoint delegates to the same
handler functions, so the API and CLI always behave identically. Swagger docs
are auto-generated at /docs.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import skill as sk


# ---------------------------------------------------------------------------
# Lifespan — warm up services once at startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    sk._get_services()  # initialise DB + all service singletons
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="JobIntel API",
    description=(
        "Intelligent job search and application tracking.\n\n"
        "All endpoints map 1-to-1 to the skill tools defined in SKILL.md."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Shared error helper
# ---------------------------------------------------------------------------

def _ok(result: Dict[str, Any]) -> Dict[str, Any]:
    """Raise 400 if the tool returned an error dict, else pass through."""
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AnalyzeJDRequest(BaseModel):
    raw_text: str = Field(..., description="Full text of the job posting")
    title: str = Field("", description="Optional job title override")
    company: str = Field("", description="Company name")
    location: str = Field("", description="Job location")
    compute_match: bool = Field(True, description="Compute match score against stored profile")


class TrackApplicationRequest(BaseModel):
    company: str
    role: str
    location: str = ""
    url: Optional[str] = None
    status: str = "wishlist"
    applied_date: Optional[str] = Field(None, description="ISO-8601 date YYYY-MM-DD")
    deadline: Optional[str] = Field(None, description="ISO-8601 date YYYY-MM-DD")
    notes: str = ""
    contact: str = ""
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None


class UpdateStatusRequest(BaseModel):
    new_status: str


class UpdateNotesRequest(BaseModel):
    notes: str


class GapAnalysisRequest(BaseModel):
    raw_jd_text: str = Field(..., description="Full job description text")
    title: str = ""
    company: str = ""


class SearchRequest(BaseModel):
    query: str = Field(..., description="Job title / keywords")
    location: Optional[str] = Field(None, description="Target location (default: Germany)")
    sources: Optional[List[str]] = Field(None, description="e.g. ['linkedin', 'indeed']")


class SkillItem(BaseModel):
    name: str
    category: str = "other"
    proficiency: Optional[float] = None


class SetProfileRequest(BaseModel):
    name: str
    email: str = ""
    skills: List[SkillItem] = []
    years_of_experience: float = 0.0
    education_level: str = ""
    education_field: str = ""
    languages: List[str] = []
    target_roles: List[str] = []
    target_locations: List[str] = []
    cv_raw_text: str = ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", tags=["Meta"])
def root():
    """Health check and link to docs."""
    return {
        "service": "JobIntel API",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "ok",
    }


@app.get("/stats", tags=["Pipeline"])
def get_stats():
    """Return application pipeline statistics and computed rates."""
    return _ok(sk.handle_get_stats({}))


@app.get("/digest", tags=["Pipeline"])
def get_daily_digest():
    """Generate the daily job search digest."""
    return _ok(sk.handle_get_daily_digest({}))


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@app.get("/applications", tags=["Applications"])
def list_applications(
    status: Optional[str] = Query(None, description="Filter by status"),
    company: Optional[str] = Query(None, description="Company name substring"),
    limit: int = Query(50, ge=1, le=200),
):
    """List applications with optional filters."""
    return _ok(sk.handle_list_applications({
        "status": status,
        "company": company,
        "limit": limit,
    }))


@app.post("/applications", status_code=201, tags=["Applications"])
def track_application(body: TrackApplicationRequest):
    """Log a new job application."""
    return _ok(sk.handle_track_application(body.model_dump()))


@app.patch("/applications/{app_id}/status", tags=["Applications"])
def update_status(
    app_id: str = Path(..., description="Application UUID"),
    body: UpdateStatusRequest = ...,
):
    """Advance an application through the hiring pipeline."""
    return _ok(sk.handle_update_application_status({
        "app_id": app_id,
        "new_status": body.new_status,
    }))


@app.patch("/applications/{app_id}/notes", tags=["Applications"])
def update_notes(
    app_id: str = Path(..., description="Application UUID"),
    body: UpdateNotesRequest = ...,
):
    """Update the notes on an application."""
    tracker, *_ = sk._get_services()
    try:
        app = tracker.update_notes(app_id, body.notes)
        return app.model_dump(mode="json")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/applications/{app_id}", status_code=204, tags=["Applications"])
def delete_application(app_id: str = Path(..., description="Application UUID")):
    """Delete an application record."""
    tracker, *_ = sk._get_services()
    deleted = tracker.delete(app_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Application {app_id!r} not found.")


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@app.post("/analyze", tags=["Analysis"])
def analyze_job_description(body: AnalyzeJDRequest):
    """Parse a job description and compute a match score against the stored profile."""
    return _ok(sk.handle_analyze_job_description(body.model_dump()))


@app.post("/gap", tags=["Analysis"])
def analyze_cv_gap(body: GapAnalysisRequest):
    """Identify skill gaps between your profile and a job description."""
    return _ok(sk.handle_analyze_cv_gap(body.model_dump()))


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@app.post("/search", tags=["Search"])
def search_jobs(body: SearchRequest):
    """Search LinkedIn, Indeed, StepStone, and XING for matching roles."""
    return _ok(sk.handle_search_jobs(body.model_dump()))


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@app.get("/profile", tags=["Profile"])
def get_profile():
    """Retrieve the stored candidate profile."""
    db = sk._get_db()
    profile = db.load_candidate_profile()
    if not profile:
        raise HTTPException(status_code=404, detail="No profile saved yet. POST to /profile first.")
    return profile.model_dump(mode="json")


@app.put("/profile", tags=["Profile"])
def set_profile(body: SetProfileRequest):
    """Store or update the candidate profile."""
    return _ok(sk.handle_set_candidate_profile(body.model_dump()))
