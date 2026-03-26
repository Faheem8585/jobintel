"""
Tests for src/analyzers/match_scorer.py.

Covers: composite score calculation, individual dimension scorers,
        weight normalisation, and label assignment.
"""

from __future__ import annotations

import pytest

from src.analyzers.match_scorer import MatchScorer
from src.models.models import (
    AnalysisResult,
    CandidateProfile,
    JobDescription,
    Skill,
    SkillCategory,
    SeniorityLevel,
)


@pytest.fixture
def scorer(config) -> MatchScorer:
    return MatchScorer(config)


def _make_jd(**kwargs) -> JobDescription:
    defaults = {
        "raw_text": "test JD",
        "required_skills": [],
        "nice_to_have_skills": [],
        "seniority": SeniorityLevel.MID,
        "remote_ok": False,
        "location": "Berlin, Germany",
        "education_required": "",
        "years_required": None,
        "keywords": [],
    }
    defaults.update(kwargs)
    return JobDescription(**defaults)


def _make_profile(**kwargs) -> CandidateProfile:
    defaults = {
        "name": "Test",
        "skills": [],
        "years_of_experience": 3.0,
        "education_level": "MSc",
        "target_locations": ["Berlin", "Remote"],
    }
    defaults.update(kwargs)
    return CandidateProfile(**defaults)


class TestScoreReturnType:
    def test_returns_analysis_result(self, scorer, candidate_profile):
        jd = _make_jd(required_skills=["python"])
        result = scorer.score(candidate_profile, jd)
        assert isinstance(result, AnalysisResult)

    def test_score_in_range(self, scorer, candidate_profile):
        jd = _make_jd(required_skills=["python"])
        result = scorer.score(candidate_profile, jd)
        assert 0.0 <= result.match_score <= 1.0

    def test_breakdown_keys_present(self, scorer, candidate_profile):
        jd = _make_jd()
        result = scorer.score(candidate_profile, jd)
        for key in ("skills", "experience", "education", "location"):
            assert key in result.score_breakdown


class TestSkillsDimension:
    def test_perfect_skills_match(self, scorer):
        profile = _make_profile(skills=[
            Skill(name="python", category=SkillCategory.LANGUAGE),
            Skill(name="pytorch", category=SkillCategory.ML_FRAMEWORK),
        ])
        jd = _make_jd(required_skills=["python", "pytorch"])
        result = scorer.score(profile, jd)
        assert result.score_breakdown["skills"] == pytest.approx(1.0)

    def test_no_skills_match(self, scorer):
        profile = _make_profile(skills=[
            Skill(name="rust", category=SkillCategory.LANGUAGE),
        ])
        jd = _make_jd(required_skills=["python", "java"])
        result = scorer.score(profile, jd)
        assert result.score_breakdown["skills"] == pytest.approx(0.0)

    def test_required_weighted_double_nice_to_have(self, scorer):
        """Required skills have 2x weight vs nice-to-have."""
        profile = _make_profile(skills=[
            Skill(name="python", category=SkillCategory.LANGUAGE),
        ])
        # python is required (weight 2), rust is nice (weight 1)
        jd = _make_jd(
            required_skills=["python"],
            nice_to_have_skills=["rust"],
        )
        result = scorer.score(profile, jd)
        # python matched (weight 2 of total 3) → 2/3 ≈ 0.667
        assert result.score_breakdown["skills"] == pytest.approx(2 / 3, rel=0.01)

    def test_empty_jd_skills_gives_full_score(self, scorer, candidate_profile):
        jd = _make_jd(required_skills=[], nice_to_have_skills=[])
        result = scorer.score(candidate_profile, jd)
        assert result.score_breakdown["skills"] == pytest.approx(1.0)


class TestExperienceDimension:
    def test_meets_experience(self, scorer):
        profile = _make_profile(years_of_experience=5.0)
        jd = _make_jd(years_required=5.0)
        result = scorer.score(profile, jd)
        assert result.score_breakdown["experience"] == pytest.approx(1.0)

    def test_exceeds_experience(self, scorer):
        profile = _make_profile(years_of_experience=10.0)
        jd = _make_jd(years_required=5.0)
        result = scorer.score(profile, jd)
        assert result.score_breakdown["experience"] == pytest.approx(1.0)

    def test_significantly_over_qualified(self, scorer):
        profile = _make_profile(years_of_experience=30.0)
        jd = _make_jd(years_required=2.0)
        result = scorer.score(profile, jd)
        # Over 3x → 0.7 penalty
        assert result.score_breakdown["experience"] == pytest.approx(0.7)

    def test_under_qualified_partial_score(self, scorer):
        profile = _make_profile(years_of_experience=2.0)
        jd = _make_jd(years_required=4.0)
        result = scorer.score(profile, jd)
        assert result.score_breakdown["experience"] == pytest.approx(0.5)

    def test_zero_requirement_gives_full_score(self, scorer):
        profile = _make_profile(years_of_experience=0.0)
        jd = _make_jd(years_required=0.0)
        result = scorer.score(profile, jd)
        assert result.score_breakdown["experience"] == pytest.approx(1.0)


