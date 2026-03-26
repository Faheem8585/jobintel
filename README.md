# JobIntel

**Intelligent job search & application tracking for the German tech market**

I built this to automate the repetitive parts of my job search — parsing JDs, tracking where I've applied, figuring out which skills I'm missing, and getting a quick daily summary of my pipeline. It's structured as a modular skill with a CLI, REST API, Streamlit dashboard, and MCP server interface.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Data models | Pydantic v2 |
| Database | SQLite (stdlib) |
| HTTP client | httpx |
| HTML parsing | BeautifulSoup4 + lxml |
| Text analysis | Regex + keyword matching |
| REST API | FastAPI + uvicorn |
| Dashboard | Streamlit |
| Protocol | MCP (Model Context Protocol) |
| Testing | pytest + pytest-cov + freezegun |
| Linting | flake8 + black + mypy |
| Container | Docker |

---

## Architecture

```
skill.py  <--  handle_tool_call(tool_name, params)
    |
    +-- src/analyzers/
    |   +-- jd_parser.py        Raw text -> JobDescription model
    |   |                       Extracts: skills, seniority, salary,
    |   |                       education, years, languages, remote status
    |   |
    |   +-- gap_analyzer.py     CandidateProfile x JobDescription -> GapReport
    |   |                       Fuzzy matching, alias resolution,
    |   |                       CV text tokenisation, prioritised suggestions
    |   |
    |   +-- match_scorer.py     CandidateProfile x JobDescription -> AnalysisResult
    |                           Weighted composite: skills (50%) + experience (25%)
    |                           + education (15%) + location (10%)
    |
    +-- src/tracker/
    |   +-- application_tracker.py  CRUD + state machine enforcement
    |
    +-- src/digest/
    |   +-- daily_digest.py     Aggregates pipeline into a daily summary
    |
    +-- src/search/
    |   +-- job_search.py       Multi-source scraping: LinkedIn, Indeed,
    |                           StepStone, XING. Results cached in DB.
    |
    +-- src/database/
    |   +-- manager.py          Thread-safe SQLite manager, parameterised SQL
    |   +-- schema.sql          4 tables: applications, candidate_profile,
    |                           search_cache, digest_history
    |
    +-- src/models/
        +-- models.py           Pydantic v2 domain models
```

### Design Decisions

**Separation of concerns** — the data layer (`database/`), business logic (`analyzers/`, `tracker/`, `digest/`), and interface (`skill.py`, `api.py`) are isolated so each can be tested and swapped independently.

**Pydantic v2 for validation** — all domain objects are Pydantic models. External input is never trusted raw; it goes through model validation before hitting the DB.

**Thread-safe DB** — `DatabaseManager` uses a `threading.Lock` to serialise writes, so concurrent tool calls don't corrupt the database.

**Config-driven** — no hardcoded thresholds. All weights, keywords, locations live in `config.yaml` so you can tweak behaviour without touching code.

**Fuzzy skill matching** — the gap analyser uses an alias table (`sklearn` <-> `scikit-learn`, `torch` <-> `pytorch`) plus substring matching to handle the messiness of real-world JD text.

**State machine for applications** — invalid status transitions (e.g. Wishlist -> Offer) raise `ValueError`. This keeps the data clean and reflects how hiring pipelines actually work.

---

## Installation

### Local setup

```bash
cd jobintel

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# quick sanity check
python skill.py get_stats '{}'
```

### Docker

```bash
docker build -t jobintel:latest .
docker run -v $(pwd)/data:/app/data -v $(pwd)/logs:/app/logs jobintel:latest \
    python skill.py get_stats '{}'
```

---

## Configuration

Edit `config.yaml` before first run:

```yaml
candidate:
  name: "Your Name"
  target_roles:
    - "AI Engineer"
    - "Data Scientist"
  target_locations:
    - "Berlin"
    - "Remote"

scoring:
  skills_weight: 0.50
  experience_weight: 0.25
  education_weight: 0.15
  location_weight: 0.10
  strong_match_threshold: 0.75
```

---

## Usage

### CLI

```bash
# set your profile
python skill.py set_candidate_profile '{
  "name": "Faheem",
  "skills": [
    {"name": "python", "category": "language", "proficiency": 0.95},
    {"name": "pytorch", "category": "ml_framework", "proficiency": 0.85}
  ],
  "years_of_experience": 3.5,
  "education_level": "MSc",
  "target_locations": ["Berlin", "Remote"]
}'

# track an application
python skill.py track_application '{
  "company": "Celonis",
  "role": "Senior ML Engineer",
  "location": "Munich",
  "status": "applied",
  "applied_date": "2026-03-20"
}'

# daily digest
python skill.py get_daily_digest '{}'

# search for jobs
python skill.py search_jobs '{"query": "AI Engineer Python", "location": "Berlin"}'
```

