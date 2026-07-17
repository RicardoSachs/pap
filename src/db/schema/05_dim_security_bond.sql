-- 05_dim_security_bond.sql
-- Bond-specific extension of dim_security (1:1).
-- ASSUMED shape: the real file 05 DDL was not captured in pgetl_db_context.json
-- (referenced by SBS rf_local/rf_exterior staging). Columns mirror the bond
-- analytics those staging tables feed; reconcile with the real file before relying on it.

CREATE TABLE IF NOT EXISTS dim_security_bond (
    security_id       INTEGER PRIMARY KEY REFERENCES dim_security (security_id),
    face_value        DOUBLE PRECISION,
    issue_date        DATE,
    maturity_date     DATE,
    coupon_rate       DOUBLE PRECISION,
    rating            TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
