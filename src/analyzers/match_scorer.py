"""
Match Scorer.

Produces a weighted composite score (0.0–1.0) comparing a CandidateProfile
against a JobDescription across four dimensions:

  1. Skills overlap (configurable weight, default 50%)
  2. Experience match (25%)
  3. Education level (15%)
  4. Location preference (10%)

Weights are read from config.yaml and normalised if they do not sum to 1.0,
so user configuration errors do not silently produce wrong scores.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from src.analyzers.gap_analyzer import _normalise, _skills_match
from src.models.models import AnalysisResult, CandidateProfile, JobDescription, SeniorityLevel

logger = logging.getLogger(__name__)

# Education level rank — higher = more qualified
_EDU_RANK: Dict[str, int] = {
    "": 0,
    "vocational": 1,
    "bsc": 2,
    "msc": 3,
    "phd": 4,
}

# Seniority → implied years of experience midpoint
_SENIORITY_YEARS: Dict[SeniorityLevel, float] = {
    SeniorityLevel.INTERN: 0.0,
    SeniorityLevel.JUNIOR: 1.0,
    SeniorityLevel.MID: 3.0,
    SeniorityLevel.SENIOR: 6.0,
    SeniorityLevel.LEAD: 9.0,
    SeniorityLevel.PRINCIPAL: 12.0,
    SeniorityLevel.STAFF: 12.0,
    SeniorityLevel.UNKNOWN: 3.0,
}


class MatchScorer:
    """Compute a multi-dimensional match score between a candidate and a JD."""

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialise scorer with scoring weights from config.

        Args:
            config: Full parsed config.yaml dict.
        """
        scoring_cfg = config.get("scoring", {})
        raw_weights = {
            "skills": scoring_cfg.get("skills_weight", 0.50),
            "experience": scoring_cfg.get("experience_weight", 0.25),
            "education": scoring_cfg.get("education_weight", 0.15),
            "location": scoring_cfg.get("location_weight", 0.10),
        }
        self._weights = self._normalise_weights(raw_weights)
        self._strong = scoring_cfg.get("strong_match_threshold", 0.75)
        self._good = scoring_cfg.get("good_match_threshold", 0.55)
        self._weak = scoring_cfg.get("weak_match_threshold", 0.35)
        logger.debug("MatchScorer initialised with weights: %s", self._weights)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, profile: CandidateProfile, jd: JobDescription) -> AnalysisResult:
        """
        Compute a match score and return a full AnalysisResult.

        Args:
            profile: Candidate profile.
            jd:      Parsed job description.

        Returns:
            AnalysisResult with score, label, breakdown, and summary.
        """
        skills_score, matching_skills = self._score_skills(profile, jd)
        exp_score = self._score_experience(profile, jd)
        edu_score = self._score_education(profile, jd)
        loc_score = self._score_location(profile, jd)

        breakdown = {
            "skills": round(skills_score, 3),
            "experience": round(exp_score, 3),
            "education": round(edu_score, 3),
            "location": round(loc_score, 3),
        }
        composite = (
            skills_score * self._weights["skills"]
            + exp_score * self._weights["experience"]
            + edu_score * self._weights["education"]
            + loc_score * self._weights["location"]
        )
        composite = round(min(max(composite, 0.0), 1.0), 3)
        label = self._score_label(composite)

        summary = self._build_summary(composite, label, breakdown, matching_skills, jd)

        logger.info("Match score for %s: %.3f (%s)", jd.title or "JD", composite, label)
        return AnalysisResult(
            job=jd,
            match_score=composite,
            match_label=label,
            score_breakdown=breakdown,
            top_matching_skills=matching_skills[:10],
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Dimension scorers
    # ------------------------------------------------------------------

    def _score_skills(
        self, profile: CandidateProfile, jd: JobDescription
    ) -> Tuple[float, List[str]]:
        """
        Skills dimension: Jaccard-like overlap of candidate skills vs JD skills.

        Required skills count double vs. nice-to-have skills.

        Returns:
            Tuple of (normalised score 0–1, list of matched skill names).
        """
        candidate_skills = list(profile.skill_names())
        if profile.cv_raw_text:
            candidate_skills.extend(profile.cv_raw_text.lower().split())

        all_jd_skills = [
            (s, 2.0) for s in jd.required_skills
        ] + [
            (s, 1.0) for s in jd.nice_to_have_skills
        ]

        if not all_jd_skills:
            return 1.0, []  # No skills listed — full score by default

        total_weight = sum(w for _, w in all_jd_skills)
        matched_weight = 0.0
        matching_names: List[str] = []

        for skill, weight in all_jd_skills:
            if any(_skills_match(cs, skill) for cs in candidate_skills):
                matched_weight += weight
                matching_names.append(skill)

        score = matched_weight / total_weight if total_weight else 0.0
        return score, matching_names

    @staticmethod
    def _score_experience(profile: CandidateProfile, jd: JobDescription) -> float:
        """
        Experience dimension: sigmoid-like function centred on the JD requirement.

        Over-qualified or meeting requirement → high score.
        Under-qualified → penalised proportionally.

        Returns:
            Normalised score 0–1.
        """
        candidate_years = profile.years_of_experience

        # Determine required years from JD
        if jd.years_required is not None:
            required_years = jd.years_required
        else:
            required_years = _SENIORITY_YEARS.get(jd.seniority, 3.0)

        if required_years == 0:
            return 1.0

        ratio = candidate_years / required_years
        if ratio >= 1.0:
            # Over-qualified — slight penalty for very over-qualified (avoids mismatch)
            if ratio > 3.0:
                return 0.7
            return 1.0
        # Under-qualified — linear penalty
        return max(ratio, 0.0)

    @staticmethod
    def _score_education(profile: CandidateProfile, jd: JobDescription) -> float:
        """
        Education dimension: compare education level ranks.

        Returns:
            1.0 if candidate meets or exceeds requirement, else partial score.
        """
        req_edu = jd.education_required.lower().strip() if jd.education_required else ""
        cand_edu = profile.education_level.lower().strip() if profile.education_level else ""

        req_rank = _EDU_RANK.get(req_edu, 0)
        cand_rank = _EDU_RANK.get(cand_edu, 0)

        if req_rank == 0:
            return 1.0  # No education requirement stated
        if cand_rank >= req_rank:
            return 1.0
        # Partial score based on gap (each level is 0.25 apart)
        gap = req_rank - cand_rank
        return max(1.0 - gap * 0.25, 0.0)

    @staticmethod
    def _score_location(profile: CandidateProfile, jd: JobDescription) -> float:
        """
        Location dimension: check if JD location is in candidate preferences.

        Returns:
            1.0 on match or if remote is OK, 0.5 for same country, 0.0 otherwise.
        """
        if jd.remote_ok:
            return 1.0

        jd_loc = jd.location.lower()
        for preferred in profile.target_locations:
            if preferred.lower() in jd_loc or jd_loc in preferred.lower():
                return 1.0

        # Check country-level match (simple heuristic: look for "germany"/"deutschland")
        germany_aliases = {"germany", "deutschland", "de"}
        if any(alias in jd_loc for alias in germany_aliases):
            return 0.5

        return 0.0

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _score_label(self, score: float) -> str:
        """Convert a numeric score to a human-readable match label."""
        if score >= self._strong:
            return "Strong Match"
        if score >= self._good:
            return "Good Match"
        if score >= self._weak:
            return "Weak Match"
        return "Poor Match"

    @staticmethod
    def _normalise_weights(weights: Dict[str, float]) -> Dict[str, float]:
        """
        Normalise weights to sum to 1.0.

        This is a defensive measure: if a user misconfigures weights,
        the scorer still produces a valid composite.
        """
        total = sum(weights.values())
        if abs(total - 1.0) < 1e-6:
            return weights
        logger.warning("Score weights sum to %.3f; normalising to 1.0.", total)
        return {k: v / total for k, v in weights.items()}

    @staticmethod
    def _build_summary(
        score: float,
        label: str,
        breakdown: Dict[str, float],
        matching: List[str],
        jd: JobDescription,
    ) -> str:
        """Build a concise human-readable summary of the match result."""
        title = jd.title or "this role"
        top = ", ".join(matching[:5]) if matching else "none"
        return (
            f"{label} ({score:.0%}) for {title}. "
            f"Skills: {breakdown['skills']:.0%} | "
            f"Experience: {breakdown['experience']:.0%} | "
            f"Education: {breakdown['education']:.0%} | "
            f"Location: {breakdown['location']:.0%}. "
            f"Top matching skills: {top}."
        )