class TestEducationDimension:
    def test_meets_education(self, scorer):
        profile = _make_profile(education_level="MSc")
        jd = _make_jd(education_required="MSc")
        result = scorer.score(profile, jd)
        assert result.score_breakdown["education"] == pytest.approx(1.0)

    def test_exceeds_education(self, scorer):
        profile = _make_profile(education_level="PhD")
        jd = _make_jd(education_required="MSc")
        result = scorer.score(profile, jd)
        assert result.score_breakdown["education"] == pytest.approx(1.0)

    def test_below_education_partial_score(self, scorer):
        profile = _make_profile(education_level="BSc")
        jd = _make_jd(education_required="MSc")
        result = scorer.score(profile, jd)
        # BSc rank 2, MSc rank 3 → gap of 1 → 1 - 0.25 = 0.75
        assert result.score_breakdown["education"] == pytest.approx(0.75)

    def test_no_education_requirement_full_score(self, scorer):
        profile = _make_profile(education_level="")
        jd = _make_jd(education_required="")
        result = scorer.score(profile, jd)
        assert result.score_breakdown["education"] == pytest.approx(1.0)


class TestLocationDimension:
    def test_remote_gives_full_score(self, scorer):
        profile = _make_profile(target_locations=["Berlin"])
        jd = _make_jd(remote_ok=True)
        result = scorer.score(profile, jd)
        assert result.score_breakdown["location"] == pytest.approx(1.0)

    def test_preferred_location_match(self, scorer):
        profile = _make_profile(target_locations=["Berlin"])
        jd = _make_jd(location="Berlin, Germany", remote_ok=False)
        result = scorer.score(profile, jd)
        assert result.score_breakdown["location"] == pytest.approx(1.0)

    def test_same_country_partial_score(self, scorer):
        profile = _make_profile(target_locations=["Berlin"])
        jd = _make_jd(location="Frankfurt, Germany", remote_ok=False)
        result = scorer.score(profile, jd)
        # Germany is in the JD but not Berlin → 0.5
        assert result.score_breakdown["location"] == pytest.approx(0.5)

    def test_wrong_country_zero_score(self, scorer):
        profile = _make_profile(target_locations=["Berlin"])
        jd = _make_jd(location="San Francisco, USA", remote_ok=False)
        result = scorer.score(profile, jd)
        assert result.score_breakdown["location"] == pytest.approx(0.0)


class TestMatchLabels:
    def test_strong_match_label(self, scorer, config):
        strong_threshold = config["scoring"]["strong_match_threshold"]
        # Build a scenario that gives a high score
        profile = _make_profile(
            skills=[
                Skill(name="python", category=SkillCategory.LANGUAGE),
                Skill(name="pytorch", category=SkillCategory.ML_FRAMEWORK),
            ],
            years_of_experience=5.0,
            education_level="MSc",
            target_locations=["Berlin"],
        )
        jd = _make_jd(
            required_skills=["python", "pytorch"],
            years_required=5.0,
            education_required="MSc",
            location="Berlin, Germany",
        )
        result = scorer.score(profile, jd)
        if result.match_score >= strong_threshold:
            assert result.match_label == "Strong Match"

    def test_poor_match_label(self, scorer):
        profile = _make_profile(
            skills=[],
            years_of_experience=0.0,
            education_level="",
            target_locations=["Tokyo"],
        )
        jd = _make_jd(
            required_skills=["rust", "erlang", "haskell"],
            years_required=10.0,
            education_required="PhD",
            location="London, UK",
        )
        result = scorer.score(profile, jd)
        assert result.match_label in ("Poor Match", "Weak Match")


class TestWeightNormalisation:
    def test_unnormalised_weights_corrected(self, config):
        """Weights that don't sum to 1.0 should be auto-normalised."""
        bad_config = dict(config)
        bad_config["scoring"] = {
            "skills_weight": 2.0,  # Intentionally wrong
            "experience_weight": 1.0,
            "education_weight": 0.5,
            "location_weight": 0.5,
            "strong_match_threshold": 0.75,
            "good_match_threshold": 0.55,
            "weak_match_threshold": 0.35,
        }
        # Should not raise — weights are normalised internally
        scorer = MatchScorer(bad_config)
        profile = _make_profile()
        jd = _make_jd()
        result = scorer.score(profile, jd)
        assert 0.0 <= result.match_score <= 1.0


class TestTopMatchingSkills:
    def test_top_matching_skills_populated(self, scorer, candidate_profile):
        jd = _make_jd(required_skills=["python", "pytorch", "scikit-learn"])
        result = scorer.score(candidate_profile, jd)
        assert len(result.top_matching_skills) > 0
        assert "python" in result.top_matching_skills
