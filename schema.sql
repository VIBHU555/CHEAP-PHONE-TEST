-- PocketTest AI SQLite schema (also applied automatically at startup by app/db.py)
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  label TEXT,
  status TEXT NOT NULL,                 -- queued | running | completed | failed | cancelled
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  target_id TEXT NOT NULL,
  target_url TEXT NOT NULL,
  target_meta TEXT,                     -- JSON, e.g. demo app mode (optimized true/false)
  profile_id TEXT NOT NULL,
  profile TEXT NOT NULL,                -- JSON snapshot of the profile used
  workflow_id TEXT NOT NULL,
  repetitions INTEGER NOT NULL,
  rules TEXT NOT NULL,                  -- JSON snapshot of classification rules used
  environment TEXT,                     -- JSON: enforcement status per setting, browser version
  progress TEXT,                        -- JSON progress/event log
  summary TEXT,                         -- JSON aggregate metrics + verdict
  verdict TEXT,                         -- passed | failed | NULL
  error TEXT
);
CREATE TABLE IF NOT EXISTS step_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, repetition INTEGER NOT NULL,
  step_id TEXT NOT NULL, step_name TEXT NOT NULL, core INTEGER NOT NULL, status TEXT NOT NULL,
  duration_ms REAL, error TEXT, pending TEXT, started_at TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, repetition INTEGER NOT NULL, step_id TEXT NOT NULL,
  method TEXT, path TEXT, resource_type TEXT, status INTEGER, failed INTEGER NOT NULL DEFAULT 0,
  failure_text TEXT, simulated_fault INTEGER NOT NULL DEFAULT 0, duration_ms REAL, transfer_bytes INTEGER,
  server_ms REAL, is_api INTEGER NOT NULL DEFAULT 0, source TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS page_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, repetition INTEGER NOT NULL, step_id TEXT NOT NULL,
  path TEXT, nav_duration_ms REAL, dom_content_loaded_ms REAL, load_ms REAL, fcp_ms REAL, lcp_ms REAL,
  resource_count INTEGER, transfer_bytes INTEGER, source TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS js_errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, repetition INTEGER NOT NULL, step_id TEXT NOT NULL,
  kind TEXT, message TEXT, FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, rule_id TEXT NOT NULL, severity TEXT NOT NULL,
  title TEXT NOT NULL, operation TEXT, key TEXT, evidence TEXT, repro TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS reports (
  run_id TEXT PRIMARY KEY, generator TEXT NOT NULL, created_at TEXT NOT NULL, content TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
CREATE INDEX IF NOT EXISTS idx_req_run ON requests(run_id);
