"""
Job Description Parser.

Extracts structured information from raw job description text using:
- Regex patterns for salary, years of experience, education
- Config-driven keyword lists for skills and seniority
- A simple noun-phrase heuristic for keyword extraction

Design: stateless class — instantiate once and call parse() many times.
The config is injected at construction to keep the class testable without
touching the filesystem.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.models.models import JobDescription, SeniorityLevel

logger = logging.getLogger(__name__)


class JobDescriptionParser:
    """Parse raw job description text into a structured JobDescription model."""

    # Patterns for salary extraction (handles €, $, £ and k/K suffix)
    _SALARY_PATTERN = re.compile(
        r"(?P<currency>[€$£])?\s*(?P<min>\d{2,3})(?:k|K|,000)?"
        r"\s*[-–—to]+\s*"
        r"(?P<currency2>[€$£])?\s*(?P<max>\d{2,3})(?:k|K|,000)?",
        re.IGNORECASE,
    )
    _SALARY_SINGLE = re.compile(
        r"(?:up to|bis zu|from|ab|circa|ca\.?)\s*"
        r"(?P<currency>[€$£])?\s*(?P<amount>\d{2,3})(?:k|K|,000)?",
        re.IGNORECASE,
    )

    # Pattern for years of experience — broad match: "3 years", "5+ years of experience",
    # "minimum 3 years", "ideally 7 years"
    _YEARS_PATTERN = re.compile(
        r"(\d+)\+?\s*(?:years?|Jahre?)",
        re.IGNORECASE,
    )

    # Patterns for required vs. nice-to-have sections
    _SECTION_REQUIRED = re.compile(
        r"(?:requirements?|required|must.have|you.bring|qualifications?|"
        r"anforderungen|voraussetzungen|was du mitbringst)",
        re.IGNORECASE,
    )
    _SECTION_NICE = re.compile(
        r"(?:nice.to.have|preferred|bonus|plus|desirable|von.vorteil|wünschenswert)",
        re.IGNORECASE,
    )

    # Remote work signals — must not be preceded by "no" or "not" (negation)
    # Positive: "remote", "fully remote", "home office", "hybrid", "distributed"
    # Negative: "no remote", "not remote", "no remote work"
    _REMOTE_POSITIVE = re.compile(
        r"\b(?:fully.?remote|home.?office|distributed|hybrid)\b"
        r"|\bremote\b(?!\s+work\s+available)",
        re.IGNORECASE,
    )
    _REMOTE_NEGATIVE = re.compile(
        r"\bno\s+remote\b|\bnot\s+remote\b|\bno\s+home.?office\b"
        r"|\bon.?site\s+only\b|\bpresence\s+required\b",
        re.IGNORECASE,
    )

    # Education levels
    _EDU_PATTERNS = [
        (re.compile(r"\b(?:phd|doctorate|doktor)\b", re.IGNORECASE), "PhD"),
        (re.compile(r"\b(?:master|msc|m\.sc|ma\b|m\.eng)\b", re.IGNORECASE), "MSc"),
        (re.compile(r"\b(?:bachelor|bsc|b\.sc|b\.eng|ba\b)\b", re.IGNORECASE), "BSc"),
        (re.compile(r"\b(?:ausbildung|apprenticeship|vocational)\b", re.IGNORECASE), "Vocational"),
    ]

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialise parser with configuration.

        Args:
            config: Parsed config.yaml as a dict. Expected keys:
                    seniority.junior_keywords, seniority.senior_keywords,
                    seniority.tech_categories.
        """
        self._cfg = config
        self._seniority_cfg = config.get("seniority", {})
        self._junior_kw: List[str] = self._seniority_cfg.get("junior_keywords", [])
        self._senior_kw: List[str] = self._seniority_cfg.get("senior_keywords", [])
        self._tech_categories: Dict[str, List[str]] = (
            self._seniority_cfg.get("tech_categories", {})
        )
        # Flatten all known tech keywords for O(1) membership tests
        self._all_tech: Set[str] = {
            kw.lower()
            for kws in self._tech_categories.values()
            for kw in kws
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, raw_text: str, title: str = "", company: str = "", location: str = "") -> JobDescription:
        """
        Parse a raw job description string into a JobDescription model.

        Args:
            raw_text: The full text of the job posting.
            title:    Optional job title (overrides any extraction).
            company:  Optional company name.
            location: Optional location string.

        Returns:
            Populated JobDescription instance.
        """
        text = raw_text.strip()
        if not text:
            logger.warning("Received empty job description text.")
            return JobDescription(raw_text=raw_text)

        required_skills, nice_skills = self._extract_skills(text)
        salary_min, salary_max = self._extract_salary(text)

        jd = JobDescription(
            title=title or self._extract_title(text),
            company=company,
            location=location,
            raw_text=raw_text,
            required_skills=required_skills,
            nice_to_have_skills=nice_skills,
            seniority=self._detect_seniority(text),
            years_required=self._extract_years(text),
            education_required=self._extract_education(text),
            salary_min=salary_min,
            salary_max=salary_max,
            keywords=self._extract_keywords(text),
            language_requirements=self._extract_languages(text),
            remote_ok=self._detect_remote(text),
        )
        logger.debug("Parsed JD: %d required skills, seniority=%s", len(required_skills), jd.seniority)
        return jd

    # ------------------------------------------------------------------
    # Private extraction helpers
    # ------------------------------------------------------------------

    def _extract_skills(self, text: str) -> Tuple[List[str], List[str]]:
        """
        Split text into required vs. nice-to-have sections and extract skills.

        Returns:
            Tuple of (required_skills, nice_to_have_skills) lists.
        """
        lines = text.splitlines()
        required: List[str] = []
        nice: List[str] = []
        current_section: str = "required"  # default

        for line in lines:
            if self._SECTION_NICE.search(line):
                current_section = "nice"
                continue
            if self._SECTION_REQUIRED.search(line):
                current_section = "required"
                continue

            found = self._skills_in_line(line)
            if current_section == "nice":
                nice.extend(found)
            else:
                required.extend(found)

        # Deduplicate preserving order
        required = list(dict.fromkeys(required))
        nice = [s for s in dict.fromkeys(nice) if s not in required]
        return required, nice

    def _skills_in_line(self, line: str) -> List[str]:
        """Return all known tech keywords found in a single line of text."""
        line_lower = line.lower()
        return [kw for kw in self._all_tech if re.search(rf"\b{re.escape(kw)}\b", line_lower)]

    def _extract_keywords(self, text: str) -> List[str]:
        """
        Extract a broader set of keywords (tech + domain terms) using the
        entire text, returned as a deduplicated list.

        Uses the union of found tech keywords plus common domain terms that
        appear without needing section context.
        """
        text_lower = text.lower()
        found = [kw for kw in self._all_tech if re.search(rf"\b{re.escape(kw)}\b", text_lower)]

        # Additional domain keywords that are useful but not in tech_categories
        domain_extras = [
            "agile", "scrum", "ci/cd", "devops", "microservices", "api",
            "rest", "grpc", "mlops", "data pipeline", "etl", "elt",
            "a/b testing", "experimentation", "monitoring", "observability",
            "unit testing", "tdd", "code review", "git", "github", "gitlab",
            "jira", "confluence",
        ]
        for kw in domain_extras:
            if re.search(rf"\b{re.escape(kw)}\b", text_lower):
                found.append(kw)

        return list(dict.fromkeys(found))

    def _detect_seniority(self, text: str) -> SeniorityLevel:
        """
        Infer seniority level from keyword signals in the text.

        Returns:
            SeniorityLevel enum value.
        """
        text_lower = text.lower()

        # Check explicit seniority keywords in defined order (most specific first)
        seniority_map = [
            ("principal", SeniorityLevel.PRINCIPAL),
            ("staff engineer", SeniorityLevel.STAFF),
            ("lead", SeniorityLevel.LEAD),
            ("senior", SeniorityLevel.SENIOR),
            ("mid-level", SeniorityLevel.MID),
            ("mid level", SeniorityLevel.MID),
            ("intern", SeniorityLevel.INTERN),
            ("werkstudent", SeniorityLevel.INTERN),
            ("trainee", SeniorityLevel.INTERN),
        ]
        for keyword, level in seniority_map:
            if keyword in text_lower:
                return level

        # Fall back to config-driven keyword lists
        if any(kw in text_lower for kw in self._junior_kw):
            return SeniorityLevel.JUNIOR
        if any(kw in text_lower for kw in self._senior_kw):
            return SeniorityLevel.SENIOR

        # Infer from required years
        years = self._extract_years(text)
        if years is not None:
            if years <= 1:
                return SeniorityLevel.JUNIOR
            if years <= 3:
                return SeniorityLevel.MID
            if years <= 6:
                return SeniorityLevel.SENIOR
            return SeniorityLevel.LEAD

        return SeniorityLevel.UNKNOWN

    def _extract_years(self, text: str) -> Optional[float]:
        """
        Extract minimum years of experience from text.

        Returns:
            Float years or None if no mention found.
        """
        matches = self._YEARS_PATTERN.findall(text)
        if not matches:
            return None
        # Take the minimum mentioned (the role's threshold, not an upper bound)
        return min(float(m) for m in matches)

    def _extract_salary(self, text: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Extract salary range from text.

        Returns:
            Tuple of (min, max) in thousands of currency units, or (None, None).
        """
        match = self._SALARY_PATTERN.search(text)
        if match:
            try:
                min_val = int(match.group("min"))
                max_val = int(match.group("max"))
                # Assume values < 200 are in thousands
                if min_val < 200:
                    min_val *= 1000
                if max_val < 200:
                    max_val *= 1000
                return min_val, max_val
            except (ValueError, TypeError):
                pass

        single = self._SALARY_SINGLE.search(text)
        if single:
            try:
                amount = int(single.group("amount"))
                if amount < 200:
                    amount *= 1000
                return None, amount
            except (ValueError, TypeError):
                pass

        return None, None

    def _extract_education(self, text: str) -> str:
        """
        Detect the minimum education requirement.

        Returns:
            Education label string or empty string.
        """
        # Evaluate patterns from highest to lowest and return the highest found
        for pattern, label in self._EDU_PATTERNS:
            if pattern.search(text):
                return label
        return ""

    def _extract_title(self, text: str) -> str:
        """
        Heuristically extract the job title from the first non-empty line.

        Returns:
            Best-guess title string.
        """
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and len(stripped) < 120:
                return stripped
        return ""

    def _detect_remote(self, text: str) -> bool:
        """
        Determine whether the role allows remote work.

        Returns True only if a positive remote signal is found AND no
        explicit negation (e.g. "no remote", "on-site only") overrides it.
        """
        has_positive = bool(self._REMOTE_POSITIVE.search(text))
        has_negative = bool(self._REMOTE_NEGATIVE.search(text))
        return has_positive and not has_negative

    def _extract_languages(self, text: str) -> List[str]:
        """
        Detect spoken language requirements.

        Returns:
            List of language names found (e.g. ['German', 'English']).
        """
        spoken_languages = [
            "english", "german", "deutsch", "french", "spanish",
            "italian", "dutch", "portuguese", "polish", "mandarin",
        ]
        text_lower = text.lower()
        found = [
            lang.capitalize()
            for lang in spoken_languages
            if re.search(rf"\b{lang}\b", text_lower)
        ]
        # Normalise "Deutsch" → "German"
        if "Deutsch" in found and "German" not in found:
            found.append("German")
            found.remove("Deutsch")
        return list(dict.fromkeys(found))
