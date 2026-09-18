CREATE TABLE IF NOT EXISTS research_jobs (
  job_id TEXT PRIMARY KEY,
  request_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed')),
  result_json TEXT,
  error_code TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  claimed_at TEXT,
  lease_expires_at TEXT,
  executor_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_jobs_claim
ON research_jobs(status, created_at);
