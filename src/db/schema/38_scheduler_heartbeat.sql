-- 38_scheduler_heartbeat.sql
-- ---------------------------------------------------------------
-- Scheduler liveness. One row per machine, upserted every few
-- minutes by the heartbeat job in scripts/scheduler.py.
--
-- Grain: machine_id. last_seen older than ~10 minutes means the
-- scheduler process on that machine is down (crashed, machine
-- rebooted and the Task Scheduler logon task did not restart it).
-- registered_jobs is a comma-separated snapshot of the job ids the
-- process registered at startup — a quick config sanity check.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS scheduler_heartbeat (
    machine_id      TEXT        PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL,
    last_seen       TIMESTAMPTZ NOT NULL,
    registered_jobs TEXT        NOT NULL DEFAULT ''
);
