
-- =============================================================
-- dim_security_equity
-- Equity-specific extension of dim_security.
-- =============================================================

CREATE TABLE IF NOT EXISTS dim_security_equity (
    security_id INTEGER PRIMARY KEY REFERENCES dim_security (security_id),
    sector TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