### REST API

```bash
uvicorn api:app --reload --port 8000
# docs at http://localhost:8000/docs
```

### Streamlit Dashboard

```bash
streamlit run dashboard.py --server.port 8501
```

### MCP Server

```bash
# interactive inspector
mcp dev mcp_server.py

# stdio transport (for desktop MCP clients)
python mcp_server.py
```

---

## Tool Reference

| Tool | Required Input | What it does |
|---|---|---|
| `analyze_job_description` | `raw_text` | Parse JD, extract skills, compute match score |
| `track_application` | `company`, `role` | Log a new application |
| `update_application_status` | `app_id`, `new_status` | Move through the pipeline |
| `list_applications` | — | Query with optional filters |
| `analyze_cv_gap` | `raw_jd_text` | Find missing skills + CV suggestions |
| `get_daily_digest` | — | Full pipeline summary |
| `search_jobs` | `query` | Multi-source job board search |
| `set_candidate_profile` | `name`, `skills` | Store your profile |
| `get_stats` | — | Pipeline counts and rates |

See `SKILL.md` for full input/output schemas.

---

## Running Tests

```bash
# full suite with coverage
pytest tests/ -v --cov=src --cov-report=term-missing

# single file
pytest tests/test_match_scorer.py -v

# enforce 80% threshold
pytest tests/ --cov=src --cov-fail-under=80
```

---

## Application Status Pipeline

```
WISHLIST -> APPLIED -> PHONE_SCREEN -> TECHNICAL -> ONSITE -> OFFER -> ACCEPTED
              |             |              |          |        |
           REJECTED      REJECTED       REJECTED   REJECTED  REJECTED
              |             |              |          |        |
           WITHDRAWN    WITHDRAWN      WITHDRAWN  WITHDRAWN WITHDRAWN
```

Invalid transitions raise `ValueError` and are never persisted.

---

## Match Scoring

Composite score (0.0-1.0) across four weighted dimensions:

| Dimension | Weight | How it works |
|---|---|---|
| Skills | 50% | Weighted Jaccard: required skills count 2x, nice-to-have 1x |
| Experience | 25% | Linear ratio vs JD requirement; over-qualification capped |
| Education | 15% | Ordinal rank comparison (PhD > MSc > BSc > Vocational) |
| Location | 10% | Exact match = 1.0 / same country = 0.5 / remote = 1.0 |

Labels: **Strong Match** (>=0.75) / **Good Match** (>=0.55) / **Weak Match** (>=0.35) / **Poor Match** (<0.35)

---

## Project Structure

```
jobintel/
+-- SKILL.md                    Tool metadata + schemas
+-- skill.py                    Entry point / tool dispatcher
+-- api.py                      FastAPI REST wrapper
+-- dashboard.py                Streamlit web UI
+-- mcp_server.py               MCP protocol adapter
+-- config.yaml                 All configuration
+-- requirements.txt
+-- Dockerfile
+-- .flake8
+-- .gitignore
+-- data/
|   +-- jobintel.db             SQLite database (created at runtime)
+-- logs/
|   +-- jobintel.log            Rotating log file
+-- src/
|   +-- models/models.py        Pydantic v2 domain models
|   +-- database/
|   |   +-- manager.py          Thread-safe SQLite CRUD
|   |   +-- schema.sql          Table definitions
|   +-- analyzers/
|   |   +-- jd_parser.py        JD text -> structured model
|   |   +-- gap_analyzer.py     Profile x JD -> GapReport
|   |   +-- match_scorer.py     Profile x JD -> scored AnalysisResult
|   +-- tracker/
|   |   +-- application_tracker.py  CRUD + state machine
|   +-- digest/
|   |   +-- daily_digest.py     Daily summary generator
|   +-- search/
|       +-- job_search.py       Multi-source job board scraper
+-- tests/
    +-- conftest.py             Shared fixtures
    +-- test_database.py
    +-- test_jd_parser.py
    +-- test_gap_analyzer.py
    +-- test_match_scorer.py
    +-- test_tracker.py
    +-- test_digest.py
    +-- test_job_search.py
```

---

## Extending

**Add a new job board** — add `_fetch_<source>` and `_parse_<source>_html` methods to `JobSearcher`, register the source name in the dispatch dict, add to `config.yaml`.

**Add a new scoring dimension** — implement `_score_<dim>` in `MatchScorer`, add a weight key to config, include in composite calculation.

**Add a new tool** — write a handler in `skill.py`, register in `_TOOL_HANDLERS`, document in `SKILL.md`.

---

## License

MIT
