# JobIntel Skill

**Version:** 1.0.0
**Author:** Faheem
**Language:** Python 3.11+
**Category:** Productivity / Career

## Overview

JobIntel is an intelligent job search and application tracking assistant designed for AI Engineers, Data Scientists, and Python Developers targeting roles in Germany. It automates the tedious parts of a job search: analysing job descriptions, tracking applications, identifying CV gaps, and delivering daily summaries.

## Capabilities

| Tool | Description |
|------|-------------|
| `analyze_job_description` | Extract skills, seniority, salary, and match score from raw JD text |
| `track_application` | Create or update a job application record |
| `update_application_status` | Advance an application through the hiring pipeline |
| `list_applications` | Query and filter your application list |
| `analyze_cv_gap` | Compare a JD against your profile and return missing keywords |
| `get_daily_digest` | Generate a structured daily summary of your job search |
| `search_jobs` | Search LinkedIn, Indeed, and StepStone for matching roles |
| `set_candidate_profile` | Store your skills, experience, and preferences |
| `get_stats` | Return application counts and pipeline overview |

---

## Tool Definitions

### 1. `analyze_job_description`

**Description:** Parse and analyse a raw job description. Extracts required skills, seniority level, years of experience, salary range, education requirements, and language requirements. Optionally computes a match score against the stored candidate profile.

**Input:**
```json
{
  "raw_text": "string (required) — full job description text",
  "title": "string (optional) — job title override",
  "company": "string (optional) — company name",
  "location": "string (optional) — job location",
  "compute_match": "boolean (optional, default: true) — whether to compute match score"
}
```

**Output:**
```json
{
  "job": {
    "title": "string",
    "company": "string",
    "location": "string",
    "required_skills": ["list of strings"],
    "nice_to_have_skills": ["list of strings"],
    "seniority": "junior|mid|senior|lead|principal|intern|unknown",
    "years_required": "number | null",
    "education_required": "string",
    "salary_min": "number | null",
    "salary_max": "number | null",
    "keywords": ["list of strings"],
    "language_requirements": ["list of strings"],
    "remote_ok": "boolean"
  },
  "match_score": "number (0.0–1.0)",
  "match_label": "Strong Match | Good Match | Weak Match | Poor Match",
  "score_breakdown": {
    "skills": "number",
    "experience": "number",
    "education": "number",
    "location": "number"
  },
  "top_matching_skills": ["list of strings"],
  "summary": "string"
}
```

---

### 2. `track_application`

**Description:** Log a new job application to the tracker. Assigns a unique ID and stores all metadata.

**Input:**
```json
{
  "company": "string (required)",
  "role": "string (required)",
  "location": "string (optional)",
  "url": "string (optional) — link to job posting",
  "status": "wishlist|applied|phone_screen|technical|onsite|offer|rejected|withdrawn|accepted (optional, default: wishlist)",
  "applied_date": "string (optional) — ISO-8601 date YYYY-MM-DD",
  "deadline": "string (optional) — ISO-8601 date",
  "notes": "string (optional)",
  "contact": "string (optional) — recruiter name",
  "salary_min": "integer (optional)",
  "salary_max": "integer (optional)"
}
```

**Output:**
```json
{
  "id": "string — UUID",
  "company": "string",
  "role": "string",
  "status": "string",
  "created_at": "string"
}
```

---

### 3. `update_application_status`

**Description:** Advance an application through the hiring pipeline. Enforces valid state transitions (e.g. cannot jump from Wishlist to Offer).

**Input:**
```json
{
  "app_id": "string (required) — application UUID",
  "new_status": "string (required) — target status"
}
```

**Output:**
```json
{
  "id": "string",
  "company": "string",
  "role": "string",
  "previous_status": "string",
  "new_status": "string",
  "updated_at": "string"
}
```

---

### 4. `list_applications`

**Description:** Query applications with optional filters. Returns a summary table.

**Input:**
```json
{
  "status": "string (optional) — filter by status",
  "company": "string (optional) — company name substring filter",
  "limit": "integer (optional, default: 50)"
}
```

**Output:**
```json
{
  "count": "integer",
  "applications": [
    {
      "id": "string",
      "company": "string",
      "role": "string",
      "location": "string",
      "status": "string",
      "applied_date": "string | null",
      "deadline": "string | null",
      "match_score": "number | null"
    }
  ]
}
```

---

### 5. `analyze_cv_gap`

**Description:** Compare a job description against the stored candidate profile. Returns missing required skills, missing nice-to-have skills, coverage percentage, and actionable suggestions.

**Input:**
```json
{
  "raw_jd_text": "string (required) — full job description",
  "title": "string (optional)",
  "company": "string (optional)"
}
```

