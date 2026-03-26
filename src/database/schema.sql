-- JobIntel SQLite Schema
-- Using strict typing where possible; ISO-8601 strings for dates.

PRAGMA journal_mode = WAL;   -- Better concurrency
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Applications table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS applications (
    id           TEXT PRIMARY KEY,
    company      TEXT NOT NULL,
    role         TEXT NOT NULL,
    location     TEXT NOT NULL DEFAULT '',
    url          TEXT,
    status       TEXT NOT NULL DEFAULT 'wishlist',
    applied_date TEXT,                        -- ISO-8601 date
    deadline     TEXT,                        -- ISO-8601 date
    notes        TEXT NOT NULL DEFAULT '',
    contact      TEXT NOT NULL DEFAULT '',
    salary_min   INTEGER,
    salary_max   INTEGER,
    match_score  REAL,
    created_at   TEXT NOT NULL,               -- ISO-8601 datetime
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_company ON applications(company);
CREATE INDEX IF NOT EXISTS idx_applications_deadline ON applications(deadline);

-- ---------------------------------------------------------------------------
-- Candidate profile (single-row JSON store)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS candidate_profile (
    id         INTEGER PRIMARY KEY CHECK (id = 1),  -- enforce singleton
    profile_json TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Job search cache (avoid hammering external sources)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS search_cache (
    id          TEXT PRIMARY KEY,
    query       TEXT NOT NULL,
    location    TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL,
    results_json TEXT NOT NULL,
    fetched_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_search_cache_query ON search_cache(query, source);

-- ---------------------------------------------------------------------------
-- Digest history (audit trail)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS digest_history (
    id           TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    digest_json  TEXT NOT NULL
);
