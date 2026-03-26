"""
Pydantic v2 data models for JobIntel.

All domain objects are defined here as the single source of truth.
Separating models from business logic allows both layers to evolve
independently and makes serialisation/deserialisation trivial.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ApplicationStatus(str, Enum):
    """Lifecycle states of a job application."""

    WISHLIST = "wishlist"
    APPLIED = "applied"
    PHONE_SCREEN = "phone_screen"
    TECHNICAL = "technical"
    ONSITE = "onsite"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    ACCEPTED = "accepted"


class SeniorityLevel(str, Enum):
    """Inferred seniority level from a job description."""

    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    PRINCIPAL = "principal"
    STAFF = "staff"
    UNKNOWN = "unknown"


class SkillCategory(str, Enum):
    """High-level category for a skill."""

    LANGUAGE = "language"
    ML_FRAMEWORK = "ml_framework"
    DATA_TOOL = "data_tool"
    CLOUD = "cloud"
    CV_TOOL = "cv_tool"
    LLM_TOOL = "llm_tool"
    WEB_FRAMEWORK = "web_framework"
    SOFT_SKILL = "soft_skill"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Core domain models
# ---------------------------------------------------------------------------


class Skill(BaseModel):
    """A single skill with an optional category and proficiency."""

    name: str
    category: SkillCategory = SkillCategory.OTHER
    proficiency: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Self-rated proficiency 0–1"
    )

    @field_validator("name")
    @classmethod
    def normalise_name(cls, v: str) -> str:
        """Lowercase and strip skill names for consistent comparison."""
        return v.strip().lower()


class Application(BaseModel):
    """A single job application record."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company: str
    role: str
    location: str = ""
    url: Optional[str] = None
    status: ApplicationStatus = ApplicationStatus.WISHLIST
    applied_date: Optional[date] = None
    deadline: Optional[date] = None
    notes: str = ""
    contact: str = ""
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    match_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("company", "role")
    @classmethod
    def non_empty(cls, v: str) -> str:
        """Ensure company and role are not blank."""
        if not v.strip():
            raise ValueError("Field must not be empty.")
        return v.strip()

    @model_validator(mode="after")
    def deadline_after_applied(self) -> "Application":
        """Deadline must be on or after the application date."""
        if self.deadline and self.applied_date and self.deadline < self.applied_date:
            raise ValueError("deadline must be on or after applied_date.")
        return self


class CandidateProfile(BaseModel):
    """The candidate's skills, experience, and preferences — stored as JSON."""

    name: str
    email: str = ""
    skills: List[Skill] = Field(default_factory=list)
    years_of_experience: float = 0.0
    education_level: str = ""  # e.g. "MSc", "BSc", "PhD"
    education_field: str = ""  # e.g. "Computer Science"
    languages: List[str] = Field(default_factory=list)  # spoken languages
    target_roles: List[str] = Field(default_factory=list)
    target_locations: List[str] = Field(default_factory=list)
    cv_raw_text: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def skill_names(self) -> List[str]:
        """Return a flat list of normalised skill names."""
        return [s.name for s in self.skills]


class JobDescription(BaseModel):
    """Parsed representation of a raw job description."""

    title: str = ""
    company: str = ""
    location: str = ""
    raw_text: str
    required_skills: List[str] = Field(default_factory=list)
    nice_to_have_skills: List[str] = Field(default_factory=list)
    seniority: SeniorityLevel = SeniorityLevel.UNKNOWN
    years_required: Optional[float] = None
    education_required: str = ""
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    keywords: List[str] = Field(default_factory=list)
    language_requirements: List[str] = Field(default_factory=list)
    remote_ok: bool = False
    parsed_at: datetime = Field(default_factory=datetime.utcnow)


class AnalysisResult(BaseModel):
    """Output of the JD analyser + match scorer pipeline."""

    job: JobDescription
    match_score: float = Field(ge=0.0, le=1.0)
    match_label: str  # "Strong Match", "Good Match", "Weak Match", "Poor Match"
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    top_matching_skills: List[str] = Field(default_factory=list)
    summary: str = ""


class GapReport(BaseModel):
    """Output of the CV keyword gap analyser."""

    missing_required: List[str] = Field(default_factory=list)
    missing_nice_to_have: List[str] = Field(default_factory=list)
    matching_skills: List[str] = Field(default_factory=list)
    coverage_pct: float = Field(ge=0.0, le=100.0)
    suggested_additions: List[str] = Field(default_factory=list)
    priority_gaps: List[str] = Field(default_factory=list)
    summary: str = ""


class DigestReport(BaseModel):
    """Daily digest payload."""

    generated_at: datetime = Field(default_factory=datetime.utcnow)
    pending_applications: List[Application] = Field(default_factory=list)
    upcoming_deadlines: List[Application] = Field(default_factory=list)
    recent_updates: List[Application] = Field(default_factory=list)
    stats: Dict[str, int] = Field(default_factory=dict)
    summary: str = ""


class SearchResult(BaseModel):
    """A single result from a job board search."""

    title: str
    company: str
    location: str = ""
    url: str = ""
    snippet: str = ""
    source: str = ""
    posted_date: Optional[str] = None
    salary_range: Optional[str] = None
