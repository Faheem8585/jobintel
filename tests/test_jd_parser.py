"""
Tests for src/analyzers/jd_parser.py.

Covers: skill extraction, seniority detection, salary parsing,
        education parsing, remote detection, and language extraction.
"""

from __future__ import annotations

import pytest

from src.analyzers.jd_parser import JobDescriptionParser
from src.models.models import SeniorityLevel


@pytest.fixture
def parser(config) -> JobDescriptionParser:
    return JobDescriptionParser(config)


class TestParse:
    def test_returns_job_description(self, parser, sample_jd_text):
        jd = parser.parse(sample_jd_text)
        assert jd.raw_text == sample_jd_text

    def test_empty_text_returns_empty_jd(self, parser):
        jd = parser.parse("")
        assert jd.required_skills == []
        assert jd.keywords == []

    def test_title_override(self, parser):
        jd = parser.parse("Python Developer needed", title="AI Engineer")
        assert jd.title == "AI Engineer"

    def test_company_and_location_preserved(self, parser):
        jd = parser.parse("We need a developer", company="Celonis", location="Munich")
        assert jd.company == "Celonis"
        assert jd.location == "Munich"


class TestSkillExtraction:
    def test_extracts_known_tech_skills(self, parser, sample_jd_text):
        jd = parser.parse(sample_jd_text)
        skill_names = jd.required_skills + jd.nice_to_have_skills
        assert "python" in skill_names or "python" in jd.keywords

    def test_extracts_python(self, parser):
        jd = parser.parse("Requirements:\n- Proficiency in Python\n- SQL experience required")
        skills = jd.required_skills + jd.keywords
        assert "python" in skills

    def test_extracts_pytorch(self, parser):
        jd = parser.parse("Requirements:\n- PyTorch for deep learning models")
        skills = jd.required_skills + jd.keywords
        assert "pytorch" in skills

    def test_nice_to_have_separated(self, parser):
        text = (
            "Requirements:\n- Python\n- SQL\n\n"
            "Nice to Have:\n- Kubernetes\n- MLflow\n"
        )
        jd = parser.parse(text)
        assert "python" in jd.required_skills or "python" in jd.keywords
        assert "kubernetes" in jd.nice_to_have_skills or "kubernetes" in jd.keywords

    def test_no_duplicate_skills(self, parser):
        text = "Requirements:\n- Python is required\n- Python proficiency needed\n"
        jd = parser.parse(text)
        assert jd.required_skills.count("python") == 1


class TestSeniorityDetection:
    def test_senior_detected(self, parser):
        jd = parser.parse("We need a Senior Software Engineer with 5+ years of experience.")
        assert jd.seniority == SeniorityLevel.SENIOR

    def test_junior_detected(self, parser):
        jd = parser.parse("Junior Developer role, entry level, 0-2 years of experience.")
        assert jd.seniority in (SeniorityLevel.JUNIOR, SeniorityLevel.MID)

    def test_lead_detected(self, parser):
        jd = parser.parse("Tech Lead position managing a team of engineers.")
        assert jd.seniority == SeniorityLevel.LEAD

    def test_intern_detected(self, parser):
        jd = parser.parse("Werkstudent / Intern position for students.")
        assert jd.seniority == SeniorityLevel.INTERN

    def test_unknown_seniority(self, parser):
        jd = parser.parse("Software Developer position at our startup.")
        # Without explicit signals, seniority is UNKNOWN or inferred from years
        assert jd.seniority in (SeniorityLevel.UNKNOWN, SeniorityLevel.MID, SeniorityLevel.JUNIOR)

    def test_seniority_from_sample_jd(self, parser, sample_jd_text):
        jd = parser.parse(sample_jd_text)
        assert jd.seniority == SeniorityLevel.SENIOR


class TestSalaryExtraction:
    def test_range_in_thousands(self, parser):
        jd = parser.parse("Salary: €80k – €110k per year")
        assert jd.salary_min == 80000
        assert jd.salary_max == 110000

    def test_range_with_comma(self, parser):
        jd = parser.parse("Compensation: $90,000 - $120,000")
        assert jd.salary_min == 90000
        assert jd.salary_max == 120000

    def test_no_salary_returns_none(self, parser):
        jd = parser.parse("Competitive salary offered based on experience.")
        assert jd.salary_min is None
        assert jd.salary_max is None

    def test_salary_from_sample_jd(self, parser, sample_jd_text):
        jd = parser.parse(sample_jd_text)
        assert jd.salary_min == 80000
        assert jd.salary_max == 110000


class TestEducationExtraction:
    def test_msc_detected(self, parser):
        jd = parser.parse("MSc or higher in Computer Science required.")
        assert jd.education_required == "MSc"

    def test_phd_detected(self, parser):
        jd = parser.parse("PhD in Machine Learning preferred.")
        assert jd.education_required == "PhD"

    def test_bsc_detected(self, parser):
        jd = parser.parse("Bachelor's degree in any engineering discipline.")
        assert jd.education_required == "BSc"

    def test_no_education_returns_empty(self, parser):
        jd = parser.parse("Great opportunity for self-taught developers.")
        assert jd.education_required == ""


class TestRemoteDetection:
    def test_remote_ok_true(self, parser):
        jd = parser.parse("Fully remote position — work from anywhere in Europe.")
        assert jd.remote_ok is True

    def test_hybrid_detected(self, parser):
        jd = parser.parse("Hybrid role, 2 days in office per week.")
        assert jd.remote_ok is True

    def test_on_site_only(self, parser):
        jd = parser.parse("On-site role in Berlin, no remote work available.")
        assert jd.remote_ok is False


class TestLanguageExtraction:
    def test_english_detected(self, parser):
        jd = parser.parse("Fluent English required for team communication.")
        assert "English" in jd.language_requirements

    def test_german_detected(self, parser):
        jd = parser.parse("German or Deutsch language skills are a plus.")
        assert "German" in jd.language_requirements

    def test_multiple_languages(self, parser):
        jd = parser.parse("English and French are required; German is nice to have.")
        assert "English" in jd.language_requirements
        assert "French" in jd.language_requirements


class TestYearsExtraction:
    def test_extract_years(self, parser):
        jd = parser.parse("Minimum 5 years of experience in software development.")
        assert jd.years_required == pytest.approx(5.0)

    def test_multiple_years_takes_minimum(self, parser):
        jd = parser.parse("3 years minimum experience, ideally 7 years for senior.")
        assert jd.years_required == pytest.approx(3.0)

    def test_no_years_mentioned(self, parser):
        jd = parser.parse("Experience in Python and ML frameworks.")
        assert jd.years_required is None
