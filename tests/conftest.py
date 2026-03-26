"""
Shared pytest fixtures for the JobIntel test suite.

Design:
- The database fixture creates a fresh in-memory SQLite instance for each test
  function, ensuring full isolation without touching the filesystem.
- The config fixture returns a minimal but structurally complete config dict
  that mirrors config.yaml.
- The candidate_profile fixture provides a realistic profile for scoring tests.
"""

from __future__ import annotations

import pytest

from src.database.manager import DatabaseManager
from src.models.models import CandidateProfile, Skill, SkillCategory


@pytest.fixture
def config() -> dict:
    """Return a minimal test configuration dict."""
    return {
        "database": {"path": ":memory:", "backup_dir": "/tmp/backups"},
        "candidate": {
            "name": "Test User",
            "target_roles": ["AI Engineer", "Data Scientist"],
            "target_locations": ["Berlin", "Munich", "Remote"],
            "target_countries": ["Germany"],
        },
        "scoring": {
            "skills_weight": 0.50,
            "experience_weight": 0.25,
            "education_weight": 0.15,
            "location_weight": 0.10,
            "strong_match_threshold": 0.75,
            "good_match_threshold": 0.55,
            "weak_match_threshold": 0.35,
        },
        "digest": {
            "lookback_days": 7,
            "upcoming_deadline_days": 3,
        },
        "search": {
            "default_location": "Germany",
            "results_per_query": 20,
            "sources": ["linkedin", "indeed"],
        },
        "logging": {
            "level": "WARNING",
            "file": "/tmp/test_jobintel.log",
        },
        "seniority": {
            "junior_keywords": ["junior", "entry level", "graduate", "0-2 years"],
            "senior_keywords": ["senior", "lead", "5+ years", "7+ years"],
            "tech_categories": {
                "languages": ["python", "java", "javascript", "typescript", "golang", "rust"],
                "ml_frameworks": ["pytorch", "tensorflow", "scikit-learn", "huggingface"],
                "data_tools": ["sql", "spark", "kafka", "pandas", "numpy"],
                "cloud": ["aws", "gcp", "azure", "docker", "kubernetes"],
                "cv_tools": ["opencv", "pillow", "torchvision"],
                "llm_tools": ["langchain", "openai", "anthropic", "rag"],
                "web_frameworks": ["fastapi", "flask", "django", "streamlit"],
            },
        },
    }


@pytest.fixture
def db(tmp_path) -> DatabaseManager:
    """Return a fresh DatabaseManager backed by a temp file for each test."""
    db_file = str(tmp_path / "test_jobintel.db")
    manager = DatabaseManager(db_file)
    yield manager
    manager.close()


@pytest.fixture
def candidate_profile() -> CandidateProfile:
    """Return a realistic candidate profile for testing."""
    return CandidateProfile(
        name="Faheem Test",
        email="faheem@test.com",
        skills=[
            Skill(name="python", category=SkillCategory.LANGUAGE, proficiency=0.95),
            Skill(name="pytorch", category=SkillCategory.ML_FRAMEWORK, proficiency=0.85),
            Skill(name="tensorflow", category=SkillCategory.ML_FRAMEWORK, proficiency=0.75),
            Skill(name="scikit-learn", category=SkillCategory.ML_FRAMEWORK, proficiency=0.90),
            Skill(name="sql", category=SkillCategory.DATA_TOOL, proficiency=0.80),
            Skill(name="docker", category=SkillCategory.CLOUD, proficiency=0.70),
            Skill(name="aws", category=SkillCategory.CLOUD, proficiency=0.65),
            Skill(name="fastapi", category=SkillCategory.WEB_FRAMEWORK, proficiency=0.75),
            Skill(name="opencv", category=SkillCategory.CV_TOOL, proficiency=0.80),
            Skill(name="pandas", category=SkillCategory.DATA_TOOL, proficiency=0.90),
            Skill(name="numpy", category=SkillCategory.DATA_TOOL, proficiency=0.90),
        ],
        years_of_experience=3.5,
        education_level="MSc",
        education_field="Computer Science",
        languages=["English", "German"],
        target_roles=["AI Engineer", "Data Scientist", "ML Engineer"],
        target_locations=["Berlin", "Munich", "Remote"],
        cv_raw_text=(
            "Experienced ML engineer with 3.5 years building production AI systems. "
            "Proficient in Python, PyTorch, TensorFlow, scikit-learn, SQL, Docker, AWS. "
            "Computer Vision specialist with OpenCV. FastAPI for model serving. "
            "MSc Computer Science. Fluent in English and German."
        ),
    )


@pytest.fixture
def sample_jd_text() -> str:
    """Return a realistic AI Engineer job description for testing."""
    return """
Senior AI Engineer — Berlin (Hybrid)

Company: TechCorp GmbH
Location: Berlin, Germany (Hybrid — 2 days on-site)
Salary: €80,000 – €110,000

About the Role:
We are looking for a Senior AI Engineer to join our Machine Learning platform team.
You will design, build, and deploy production ML systems at scale.

Requirements:
- 5+ years of professional experience in software engineering or ML
- Strong proficiency in Python (our primary language)
- Experience with PyTorch or TensorFlow for deep learning
- Proficiency with scikit-learn and classical ML techniques
- Knowledge of SQL and working with large datasets
- Experience with Docker and Kubernetes for containerised deployments
- Familiarity with AWS or GCP cloud platforms
- MSc or higher in Computer Science, Mathematics, or related field
- Fluent in English; German is a plus

Nice to Have:
- Experience with LangChain or similar LLM frameworks
- Knowledge of MLflow or similar MLOps tools
- Computer Vision experience (OpenCV, torchvision)
- FastAPI or similar for model serving

What we offer:
- Competitive salary (€80k – €110k)
- Flexible working hours and hybrid setup
- Annual conference budget
- 30 days holiday
"""
