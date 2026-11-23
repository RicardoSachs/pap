-- 37_job_runs.sql
-- ---------------------------------------------------------------
-- Scheduler job-run log. One row per scheduled job execution,
-- written by the tracking decorator in scripts/scheduler.py.
--
-- Grain: one row per (job_id, started_at) execution attempt.
-- status lifecycle: 'running' -> 'success' | 'error'.
-- run_date is the business date the job processed (NULL until the
-- job finishes, for jobs with no single business date, and for a
-- polling job's slot that found nothing to load yet - a 'success'
-- with a NULL run_date keeps the day open for the next slot).
--
-- Append-only: the scheduler inserts at job start and updates the
-- same row at job end. A row stuck in 'running' with an old
-- started_at means the scheduler process died mid-job.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS job_runs (
    job_run_id  BIGSERIAL   PRIMARY KEY,
    job_id      TEXT        NOT NULL,
    machine_id  TEXT        NOT NULL,
    run_date    DATE,
    status      TEXT        NOT NULL DEFAULT 'running',
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_runs_job_id_started_at
    ON job_runs (job_id, started_at DESC);
