"""
CV Keyword Gap Analyser.

Compares a parsed JobDescription against a CandidateProfile and produces
a GapReport identifying:
  - Missing required skills (highest priority)
  - Missing nice-to-have skills
  - Already-matching skills
  - Coverage percentage
  - Prioritised suggestions for CV improvement

The comparison is fuzzy: partial matches, plurals, and common abbreviations
are handled so that e.g. "scikit-learn" matches "sklearn".
"""

from __future__ import annotations

import logging
from typing import Dict, List, Set, Tuple

from src.models.models import CandidateProfile, GapReport, JobDescription

logger = logging.getLogger(__name__)

# Known aliases: canonical name → set of accepted alternatives
_ALIASES: Dict[str, Set[str]] = {
    "scikit-learn": {"sklearn", "scikit learn"},
    "pytorch": {"torch"},
    "tensorflow": {"tf"},
    "huggingface": {"hugging face", "hf transformers"},
    "transformers": {"huggingface transformers"},
    "kubernetes": {"k8s"},
    "postgresql": {"postgres", "pg"},
    "elasticsearch": {"elastic", "es"},
    "javascript": {"js"},
    "typescript": {"ts"},
    "golang": {"go"},
    "opencv": {"cv2"},
    "machine learning": {"ml"},
    "natural language processing": {"nlp"},
    "computer vision": {"cv"},
    "large language models": {"llm", "llms"},
    "retrieval augmented generation": {"rag"},
    "continuous integration": {"ci/cd", "ci"},
    "amazon web services": {"aws"},
    "google cloud platform": {"gcp"},
    "microsoft azure": {"azure"},
}

# Reverse map: alias → canonical
_ALIAS_REVERSE: Dict[str, str] = {
    alias: canonical
    for canonical, aliases in _ALIASES.items()
    for alias in aliases
}


def _normalise(skill: str) -> str:
    """Lowercase and strip a skill string."""
    return skill.strip().lower()


def _canonical(skill: str) -> str:
    """Resolve a skill to its canonical form via the alias table."""
    norm = _normalise(skill)
    return _ALIAS_REVERSE.get(norm, norm)


def _skills_match(candidate_skill: str, jd_skill: str) -> bool:
    """
    Fuzzy match between two skill strings.

    Checks:
      1. Exact normalised match
      2. Canonical alias match
      3. One string is a substring of the other (handles plurals, e.g. "api" in "rest apis")
    """
    c_norm = _normalise(candidate_skill)
    j_norm = _normalise(jd_skill)
    c_canon = _canonical(candidate_skill)
    j_canon = _canonical(jd_skill)

    if c_norm == j_norm or c_canon == j_canon:
        return True
    if c_norm in j_norm or j_norm in c_norm:
        return True
    if c_canon in j_canon or j_canon in c_canon:
        return True
    return False


class GapAnalyzer:
    """Identify skill gaps between a candidate profile and a job description."""

    def __init__(self) -> None:
        """Initialise the analyser (stateless — no config needed)."""
        pass

    def analyse(self, profile: CandidateProfile, jd: JobDescription) -> GapReport:
        """
        Compare a candidate profile against a parsed job description.

        Args:
            profile: The candidate's stored profile with skills and CV text.
            jd:      Parsed JobDescription.

        Returns:
            GapReport with missing skills, matches, coverage, and suggestions.
        """
        candidate_skills = self._collect_candidate_skills(profile)

        matching, missing_req = self._partition(
            candidate_skills, jd.required_skills
        )
        _, missing_nice = self._partition(candidate_skills, jd.nice_to_have_skills)

        total_required = len(jd.required_skills)
        coverage_pct = (
            (len(matching) / total_required * 100) if total_required > 0 else 100.0
        )

        priority_gaps = self._prioritise_gaps(missing_req, jd)
        suggestions = self._generate_suggestions(missing_req, missing_nice)

        summary = self._build_summary(
            matching, missing_req, missing_nice, coverage_pct, jd
        )

        logger.info(
            "Gap analysis: %.1f%% coverage, %d missing required, %d missing nice-to-have",
            coverage_pct, len(missing_req), len(missing_nice),
        )
        return GapReport(
            missing_required=missing_req,
            missing_nice_to_have=missing_nice,
            matching_skills=sorted(matching),
            coverage_pct=round(coverage_pct, 1),
            suggested_additions=suggestions,
            priority_gaps=priority_gaps,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_candidate_skills(profile: CandidateProfile) -> List[str]:
        """
        Gather all skill identifiers from the candidate profile.

        Also tokenises the raw CV text so even skills not explicitly added
        to the profile's skill list can be detected.
        """
        skills: List[str] = list(profile.skill_names())

        # Tokenise cv_raw_text to catch inline mentions
        if profile.cv_raw_text:
            words = profile.cv_raw_text.lower().split()
            skills.extend(words)

        return skills

    @staticmethod
    def _partition(
        candidate_skills: List[str], jd_skills: List[str]
    ) -> Tuple[Set[str], List[str]]:
        """
        Partition *jd_skills* into (matched, missing) sets.

        Args:
            candidate_skills: Flat list of candidate skill tokens.
            jd_skills:        Skills required or preferred by the JD.

        Returns:
            Tuple of (matched set, missing list) preserving JD skill order.
        """
        matched: Set[str] = set()
        missing: List[str] = []

        for jd_skill in jd_skills:
            found = any(
                _skills_match(cs, jd_skill) for cs in candidate_skills
            )
            if found:
                matched.add(jd_skill)
            else:
                missing.append(jd_skill)

        return matched, missing

    @staticmethod
    def _prioritise_gaps(missing: List[str], jd: JobDescription) -> List[str]:
        """
        Rank missing required skills by likely importance.

        Heuristic: skills that also appear in the extracted keywords list
        are mentioned more prominently and scored higher.
        """
        keyword_set = {_normalise(k) for k in jd.keywords}
        priority = [s for s in missing if _normalise(s) in keyword_set]
        non_priority = [s for s in missing if _normalise(s) not in keyword_set]
        return priority + non_priority

    @staticmethod
    def _generate_suggestions(
        missing_req: List[str], missing_nice: List[str]
    ) -> List[str]:
        """
        Produce concrete, actionable CV improvement suggestions.

        Args:
            missing_req:  Required skills not found in the candidate profile.
            missing_nice: Nice-to-have skills not found.

        Returns:
            List of suggestion strings.
        """
        suggestions: List[str] = []

        if missing_req:
            top = missing_req[:5]
            suggestions.append(
                f"Add these high-priority skills to your CV/profile: {', '.join(top)}."
            )
        if missing_nice:
            top_nice = missing_nice[:3]
            suggestions.append(
                f"Consider adding these preferred skills to stand out: {', '.join(top_nice)}."
            )
        if len(missing_req) > 5:
            suggestions.append(
                "You are missing several required skills — consider upskilling or "
                "targeting a role that better fits your current profile."
            )
        if not missing_req:
            suggestions.append(
                "You meet all required skills. Tailor your CV with quantified achievements "
                "and JD-specific keywords to maximise ATS score."
            )
        return suggestions

    @staticmethod
    def _build_summary(
        matching: Set[str],
        missing_req: List[str],
        missing_nice: List[str],
        coverage_pct: float,
        jd: JobDescription,
    ) -> str:
        """Build a human-readable summary string."""
        title = jd.title or "this role"
        return (
            f"For {title}: you match {len(matching)} of {len(matching) + len(missing_req)} "
            f"required skills ({coverage_pct:.0f}% coverage). "
            f"Missing required: {len(missing_req)} | Missing preferred: {len(missing_nice)}."
        )