**Output:**
```json
{
  "missing_required": ["list of strings"],
  "missing_nice_to_have": ["list of strings"],
  "matching_skills": ["list of strings"],
  "coverage_pct": "number (0–100)",
  "priority_gaps": ["list of strings"],
  "suggested_additions": ["list of strings"],
  "summary": "string"
}
```

---

### 6. `get_daily_digest`

**Description:** Generate a daily summary of your job search: active applications, upcoming deadlines, recent updates, and pipeline statistics.

**Input:**
```json
{}
```

**Output:**
```json
{
  "generated_at": "string — ISO datetime",
  "stats": {"status_name": "count"},
  "pending_count": "integer",
  "upcoming_deadlines": ["list of application summaries"],
  "recent_updates": ["list of application summaries"],
  "summary": "string",
  "formatted_text": "string — human-readable multi-line report"
}
```

---

### 7. `search_jobs`

**Description:** Search for job listings on LinkedIn, Indeed, StepStone, and XING. Results are cached to reduce external requests.

**Input:**
```json
{
  "query": "string (required) — job title / keywords",
  "location": "string (optional, default: Germany)",
  "sources": ["list of strings (optional) — e.g. ['linkedin', 'indeed']"]
}
```

**Output:**
```json
{
  "count": "integer",
  "results": [
    {
      "title": "string",
      "company": "string",
      "location": "string",
      "url": "string",
      "snippet": "string",
      "source": "string"
    }
  ]
}
```

---

### 8. `set_candidate_profile`

**Description:** Store or update your candidate profile: skills, years of experience, education, and target preferences. Used as the reference for all match scoring and gap analysis.

**Input:**
```json
{
  "name": "string (required)",
  "email": "string (optional)",
  "skills": [
    {
      "name": "string",
      "category": "language|ml_framework|data_tool|cloud|cv_tool|llm_tool|web_framework|soft_skill|other",
      "proficiency": "number 0–1 (optional)"
    }
  ],
  "years_of_experience": "number (optional)",
  "education_level": "string (optional) — e.g. MSc, BSc, PhD",
  "education_field": "string (optional)",
  "target_roles": ["list of strings"],
  "target_locations": ["list of strings"],
  "cv_raw_text": "string (optional) — paste your full CV text"
}
```

**Output:**
```json
{
  "status": "saved",
  "name": "string",
  "skills_count": "integer",
  "updated_at": "string"
}
```

---

### 9. `get_stats`

**Description:** Return a high-level overview of your application pipeline.

**Input:**
```json
{}
```

**Output:**
```json
{
  "total": "integer",
  "by_status": {"status_name": "count"},
  "active": "integer",
  "response_rate_pct": "number",
  "offer_rate_pct": "number"
}
```

---

## Usage Examples

### Analyse a job description and get match score
```
User: Analyse this JD for me: [paste JD text]
→ Returns: required skills, seniority, salary, match score, and breakdown
```

### Log a new application
```
User: Add application: Senior ML Engineer at Celonis, Berlin, applied today
→ Returns: new application ID and confirmation
```

### Morning digest
```
User: Show me my daily job search digest
→ Returns: formatted summary of all active applications, deadlines, and stats
```

### Find gaps before applying
```
User: What skills am I missing for this role? [paste JD]
→ Returns: missing required/optional skills and CV improvement suggestions
```

### Search for roles
```
User: Search for Python AI Engineer jobs in Berlin
→ Returns: top matching results from LinkedIn, Indeed, StepStone
```

---

## Architecture

```
skill.py (entry point / dispatcher)
    │
    ├── src/analyzers/
    │   ├── jd_parser.py       ← Raw text → JobDescription model
    │   ├── gap_analyzer.py    ← Profile × JD → GapReport
    │   └── match_scorer.py    ← Profile × JD → AnalysisResult (0–1 score)
    │
    ├── src/tracker/
    │   └── application_tracker.py  ← CRUD + state machine
    │
    ├── src/digest/
    │   └── daily_digest.py    ← Aggregated digest report
    │
    ├── src/search/
    │   └── job_search.py      ← Multi-source web scraping + caching
    │
    ├── src/database/
    │   ├── manager.py         ← SQLite CRUD layer (thread-safe)
    │   └── schema.sql         ← Table definitions
    │
    └── src/models/
        └── models.py          ← Pydantic v2 domain models
```

## Setup

```bash
pip install -r requirements.txt
python -c "import nltk; nltk.download('punkt')"
python skill.py
```

## Configuration

Edit `config.yaml` to customise:
- Scoring weights for match calculation
- Target locations and roles
- Database path
- Digest schedule and digest window
- Search sources and result limits
